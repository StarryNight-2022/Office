"""Reusable Kechuang building application wiring and shared fixtures."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.building_world import (
    AirDeviceApp,
    BuildingSensorApp,
    BuildingWorldApp,
    DeviceRegistryApp,
    HvacApp,
    LightingApp,
    MeetingEquipmentApp,
    OccupancyApp,
    PrintingApp,
    ResourceAllocationApp,
    RoomApp,
    ScheduleApp,
    VentilationApp,
)
from fairy.apps.building_world.room_loader import load_room_configuration
from fairy.apps.building_world.runtime import (
    BuildingWorldRuntime,
    constant_outdoor_provider,
    utc_datetime,
)
from fairy.apps.building_world.types import PersonRole, PersonState
from fairy.apps.system import SystemApp
from fairy.physics.building.models import OutdoorConditions
from fairy.scenarios.scenario import Scenario

CST = timezone(timedelta(hours=8))


def local_timestamp(year: int, month: int, day: int, hour: int = 0) -> float:
    return datetime(year, month, day, hour, tzinfo=CST).timestamp()


def collect_event_graph(root: Any) -> list[Any]:
    """Return every event reachable from ``root`` in dependency order.

    ``EventRegisterer`` captures App calls, while ``depends_on`` connects those
    calls into a graph.  Building scenarios keep this small traversal locally
    so they do not depend on farm-specific scenario helpers.
    """

    ordered: list[Any] = []
    seen: set[int] = set()
    pending = [root]
    while pending:
        event = pending.pop(0)
        marker = id(event)
        if marker in seen:
            continue
        seen.add(marker)
        ordered.append(event)
        # Insert successors at the front to preserve the declared event path.
        pending[0:0] = list(getattr(event, "successors", []))
    return ordered


class KechuangBuildingScenario(Scenario):
    """Base fixture shared by all K1324, K1316 and K1315 scenarios."""

    start_time: float | None = local_timestamp(2026, 9, 9, 9)
    time_increment_in_seconds: int = 60

    def initiate_scenario(self) -> None:
        if self.apps:
            return
        # The UI app turns the scenario briefing and final response into
        # first-class events, matching the current build_events_flow format.
        aui = AgentUserInterface()
        room_config_dir = Path(__file__).parents[2] / "configs" / "rooms"
        configurations = tuple(
            load_room_configuration(room_config_dir / filename)
            for filename in ("k1324.yaml", "k1316.yaml", "k1315.yaml")
        )
        world = BuildingWorldApp()
        runtime = BuildingWorldRuntime.from_room_configurations(
            configurations,
            world=world,
            start_at=utc_datetime(float(self.start_time or 0.0)),
            outdoor_provider=constant_outdoor_provider(
                OutdoorConditions(
                    air_temperature_c=30.0,
                    relative_humidity_pct=65.0,
                    co2_ppm=420.0,
                    pm25_ug_m3=25.0,
                    solar_irradiance_w_m2=300.0,
                )
            ),
            observation_seed=self.seed,
        )
        room = RoomApp(world)
        allocation = ResourceAllocationApp(world, room)
        schedule = ScheduleApp(world, room, allocation)
        occupancy = OccupancyApp(world)
        registry = DeviceRegistryApp(world)
        hvac = HvacApp(world)
        air_devices = AirDeviceApp(world)
        ventilation = VentilationApp(world)
        lighting = LightingApp(world)
        meeting_equipment = MeetingEquipmentApp(world)
        printing = PrintingApp(world)
        sensors = BuildingSensorApp(runtime.sensors)
        system = SystemApp()
        system.register_time_advance_hook(
            lambda _previous, current: runtime.advance_to(utc_datetime(current))
        )
        self.building_runtime = runtime
        self.apps = [
            aui,
            world,
            room,
            allocation,
            schedule,
            occupancy,
            registry,
            hvac,
            air_devices,
            ventilation,
            lighting,
            meeting_equipment,
            printing,
            sensors,
            system,
        ]
        self._configure_people(world)

    def _configure_people(self, world: BuildingWorldApp) -> None:
        for person in (
            PersonState(
                person_id="student-01",
                name="Student 01",
                role=PersonRole.STUDENT,
                on_campus=True,
            ),
            PersonState(
                person_id="professor-01",
                name="Professor 01",
                role=PersonRole.PROFESSOR,
                on_campus=True,
            ),
            PersonState(
                person_id="staff-01",
                name="Staff 01",
                role=PersonRole.STAFF,
                on_campus=True,
            ),
        ):
            world.add_person(person)
