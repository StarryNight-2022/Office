"""Offline tests for the staged Building live-model runner."""

import importlib.util
from pathlib import Path


def _runner_module():
    path = Path(__file__).parents[1] / "scripts" / "building_l3_live_runner.py"
    spec = importlib.util.spec_from_file_location("building_l3_live_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_runner_stages_and_cli_command_are_stable(tmp_path) -> None:
    runner = _runner_module()

    smoke = runner.scenario_ids_for_stage("smoke")
    diagnostic = runner.scenario_ids_for_stage("diagnostic")
    repair = runner.scenario_ids_for_stage("repair")
    constraint_repair = runner.scenario_ids_for_stage("constraint_repair")
    environment_repair = runner.scenario_ids_for_stage("environment_repair")
    final_repairs = runner.scenario_ids_for_stage("final_repairs")
    comfort_repair = runner.scenario_ids_for_stage("comfort_repair")
    all_scenarios = runner.scenario_ids_for_stage("all")
    command = runner.build_cli_command(
        smoke[0],
        endpoint="http://example.test/v1",
        model="served-model",
        output_dir=tmp_path,
        max_tool_calls=180,
        timeout_seconds=1800,
        max_output_tokens=4096,
    )

    assert len(smoke) == 1
    assert len(diagnostic) == 6
    assert len(repair) == 6
    assert {"_13_", "_14_"} <= {
        f"_{scenario_id.split('_l3_')[1].split('_')[0]}_"
        for scenario_id in repair
    }
    assert {
        int(scenario_id.split("_l3_")[1].split("_")[0])
        for scenario_id in constraint_repair
    } == {16, 20}
    assert len(environment_repair) == 1
    assert "_l3_20_" in environment_repair[0]
    assert {
        int(scenario_id.split("_l3_")[1].split("_")[0])
        for scenario_id in final_repairs
    } == {5, 13, 20}
    assert len(comfort_repair) == 1
    assert "_l3_13_" in comfort_repair[0]
    assert len(all_scenarios) == 20
    assert len(set(all_scenarios)) == 20
    assert "building_baseline_react" in command
    assert "vllm" in command
    assert "false" in command
    assert "http://example.test/v1" in command


def test_failure_row_is_reportable(tmp_path) -> None:
    runner = _runner_module()
    report_path = tmp_path / "missing.run_report.json"

    row = runner._failure_row(
        "scenario_building_test",
        report_path,
        status="wrapper_timeout",
        error="timed out",
    )
    runner._write_summary(tmp_path, [row])

    assert row["validation_success"] is False
    assert row["return_code"] is None
    assert "wrapper_timeout" in (tmp_path / "summary.md").read_text()


def test_private_endpoint_is_added_to_no_proxy(monkeypatch) -> None:
    runner = _runner_module()
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.delenv("no_proxy", raising=False)

    runner.configure_direct_endpoint("http://100.115.106.71:8000/v1")

    assert runner.os.environ["NO_PROXY"] == "localhost,100.115.106.71"
    assert runner.os.environ["no_proxy"] == "100.115.106.71"
