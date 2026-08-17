"""Deterministic HVAC command tools; physics effects occur in the runtime."""

from __future__ import annotations

from typing import Any

from fairy.apps.app import App
from fairy.apps.building_world.building_world_app import BuildingWorldApp
from fairy.apps.building_world.types import (
    BuildingEventType,
    DeviceHealth,
    DeviceType,
)
from fairy.tool_utils import OperationType, app_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class HvacApp(App):
    def __init__(self, world: BuildingWorldApp) -> None:
        super().__init__(name="HvacApp")
        self.world = world

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def set_hvac(
        self,
        device_id: str,
        power_on: bool,
        mode: str,
        target_temperature_c: float,
        fan_level: int,
    ) -> dict[str, Any]:
        spec = self.world.devices.get(device_id)
        state = self.world.device_states.get(device_id)
        if spec is None or state is None:
            return _rejected("unknown_device", device_id=device_id)
        if spec.device_type != DeviceType.HVAC:
            return _rejected("wrong_device_type", device_id=device_id)
        if state.health != DeviceHealth.ONLINE:
            return _rejected("device_unavailable", health=state.health.value)
        if mode not in {"off", "cooling", "heating", "fan"}:
            return _rejected("unsupported_mode", mode=mode)
        if not 16.0 <= target_temperature_c <= 30.0:
            return _rejected("target_temperature_out_of_range")
        if power_on and mode == "off":
            return _rejected("active_hvac_requires_operating_mode")
        if power_on and fan_level not in {1, 2, 3}:
            return _rejected("invalid_fan_level")
        if not power_on and fan_level not in {0, 1, 2, 3}:
            return _rejected("invalid_fan_level")

        state.power_on = bool(power_on)
        state.mode = mode if power_on else "off"
        state.target_temperature_c = (
            float(target_temperature_c) if power_on else None
        )
        state.level = fan_level if power_on else 0
        event = self.world.publish_building_event(
            BuildingEventType.DEVICE_STATE_CHANGED,
            source=self.name,
            subject_id=device_id,
            payload={
                "power_on": state.power_on,
                "mode": state.mode,
                "target_temperature_c": state.target_temperature_c,
                "fan_level": state.level,
            },
        )
        return {
            "status": "accepted",
            "device_id": device_id,
            "event_id": event.event_id,
            "message": "command accepted; verify physical effect using sensors",
        }


def _rejected(reason: str, **details: Any) -> dict[str, Any]:
    return {"status": "rejected", "reason": reason, **details}
