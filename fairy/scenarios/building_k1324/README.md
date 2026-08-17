# K1324 Scenarios

完整代码架构和跨层数据流见：

`fairy/apps/building_world/README.md`

当前已实现：

| Scenario ID | 文件 | 目标 |
|---|---|---|
| `scenario_building_k1324_meeting_booking` | `scenario_meeting_booking.py` | 首选房冲突后选择合法替代房并完成预约 |

新增场景应继承 `K1324BuildingScenario`，只覆盖差异化初始状态、任务、
`build_events_flow()` 和验证逻辑。基类会从 `configs/rooms/k1324.yaml` 装配房间、
设备、物理、模拟传感器和统一 Runtime。房间冲突、容量、设备能力、人员日程及权限
规则应修改对应 App，不应复制到 Scenario。
