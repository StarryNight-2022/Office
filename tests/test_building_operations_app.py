"""Contracts for L3 operating status, readiness and guarded completion."""

from types import SimpleNamespace

from fairy.agents.agent.agent import Agent
from fairy.apps.building_world import (
    BuildingOperationsApp,
    HvacApp,
    MeetingEquipmentApp,
    VentilationApp,
)
from fairy.controllers.engine import Engine
from fairy.apps.system import SystemApp
from fairy.scenarios.building_kechuang.l3.scenarios import L3_SCENARIO_CLASSES
from fairy.physics.building import SensorQuantity, SensorReading


def test_l3_operational_status_blocks_early_completion_without_future_leak() -> None:
    scenario = L3_SCENARIO_CLASSES[10]()
    scenario.setup()
    Engine(None, scenario)
    operations = scenario.get_typed_app(BuildingOperationsApp)

    status = operations.get_operational_status()

    assert status["can_finish"] is False
    assert status["next_scheduled_event_at"] is not None
    assert {item["code"] for item in status["blockers"]} >= {
        "operational_horizon_not_reached",
        "scheduled_event_pending",
        "meetings_open",
    }
    # Only the timestamp is disclosed; event type/payload remain in Runtime.
    assert "event_type" not in str(status)
    assert scenario.spec.interaction.description not in str(status)


def test_meeting_readiness_uses_current_schedule_and_explicit_device_checklist() -> None:
    scenario = L3_SCENARIO_CLASSES[11]()
    scenario.setup()
    Engine(None, scenario)
    operations = scenario.get_typed_app(BuildingOperationsApp)

    initial = operations.get_meeting_readiness("upgraded-meeting")
    assert initial["room_id"] == "k1316"
    assert {item["device_id"] for item in initial["checklist"]} == {
        "k1316_hvac_01",
        "k1316_ventilation_01",
        "k1316_projector_01",
        "k1316_audio_01",
    }

    scenario.building_runtime.advance_by(120 * 60)
    changed = operations.get_meeting_readiness("upgraded-meeting")
    assert changed["room_id"] == "k1315"
    assert {item["device_id"] for item in changed["checklist"]} == {
        "k1315_hvac_01",
        "k1315_ventilation_01",
        "k1315_projector_01",
        "k1315_audio_01",
    }


def test_time_advance_cannot_cross_meeting_start_with_readiness_regression() -> None:
    scenario = L3_SCENARIO_CLASSES[12]()
    scenario.setup()
    Engine(None, scenario)
    system = scenario.get_typed_app(SystemApp)
    hvac = scenario.get_typed_app(HvacApp)
    ventilation = scenario.get_typed_app(VentilationApp)
    equipment = scenario.get_typed_app(MeetingEquipmentApp)

    # Normal wake-ups expose the 09:30 schedule change that advances the
    # meeting start to 10:30.
    assert system.advance_time(hours=3)["interrupted"] is True
    assert system.advance_time(hours=3)["interrupted"] is True
    hvac.set_hvac("k1315_hvac_01", True, "cooling", 24.0, 3)
    equipment.set_projector("k1315_projector_01", True, "hdmi")
    equipment.set_audio_system("k1315_audio_01", True, 70, True)

    # Turning ventilation off for humidity control must not silently cross the
    # meeting boundary with an incomplete readiness checklist.
    rejected = system.advance_time(hours=2)
    assert rejected["status"] == "rejected"
    assert rejected["details"]["code"] == "meeting_readiness_required"
    assert rejected["details"]["meetings"][0]["missing_device_ids"] == [
        "k1315_ventilation_01"
    ]

    ventilation.set_ventilation("k1315_ventilation_01", True, 1)
    readiness = scenario.get_typed_app(
        BuildingOperationsApp
    ).get_meeting_readiness("advanced-meeting")
    assert readiness["ready"] is True


def test_environment_control_status_exposes_policy_and_initial_observations() -> None:
    scenario = L3_SCENARIO_CLASSES[0]()
    scenario.setup()
    Engine(None, scenario)
    status = scenario.get_typed_app(
        BuildingOperationsApp
    ).get_environment_control_status()

    assert status["rooms"]
    assert status["policy"]["occupied_temperature_band_c"] == [21.0, 25.0]
    assert status["policy"]["occupied_humidity_band_pct"] == [40.0, 60.0]
    assert status["policy"]["required_stable_checks_after_control"] == 2
    assert status["recommended_recheck_minutes"] > 0


def test_co2_warning_requires_preventive_control_before_hard_limit() -> None:
    scenario = L3_SCENARIO_CLASSES[0]()
    scenario.setup()
    Engine(None, scenario)
    runtime = scenario.building_runtime
    assert runtime is not None
    operations = scenario.get_typed_app(BuildingOperationsApp)
    ventilation = scenario.get_typed_app(VentilationApp)
    room_id = "k1324"
    zone_id = "k1324_office_zone"
    scenario.get_typed_app(BuildingOperationsApp).world.room_states[
        room_id
    ].occupancy_count = 1
    runtime.sensors.publish(
        SensorReading(
            sensor_id="co2-warning-contract",
            zone_id=zone_id,
            quantity=SensorQuantity.CO2_PPM,
            value=1050.0,
            unit="ppm",
            observed_at=runtime.current_time,
        )
    )

    status = operations.get_environment_control_status()
    room = next(item for item in status["rooms"] if item["room_id"] == room_id)
    assert "co2_control_warning" in room["warnings"]
    assert "co2_above_scenario_limit" not in room["violations"]
    assert "co2_control_warning" in room["uncontrolled_warnings"]
    guard = operations.time_advance_precondition()
    assert guard["allowed"] is False
    assert {
        (item["room_id"], item["device_type"])
        for item in guard["missing_controls"]
    } >= {(room_id, "ventilation")}

    ventilation.set_ventilation("k1324_ventilation_01", True, 2)
    controlled = operations.get_environment_control_status()
    room = next(item for item in controlled["rooms"] if item["room_id"] == room_id)
    assert "co2_control_warning" in room["warnings"]
    assert "co2_control_warning" not in room["uncontrolled_warnings"]


def test_commitment_status_prioritizes_public_deadlines_without_hidden_events() -> None:
    scenario = L3_SCENARIO_CLASSES[19]()
    scenario.setup()
    Engine(None, scenario)
    status = scenario.get_typed_app(BuildingOperationsApp).get_commitment_status()

    assert status["commitments"]
    deadlines = [item["minutes_until_deadline"] for item in status["commitments"]]
    assert deadlines == sorted(deadlines)
    assert any(
        item["commitment_type"] == "print_request"
        and item["document_name"] == "priority_meeting_pack"
        for item in status["commitments"]
    )
    assert scenario.spec.interaction.description not in str(status)


def test_power_budget_status_detects_unsafe_parallel_hvac_configuration() -> None:
    scenario = L3_SCENARIO_CLASSES[15]()
    scenario.setup()
    Engine(None, scenario)
    operations = scenario.get_typed_app(BuildingOperationsApp)
    hvac = scenario.get_typed_app(HvacApp)

    for room_id in ("k1324", "k1316", "k1315"):
        result = hvac.set_hvac(
            f"{room_id}_hvac_01", True, "cooling", 22.0, 3
        )
        assert result["status"] == "accepted"

    status = operations.get_power_budget_status()

    assert status["power_limit_w"] == 4200.0
    assert status["within_limit"] is False
    assert status["headroom_w"] < 0.0
    assert len(status["active_devices"]) == 3


def test_time_advance_guard_requires_occupied_environment_reconciliation() -> None:
    scenario = L3_SCENARIO_CLASSES[19]()
    scenario.setup()
    Engine(None, scenario)
    operations = scenario.get_typed_app(BuildingOperationsApp)
    system = scenario.get_typed_app(SystemApp)
    hvac = scenario.get_typed_app(HvacApp)

    # Reach the first office occupancy event through the domain runtime. The
    # next Agent-facing clock advance must first reconcile observed conditions.
    initial_advance = system.advance_time(minutes=30)
    assert initial_advance["status"] == "ok"
    rejected = system.advance_time(minutes=5)
    assert rejected["status"] == "rejected"
    assert rejected["details"]["code"] == "environment_reconciliation_required"

    status = operations.get_environment_control_status()
    assert status["occupied_environment_stable"] is False
    rejected = system.advance_time(minutes=5)
    assert rejected["details"]["code"] == "occupied_environment_uncontrolled"
    assert any(
        item.get("device_type") == "hvac"
        and item.get("minimum_level") == 3
        for item in rejected["details"]["missing_controls"]
    )

    hvac.set_hvac("k1324_hvac_01", True, "cooling", 24.0, 3)
    operations.get_environment_control_status()
    accepted = system.advance_time(minutes=5)
    assert accepted["status"] == "ok"


def test_agent_rejects_premature_final_response_and_retries() -> None:
    agent = Agent(
        "guard-test",
        SimpleNamespace(provider="openai", model="fake"),
        toolsets=[],
    )
    messages = [
        SimpleNamespace(content="premature", tool_calls=None),
        SimpleNamespace(content="complete", tool_calls=None),
    ]
    agent._chat_completion_with_retries = lambda *_args, **_kwargs: messages.pop(0)  # type: ignore[method-assign]
    guard_results = iter(
        (
            {
                "can_finish": False,
                "blockers": [{"code": "operational_horizon_not_reached"}],
            },
            {"can_finish": True, "blockers": []},
        )
    )
    agent.completion_guard = lambda: next(guard_results)

    answer = agent.run("operate through the horizon", timeout_seconds=5)

    assert answer == "complete"
    assert agent.completion_guard_rejections == 1
    assert any(
        event["event_type"] == "completion_guard_rejected"
        for event in agent.runtime_events
    )
