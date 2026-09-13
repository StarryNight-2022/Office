"""Generated from l1/manifest.json; do not edit this module directly."""

from fairy.scenarios.building_kechuang.l1.base import (
    ManifestDrivenBuildingL1Scenario,
    contract_timestamp,
)
from fairy.scenarios.building_kechuang.l1.manifest import load_contract
from fairy.scenarios.registry import register_scenario

CONTRACT = load_contract("scenario_building_kechuang_l1_meeting_requirement_change")


@register_scenario("scenario_building_kechuang_l1_meeting_requirement_change")
class ScenarioBuildingKechuangL1MeetingRequirementChange(ManifestDrivenBuildingL1Scenario):
    contract_id = "scenario_building_kechuang_l1_meeting_requirement_change"
    start_time: float | None = contract_timestamp(CONTRACT)
    duration: float | None = float(CONTRACT["duration_seconds"])
    time_increment_in_seconds: int = 60
    scenario_input: str = CONTRACT["task"]["prompt"]
