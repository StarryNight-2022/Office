from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fairy.adapters.building import (
    MqttConnectionSettings,
    MqttSensorAdapter,
    MqttSensorPublisher,
    MqttSensorSubscriber,
)
from fairy.apps.building_world.room_loader import load_room_configuration
from fairy.physics.building import (
    SensorQuality,
    SensorQuantity,
    SensorReading,
    SensorReadRequest,
)
from fairy.simulators.building import (
    BuildingMqttSensorSimulator,
    build_sensor_point_mappings,
    build_sensor_topics,
)
from fairy.simulators.building.mqtt_sensor_simulator import create_runtime

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
ROOM_CONFIG_DIRECTORY = Path(__file__).parents[1] / "fairy" / "configs" / "rooms"


class FakeMqttClient:
    """Record MQTT calls while exposing paho-compatible callback attributes."""

    def __init__(self) -> None:
        self.on_connect: Any = None
        self.on_message: Any = None
        self.calls: list[tuple[Any, ...]] = []

    def connect(self, host: str, port: int, keepalive: int) -> None:
        self.calls.append(("connect", host, port, keepalive))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))

    def loop_start(self) -> None:
        self.calls.append(("loop_start",))

    def loop_stop(self) -> None:
        self.calls.append(("loop_stop",))

    def publish(
        self, topic: str, payload: str, qos: int = 0, retain: bool = False
    ) -> SimpleNamespace:
        self.calls.append(("publish", topic, payload, qos, retain))
        return SimpleNamespace(rc=0)

    def subscribe(self, topic: str, qos: int = 0) -> None:
        self.calls.append(("subscribe", topic, qos))

    def username_pw_set(self, username: str, password: str | None = None) -> None:
        self.calls.append(("credentials", username, password))

    def tls_set(self, **kwargs: Any) -> None:
        self.calls.append(("tls", kwargs))


class RecordingPublisher:
    def __init__(self) -> None:
        self.readings: list[SensorReading] = []
        self.started = False

    def start(self) -> None:
        self.started = True

    def publish(self, reading: SensorReading) -> None:
        self.readings.append(reading)

    def stop(self) -> None:
        self.started = False


def test_mqtt_publisher_serializes_canonical_sensor_contract() -> None:
    client = FakeMqttClient()
    settings = MqttConnectionSettings(qos=1, retain=True)
    publisher = MqttSensorPublisher(
        settings,
        {"temp-01": "kechuang/k1324/environment/temperature"},
        client=client,
    )
    reading = SensorReading(
        sensor_id="temp-01",
        zone_id="k1324_office_zone",
        quantity=SensorQuantity.AIR_TEMPERATURE_C,
        value=24.5,
        unit="degC",
        observed_at=NOW,
        quality=SensorQuality.GOOD,
    )

    publisher.start()
    publisher.publish(reading)
    publisher.stop()

    publish_call = next(call for call in client.calls if call[0] == "publish")
    assert publish_call[1] == "kechuang/k1324/environment/temperature"
    assert json.loads(publish_call[2]) == {
        "sensor_id": "temp-01",
        "zone_id": "k1324_office_zone",
        "quantity": "air_temperature_c",
        "value": 24.5,
        "unit": "degC",
        "observed_at": "2026-08-17T12:00:00+00:00",
        "quality": "good",
    }
    assert publish_call[3:] == (1, True)


def test_mqtt_subscriber_resubscribes_and_feeds_adapter() -> None:
    configuration = load_room_configuration(ROOM_CONFIG_DIRECTORY / "k1324.yaml")
    mappings = build_sensor_point_mappings((configuration,))
    adapter = MqttSensorAdapter(mappings)
    client = FakeMqttClient()
    subscriber = MqttSensorSubscriber(
        MqttConnectionSettings(qos=1), adapter, client=client
    )

    subscriber.start()
    client.on_connect(client, None, None, 0, None)
    topic = "kechuang/k1324/environment/temperature"
    client.on_message(
        client,
        None,
        SimpleNamespace(
            topic=topic,
            payload=b'{"value":24.75,"observed_at":"2026-08-17T12:00:00Z"}',
        ),
    )
    subscriber.stop()

    subscriptions = [call for call in client.calls if call[0] == "subscribe"]
    assert len(subscriptions) == len(configuration.sensors)
    readings = adapter.read(
        SensorReadRequest(
            at_time=datetime.now(timezone.utc) + timedelta(seconds=1),
            zone_ids=("k1324_office_zone",),
            quantities=(SensorQuantity.AIR_TEMPERATURE_C,),
        )
    )
    assert readings[0].value == 24.75
    assert readings[0].metadata["source"] == "mqtt"


def test_building_simulator_publishes_only_new_physical_observations() -> None:
    configuration = load_room_configuration(ROOM_CONFIG_DIRECTORY / "k1316.yaml")
    runtime = create_runtime((configuration,), start_at=NOW)
    publisher = RecordingPublisher()
    simulator = BuildingMqttSensorSimulator(runtime, publisher)

    first = simulator.step(60.0)
    second = simulator.step(30.0)

    assert {reading.quantity for reading in first} == {
        SensorQuantity.AIR_TEMPERATURE_C,
        SensorQuantity.RELATIVE_HUMIDITY_PCT,
        SensorQuantity.CO2_PPM,
    }
    assert second == []
    assert publisher.readings == first
    assert build_sensor_topics((configuration,))["k1316_co2_01"] == (
        "kechuang/k1316/environment/co2"
    )
