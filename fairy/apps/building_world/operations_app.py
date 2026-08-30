"""Public operating contract and completion guard for long Building runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fairy.apps.app import App
from fairy.apps.building_world.building_world_app import BuildingWorldApp
from fairy.apps.building_world.printing_app import PrintingApp
from fairy.apps.building_world.runtime import BuildingWorldRuntime
from fairy.apps.building_world.types import (
    DeviceHealth,
    DeviceType,
    MeetingStatus,
    ReservationStatus,
)
from fairy.physics.building.sensor_api import SensorQuantity
from fairy.physics.building.orchestrator import (
    CO2_WARNING_THRESHOLD_PPM,
    PM25_WARNING_THRESHOLD_UG_M3,
)
from fairy.tool_utils import OperationType, app_tool, data_tool
from fairy.types import event_registered
from fairy.utils.type_utils import type_check


class BuildingOperationsApp(App):
    """Expose what must remain true across a complete operational horizon.

    The App publishes policy and current observations, never simulator truth or
    future event payloads.  Its internal completion result is also consumed by
    the controller so a model cannot end while known commitments remain open.
    """

    completion_guard_enabled = True

    def __init__(
        self,
        *,
        world: BuildingWorldApp,
        runtime: BuildingWorldRuntime,
        printing: PrintingApp,
        operational_end_at: datetime,
        target_temperature_c: float,
        max_co2_ppm: float,
        max_pm25_ug_m3: float,
        power_limit_w: float | None = None,
    ) -> None:
        super().__init__(name="BuildingOperationsApp")
        if operational_end_at.tzinfo is None:
            raise ValueError("operational_end_at must be timezone-aware")
        self.world = world
        self.runtime = runtime
        self.printing = printing
        self.operational_end_at = operational_end_at
        self.target_temperature_c = float(target_temperature_c)
        self.max_co2_ppm = float(max_co2_ppm)
        self.max_pm25_ug_m3 = float(max_pm25_ug_m3)
        self.power_limit_w = (
            float(power_limit_w) if power_limit_w is not None else None
        )
        self._last_environment_check_at: datetime | None = None
        self._last_environment_device_event_count = -1
        self._last_environment_status: dict[str, Any] | None = None

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_operational_status(self) -> dict[str, Any]:
        """Return horizon progress and blockers that must clear before finishing.

        The next scheduled timestamp is public, but its hidden event type and
        payload are not disclosed before occurrence.
        """

        return self.completion_status()

    def completion_status(self) -> dict[str, Any]:
        """Return the controller-facing completion decision without side effects."""

        now = self.runtime.current_time
        next_event_at = self.runtime.event_queue.next_time()
        occupied_rooms = {
            room_id: state.occupancy_count
            for room_id, state in self.world.room_states.items()
            if state.occupancy_count > 0
        }
        open_meetings = [
            meeting.meeting_id
            for meeting in self.world.schedule.values()
            if meeting.status == MeetingStatus.CONFIRMED
        ]
        active_reservations = [
            reservation.reservation_id
            for reservation in self.world.reservations.values()
            if reservation.status == ReservationStatus.ACTIVE
        ]
        unfinished_print_requests = [
            request_id
            for request_id, request in self.printing.requests.items()
            if request["status"] != "completed"
        ]
        active_devices = [
            device_id
            for device_id, state in self.world.device_states.items()
            if state.power_on
        ]
        blockers: list[dict[str, Any]] = []
        if now < self.operational_end_at:
            blockers.append(
                {
                    "code": "operational_horizon_not_reached",
                    "minutes_remaining": (
                        self.operational_end_at - now
                    ).total_seconds()
                    / 60.0,
                }
            )
        if next_event_at is not None and next_event_at <= self.operational_end_at:
            blockers.append(
                {
                    "code": "scheduled_event_pending",
                    "next_event_at": next_event_at.isoformat(),
                    "minutes_until_event": (next_event_at - now).total_seconds()
                    / 60.0,
                }
            )
        if occupied_rooms:
            blockers.append({"code": "rooms_occupied", "rooms": occupied_rooms})
        if open_meetings:
            blockers.append({"code": "meetings_open", "meeting_ids": open_meetings})
        if active_reservations:
            blockers.append(
                {
                    "code": "reservations_active",
                    "reservation_ids": active_reservations,
                }
            )
        if unfinished_print_requests:
            blockers.append(
                {
                    "code": "print_requests_unfinished",
                    "request_ids": unfinished_print_requests,
                }
            )
        if active_devices:
            blockers.append(
                {"code": "devices_still_on", "device_ids": active_devices}
            )
        return {
            "status": "ok",
            "can_finish": not blockers,
            "current_time": now.isoformat(),
            "operational_end_at": self.operational_end_at.isoformat(),
            "next_scheduled_event_at": (
                next_event_at.isoformat() if next_event_at is not None else None
            ),
            "blockers": blockers,
        }

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_meeting_readiness(self, meeting_id: str) -> dict[str, Any]:
        """Return the explicit device checklist for one currently known meeting."""

        meeting = self.world.schedule.get(meeting_id)
        if meeting is None or meeting.status != MeetingStatus.CONFIRMED:
            return {"error": f"unknown confirmed meeting_id {meeting_id!r}"}
        required_devices = {
            f"{meeting.room_id}_hvac_01": "thermal_control",
            f"{meeting.room_id}_ventilation_01": "outdoor_air_control",
        }
        if "projector" in meeting.required_capabilities:
            required_devices[f"{meeting.room_id}_projector_01"] = "projector"
        if {"audio", "microphone"} & set(meeting.required_capabilities):
            required_devices[f"{meeting.room_id}_audio_01"] = "audio_microphone"
        checklist = []
        for device_id, purpose in required_devices.items():
            state = self.world.device_states.get(device_id)
            checklist.append(
                {
                    "device_id": device_id,
                    "purpose": purpose,
                    "exists": state is not None,
                    "power_on": bool(state.power_on) if state is not None else False,
                    "ready": bool(state is not None and state.power_on),
                }
            )
        now = self.runtime.current_time
        return {
            "meeting_id": meeting_id,
            "room_id": meeting.room_id,
            "start_at": meeting.start_at.isoformat(),
            "minutes_until_start": (meeting.start_at - now).total_seconds() / 60.0,
            "required_capabilities": list(meeting.required_capabilities),
            "ready": all(item["ready"] for item in checklist),
            "checklist": checklist,
        }

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_commitment_status(self) -> dict[str, Any]:
        """Return public commitments ordered by their next actionable deadline.

        This combines the public schedule and print queue so the controller can
        prioritize a near deadline before spending simulated time on lower-risk
        comfort tuning. It does not expose scheduled interaction events that
        have not happened yet.
        """

        now = self.runtime.current_time
        meetings = []
        for meeting in self.world.schedule.values():
            if meeting.status != MeetingStatus.CONFIRMED:
                continue
            readiness = self.get_meeting_readiness(meeting.meeting_id)
            minutes_until_start = (meeting.start_at - now).total_seconds() / 60.0
            meetings.append(
                {
                    "commitment_type": "meeting",
                    "meeting_id": meeting.meeting_id,
                    "room_id": meeting.room_id,
                    "start_at": meeting.start_at.isoformat(),
                    "minutes_until_deadline": minutes_until_start,
                    "urgent": minutes_until_start <= 60.0,
                    "ready": readiness["ready"],
                    "missing_device_ids": [
                        item["device_id"]
                        for item in readiness["checklist"]
                        if not item["ready"]
                    ],
                }
            )

        print_requests = []
        for request_id, request in self.printing.requests.items():
            if request["status"] == "completed":
                continue
            ready_by = datetime.fromisoformat(str(request["ready_by"]))
            minutes_until_deadline = (ready_by - now).total_seconds() / 60.0
            print_requests.append(
                {
                    "commitment_type": "print_request",
                    "request_id": request_id,
                    "document_name": request["document_name"],
                    "copies": request["copies"],
                    "pages_per_copy": request["pages_per_copy"],
                    "priority": request["priority"],
                    "ready_by": ready_by.isoformat(),
                    "minutes_until_deadline": minutes_until_deadline,
                    "urgent": minutes_until_deadline <= 60.0,
                    "status": request["status"],
                    "job_id": request.get("job_id"),
                }
            )

        commitments = sorted(
            [*meetings, *print_requests],
            key=lambda item: float(item["minutes_until_deadline"]),
        )
        return {
            "status": "ok",
            "current_time": now.isoformat(),
            "commitments": commitments,
            "urgent_commitments": [item for item in commitments if item["urgent"]],
            "rule": (
                "Complete urgent print work and meeting readiness before advancing "
                "time for non-urgent environment tuning."
            ),
        }

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_power_budget_status(self) -> dict[str, Any]:
        """Estimate configured maximum draw from current public device states.

        HVAC compressor draw varies with thermal demand. The estimate therefore
        assumes full demand at the commanded level; staying under this bound is
        a safe precondition before advancing simulated time.
        """

        active_devices = []
        estimated_power_w = 0.0
        for device_id, spec in self.world.devices.items():
            state = self.world.device_states[device_id]
            if not state.power_on or state.health != DeviceHealth.ONLINE:
                continue
            level_fraction = max(1, min(3, state.level)) / 3.0
            estimate = spec.rated_power_w
            if spec.device_type == DeviceType.HVAC:
                fan_power = float(
                    spec.parameters.get("fan_power_w", spec.rated_power_w)
                ) * level_fraction
                if state.mode in {"cooling", "heating"}:
                    capacity = float(
                        spec.parameters.get("thermal_capacity_w", 0.0)
                    ) * level_fraction
                    cop = 3.2 if state.mode == "cooling" else 3.0
                    estimate = fan_power + capacity / cop
                else:
                    estimate = fan_power
            elif spec.device_type in {
                DeviceType.VENTILATION,
                DeviceType.HUMIDIFIER,
                DeviceType.AIR_PURIFIER,
            }:
                estimate = spec.rated_power_w * level_fraction
            elif spec.device_type == DeviceType.LIGHTING:
                estimate = spec.rated_power_w * (
                    float(state.settings.get("brightness_pct", 100.0)) / 100.0
                )
            estimated_power_w += estimate
            active_devices.append(
                {
                    "device_id": device_id,
                    "room_id": spec.room_id,
                    "device_type": spec.device_type.value,
                    "level": state.level,
                    "estimated_max_power_w": estimate,
                }
            )

        latest_measured_w = None
        for item in reversed(self.runtime.trace):
            if item.get("kind") == "physics_step":
                latest_measured_w = sum(
                    float(zone.get("electric_power_w", 0.0))
                    for zone in item.get("zones", [])
                )
                break
        within_limit = (
            self.power_limit_w is None
            or estimated_power_w <= self.power_limit_w
        )
        return {
            "status": "ok",
            "power_limit_w": self.power_limit_w,
            "estimated_configured_max_power_w": estimated_power_w,
            "latest_measured_power_w": latest_measured_w,
            "headroom_w": (
                self.power_limit_w - estimated_power_w
                if self.power_limit_w is not None
                else None
            ),
            "within_limit": within_limit,
            "active_devices": sorted(
                active_devices,
                key=lambda item: float(item["estimated_max_power_w"]),
                reverse=True,
            ),
            "rule": (
                "Do not advance time while within_limit is false; reduce or "
                "stage lower-priority device levels and check again."
                if self.power_limit_w is not None
                else "No scenario-wide power cap is active."
            ),
        }

    @type_check
    @app_tool()
    @data_tool()
    @event_registered(operation_type=OperationType.READ)
    def get_environment_control_status(self) -> dict[str, Any]:
        """Evaluate current public sensor readings against the operating policy."""

        latest = self.runtime.sensors.read_all(self.runtime.current_time)
        by_zone: dict[str, dict[str, float]] = {}
        for reading in latest:
            by_zone.setdefault(reading.zone_id, {})[reading.quantity.value] = float(
                reading.value
            )
        rows = []
        for zone_id, values in sorted(by_zone.items()):
            room_id = self.world.zones[zone_id].room_id
            occupancy = self.world.room_states[room_id].occupancy_count
            temperature = values.get(SensorQuantity.AIR_TEMPERATURE_C.value)
            humidity = values.get(SensorQuantity.RELATIVE_HUMIDITY_PCT.value)
            co2 = values.get(SensorQuantity.CO2_PPM.value)
            pm25 = values.get(SensorQuantity.PM25_UG_M3.value)
            warnings = []
            violations = []
            if occupancy > 0 and temperature is not None and not 21.0 <= temperature <= 25.0:
                violations.append("temperature_outside_comfort_band")
            if occupancy > 0 and humidity is not None and not 40.0 <= humidity <= 60.0:
                violations.append("humidity_outside_comfort_band")
            if occupancy > 0 and co2 is not None and co2 > self.max_co2_ppm:
                violations.append("co2_above_scenario_limit")
            if occupancy > 0 and pm25 is not None and pm25 > self.max_pm25_ug_m3:
                violations.append("pm25_above_scenario_limit")
            if (
                occupancy > 0
                and co2 is not None
                and co2 >= min(CO2_WARNING_THRESHOLD_PPM, self.max_co2_ppm)
            ):
                warnings.append("co2_control_warning")
            if (
                occupancy > 0
                and pm25 is not None
                and pm25 >= min(PM25_WARNING_THRESHOLD_UG_M3, self.max_pm25_ug_m3)
            ):
                warnings.append("pm25_control_warning")
            active_device_types = {
                spec.device_type
                for device_id, spec in self.world.devices.items()
                if spec.room_id == room_id
                and self.world.device_states[device_id].power_on
                and self.world.device_states[device_id].health == DeviceHealth.ONLINE
            }
            # A warning is actionable before it becomes a scenario-limit
            # violation.  Once the appropriate preventive control is running,
            # retain the warning as evidence but stop forcing five-minute
            # polling; the normal periodic check remains in effect.
            uncontrolled_warnings = []
            if (
                "co2_control_warning" in warnings
                and DeviceType.VENTILATION not in active_device_types
            ):
                uncontrolled_warnings.append("co2_control_warning")
            if (
                "pm25_control_warning" in warnings
                and DeviceType.AIR_PURIFIER not in active_device_types
            ):
                uncontrolled_warnings.append("pm25_control_warning")
            recommended_actions = []
            if temperature is not None and temperature > 25.0:
                recommended_actions.append(
                    {
                        "action": "strengthen_hvac",
                        "device_type": DeviceType.HVAC.value,
                        "required_mode": "cooling",
                        "minimum_level": 3,
                        "reason": "occupied_temperature_above_band",
                    }
                )
            elif temperature is not None and temperature < 21.0:
                recommended_actions.append(
                    {
                        "action": "strengthen_hvac",
                        "device_type": DeviceType.HVAC.value,
                        "required_mode": "heating",
                        "minimum_level": 3,
                        "reason": "occupied_temperature_below_band",
                    }
                )
            if humidity is not None and humidity > 60.0:
                recommended_actions.append(
                    {
                        "action": "avoid_moisture_addition",
                        "reason": "occupied_humidity_above_band",
                        "guidance": (
                            "Keep humidification off; in cooling conditions use "
                            "stronger HVAC cooling and avoid more outdoor air than "
                            "CO2 control requires."
                        ),
                    }
                )
            rows.append(
                {
                    "room_id": room_id,
                    "zone_id": zone_id,
                    "occupancy_count": occupancy,
                    "readings": values,
                    "warnings": warnings,
                    "uncontrolled_warnings": uncontrolled_warnings,
                    "violations": violations,
                    "recommended_actions": recommended_actions,
                    "stable": not uncontrolled_warnings and not violations,
                }
            )
        occupied_unstable = any(
            row["occupancy_count"] > 0 and not row["stable"] for row in rows
        )
        next_event_at = self.runtime.event_queue.next_time()
        minutes_until_event = (
            max(0.0, (next_event_at - self.runtime.current_time).total_seconds() / 60.0)
            if next_event_at is not None
            else None
        )
        default_recheck = 5 if occupied_unstable else 15
        status = {
            "status": "ok",
            "policy": {
                "target_temperature_c": self.target_temperature_c,
                "occupied_temperature_band_c": [21.0, 25.0],
                "occupied_humidity_band_pct": [40.0, 60.0],
                "max_co2_ppm": self.max_co2_ppm,
                "max_pm25_ug_m3": self.max_pm25_ug_m3,
                "co2_warning_threshold_ppm": min(
                    CO2_WARNING_THRESHOLD_PPM, self.max_co2_ppm
                ),
                "pm25_warning_threshold_ug_m3": min(
                    PM25_WARNING_THRESHOLD_UG_M3, self.max_pm25_ug_m3
                ),
                "required_stable_checks_after_control": 2,
            },
            "rooms": rows,
            "occupied_environment_stable": not occupied_unstable,
            "recommended_recheck_minutes": (
                min(default_recheck, max(1, int(minutes_until_event)))
                if minutes_until_event is not None and minutes_until_event > 0
                else default_recheck
            ),
        }
        self._last_environment_check_at = self.runtime.current_time
        self._last_environment_device_event_count = self._device_event_count()
        self._last_environment_status = status
        return status

    def time_advance_precondition(
        self, requested_target_timestamp: float | None = None
    ) -> dict[str, Any]:
        """Require readiness and reconciliation before physical time advances."""

        requested_target = datetime.fromtimestamp(
            (
                requested_target_timestamp
                if requested_target_timestamp is not None
                else self.runtime.current_time.timestamp()
            ),
            tz=self.runtime.current_time.tzinfo,
        )
        # A meeting-start boundary is a hard business commitment.  Environment
        # tuning may legitimately change ventilation, so validate the complete
        # readiness checklist again immediately before an advance can cross
        # the start time (and while a confirmed meeting is already active).
        unreadied_meetings = []
        for meeting in self.world.schedule.values():
            if meeting.status != MeetingStatus.CONFIRMED:
                continue
            crosses_start = (
                self.runtime.current_time < meeting.start_at <= requested_target
            )
            active = meeting.start_at <= self.runtime.current_time < meeting.end_at
            if not (crosses_start or active):
                continue
            readiness = self.get_meeting_readiness(meeting.meeting_id)
            if not readiness["ready"]:
                unreadied_meetings.append(
                    {
                        "meeting_id": meeting.meeting_id,
                        "room_id": meeting.room_id,
                        "start_at": meeting.start_at.isoformat(),
                        "missing_device_ids": [
                            item["device_id"]
                            for item in readiness["checklist"]
                            if not item["ready"]
                        ],
                    }
                )
        if unreadied_meetings:
            return {
                "allowed": False,
                "code": "meeting_readiness_required",
                "meetings": unreadied_meetings,
                "required_tool": "BuildingOperationsApp.get_meeting_readiness",
            }

        occupied_rooms = {
            room_id: state.occupancy_count
            for room_id, state in self.world.room_states.items()
            if state.occupancy_count > 0
        }
        if not occupied_rooms:
            return {"allowed": True}
        if (
            self._last_environment_check_at != self.runtime.current_time
            or self._last_environment_device_event_count != self._device_event_count()
            or self._last_environment_status is None
        ):
            return {
                "allowed": False,
                "code": "environment_reconciliation_required",
                "occupied_rooms": occupied_rooms,
                "required_tool": (
                    "BuildingOperationsApp.get_environment_control_status"
                ),
            }

        missing_controls = []
        for room in self._last_environment_status["rooms"]:
            if room["occupancy_count"] <= 0 or not (
                room["uncontrolled_warnings"] or room["violations"]
            ):
                continue
            room_id = room["room_id"]
            conditions = set(room["warnings"]) | set(room["violations"])
            required_types = set()
            if "temperature_outside_comfort_band" in conditions:
                temperature = room["readings"].get(
                    SensorQuantity.AIR_TEMPERATURE_C.value
                )
                required_mode = "cooling" if temperature > 25.0 else "heating"
                hvac = next(
                    (
                        (device_id, self.world.device_states[device_id])
                        for device_id, spec in self.world.devices.items()
                        if spec.room_id == room_id
                        and spec.device_type == DeviceType.HVAC
                    ),
                    None,
                )
                if hvac is None or not (
                    hvac[1].power_on
                    and hvac[1].health == DeviceHealth.ONLINE
                    and hvac[1].mode == required_mode
                    and hvac[1].level >= 3
                ):
                    missing_controls.append(
                        {
                            "room_id": room_id,
                            "device_type": DeviceType.HVAC.value,
                            "required_mode": required_mode,
                            "minimum_level": 3,
                            "reason": "occupied_temperature_outside_band",
                        }
                    )
            if "humidity_outside_comfort_band" in conditions:
                required_types.add(DeviceType.HVAC)
            if conditions & {"co2_control_warning", "co2_above_scenario_limit"}:
                required_types.add(DeviceType.VENTILATION)
            if conditions & {"pm25_control_warning", "pm25_above_scenario_limit"}:
                required_types.add(DeviceType.AIR_PURIFIER)
            for device_type in required_types:
                active = any(
                    spec.room_id == room_id
                    and spec.device_type == device_type
                    and self.world.device_states[device_id].power_on
                    for device_id, spec in self.world.devices.items()
                )
                if not active:
                    missing_controls.append(
                        {"room_id": room_id, "device_type": device_type.value}
                    )
        if missing_controls:
            return {
                "allowed": False,
                "code": "occupied_environment_uncontrolled",
                "missing_controls": missing_controls,
                "required_action": (
                    "Activate a relevant control, recheck environment status, "
                    "then retry time advance."
                ),
            }
        return {"allowed": True}

    def _device_event_count(self) -> int:
        return sum(
            event.event_type.value == "device_state_changed"
            for event in self.world.events
        )
