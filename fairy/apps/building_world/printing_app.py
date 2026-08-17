"""Deterministic printer controls and time-aware meeting print jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fairy.apps.app import App
from fairy.apps.building_world.building_world_app import BuildingWorldApp
from fairy.apps.building_world.types import BuildingEventType, DeviceHealth, DeviceType
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class PrintingApp(App):
    """Own print-job workflow while World remains the device-state authority."""

    def __init__(self, world: BuildingWorldApp) -> None:
        super().__init__(name="PrintingApp")
        self.world = world
        self.jobs: dict[str, dict[str, Any]] = {}

    def reset(self) -> None:
        super().reset()
        self.jobs = {}

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def set_printer_power(self, device_id: str, power_on: bool) -> dict[str, Any]:
        spec = self.world.devices.get(device_id)
        state = self.world.device_states.get(device_id)
        if spec is None or state is None:
            return _rejected("unknown_device", device_id=device_id)
        if spec.device_type != DeviceType.PRINTER:
            return _rejected("wrong_device_type", device_id=device_id)
        if state.health != DeviceHealth.ONLINE:
            return _rejected("device_unavailable", health=state.health.value)
        state.power_on = power_on
        state.mode = "ready" if power_on else "off"
        state.level = 1 if power_on else 0
        event = self.world.publish_building_event(
            BuildingEventType.DEVICE_STATE_CHANGED,
            source=self.name,
            subject_id=device_id,
            payload={"power_on": power_on},
        )
        return {
            "status": "accepted",
            "device_id": device_id,
            "event_id": event.event_id,
        }

    @type_check
    @app_tool()
    @event_registered(operation_type=OperationType.WRITE)
    def submit_print_job(
        self,
        printer_id: str,
        document_name: str,
        copies: int,
        pages_per_copy: int,
        requested_by: str,
    ) -> dict[str, Any]:
        spec = self.world.devices.get(printer_id)
        state = self.world.device_states.get(printer_id)
        if spec is None or state is None:
            return _rejected("unknown_device", device_id=printer_id)
        if spec.device_type != DeviceType.PRINTER:
            return _rejected("wrong_device_type", device_id=printer_id)
        if state.health != DeviceHealth.ONLINE or not state.power_on:
            return _rejected("printer_not_ready", device_id=printer_id)
        if copies <= 0 or pages_per_copy <= 0:
            return _rejected("invalid_page_count")

        now = self._now()
        pages = copies * pages_per_copy
        pages_per_minute = float(spec.parameters.get("pages_per_minute", 20.0))
        duration_seconds = max(1.0, pages / pages_per_minute * 60.0)
        job_id = self.world.next_id("print-job")
        self.jobs[job_id] = {
            "job_id": job_id,
            "printer_id": printer_id,
            "document_name": document_name,
            "copies": copies,
            "pages_per_copy": pages_per_copy,
            "requested_by": requested_by,
            "status": "printing",
            "submitted_at": now.isoformat(),
            "ready_at_timestamp": now.timestamp() + duration_seconds,
        }
        event = self.world.publish_building_event(
            BuildingEventType.PRINT_JOB_SUBMITTED,
            source=self.name,
            subject_id=job_id,
            payload={"printer_id": printer_id, "pages": pages},
        )
        return {
            "status": "accepted",
            "job_id": job_id,
            "event_id": event.event_id,
            "estimated_duration_seconds": duration_seconds,
        }

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_print_job(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        if job is None:
            return _rejected("unknown_print_job", job_id=job_id)
        if job["status"] == "printing" and self._now().timestamp() >= float(
            job["ready_at_timestamp"]
        ):
            job["status"] = "completed"
            self.world.publish_building_event(
                BuildingEventType.PRINT_JOB_COMPLETED,
                source=self.name,
                subject_id=job_id,
                payload={"printer_id": job["printer_id"]},
            )
        return {key: value for key, value in job.items() if key != "ready_at_timestamp"}

    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.time_manager.time(), tz=timezone.utc)


def _rejected(reason: str, **details: Any) -> dict[str, Any]:
    return {"status": "rejected", "reason": reason, **details}
