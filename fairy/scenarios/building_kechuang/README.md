# Kechuang Building Scenarios

本包是科创空间智慧建筑场景的统一入口。房间静态事实来自
`fairy/configs/rooms/`，Scenario 只描述任务、时间线、工具路径和最终验证。

## 目录结构

```text
building_kechuang/
├── base.py                     # 三房间 Runtime 与 Apps 共享装配
├── meeting_lifecycle.py        # 可复用会议阶段与状态转换
├── scenario_room_booking.py    # 跨房间预约与选择
├── k1324/
│   ├── scenario_climate_coordination.py
│   └── scenario_occupancy_ramp.py
├── k1316/                      # 研讨室专属场景入口
│   └── scenario_seminar_standard.py
└── k1315/
    └── scenario_conference_standard.py
```

## 当前可运行场景

| Scenario ID | 房间范围 | 目标 |
|---|---|---|
| `scenario_building_kechuang_room_booking` | 跨房间 | K1315 冲突后选择 K1316，并证明 K1324 不可预约 |
| `scenario_building_kechuang_k1324_climate_coordination` | K1324 | 办公室温湿度观测反馈控制 |
| `scenario_building_kechuang_k1324_occupancy_ramp` | K1324 | 工作日人数变化、CO₂ 上升与空房恢复 |
| `scenario_building_kechuang_k1315_conference_standard` | K1315 | 12 人正式会议的环境、打印、灯光、投影音响与会后清理 |
| `scenario_building_kechuang_k1316_seminar_standard` | K1316 | 8 人研讨的环境预处理、投影准备、会中通风与会后清理 |

每个运行型场景同时包含：

1. Runtime Event Queue 中真实发生的时间事件；
2. `build_events_flow()` 中供 Agent/Oracle 执行的工具 DAG；
3. `validate()` 中不可由自然语言报告替代的最终状态判定。

候选场景与优先级见 `scenario_catalog.md`。
真实模型首轮工程实验结果和已暴露问题见 `experiment_status.md`。

## 命名迁移

本次重构删除了 `fairy/scenarios/building_k1324/` 源码目录，不保留容易造成房间归属
误解的旧注册 ID。调用脚本需要按下表更新：

| 旧 ID | 新 ID |
|---|---|
| `scenario_building_k1324_meeting_booking` | `scenario_building_kechuang_room_booking` |
| `scenario_building_k1324_conference_standard` | `scenario_building_kechuang_k1315_conference_standard` |
| `scenario_building_k1324_climate_coordination` | `scenario_building_kechuang_k1324_climate_coordination` |
| `scenario_building_k1324_occupancy_ramp` | `scenario_building_kechuang_k1324_occupancy_ramp` |

## 测试与真实模型运行

```bash
conda run -n are env PYTHONPATH=. pytest -q tests/test_building_*.py
```

```bash
OPENAI_API_KEY=EMPTY PYTHONPATH=. python -m fairy.cli \
  --agent \
  --scenario scenario_building_kechuang_k1315_conference_standard \
  --controller building_baseline_react \
  --provider openai-compatible \
  --model Qwen3.6-35B-A3B-FP8 \
  --endpoint http://100.95.189.92:8000/v1 \
  --max-tool-calls 80 \
  --timeout-seconds 600
```
