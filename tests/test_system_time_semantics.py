from datetime import datetime

from fairy.apps.system import SystemApp


def test_system_time_exposes_explicit_local_and_utc_values() -> None:
    app = SystemApp()
    timestamp = datetime.fromisoformat("2026-09-10T09:00:00+08:00").timestamp()
    app.time_manager.reset(timestamp)

    current = app.get_current_time()
    advanced = app.advance_time(minutes=15)

    assert current["current_datetime"] == "2026-09-10 01:00:00"
    assert current["current_datetime_local"] == "2026-09-10T09:00:00+08:00"
    assert advanced["current_datetime"] == "2026-09-10 01:15:00"
