"""Unified deterministic runtime for Building World, physics and sensing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping

from fairy.apps.building_world.building_world_app import BuildingWorldApp
from fairy.apps.building_world.room_loader import LoadedRoomConfiguration
from fairy.apps.building_world.sensor_hub import SensorHub
from fairy.apps.building_world.types import (
    BuildingEventType,
    DeviceHealth,
    DeviceType,
)
from fairy.physics.building.equipment_model import BuildingEquipmentModel
from fairy.physics.building.indoor_environment_engine import IndoorEnvironmentEngine
from fairy.physics.building.models import InternalLoads, OutdoorConditions
from fairy.physics.building.observation_model import BuildingObservationModel
from fairy.physics.building.orchestrator import (
    BuildingPhysicsOrchestrator,
    BuildingPhysicsStepResult,
    PhysicsEventType,
)

OutdoorProvider = Callable[[datetime], OutdoorConditions]


@dataclass(frozen=True)
class RuntimeAdvanceResult:
    """Aggregate all fixed-size physics ticks used to reach a target time."""

    started_at: datetime
    ended_at: datetime
    steps: tuple[BuildingPhysicsStepResult, ...]


class BuildingWorldRuntime:
    """Own cross-layer time advancement without exposing simulator truth."""

    def __init__(
        self,
        *,
        world: BuildingWorldApp,
        physics: BuildingPhysicsOrchestrator,
        sensors: SensorHub,
        start_at: datetime,
        outdoor_provider: OutdoorProvider,
        equipment_model: BuildingEquipmentModel | None = None,
        max_timestep_seconds: float = 300.0,
    ) -> None:
        if start_at.tzinfo is None:
            raise ValueError("start_at must be timezone-aware")
        if max_timestep_seconds <= 0.0:
            raise ValueError("max_timestep_seconds must be positive")
        self.world = world
        self.physics = physics
        self.sensors = sensors
        self.current_time = start_at
        self.outdoor_provider = outdoor_provider
        self.equipment_model = equipment_model or BuildingEquipmentModel()
        self.max_timestep_seconds = float(max_timestep_seconds)
        self.trace: list[dict[str, object]] = []

    @classmethod
    def from_room_configuration(
        cls,
        configuration: LoadedRoomConfiguration,
        *,
        start_at: datetime,
        outdoor_provider: OutdoorProvider,
        world: BuildingWorldApp | None = None,
        observation_seed: int = 0,
        max_timestep_seconds: float = 300.0,
    ) -> "BuildingWorldRuntime":
        world = world or BuildingWorldApp()
        configuration.install_into(world)
        sensors = SensorHub(configuration.zone_parameters)
        observation = BuildingObservationModel(
            configuration.sensors, seed=observation_seed
        )
        physics = BuildingPhysicsOrchestrator(
            IndoorEnvironmentEngine(
                configuration.zone_parameters,
                configuration.initial_zone_states,
            ),
            observation_model=observation,
            observation_sink=sensors,
        )
        return cls(
            world=world,
            physics=physics,
            sensors=sensors,
            start_at=start_at,
            outdoor_provider=outdoor_provider,
            max_timestep_seconds=max_timestep_seconds,
        )

    def advance_by(self, seconds: float) -> RuntimeAdvanceResult:
        if seconds <= 0.0:
            raise ValueError("advance duration must be positive")
        return self.advance_to(self.current_time + timedelta(seconds=seconds))

    def advance_to(self, target_time: datetime) -> RuntimeAdvanceResult:
        if target_time.tzinfo is None:
            raise ValueError("target_time must be timezone-aware")
        if target_time <= self.current_time:
            raise ValueError("target_time must be later than current runtime time")
        started_at = self.current_time
        steps: list[BuildingPhysicsStepResult] = []
        while self.current_time < target_time:
            remaining = (target_time - self.current_time).total_seconds()
            timestep = min(self.max_timestep_seconds, remaining)
            step_at = self.current_time + timedelta(seconds=timestep)
            truth = self.physics.engine.get_state()
            commands = self.equipment_model.commands_by_zone(
                self.world.devices, self.world.device_states, truth
            )
            step = self.physics.step(
                at_time=step_at,
                timestep_seconds=timestep,
                outdoor=self.outdoor_provider(step_at),
                loads_by_zone=self._loads_by_zone(),
                hvac_by_zone=commands,
            )
            self.current_time = step_at
            self._publish_step_events(step)
            self._record_trace(step)
            steps.append(step)
        return RuntimeAdvanceResult(started_at, self.current_time, tuple(steps))

    def snapshot(self) -> dict[str, object]:
        return {
            "current_time": self.current_time,
            "world": self.world.snapshot(),
            "physics": self.physics.snapshot(),
            "sensors": self.sensors.snapshot(),
            "trace": list(self.trace),
        }

    def restore(self, snapshot: Mapping[str, object]) -> None:
        current_time = snapshot.get("current_time")
        if not isinstance(current_time, datetime):
            raise ValueError("runtime snapshot has invalid current_time")
        self.world.restore(snapshot["world"])  # type: ignore[arg-type]
        self.physics.restore(snapshot["physics"])  # type: ignore[arg-type]
        self.sensors.restore(snapshot["sensors"])  # type: ignore[arg-type]
        self.current_time = current_time
        self.trace = list(snapshot.get("trace", []))  # type: ignore[arg-type]

    def _loads_by_zone(self) -> dict[str, InternalLoads]:
        located_people: dict[str, int] = {zone_id: 0 for zone_id in self.world.zones}
        for person in self.world.people.values():
            if not person.on_campus or person.current_zone_id is None:
                continue
            if person.current_zone_id in located_people:
                located_people[person.current_zone_id] += 1
                continue
            # Older fixtures store a room ID as location. Map it to the first
            # declared zone so they remain compatible with zone-level physics.
            matching_zones = [
                zone.zone_id
                for zone in self.world.zones.values()
                if zone.room_id == person.current_zone_id
            ]
            if matching_zones:
                located_people[matching_zones[0]] += 1
        loads: dict[str, InternalLoads] = {}
        for zone_id, zone in self.world.zones.items():
            explicit_room_count = self.world.room_states[zone.room_id].occupancy_count
            occupants = max(located_people[zone_id], explicit_room_count)
            equipment_power = 0.0
            for device_id, spec in self.world.devices.items():
                state = self.world.device_states[device_id]
                if (
                    spec.zone_id == zone_id
                    and state.power_on
                    and state.health == DeviceHealth.ONLINE
                    and spec.device_type
                    not in {
                        DeviceType.HVAC,
                        DeviceType.HUMIDIFIER,
                        DeviceType.AIR_PURIFIER,
                    }
                ):
                    equipment_power += spec.rated_power_w
            loads[zone_id] = InternalLoads(
                occupants=float(occupants),
                equipment_heat_w=equipment_power,
                equipment_electric_power_w=equipment_power,
            )
        return loads

    def _publish_step_events(self, step: BuildingPhysicsStepResult) -> None:
        if step.observations:
            self.world.publish_building_event(
                BuildingEventType.SENSOR_UPDATED,
                source=self.__class__.__name__,
                subject_id="building-sensors",
                occurred_at=step.at_time,
                payload={"sample_count": len(step.observations)},
            )
        event_types = {
            PhysicsEventType.COMFORT_THRESHOLD_VIOLATED: (
                BuildingEventType.COMFORT_THRESHOLD_VIOLATED
            ),
            PhysicsEventType.AIR_QUALITY_THRESHOLD_VIOLATED: (
                BuildingEventType.AIR_QUALITY_THRESHOLD_VIOLATED
            ),
            PhysicsEventType.THRESHOLD_RECOVERED: BuildingEventType.THRESHOLD_RECOVERED,
        }
        for event in step.events:
            self.world.publish_building_event(
                event_types[event.event_type],
                source="BuildingPhysicsOrchestrator",
                subject_id=event.zone_id,
                occurred_at=event.occurred_at,
                payload={"condition": event.condition, **dict(event.payload)},
            )

    def _record_trace(self, step: BuildingPhysicsStepResult) -> None:
        self.trace.append(
            {
                "at_time": step.at_time.isoformat(),
                "zones": [
                    {
                        "zone_id": result.zone_id,
                        "air_temperature_c": result.air_temperature_c,
                        "relative_humidity_pct": result.relative_humidity_pct,
                        "co2_ppm": result.co2_ppm,
                        "pm25_ug_m3": result.pm25_ug_m3,
                        "electric_power_w": result.electric_power_w,
                        "energy_kwh": result.energy_kwh,
                        "comfort_score": result.comfort.score,
                    }
                    for result in step.zones
                ],
                "physics_events": [event.event_type.value for event in step.events],
                "observation_count": len(step.observations),
            }
        )


def constant_outdoor_provider(
    conditions: OutdoorConditions,
) -> OutdoorProvider:
    """Return a deterministic provider useful before adding a weather API."""

    return lambda _at_time: conditions


def utc_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)
