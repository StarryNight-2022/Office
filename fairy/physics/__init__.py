"""Physics namespace shared by independent domain packages.

The root package intentionally imports no domain implementation.  Legacy Farm
symbols remain available lazily so existing scenarios keep working without
making ``fairy.physics.building`` import Farm dependencies such as NumPy.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_FARM_EXPORT_MODULES: dict[str, str] = {}


def _exports(module: str, names: str) -> None:
    for name in names.split():
        _FARM_EXPORT_MODULES[name] = module


_exports(
    "fairy.physics.farm.weather_engine",
    "MonthlyClimate WeatherDay WeatherEvent WeatherGenerator WeatherGeneratorConfig",
)
_exports(
    "fairy.physics.farm.soil_engine",
    "RidgeSoilState SoilDayResult SoilEngine SoilHydraulicModifier SoilParameters",
)
_FARM_EXPORT_MODULES["SoilWeatherInput"] = "fairy.physics.farm.soil_engine"
_exports(
    "fairy.physics.farm.phenology_engine",
    "PhenologyDayResult PhenologyParameters PhenologySoilInput PhenologyState "
    "PhenologyWeatherInput PlantingConfig SeedType SeedTypeParameters SoybeanStage "
    "ThermalTimePhenologyEngine",
)
_exports(
    "fairy.physics.farm.canopy_biomass_engine",
    "CanopyBiomassDayResult CanopyBiomassGrowthEngine CanopyBiomassParameters "
    "CanopyBiomassState GrowthSoilInput GrowthWeatherInput ManagementStressInput "
    "SeedGrowthParameters",
)
_FARM_EXPORT_MODULES["CanopyPhenologyInput"] = (
    "fairy.physics.farm.canopy_biomass_engine"
)
_exports(
    "fairy.physics.farm.biotic_pressure_engine",
    "BioticCropInput BioticPressureDayResult BioticPressureEngine "
    "BioticPressureParameters BioticPressureState BioticSoilInput BioticWeatherInput "
    "SeedBioticResistanceParameters TreatmentApplication TreatmentType",
)
_exports(
    "fairy.physics.farm.management_effect_engine",
    "ManagementAction ManagementActionType ManagementCropInput ManagementEffectDayResult "
    "ManagementEffectEngine ManagementEffectParameters ManagementEffectState "
    "ManagementSoilInput ManagementWeatherInput",
)
_exports(
    "fairy.physics.farm.yield_recovery_engine",
    "HarvestAction YieldGrowthInput YieldPhenologyInput YieldRecoveryDayResult "
    "YieldRecoveryEngine YieldRecoveryParameters YieldRecoveryState YieldStressInput "
    "YieldWeatherInput",
)
_exports(
    "fairy.physics.farm.observation_model",
    "HiddenRidgeTruth ObservationModality ObservationModel ObservationModelParameters "
    "ObservationProduct ObservationProductType SensorAsset",
)

__all__ = sorted(_FARM_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    module_name = _FARM_EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    # Two historical aliases use a different class name in their source file.
    source_name = {
        "SoilWeatherInput": "WeatherInput",
        "CanopyPhenologyInput": "PhenologyInput",
    }.get(name, name)
    value = getattr(module, source_name)
    globals()[name] = value
    return value
