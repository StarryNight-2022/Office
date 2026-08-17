"""Translate device command state into hardware-independent physics inputs."""

from __future__ import annotations

from collections import defaultdict
from typing import Mapping

from fairy.apps.building_world.types import (
    DeviceHealth,
    DeviceSpec,
    DeviceState,
    DeviceType,
)
from fairy.physics.building.models import HvacCommand, HvacMode, ZoneState


class BuildingEquipmentModel:
    """Aggregate all active devices in a zone into one ``HvacCommand``."""

    def commands_by_zone(
        self,
        devices: Mapping[str, DeviceSpec],
        states: Mapping[str, DeviceState],
        zone_truth: Mapping[str, ZoneState],
    ) -> dict[str, HvacCommand]:
        values: dict[str, dict[str, float | HvacMode]] = defaultdict(
            lambda: {
                "mode": HvacMode.OFF,
                "heating_w": 0.0,
                "cooling_w": 0.0,
                "outdoor_airflow_m3_s": 0.0,
                "humidification_g_s": 0.0,
                "clean_air_delivery_m3_s": 0.0,
                "auxiliary_electric_power_w": 0.0,
            }
        )
        for device_id, spec in devices.items():
            state = states[device_id]
            if not state.power_on or state.health != DeviceHealth.ONLINE:
                continue
            level_fraction = max(1, min(3, state.level)) / 3.0
            row = values[spec.zone_id]
            if spec.device_type == DeviceType.HVAC:
                mode = HvacMode(state.mode)
                row["mode"] = mode
                capacity = _number(spec, "thermal_capacity_w", 0.0)
                target = state.target_temperature_c
                truth = zone_truth[spec.zone_id].air_temperature_c
                demand = 1.0
                if target is not None:
                    delta = (
                        truth - target
                        if mode == HvacMode.COOLING
                        else target - truth
                    )
                    demand = max(0.0, min(1.0, delta / 3.0))
                delivered = capacity * level_fraction * demand
                if mode == HvacMode.COOLING:
                    row["cooling_w"] = float(row["cooling_w"]) + delivered
                elif mode == HvacMode.HEATING:
                    row["heating_w"] = float(row["heating_w"]) + delivered
                row["outdoor_airflow_m3_s"] = float(
                    row["outdoor_airflow_m3_s"]
                ) + _number(spec, "outdoor_airflow_m3_s", 0.0) * level_fraction
                row["auxiliary_electric_power_w"] = float(
                    row["auxiliary_electric_power_w"]
                ) + _number(spec, "fan_power_w", spec.rated_power_w) * level_fraction
            elif spec.device_type == DeviceType.HUMIDIFIER:
                row["humidification_g_s"] = float(
                    row["humidification_g_s"]
                ) + _number(spec, "humidification_g_s_max", 0.0) * level_fraction
                row["auxiliary_electric_power_w"] = float(
                    row["auxiliary_electric_power_w"]
                ) + spec.rated_power_w * level_fraction
            elif spec.device_type == DeviceType.AIR_PURIFIER:
                row["clean_air_delivery_m3_s"] = float(
                    row["clean_air_delivery_m3_s"]
                ) + _number(spec, "clean_air_delivery_m3_s_max", 0.0) * level_fraction
                row["auxiliary_electric_power_w"] = float(
                    row["auxiliary_electric_power_w"]
                ) + spec.rated_power_w * level_fraction

        return {
            zone_id: HvacCommand(**row)  # type: ignore[arg-type]
            for zone_id, row in values.items()
        }


def _number(spec: DeviceSpec, name: str, default: float) -> float:
    value = spec.parameters.get(name, default)
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"device {spec.device_id!r} parameter {name!r} is invalid"
        ) from exc
