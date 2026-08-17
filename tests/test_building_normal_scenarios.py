import pytest

from fairy.apps.building_world import BuildingEventType
from fairy.controllers.engine import Engine
from fairy.scenarios.building_k1324.scenario_climate_coordination import (
    ScenarioBuildingK1324ClimateCoordination,
)
from fairy.scenarios.building_k1324.scenario_conference_standard import (
    ScenarioBuildingK1324ConferenceStandard,
)
from fairy.scenarios.building_k1324.scenario_occupancy_ramp import (
    OCCUPANCY_TIMELINE,
    ScenarioBuildingK1324OccupancyRamp,
)
from fairy.scenarios.registry import get_scenario_class


def _replay(scenario_class):
    build_engine = Engine(None, scenario_class())
    oracle = build_engine.build_oracle_workflow(run_oracle=False)
    replay_engine = Engine(None, scenario_class())
    replayed = replay_engine.replay_workflow(oracle)
    report = replay_engine.evaluation_report(replayed)
    return oracle, replay_engine, replayed, report


@pytest.mark.parametrize(
    "scenario_class",
    [
        ScenarioBuildingK1324ConferenceStandard,
        ScenarioBuildingK1324ClimateCoordination,
        ScenarioBuildingK1324OccupancyRamp,
    ],
)
def test_normal_scenario_oracle_replay_validates(scenario_class) -> None:
    oracle, _, replayed, report = _replay(scenario_class)

    assert len(oracle.dag) == len(replayed.dag)
    assert report["validation"]["success"] is True


def test_standard_conference_runs_ordered_lifecycle_and_cleanup() -> None:
    _, replay_engine, replayed, report = _replay(
        ScenarioBuildingK1324ConferenceStandard
    )
    metadata = report["validation"]["metadata"]

    assert metadata["lifecycle_events"] == [
        BuildingEventType.MEETING_PREPARATION_DUE.value,
        BuildingEventType.OCCUPANCY_CHANGED.value,
        BuildingEventType.MEETING_STARTED.value,
        BuildingEventType.MEETING_ENDED.value,
    ]
    assert metadata["energy_kwh"] > 0.0
    assert len(replayed.dag["verify_at_meeting_start"].content["readings"]) == 4
    wake_types = {
        item["event_type"]
        for item in replay_engine.scenario.building_runtime.trace
        if item.get("kind") == "trigger_decision"
        and item.get("should_wake_agent")
    }
    assert BuildingEventType.MEETING_PREPARATION_DUE.value in wake_types
    assert BuildingEventType.MEETING_ENDED.value in wake_types


def test_climate_coordination_observes_cooling_and_humidity() -> None:
    _, _, replayed, report = _replay(ScenarioBuildingK1324ClimateCoordination)
    metadata = report["validation"]["metadata"]

    assert metadata["final_temperature_c"] < metadata["initial_temperature_c"]
    assert 40.0 <= metadata["final_relative_humidity_pct"] <= 65.0
    assert metadata["environment_checks"] == 2
    for step_id in (
        "read_after_cooling",
        "read_coordinated_climate",
        "read_final_climate",
    ):
        assert len(replayed.dag[step_id].content["readings"]) == 4


def test_occupancy_ramp_records_planned_counts_and_co2_recovery() -> None:
    _, _, _, report = _replay(ScenarioBuildingK1324OccupancyRamp)
    metadata = report["validation"]["metadata"]

    assert metadata["occupancy_counts"] == [
        count for _, count in OCCUPANCY_TIMELINE
    ]
    assert metadata["peak_co2_ppm"] > metadata["initial_co2_ppm"]
    assert metadata["final_co2_ppm"] < metadata["peak_co2_ppm"]


@pytest.mark.parametrize(
    ("scenario_id", "scenario_class"),
    [
        (
            "scenario_building_k1324_conference_standard",
            ScenarioBuildingK1324ConferenceStandard,
        ),
        (
            "scenario_building_k1324_climate_coordination",
            ScenarioBuildingK1324ClimateCoordination,
        ),
        (
            "scenario_building_k1324_occupancy_ramp",
            ScenarioBuildingK1324OccupancyRamp,
        ),
    ],
)
def test_normal_scenario_is_registered(scenario_id, scenario_class) -> None:
    assert get_scenario_class(scenario_id) is scenario_class
