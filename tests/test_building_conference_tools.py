from datetime import datetime, timezone
from pathlib import Path

from fairy.apps.building_world import (
    LightingApp,
    MeetingEquipmentApp,
    PrintingApp,
    VentilationApp,
)
from fairy.apps.building_world.room_loader import load_room_configuration
from fairy.apps.building_world.runtime import (
    BuildingWorldRuntime,
    constant_outdoor_provider,
)
from fairy.apps.system import SystemApp
from fairy.controllers.engine import Engine
from fairy.physics.building import OutdoorConditions
from fairy.scenarios.building_k1324.scenario_conference_standard import (
    ScenarioBuildingK1324ConferenceStandard,
)

CONFIG_PATH = Path(__file__).parents[1] / "fairy" / "configs" / "rooms" / "k1315.yaml"
ZONE_ID = "k1315_conference_zone"


def _runtime() -> BuildingWorldRuntime:
    return BuildingWorldRuntime.from_room_configuration(
        load_room_configuration(CONFIG_PATH),
        start_at=datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc),
        outdoor_provider=constant_outdoor_provider(
            OutdoorConditions(
                air_temperature_c=30.0,
                relative_humidity_pct=65.0,
                co2_ppm=420.0,
                pm25_ug_m3=25.0,
            )
        ),
    )


def test_ventilation_reduces_occupied_room_co2_and_consumes_energy() -> None:
    without_ventilation = _runtime()
    with_ventilation = _runtime()
    without_ventilation.world.room_states["k1315"].occupancy_count = 12
    with_ventilation.world.room_states["k1315"].occupancy_count = 12

    command = VentilationApp(with_ventilation.world).set_ventilation(
        "k1315_ventilation_01", True, 3
    )
    without_ventilation.advance_by(30 * 60)
    with_ventilation.advance_by(30 * 60)

    assert command["status"] == "accepted"
    assert with_ventilation.physics.engine.get_state()[ZONE_ID].co2_ppm < (
        without_ventilation.physics.engine.get_state()[ZONE_ID].co2_ppm
    )
    assert with_ventilation.physics.cumulative_energy_kwh_by_zone[ZONE_ID] > 0.0


def test_meeting_tools_track_settings_print_completion_and_cleanup() -> None:
    scenario = ScenarioBuildingK1324ConferenceStandard()
    Engine(None, scenario).build_oracle_workflow(run_oracle=False)
    lighting = scenario.get_typed_app(LightingApp)
    equipment = scenario.get_typed_app(MeetingEquipmentApp)
    printing = scenario.get_typed_app(PrintingApp)
    system = scenario.get_typed_app(SystemApp)

    assert (
        lighting.set_lighting(
            "k1315_lighting_front_01", True, 45, 4000, "presentation"
        )["status"]
        == "accepted"
    )
    assert (
        equipment.set_projector("k1315_projector_01", True, "hdmi")["status"]
        == "accepted"
    )
    assert (
        equipment.set_audio_system("k1315_audio_01", True, 55, True)["status"]
        == "accepted"
    )
    assert equipment.get_meeting_equipment_readiness("k1315")["ready"] is True

    assert printing.set_printer_power("k1315_printer_01", True)["status"] == "accepted"
    submitted = printing.submit_print_job(
        "k1315_printer_01", "conference_materials", 12, 2, "staff-01"
    )
    assert submitted["status"] == "accepted"
    assert printing.get_print_job(submitted["job_id"])["status"] == "printing"
    system.advance_time(minutes=2)
    assert printing.get_print_job(submitted["job_id"])["status"] == "completed"

    equipment.set_projector("k1315_projector_01", False, "off")
    equipment.set_audio_system("k1315_audio_01", False, 0, False)
    assert equipment.get_meeting_equipment_readiness("k1315")["ready"] is False
