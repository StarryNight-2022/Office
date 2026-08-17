# Building Rooms 与现有 Scenarios

完整代码架构和跨层数据流见：

`fairy/apps/building_world/README.md`

当前已实现：

| Scenario ID | 文件 | 目标 |
|---|---|---|
| `scenario_building_k1324_meeting_booking` | `scenario_meeting_booking.py` | 首选房冲突后选择合法替代房并完成预约 |
| `scenario_building_k1324_conference_standard` | `scenario_conference_standard.py` | 在 K1315 执行环境预处理、材料打印、会议设备准备与完整关机 |
| `scenario_building_k1324_climate_coordination` | `scenario_climate_coordination.py` | 通过物理等待和传感器反馈协调空调与加湿器 |
| `scenario_building_k1324_occupancy_ramp` | `scenario_occupancy_ramp.py` | 人数分批进入/离开时的 CO₂ 演化与空房恢复 |

后三个场景当前只覆盖正常业务和环境过程，不注入设备故障、会议取消、传感器
掉线或人工覆盖。`meeting_lifecycle.py` 提供声明式 `MeetingPhase`、正常占用更新、
会议开始/结束状态转换和资源释放逻辑，避免在每个 Scenario 中复制生命周期规则。

每个正常场景同时包含两层时间表达：

1. Runtime Event Queue 保存实际发生的会议阶段和人数变化；
2. `build_events_flow()` 保存 Agent/Oracle 应执行的 Tool、物理等待和观测路径。

测试应先运行 Oracle → Replay → Validate，以区分框架/物理问题和 LLM 决策问题。

新增场景暂时仍继承兼容名称 `K1324BuildingScenario`，只覆盖差异化初始状态、任务、
`build_events_flow()` 和验证逻辑。基类会从 `configs/rooms/k1324.yaml`、
`k1316.yaml`、`k1315.yaml` 装配三个房间、设备、物理、模拟传感器和统一 Runtime。
房间冲突、容量、可预约性、设备能力、人员日程及权限
规则应修改对应 App，不应复制到 Scenario。

## 标准会议的双层执行链

`scenario_conference_standard.py` 当前在 K1315 依次执行：初始传感器观测 → 独立通风 →
HVAC/净化器 → 打印材料 → 分区灯光 → 投影/音响 → 推进 30 分钟 → 检查打印与
设备 readiness → 会前环境复测 → 会议开始/运行 → 会末观测 → 关闭八类受控设备。
通风通过物理模型改变室外风量，灯光和会议设备通过额定功率进入室内热负荷与能耗。

确定性回放：

```bash
conda run -n are env PYTHONPATH=. pytest -q tests/test_building_normal_scenarios.py
```

真实模型运行时建议使用 `building_baseline_react`。CLI 会依据 Building scenario ID
自动选择 Building 专用 system prompt。模型服务地址应通过 CLI 或环境配置传入，
不应硬编码进 Scenario。例如 OpenAI-compatible vLLM 服务可运行：

```bash
OPENAI_API_KEY=EMPTY PYTHONPATH=. python -m fairy.cli \
  --agent \
  --scenario scenario_building_k1324_conference_standard \
  --controller building_baseline_react \
  --provider openai-compatible \
  --model Qwen3.6-35B-A3B-FP8 \
  --endpoint http://100.95.189.92:8000/v1 \
  --max-tool-calls 80 \
  --timeout-seconds 600
```

其中 `EMPTY` 只是满足客户端预检的非敏感占位值；若服务启用了认证，应换成真实
密钥。具体参数以 `python -m fairy.cli --help` 为准。
