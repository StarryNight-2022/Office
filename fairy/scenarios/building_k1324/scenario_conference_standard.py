"""Normal K1324 conference lifecycle with environment preparation."""

from __future__ import annotations

from datetime import datetime

from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.building_world import (
    AirDeviceApp,
    BuildingEventType,
    BuildingSensorApp,
    BuildingWorldApp,
    HvacApp,
    MeetingStatus,
    ReservationStatus,
    ResourceReservation,
    ScheduleEntry,
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
    event_types_in_order,
    install_normal_lifecycle,
)
from fairy.scenarios.registry import register_scenario
from fairy.scenarios.validation_result import ScenarioValidationResult
from fairy.types import EventRegisterer


ZONE_ID = "k1324_meeting_zone"
MEETING_ID = "conference-standard-001"
RESERVATION_ID = "conference-standard-reservation-001"


@register_scenario("scenario_building_k1324_conference_standard")
class ScenarioBuildingK1324ConferenceStandard(K1324BuildingScenario):
    """Prepare, host and close a scheduled conference without exceptions."""

    start_time: float | None = local_timestamp(2026, 9, 10, 9)
    time_increment_in_seconds: int = 60
    scenario_input = """
K1324 将在今天 10:00 至 11:00 举行 12 人正式会议。
请在 09:15 开始正常环境准备，使用传感器确认环境变化，并在会议正常结束后
关闭环境设备。会议期间不得跳过物理等待或把设备命令视为已经达到环境目标。
""".strip()

    def initiate_scenario(self) -> None:
        super().initiate_scenario()
        world = self.get_typed_app(BuildingWorldApp)
        start = datetime(2026, 9, 10, 10, 0, tzinfo=CST)
        end = datetime(2026, 9, 10, 11, 0, tzinfo=CST)
        world.reservations[RESERVATION_ID] = ResourceReservation(
            reservation_id=RESERVATION_ID,
            resource_id="k1324",
            owner_id=MEETING_ID,
            start_at=start,
            end_at=end,
        )
        world.add_schedule_entry(
            ScheduleEntry(
                meeting_id=MEETING_ID,
                room_id="k1324",
                organizer_id="staff-01",
                participant_ids=("professor-01",),
                start_at=start,
                end_at=end,
                expected_attendees=12,
                title="Standard research conference",
                required_capabilities=("projector", "audio", "microphone"),
                reservation_id=RESERVATION_ID,
            )
        )
        install_normal_lifecycle(
            self.building_runtime,
            (
                MeetingPhase(
                    "conference-preparation",
                    datetime(2026, 9, 10, 9, 15, tzinfo=CST),
                    BuildingEventType.MEETING_PREPARATION_DUE,
                    MEETING_ID,
                    {"room_id": "k1324"},
                ),
                MeetingPhase(
                    "conference-arrival",
                    datetime(2026, 9, 10, 9, 45, tzinfo=CST),
                    BuildingEventType.OCCUPANCY_CHANGED,
                    "k1324",
                    {"room_id": "k1324", "occupancy_count": 12},
                ),
                MeetingPhase(
                    "conference-start",
                    start,
                    BuildingEventType.MEETING_STARTED,
                    MEETING_ID,
                    {"occupancy_count": 12},
                ),
                MeetingPhase(
                    "conference-end",
                    end,
                    BuildingEventType.MEETING_ENDED,
                    MEETING_ID,
                ),
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
            wait_for_preparation = (
                system.advance_time(minutes=15)
                .oracle()
                .with_id("wait_for_preparation")
                .depends_on(briefing, delay_seconds=1)
            )
            initial_environment = (
                sensors.read_zone_sensors(ZONE_ID)
                .oracle()
                .with_id("read_preparation_environment")
                .depends_on(wait_for_preparation, delay_seconds=1)
            )
            start_hvac = (
                hvac.set_hvac("k1324_hvac_01", True, "cooling", 24.0, 3)
                .oracle()
                .with_id("start_conference_hvac")
                .depends_on(initial_environment, delay_seconds=1)
            )
            start_purifier = (
                air.set_air_purifier("k1324_purifier_01", True, 2)
                .oracle()
                .with_id("start_conference_purifier")
                .depends_on(start_hvac, delay_seconds=1)
            )
            precondition = (
                system.advance_time(minutes=30)
                .oracle()
                .with_id("precondition_room")
                .depends_on(start_purifier, delay_seconds=1)
            )
            before_meeting = (
                sensors.read_zone_sensors(ZONE_ID)
                .oracle()
                .with_id("verify_before_meeting")
                .depends_on(precondition, delay_seconds=1)
            )
            wait_for_start = (
                system.advance_time(minutes=15)
                .oracle()
                .with_id("wait_for_meeting_start")
                .depends_on(before_meeting, delay_seconds=1)
            )
            meeting_start_reading = (
                sensors.read_zone_sensors(ZONE_ID)
                .oracle()
                .with_id("verify_at_meeting_start")
                .depends_on(wait_for_start, delay_seconds=1)
            )
            run_meeting = (
                system.advance_time(minutes=60)
                .oracle()
                .with_id("run_standard_meeting")
                .depends_on(meeting_start_reading, delay_seconds=1)
            )
            end_reading = (
                sensors.read_zone_sensors(ZONE_ID)
                .oracle()
                .with_id("read_at_meeting_end")
                .depends_on(run_meeting, delay_seconds=1)
            )
            stop_hvac = (
                hvac.set_hvac("k1324_hvac_01", False, "off", 24.0, 0)
                .oracle()
                .with_id("stop_conference_hvac")
                .depends_on(end_reading, delay_seconds=1)
            )
            stop_purifier = (
                air.set_air_purifier("k1324_purifier_01", False, 0)
                .oracle()
                .with_id("stop_conference_purifier")
                .depends_on(stop_hvac, delay_seconds=1)
            )
            report = (
                aui.send_message_to_user(
                    content="K1324 标准会议已正常结束，环境设备已关闭，房间资源已释放。"
                )
                .oracle()
                .with_id("report_conference_complete")
                .depends_on(stop_purifier, delay_seconds=1)
            )
            self.events = collect_event_graph(briefing)
            assert any(event is report for event in self.events)

    def validate(self, env) -> ScenarioValidationResult:
        world = self.get_typed_app(BuildingWorldApp)
        meeting = world.schedule[MEETING_ID]
        reservation = world.reservations[RESERVATION_ID]
        hvac_off = not world.device_states["k1324_hvac_01"].power_on
        purifier_off = not world.device_states["k1324_purifier_01"].power_on
        ordered = event_types_in_order(world.events)
        expected = [
            BuildingEventType.MEETING_PREPARATION_DUE,
            BuildingEventType.OCCUPANCY_CHANGED,
            BuildingEventType.MEETING_STARTED,
            BuildingEventType.MEETING_ENDED,
        ]
        success = (
            meeting.status == MeetingStatus.COMPLETED
            and reservation.status == ReservationStatus.RELEASED
            and world.room_states["k1324"].occupancy_count == 0
            and hvac_off
            and purifier_off
            and ordered == expected
            and self.building_runtime.physics.cumulative_energy_kwh_by_zone[ZONE_ID]
            > 0.0
        )
        return ScenarioValidationResult(
            success=success,
            rationale=(
                "standard conference lifecycle completed"
                if success
                else "conference lifecycle or cleanup is incomplete"
            ),
            metadata={
                "lifecycle_events": [item.value for item in ordered],
                "meeting_status": meeting.status.value,
                "reservation_status": reservation.status.value,
                "energy_kwh": self.building_runtime.physics.cumulative_energy_kwh_by_zone[
                    ZONE_ID
                ],
            },
        )
