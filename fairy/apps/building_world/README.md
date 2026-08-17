# Building World 代码架构与工作流

本文是当前智慧建筑代码的总入口。目标是回答四个问题：

1. 一次请求在代码中如何流动；
2. 哪个对象拥有哪类状态；
3. 新增场景、设备、传感器或物理量时应修改哪里；
4. 当前哪些链路已经运行，哪些仍未连接。

K1324 传感器筛选、公共天气替代项及分阶段采购建议见
`fairy/configs/rooms/k1324_sensor_selection.md`。

### 开发环境

已有 Conda 环境 `are` 时，可在项目根目录执行：

```bash
conda activate are
python -m pip install -r requirements-building.txt
PYTHONPATH=. python -m pytest tests/test_building_*.py -q
```

`k1324.yaml` 当前使用 JSON-compatible YAML，因此运行时不依赖 PyYAML。真实 MQTT
部署使用 `paho-mqtt` 建立连接、认证、订阅和重连，再把消息交给现有 Adapter。

## 1. 当前总体结构

```text
Scenario / Engine / Agent
          |
          | Tool call
          v
Building Apps ---------------------------------------------------+
  Room/Schedule/Occupancy/Device/HVAC/AirDevice/Sensor Apps      |
          |                                            |
          v                                            |
BuildingWorldApp                            SensorHub  |
  rooms / people / meetings                 ^    ^     |
  reservations / BuildingEvent              |    |     |
                                             |    |     |
                            simulated reading|    |real reading
                                             |    |
BuildingWorldRuntime                         |  Sensor Adapter
  device state -> EquipmentModel -> HvacCommand
  BuildingPhysicsOrchestrator                |  MQTT/BACnet/...
  IndoorEnvironmentEngine ------------------+
  BuildingObservationModel
  energy / comfort / PhysicsEvent
```

当前会议预约与环境感知均已装配到 `K1324BuildingScenario`。设备命令可通过
`BuildingWorldRuntime` 在 `SystemApp.advance_time()` 后形成物理效果和模拟观测；
Event Queue、第一版 Trigger Policy、Building 专用 system prompt 和
`building_baseline_react` 已接入。尚未完成的是事件直接唤醒 Agent 的在线执行器与
Conference 长时自适应控制循环。

## 2. 分层职责

### 2.1 Scenario 层

目录：`fairy/scenarios/building_k1324/`

Scenario 只负责：

- 组装本场景使用的 App；
- 设置初始房间、人员、日程和外部事件；
- 描述 Agent 任务；
- 定义 Oracle workflow；
- 验证最终结果。

Scenario 不应实现房间冲突、权限、容量判断或物理公式。这些规则必须进入可复用
App 或 Physics，否则换一个场景就会复制业务逻辑。

当前场景：

- `base.py`：K1324 房间、人员及 App 组装；
- `scenario_meeting_booking.py`：首选 K1324 冲突后预约 K1316。
- `meeting_lifecycle.py`：正常会议阶段、占用变化和会后资源释放；
- `scenario_conference_standard.py`：标准会议完整生命周期；
- `scenario_climate_coordination.py`：空调与加湿器的观测反馈协同；
- `scenario_occupancy_ramp.py`：计划人数变化下的 CO₂ 响应。

### 2.2 App 层

目录：`fairy/apps/building_world/`

| 组件 | 职责 | 是否可写状态 |
|---|---|---|
| `BuildingWorldApp` | 建筑领域唯一业务状态源、ID、事件和快照 | 是 |
| `RoomApp` | 查询房间和确定性冲突检查 | 否 |
| `ScheduleApp` | 会议查询、创建、取消及业务规则 | 通过 World 写 |
| `ResourceAllocationApp` | 原子预留和释放共享资源 | 通过 World 写 |
| `OccupancyApp` | 人员在校和位置查询/更新 | 通过 World 写 |
| `BuildingSensorApp` | 向 Agent 暴露规范化传感器读数 | 否 |
| `SensorHub` | 合并模拟与真实 Provider，处理来源优先级 | 只缓存读数 |
| `DeviceRegistryApp` | 查询设备能力、位置、健康和可用性 | 否 |
| `HvacApp` | 校验并修改 HVAC 命令状态 | 通过 World 写 |
| `AirDeviceApp` | 校验并修改加湿器/净化器状态 | 通过 World 写 |
| `VentilationApp` | 控制独立新风档位，映射为室外风量 | 通过 World 写 |
| `LightingApp` | 控制分区亮度、色温与场景 | 通过 World 写 |
| `MeetingEquipmentApp` | 控制投影、音响和麦克风并查询 readiness | 通过 World 写 |
| `PrintingApp` | 控制打印机并管理随仿真时间完成的打印任务 | 设备通过 World；任务由 App 写 |
| `BuildingWorldRuntime` | 统一推进设备、负荷、物理、观测和事件 | 是 |

App Tool 返回结构化 `dict`。确定性违规通常返回：

```python
{
    "status": "rejected",
    "reason": "room_conflict",
    "conflicting_id": "existing-001",
}
```

LLM 不能通过换一种 Tool 参数绕过这些规则。

### 2.3 Physics 层

目录：`fairy/physics/building/`

| 组件 | 职责 |
|---|---|
| `models.py` | 区域参数、隐藏真值、HVAC 物理输入、能耗和舒适度结果 |
| `indoor_environment_engine.py` | 温度、湿度、CO₂、PM2.5 守恒计算 |
| `observation_model.py` | 从隐藏真值生成带噪声、延迟和缺失的模拟读数 |
| `sensor_api.py` | `SensorReading`、`SensorProvider`、`SensorPublisher` 稳定边界 |
| `orchestrator.py` | 推进物理、累计能耗、发布观测、生成阈值 transition |

关键边界：

```text
Tool / Device state -> HvacCommand -> Physics truth -> ObservationModel
                                                  -> SensorReading
```

Agent 不能读取 `ZoneState`，只能通过 `BuildingSensorApp` 读取
`SensorReading`。

### 2.4 Adapter 层

目录：`fairy/adapters/building/`

Adapter 将厂商/协议数据转换成统一 `SensorReading`：

```text
topic / point address / raw payload
        -> SensorPointMapping
        -> unit conversion
        -> timestamp + quality mapping
        -> SensorReading
```

`MqttSensorAdapter` 不负责建立网络连接。paho-mqtt 或其他部署客户端负责认证、
订阅、重连，并在回调中调用 `adapter.on_message(...)`。

## 3. 状态所有权

后续修改前应先确定目标状态属于哪一层。

| 状态 | 唯一所有者 | 其他组件如何访问 |
|---|---|---|
| 房间静态信息 | `BuildingWorldApp.rooms` | `RoomApp` 只读 |
| 人员及位置 | `BuildingWorldApp.people` | `OccupancyApp` 查询/更新 |
| 会议日程 | `BuildingWorldApp.schedule` | `ScheduleApp` 查询/更新 |
| 资源预留 | `BuildingWorldApp.reservations` | `ResourceAllocationApp` 更新 |
| 业务事件 | `BuildingWorldApp.events` | Scenario 验证/未来 Event Bus 消费 |
| 功能分区 | `BuildingWorldApp.functional_areas` | 房间配置与设备位置查询 |
| 通用设备设置 | `BuildingWorldApp.device_states.settings` | 设备 App 更新；Runtime 读取物理相关设置 |
| 打印任务 | `PrintingApp.jobs` | PrintingApp 查询并按仿真时钟完成 |
| 环境隐藏真值 | `IndoorEnvironmentEngine.states` | Orchestrator 推进 |
| 累计能耗 | `BuildingPhysicsOrchestrator` | step result/snapshot |
| 模拟传感器采样状态 | `BuildingObservationModel` | snapshot/restore |
| 最新读数 | Adapter / `SensorHub` | `BuildingSensorApp` 只读 |

禁止在 Scenario、SensorApp 或 ScheduleApp 中复制另一层的可变状态。

K1324 当前仍只有一个物理空气区 `k1324_meeting_zone`，但配置中增加了演示区、前后
观众区、入口区和服务区五个功能分区。功能分区用于设备布置和业务推理，全部映射到
同一物理 zone；在有分区传感器或可靠流体参数之前，不人为制造多个独立空气真值。

## 4. 会议预约完整工作流

入口类：`ScenarioBuildingK1324MeetingBooking`

```text
Engine.run_scenario_agent / replay_workflow
        |
        v
OccupancyApp.get_person_presence(professor-01)
        |
        v
ScheduleApp.get_person_schedule(...)
        |
        v
RoomApp.find_available_rooms(... capacity=6, projector)
        |
        +-- K1324: existing-001 时间冲突 -> 排除
        +-- K1315: 容量/投影不满足      -> 排除
        +-- K1316: 满足条件             -> 返回
        |
        v
ScheduleApp.create_meeting(room_id=k1316)
        |
        +-- 校验时间、人员、权限、容量、能力
        +-- 再次检查房间和人员冲突
        +-- ResourceAllocationApp.reserve_room()
        |       `-> RESOURCE_RESERVED (event-0001)
        +-- BuildingWorldApp.add_schedule_entry()
        |       `-> SCHEDULE_CREATED (event-0002, parent=event-0001)
        v
Scenario.validate()
        `-> 必须只有一个新会议，且房间为 k1316
```

会议时间使用带 UTC offset 的 ISO-8601 字符串。`datetime_utils.py` 会拒绝无时区
时间。时间段采用半开区间 `[start, end)`，因此 14:00–15:00 与 15:00–16:00
不冲突。

### Oracle / Replay 调用

```python
from fairy.controllers.engine import Engine
from fairy.scenarios.building_k1324.scenario_meeting_booking import (
    ScenarioBuildingK1324MeetingBooking,
)

oracle_engine = Engine(None, ScenarioBuildingK1324MeetingBooking())
oracle = oracle_engine.build_oracle_workflow(run_oracle=False)

replay_engine = Engine(None, ScenarioBuildingK1324MeetingBooking())
replayed = replay_engine.replay_workflow(oracle)
report = replay_engine.evaluation_report(replayed)
```

场景 ID：`scenario_building_k1324_meeting_booking`。Registry 会扫描
`fairy.scenarios.building_k1324`。

## 5. 模拟环境与传感器工作流

```text
Device/occupancy/outdoor inputs
        |
        v
BuildingPhysicsOrchestrator.step(at_time, dt, ...)
        |
        +-- IndoorEnvironmentEngine.step()
        |      -> temperature / RH / CO2 / PM2.5 truth
        |      -> step energy / comfort
        |
        +-- BuildingObservationModel.sample(truth)
        |      -> bias + noise + missing + latency
        |      -> ObservationSample(reading, truth_value)
        |
        +-- observation_sink.publish_many(readings)
        |      -> SensorHub
        |
        +-- threshold transition
               -> PhysicsEvent

BuildingSensorApp -> SensorHub.read() -> Agent-visible SensorReading
```

`ObservationSample.truth_value` 只用于内部评估，`BuildingSensorApp` 序列化结果中
没有该字段。

## 6. 真实传感器与 Shadow Mode

```text
MQTT client callback
        -> MqttSensorAdapter.on_message()
        -> PushSensorAdapter.ingest()
        -> canonical SensorReading
        -> SensorHub.register_provider(priority=100)
        -> BuildingSensorApp
```

模拟读数一般使用 priority 0。真实 Provider 使用更高 priority 后，Hub 合并视图
选择真实读数。Shadow Mode 使用：

```python
hub.read_by_source(request)
```

同时取得 `published` 模拟读数与真实 Provider 读数，用于误差和标定分析。

时间字段：

- `observed_at`：设备采样时间；
- `available_at`：网关收到、允许对外提供的时间；
- `read()` 只返回 `available_at <= request.at_time` 的读数。

点位示例在 `fairy/configs/rooms/k1324_sensors.yaml`。

## 7. Snapshot 与 Replay

Runtime 组合快照包含：

```text
BuildingWorldRuntime.snapshot()
  + BuildingWorldApp: rooms / zones / devices / people / schedule / events
  + BuildingPhysicsOrchestrator: truth / energy / threshold memory / RNG
  + SensorHub: internally published simulated readings
  + runtime current time and trace
```

真实 Adapter/Provider 的缓存仍由外部网关负责持久化，不包含在纯模拟 checkpoint
中。

## 8. 常见扩展应修改哪里

### 8.1 新增会议预约规则

例如“访客必须由 Staff 发起”或“领导会议优先级更高”：

1. 在 `types.py` 增加必要的角色/字段；
2. 在 `ScheduleApp.create_meeting()` 增加确定性校验；
3. 若影响预留竞争，在 `ResourceAllocationApp` 增加优先级规则；
4. 增加 App 单元测试；
5. Scenario 只负责提供触发规则的初始条件。

### 8.2 新增房间

在 `configs/rooms/` 中增加符合 `room_schema.json` 的 YAML，并通过
`room_loader.load_room_configuration()` 创建业务、物理、设备和传感器对象。不要继续
在 Scenario `base.py` 中手工复制完整房间定义。

### 8.3 新增真实传感器

1. 在点位配置增加 address、zone、quantity 和单位；
2. 使用现有 `SensorPointMapping`，或新增 BACnet/Modbus Adapter；
3. 注册到 `SensorHub`；
4. 不修改 `IndoorEnvironmentEngine`；
5. 增加单位、时间戳、延迟、坏质量和掉线测试。

### 8.4 新增物理量

例如 VOC：

1. `physics/building/models.py`：给 `ZoneState` 和结果增加字段；
2. `indoor_environment_engine.py`：增加守恒方程；
3. `sensor_api.py`：增加 `SensorQuantity` 和标准单位；
4. `observation_model.py`：增加 truth 映射；
5. `orchestrator.py`：增加阈值 transition；
6. 更新 Physics 和 Sensor Integration 测试。

### 8.5 新增设备 Tool

例如空调 App：

1. 在 Building World 定义 `DeviceSpec/DeviceState`；
2. `HvacApp.set_hvac()` 只修改设备状态并产生 Device 事件；
3. Equipment Model 将设定温度、档位和故障转换成 `HvacCommand`；
4. Orchestrator 用 `HvacCommand` 推进物理；
5. SensorApp 返回环境变化；
6. Agent 根据 Effect/Observation 验证目标，而不是把 Tool 成功视为环境达标。

### 8.6 新增 Scenario

1. 继承 `K1324BuildingScenario`；
2. `initiate_scenario()` 只设置差异化初始状态；
3. 定义 `scenario_input`；
4. 用 `build_events_flow()` 和 `EventRegisterer.capture_mode()` 定义 Oracle 事件图；
5. 定义最终状态 `validate()`；
6. 使用 `@register_scenario("...")`；
7. 添加 Oracle → Replay → Evaluate 测试。

## 9. 当前尚未接通的关键边界

以下能力不要误认为已经完成：

1. **预约成功不会自动决定何时启动空调**：仍缺 Trigger Policy/Agent 决策；
2. **灯光、打印机和门禁仅有配置，尚无控制 App**；
3. **已有 Building Event Queue 和 Trigger Policy，但尚无 Building ARE Controller**；
4. **真实 MQTT 连接、认证和重连客户端未实现，仅实现消息 Adapter**；
5. **Agent Builder 尚无 Building 专用 system prompt/family**；
6. **真实 Provider 缓存尚未纳入 Runtime checkpoint**，纯模拟缓存已支持。

## 10. 推荐的下一步整合目标

统一 Runtime 已实现按事件边界推进。`BuildingEventQueue` 保存尚未发生的事件，
`BuildingTriggerPolicy` 对已经发生的领域事件生成可审计的 `TriggerDecision`：

```python
class BuildingWorldRuntime:
    world: BuildingWorldApp
    physics: BuildingPhysicsOrchestrator
    sensors: SensorHub
    event_queue: BuildingEventQueue
    trigger_policy: BuildingTriggerPolicy

    def advance_to(self, target_time):
        # 1. 取下一外部事件
        # 2. 推进 physics 到事件时间
        # 3. 发布 observation 和 physics transition
        # 4. 应用日程/人员/设备事件
        # 5. Trigger Policy 决定是否唤醒 Agent
        ...
```

当前实现保证：

- 未来事件在执行时刻之前不会出现在 `BuildingWorldApp.events`；
- 事件落在物理步中间时，Runtime 会在事件时间切开该物理步；
- 相同时间的事件按稳定 sequence 执行；
- 普通 `SENSOR_UPDATED` 事件被记录但不会唤醒 Agent；
- 日程取消、设备故障、人工覆盖和环境阈值越界会请求唤醒；
- Queue、事件分类游标和决策 trace 均包含在 Runtime checkpoint 中。

下一阶段由 `BuildingAREController` 消费 `RuntimeAdvanceResult.trigger_decisions`，
构造 Agent 上下文并执行 Tool Calls。Trigger Policy 不应直接依赖或调用 LLM。

届时 Conference 场景的数据流应是：

```text
SCHEDULE_CREATED
  -> Event Queue 安排 T-45 preparation
  -> Trigger Policy 唤醒 Agent
  -> HVAC/lighting/printing Tools
  -> Physics step
  -> Sensor observation / threshold event
  -> Agent verification or replan
  -> MEETING_ENDED
  -> 关闭设备并释放资源
```

## 11. 测试对应关系

| 测试文件 | 覆盖范围 |
|---|---|
| `test_building_indoor_environment_engine.py` | 热湿、CO₂、PM2.5、能耗、阈值和快照 |
| `test_building_sensor_integration.py` | MQTT 映射、真实/模拟优先级、Agent 真值隔离 |
| `test_building_meeting_booking.py` | 预约、冲突、容量、能力、事件、快照和 Replay |

修改某一层时，应优先运行对应测试，再运行 FAIRY migration smoke test，确认 Farm
场景没有受到 Building 扩展影响。

## 12. 需要长期保持的架构约束

- Scenario 描述问题，不实现可复用规则；
- App 执行业务规则，不实现物理公式；
- Physics 维护隐藏真值，不读取或信任 Agent 输出；
- SensorReading 不携带 truth；
- Tool 成功不等于物理目标达成；
- 所有时间必须有明确时区；
- 所有 replay ID 必须确定性生成；
- 资源冲突和安全规则必须由确定性代码执行；
- 模拟与真实设备通过 Adapter 边界替换，上层场景不依赖厂商 SDK。
