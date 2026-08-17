from fairy.apps.agent_user_interface import AgentUserInterface
from fairy.apps.building_world import (
    BuildingWorldApp,
    ResourceAllocationApp,
    RoomApp,
    ScheduleApp,
)
from fairy.apps.building_world.types import (
    BuildingEventType,
    PersonRole,
    PersonState,
    ReservationStatus,
    RoomSpec,
)
from fairy.controllers.engine import Engine
from fairy.scenarios.building_k1324.scenario_meeting_booking import (
    END_AT,
    START_AT,
    ScenarioBuildingK1324MeetingBooking,
)
from fairy.scenarios.registry import get_scenario_class


def _apps():
    world = BuildingWorldApp()
    world.add_room(
        RoomSpec("room-01", "Meeting Room", 8, frozenset({"projector"}))
    )
    world.add_person(PersonState("student", "Student", PersonRole.STUDENT))
    world.add_person(PersonState("professor", "Professor", PersonRole.PROFESSOR))
    room = RoomApp(world)
    allocation = ResourceAllocationApp(world, room)
    schedule = ScheduleApp(world, room, allocation)
    return world, room, allocation, schedule


def _create(schedule: ScheduleApp, **overrides):
    args = {
        "request_id": "request-01",
        "organizer_id": "student",
        "participant_ids": ["professor"],
        "room_id": "room-01",
        "start_at": START_AT,
        "end_at": END_AT,
        "expected_attendees": 2,
        "required_capabilities": ["projector"],
        "title": "Consultation",
    }
    args.update(overrides)
    return schedule.create_meeting(**args)


def test_create_meeting_reserves_room_and_emits_causal_events() -> None:
    world, _, _, schedule = _apps()

    result = _create(schedule)

    assert result["status"] == "confirmed"
    reservation = world.reservations[result["reservation_id"]]
    assert reservation.status == ReservationStatus.ACTIVE
    assert [event.event_type for event in world.events] == [
        BuildingEventType.RESOURCE_RESERVED,
        BuildingEventType.SCHEDULE_CREATED,
    ]
    assert world.events[1].parent_event_id == world.events[0].event_id


def test_conflicting_meeting_is_rejected_without_leaking_reservation() -> None:
    world, _, _, schedule = _apps()
    assert _create(schedule)["status"] == "confirmed"
    reservation_count = len(world.reservations)

    conflict = _create(
        schedule,
        request_id="request-02",
        start_at="2026-09-10T14:30:00+08:00",
        end_at="2026-09-10T15:30:00+08:00",
    )

    assert conflict["status"] == "rejected"
    assert conflict["reason"] == "room_conflict"
    assert len(world.reservations) == reservation_count


def test_adjacent_meetings_do_not_overlap() -> None:
    _, _, _, schedule = _apps()
    assert _create(schedule)["status"] == "confirmed"

    adjacent = _create(
        schedule,
        request_id="request-02",
        start_at=END_AT,
        end_at="2026-09-10T16:00:00+08:00",
    )

    assert adjacent["status"] == "confirmed"


def test_capacity_and_capability_rules_are_deterministic() -> None:
    _, _, _, schedule = _apps()

    assert _create(schedule, expected_attendees=9)["reason"] == "room_capacity_exceeded"
    assert _create(schedule, required_capabilities=["audio"])["reason"] == (
        "missing_room_capabilities"
    )


def test_snapshot_restore_preserves_meeting_and_id_sequence() -> None:
    world, _, _, schedule = _apps()
    result = _create(schedule)
    snapshot = world.snapshot()
    restored = BuildingWorldApp()

    restored.restore(snapshot)

    meeting_id = result["meeting"]["meeting_id"]
    assert restored.schedule[meeting_id].room_id == "room-01"
    assert restored.next_id("meeting") == "meeting-0002"


def test_meeting_booking_oracle_replay_and_validation() -> None:
    build_engine = Engine(None, ScenarioBuildingK1324MeetingBooking())
    oracle = build_engine.build_oracle_workflow(run_oracle=False)
    replay_engine = Engine(None, ScenarioBuildingK1324MeetingBooking())

    replayed = replay_engine.replay_workflow(oracle)
    report = replay_engine.evaluation_report(replayed)

    assert list(oracle.dag) == [
        "briefing",
        "check_professor_presence",
        "check_professor_schedule",
        "find_available_room",
        "book_k1316",
        "report_booking_result",
    ]
    assert replayed.dag["book_k1316"].content["status"] == "confirmed"
    assert report["validation"]["success"] is True


def test_meeting_booking_builds_agent_briefing_event() -> None:
    scenario = ScenarioBuildingK1324MeetingBooking()

    scenario.setup()

    assert scenario.events
    briefing = scenario.events[0]
    assert isinstance(briefing.app, AgentUserInterface)
    assert briefing.function.__name__ == "send_message_to_agent"
    assert briefing.kwargs["content"] == scenario.scenario_input


def test_building_scenario_is_registered() -> None:
    assert get_scenario_class("scenario_building_k1324_meeting_booking") is (
        ScenarioBuildingK1324MeetingBooking
    )
