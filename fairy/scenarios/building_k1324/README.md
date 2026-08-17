# K1324 Scenarios

完整代码架构和跨层数据流见：

`fairy/apps/building_world/README.md`

当前已实现：

| Scenario ID | 文件 | 目标 |
|---|---|---|
| `scenario_building_k1324_meeting_booking` | `scenario_meeting_booking.py` | 首选房冲突后选择合法替代房并完成预约 |
| `scenario_building_k1324_conference_standard` | `scenario_conference_standard.py` | 正常会前准备、人员到场、会议运行、会后关闭与资源释放 |
| `scenario_building_k1324_climate_coordination` | `scenario_climate_coordination.py` | 通过物理等待和传感器反馈协调空调与加湿器 |
| `scenario_building_k1324_occupancy_ramp` | `scenario_occupancy_ramp.py` | 人数分批进入/离开时的 CO₂ 演化与空房恢复 |

后三个场景当前只覆盖正常业务和环境过程，不注入设备故障、会议取消、传感器
掉线或人工覆盖。`meeting_lifecycle.py` 提供声明式 `MeetingPhase`、正常占用更新、
会议开始/结束状态转换和资源释放逻辑，避免在每个 Scenario 中复制生命周期规则。

每个正常场景同时包含两层时间表达：

1. Runtime Event Queue 保存实际发生的会议阶段和人数变化；
2. `build_events_flow()` 保存 Agent/Oracle 应执行的 Tool、物理等待和观测路径。

测试应先运行 Oracle → Replay → Validate，以区分框架/物理问题和 LLM 决策问题。

新增场景应继承 `K1324BuildingScenario`，只覆盖差异化初始状态、任务、
`build_events_flow()` 和验证逻辑。基类会从 `configs/rooms/k1324.yaml` 装配房间、
设备、物理、模拟传感器和统一 Runtime。房间冲突、容量、设备能力、人员日程及权限
规则应修改对应 App，不应复制到 Scenario。
