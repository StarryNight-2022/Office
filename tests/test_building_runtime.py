import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fairy.apps.building_world import AirDeviceApp, BuildingEventType, HvacApp
from fairy.apps.building_world.room_loader import load_room_configuration
from fairy.apps.building_world.runtime import (
    BuildingWorldRuntime,
    constant_outdoor_provider,
)
from fairy.apps.building_world.sensor_app import BuildingSensorApp
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.physics.building import OutdoorConditions, SensorReadRequest
from fairy.scenarios.building_k1324.scenario_meeting_booking import (
    ScenarioBuildingK1324MeetingBooking,
)

CONFIG_PATH = Path(__file__).parents[1] / "fairy" / "configs" / "rooms" / "k1324.yaml"
START_AT = datetime(2026, 9, 10, 5, 0, tzinfo=timezone.utc)
ZONE_ID = "k1324_meeting_zone"


def _runtime() -> BuildingWorldRuntime:
    return BuildingWorldRuntime.from_room_configuration(
        load_room_configuration(CONFIG_PATH),
        start_at=START_AT,
        outdoor_provider=constant_outdoor_provider(
            OutdoorConditions(
                air_temperature_c=32.0,
                relative_humidity_pct=70.0,
                co2_ppm=420.0,
                pm25_ug_m3=45.0,
            )
        ),
    )


def test_room_loader_builds_business_physics_device_and_sensor_models() -> None:
    config = load_room_configuration(CONFIG_PATH)

    assert config.room.room_id == "k1324"
    assert list(config.zone_parameters) == [ZONE_ID]
    assert config.zone_parameters[ZONE_ID].volume_m3 == pytest.approx(150.0)
    assert {area.area_id for area in config.functional_areas} == {
        "k1324_presentation_area",
        "k1324_audience_front",
        "k1324_audience_rear",
        "k1324_entrance_area",
        "k1324_service_area",
    }
    assert {device.device_id for device in config.devices} >= {
        "k1324_hvac_01",
        "k1324_humidifier_01",
        "k1324_purifier_01",
    }
    assert len(config.sensors) == 4

    world = _runtime().world
    snapshot = world.snapshot()
    assert len(snapshot["functional_areas"]) == 5
    assert (
        next(
            device
            for device in snapshot["devices"]
            if device["device_id"] == "k1324_projector_01"
        )["functional_area_id"]
        == "k1324_presentation_area"
    )


def test_room_loader_rejects_unknown_device_zone(tmp_path: Path) -> None:
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["devices"][0]["zone_id"] = "missing"
    invalid = tmp_path / "invalid-room.yaml"
    invalid.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown zone"):
        load_room_configuration(invalid)


def test_cooling_humidification_energy_events_and_checkpoint() -> None:
    runtime = _runtime()
    world = runtime.world
    hvac = HvacApp(world)
    air = AirDeviceApp(world)
    initial = runtime.physics.engine.get_state()[ZONE_ID]

    accepted = hvac.set_hvac(
        "k1324_hvac_01", True, "cooling", target_temperature_c=22.0, fan_level=3
    )
    assert accepted["status"] == "accepted"
    runtime.advance_by(30 * 60)
    cooled = runtime.physics.engine.get_state()[ZONE_ID]
    checkpoint = runtime.snapshot()
    energy_after_cooling = runtime.physics.cumulative_energy_kwh_by_zone[ZONE_ID]

    assert cooled.air_temperature_c < initial.air_temperature_c
    assert cooled.relative_humidity_pct < initial.relative_humidity_pct
    assert energy_after_cooling > 0.0
    assert any(
        event.event_type == BuildingEventType.SENSOR_UPDATED for event in world.events
    )

    assert air.set_humidifier("k1324_humidifier_01", True, 3)["status"] == ("accepted")
    runtime.advance_by(15 * 60)
    humidified = runtime.physics.engine.get_state()[ZONE_ID]
    assert humidified.relative_humidity_pct > cooled.relative_humidity_pct
    assert runtime.physics.cumulative_energy_kwh_by_zone[ZONE_ID] > (
        energy_after_cooling
    )

    readings = runtime.sensors.read(
        SensorReadRequest(
            at_time=runtime.current_time,
            zone_ids=(ZONE_ID,),
        )
    )
    assert len(readings) == 4

    runtime.restore(checkpoint)
    restored = runtime.physics.engine.get_state()[ZONE_ID]
    assert restored.relative_humidity_pct == pytest.approx(cooled.relative_humidity_pct)
    assert world.device_states["k1324_humidifier_01"].power_on is False
    assert runtime.physics.cumulative_energy_kwh_by_zone[ZONE_ID] == pytest.approx(
        energy_after_cooling
    )


def test_k1324_system_time_advance_drives_runtime_and_sensor_app() -> None:
    scenario = ScenarioBuildingK1324MeetingBooking()
    engine = Engine(None, scenario)
    engine.build_oracle_workflow(run_oracle=False)
    hvac = scenario.get_typed_app(HvacApp)
    system = scenario.get_typed_app(SystemApp)
    sensors = scenario.get_typed_app(BuildingSensorApp)
    runtime = scenario.building_runtime
    before = runtime.physics.engine.get_state()[ZONE_ID].air_temperature_c

    assert (
        hvac.set_hvac("k1324_hvac_01", True, "cooling", 22.0, 3)["status"] == "accepted"
    )
    assert system.advance_time(minutes=5)["status"] == "ok"

    after = runtime.physics.engine.get_state()[ZONE_ID].air_temperature_c
    response = sensors.read_zone_sensors(ZONE_ID)
    assert after < before
    assert len(response["readings"]) == 4
