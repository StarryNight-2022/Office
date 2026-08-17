"""Normal temperature and humidity coordination in K1324."""

from __future__ import annotations

from datetime import datetime

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.building_world import (
    AirDeviceApp,
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

ZONE_ID = "k1324_office_zone"


@register_scenario("scenario_building_k1324_climate_coordination")
class ScenarioBuildingK1324ClimateCoordination(K1324BuildingScenario):
    """Coordinate cooling and humidification using periodic observations."""

    start_time: float | None = local_timestamp(2026, 9, 10, 9)
    time_increment_in_seconds: int = 60
    scenario_input = """
请将 K1324 研究生办公室从当前环境平稳调节到适合日常办公的状态。先启动空调制冷，等待并读取
传感器，再根据温湿度开启加湿器；继续观察后转为低档维持，完成时关闭设备。
每个控制阶段都必须经过物理时间推进和传感器验证。
""".strip()

    def initiate_scenario(self) -> None:
        super().initiate_scenario()
        self.initial_truth = self.building_runtime.physics.engine.get_state()[ZONE_ID]
        install_normal_lifecycle(
            self.building_runtime,
            tuple(
                MeetingPhase(
                    f"climate-check-{minute}",
                    datetime(2026, 9, 10, 9, minute, tzinfo=CST),
                    BuildingEventType.ENVIRONMENT_CHECK_DUE,
                    ZONE_ID,
                    {"stage": stage},
                )
                for minute, stage in (
                    (20, "after_cooling"),
                    (40, "after_humidification"),
                )
            ),
        )

    def build_events_flow(self) -> None:
        aui = self.get_typed_app(AgentUserInterface)
        system = self.get_typed_app(SystemApp)
        sensors = self.get_typed_app(BuildingSensorApp)
        hvac = self.get_typed_app(HvacApp)
        air = self.get_typed_app(AirDeviceApp)

        with EventRegisterer.capture_mode():
            briefing = (
                aui.send_message_to_agent(content=self.scenario_input)
                .with_id("briefing")
                .depends_on(None, delay_seconds=1)
            )
            start_hvac = (
                hvac.set_hvac("k1324_hvac_01", True, "cooling", 24.0, 3)
                .oracle()
                .with_id("start_climate_hvac")
                .depends_on(briefing, delay_seconds=1)
            )
            cool = (
                system.advance_time(minutes=20)
                .oracle()
                .with_id("wait_for_cooling")
                .depends_on(start_hvac, delay_seconds=1)
            )
            after_cooling = (
                sensors.read_zone_sensors(ZONE_ID)
                .oracle()
                .with_id("read_after_cooling")
                .depends_on(cool, delay_seconds=1)
            )
            start_humidifier = (
                air.set_humidifier("k1324_humidifier_01", True, 2)
                .oracle()
                .with_id("start_humidifier")
                .depends_on(after_cooling, delay_seconds=1)
            )
            coordinate = (
                system.advance_time(minutes=20)
                .oracle()
                .with_id("wait_for_humidity_coordination")
                .depends_on(start_humidifier, delay_seconds=1)
            )
            coordinated = (
                sensors.read_zone_sensors(ZONE_ID)
                .oracle()
                .with_id("read_coordinated_climate")
                .depends_on(coordinate, delay_seconds=1)
            )
            maintain = (
                hvac.set_hvac("k1324_hvac_01", True, "cooling", 24.0, 2)
                .oracle()
                .with_id("set_low_climate_maintenance")
                .depends_on(coordinated, delay_seconds=1)
            )
            stop_humidifier = (
                air.set_humidifier("k1324_humidifier_01", False, 0)
                .oracle()
                .with_id("stop_humidifier")
                .depends_on(maintain, delay_seconds=1)
            )
            stabilize = (
                system.advance_time(minutes=30)
                .oracle()
                .with_id("stabilize_climate")
                .depends_on(stop_humidifier, delay_seconds=1)
            )
            final_reading = (
                sensors.read_zone_sensors(ZONE_ID)
                .oracle()
                .with_id("read_final_climate")
                .depends_on(stabilize, delay_seconds=1)
            )
            stop_hvac = (
                hvac.set_hvac("k1324_hvac_01", False, "off", 24.0, 0)
                .oracle()
                .with_id("stop_climate_hvac")
                .depends_on(final_reading, delay_seconds=1)
            )
            report = (
                aui.send_message_to_user(
                    content="K1324 温湿度协同调节完成，设备已关闭。"
                )
                .oracle()
                .with_id("report_climate_complete")
                .depends_on(stop_hvac, delay_seconds=1)
            )
            self.events = collect_event_graph(briefing)
            assert any(event is report for event in self.events)

    def validate(self, env) -> ScenarioValidationResult:
        world = self.get_typed_app(BuildingWorldApp)
        final = self.building_runtime.physics.engine.get_state()[ZONE_ID]
        checks = [
            event
            for event in world.events
            if event.event_type == BuildingEventType.ENVIRONMENT_CHECK_DUE
        ]
        success = (
            final.air_temperature_c < self.initial_truth.air_temperature_c
            and 21.0 <= final.air_temperature_c <= 25.5
            and 40.0 <= final.relative_humidity_pct <= 65.0
            and len(checks) == 2
            and not world.device_states["k1324_hvac_01"].power_on
            and not world.device_states["k1324_humidifier_01"].power_on
        )
        return ScenarioValidationResult(
            success=success,
            rationale=(
                "temperature and humidity were coordinated through observations"
                if success
                else "climate coordination did not reach its normal target"
            ),
            metadata={
                "initial_temperature_c": self.initial_truth.air_temperature_c,
                "final_temperature_c": final.air_temperature_c,
                "final_relative_humidity_pct": final.relative_humidity_pct,
                "environment_checks": len(checks),
            },
        )
