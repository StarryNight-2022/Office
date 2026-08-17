"""Normal staged occupancy and indoor-air response in K1324."""

from __future__ import annotations

from datetime import datetime, timedelta

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.building_world import (
    BuildingEventType,
    BuildingSensorApp,
    BuildingWorldApp,
    HvacApp,
)
from fairy.apps.system import SystemApp
from fairy.scenarios.building_k1324.base import (
    CST,
    K1324BuildingScenario,
    collect_event_graph,
    local_timestamp,
)
from fairy.scenarios.building_k1324.meeting_lifecycle import (
    MeetingPhase,
    install_normal_lifecycle,
)
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.types import EventRegisterer


ZONE_ID = "k1324_meeting_zone"
OCCUPANCY_TIMELINE = ((10, 5), (20, 10), (30, 15), (45, 10), (55, 5), (65, 0))


@register_scenario("scenario_building_k1324_occupancy_ramp")
class ScenarioBuildingK1324OccupancyRamp(K1324BuildingScenario):
    """Observe CO2 as attendees enter and leave in normal planned batches."""

    start_time: float | None = local_timestamp(2026, 9, 10, 9)
    time_increment_in_seconds: int = 60
    scenario_input = """
K1324 的参会人员会按照计划分批进入并在活动后分批离开。请开启正常通风，
在每个人数阶段等待物理环境演化并检查传感器；全部人员离开后继续通风一段时间，
确认空气质量开始恢复，然后关闭空调风机。
""".strip()

    def initiate_scenario(self) -> None:
        super().initiate_scenario()
        self.initial_co2_ppm = self.building_runtime.physics.engine.get_state()[
            ZONE_ID
        ].co2_ppm
        install_normal_lifecycle(
            self.building_runtime,
            tuple(
                MeetingPhase(
                    f"occupancy-{minute:02d}-{count:02d}",
                    datetime(2026, 9, 10, 9, tzinfo=CST)
                    + timedelta(minutes=minute),
                    BuildingEventType.OCCUPANCY_CHANGED,
                    "k1324",
                    {"room_id": "k1324", "occupancy_count": count},
                )
                for minute, count in OCCUPANCY_TIMELINE
            ),
        )

    def build_events_flow(self) -> None:
        aui = self.get_typed_app(AgentUserInterface)
        system = self.get_typed_app(SystemApp)
        sensors = self.get_typed_app(BuildingSensorApp)
        hvac = self.get_typed_app(HvacApp)

        with EventRegisterer.capture_mode():
            briefing = (
                aui.send_message_to_agent(content=self.scenario_input)
                .with_id("briefing")
                .depends_on(None, delay_seconds=1)
            )
            previous = (
                hvac.set_hvac("k1324_hvac_01", True, "fan", 24.0, 3)
                .oracle()
                .with_id("start_normal_ventilation")
                .depends_on(briefing, delay_seconds=1)
            )
            previous_minute = 0
            for minute, count in OCCUPANCY_TIMELINE:
                wait = (
                    system.advance_time(minutes=minute - previous_minute)
                    .oracle()
                    .with_id(f"wait_to_minute_{minute:02d}_occupancy_{count:02d}")
                    .depends_on(previous, delay_seconds=1)
                )
                previous = (
                    sensors.read_zone_sensors(ZONE_ID)
                    .oracle()
                    .with_id(f"read_minute_{minute:02d}_occupancy_{count:02d}")
                    .depends_on(wait, delay_seconds=1)
                )
                previous_minute = minute
            recover = (
                system.advance_time(minutes=15)
                .oracle()
                .with_id("wait_for_empty_room_recovery")
                .depends_on(previous, delay_seconds=1)
            )
            recovered = (
                sensors.read_zone_sensors(ZONE_ID)
                .oracle()
                .with_id("read_after_empty_room_recovery")
                .depends_on(recover, delay_seconds=1)
            )
            stop = (
                hvac.set_hvac("k1324_hvac_01", False, "off", 24.0, 0)
                .oracle()
                .with_id("stop_normal_ventilation")
                .depends_on(recovered, delay_seconds=1)
            )
            report = (
                aui.send_message_to_user(
                    content="人员已按计划全部离开，空气恢复阶段完成，通风设备已关闭。"
                )
                .oracle()
                .with_id("report_occupancy_complete")
                .depends_on(stop, delay_seconds=1)
            )
            self.events = collect_event_graph(briefing)
            assert any(event is report for event in self.events)

    def validate(self, env) -> ScenarioValidationResult:
        world = self.get_typed_app(BuildingWorldApp)
        occupancy_events = [
            event
            for event in world.events
            if event.event_type == BuildingEventType.OCCUPANCY_CHANGED
        ]
        observed_counts = [
            int(event.payload["occupancy_count"]) for event in occupancy_events
        ]
        co2_series = [
            float(zone["co2_ppm"])
            for item in self.building_runtime.trace
            if item.get("kind") == "physics_step"
            for zone in item["zones"]
            if zone["zone_id"] == ZONE_ID
        ]
        peak_co2 = max(co2_series, default=self.initial_co2_ppm)
        final_co2 = co2_series[-1] if co2_series else self.initial_co2_ppm
        success = (
            observed_counts == [count for _, count in OCCUPANCY_TIMELINE]
            and world.room_states["k1324"].occupancy_count == 0
            and peak_co2 > self.initial_co2_ppm
            and final_co2 < peak_co2
            and not world.device_states["k1324_hvac_01"].power_on
        )
        return ScenarioValidationResult(
            success=success,
            rationale=(
                "occupancy-driven CO2 rise and empty-room recovery were observed"
                if success
                else "occupancy or CO2 response did not follow the planned ramp"
            ),
            metadata={
                "occupancy_counts": observed_counts,
                "initial_co2_ppm": self.initial_co2_ppm,
                "peak_co2_ppm": peak_co2,
                "final_co2_ppm": final_co2,
            },
        )
