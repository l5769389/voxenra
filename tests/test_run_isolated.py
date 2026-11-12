"""The process runner bounds concurrency and preserves per-file diagnostics."""
import json
from pathlib import Path
import subprocess
import sys
from threading import Event, Lock

import pytest

import run_isolated


def configure(monkeypatch, tmp_path, names, *options):
    root = tmp_path / "repo"
    tests = root / "tests"
    tests.mkdir(parents=True)
    paths = [tests / name for name in names]
    output = tmp_path / "results"
    monkeypatch.setattr(run_isolated, "__file__", str(tests / "run_isolated.py"))
    monkeypatch.setattr(sys, "argv", ["run_isolated.py", *map(str, paths),
                                    "--output", str(output), *options])
    return paths, output


def report_path(command):
    return Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml=")))


def write_report(command, *, tests=1, failures=0):
    report_path(command).write_text(
        f'<testsuites><testsuite tests="{tests}" failures="{failures}" errors="0" skipped="0"/></testsuites>',
        encoding="utf-8")


def test_parallel_workers_preserve_input_order_and_isolate_temp_paths(monkeypatch, tmp_path):
    paths, output = configure(monkeypatch, tmp_path,
                              ["test_third.py", "test_first.py", "test_second.py"], "--workers", "2")
    lock = Lock()
    later_finished = Event()
    active = maximum = 0
    completion_order = []
    commands = []

    def run(command, **kwargs):
        nonlocal active, maximum
        index = paths.index(Path(command[3]))
        temp_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--basetemp=")))
        assert temp_path.parent.is_dir()
        with lock:
            active += 1
            maximum = max(maximum, active)
            commands.append(command)
        try:
            if index == 0:
                assert later_finished.wait(5), "The second worker must finish both later files"
            write_report(command, tests=index + 1)
            with lock:
                completion_order.append(index)
                if index == 2:
                    later_finished.set()
            return subprocess.CompletedProcess(command, 0, f"file {index}\n")
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(run_isolated.subprocess, "run", run)
    assert run_isolated.main() == 0
    summary = json.loads((output / "results.json").read_text())
    assert [item["file"] for item in summary["files"]] == [str(Path("tests") / path.name) for path in paths]
    assert summary["totals"] == dict(tests=6, failures=0, errors=0, skipped=0)
    assert completion_order == [1, 2, 0]
    assert maximum == 2
    temp_paths = [Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--basetemp=")))
                  for command in commands]
    assert len(set(temp_paths)) == 3
    assert all(path.parent == output / "tmp" for path in temp_paths)
    assert len(list(output.glob("*.log"))) == len(list(output.glob("*.xml"))) == 3


def test_default_is_sequential_and_retains_pytest_temp_defaults(monkeypatch, tmp_path):
    paths, output = configure(monkeypatch, tmp_path, ["test_one.py", "test_two.py"])
    visited = []

    def run(command, **kwargs):
        visited.append(Path(command[3]))
        assert not any(arg.startswith("--basetemp=") for arg in command)
        write_report(command)
        return subprocess.CompletedProcess(command, 0, "passed\n")

    monkeypatch.setattr(run_isolated.subprocess, "run", run)
    assert run_isolated.main() == 0
    assert visited == paths
    assert json.loads((output / "results.json").read_text())["totals"]["tests"] == 2


def test_failure_timeout_and_launch_error_are_recorded(monkeypatch, tmp_path):
    paths, output = configure(monkeypatch, tmp_path,
                              ["test_failure.py", "test_timeout.py", "test_launch.py"],
                              "--workers", "2", "--timeout", "7")

    def run(command, **kwargs):
        assert kwargs["timeout"] == 7
        index = paths.index(Path(command[3]))
        if index == 0:
            write_report(command, tests=2, failures=1)
            return subprocess.CompletedProcess(command, 1, "assertion failed\n")
        if index == 1:
            report_path(command).write_text("<testsuites>")
            raise subprocess.TimeoutExpired(command, 7, output=b"partial output\xff")
        raise OSError("unable to launch")

    monkeypatch.setattr(run_isolated.subprocess, "run", run)
    assert run_isolated.main() == 1
    summary = json.loads((output / "results.json").read_text())
    assert [item["exit_code"] for item in summary["files"]] == [1, 124, 1]
    assert summary["totals"] == dict(tests=2, failures=1, errors=0, skipped=0)
    timeout_log = (output / "002-test_timeout.log").read_text()
    assert "partial output\ufffd" in timeout_log and "Timed out after 7 seconds" in timeout_log
    assert "Could not read JUnit report" in timeout_log
    assert "Could not start pytest" in (output / "003-test_launch.log").read_text()


def test_reused_output_discards_stale_report(monkeypatch, tmp_path):
    _, output = configure(monkeypatch, tmp_path, ["test_retry.py"])
    output.mkdir()
    stale = output / "001-test_retry.xml"
    stale.write_text('<testsuites><testsuite tests="99" failures="99"/></testsuites>')

    def run(command, **kwargs):
        assert not stale.exists()
        return subprocess.CompletedProcess(command, 1, "collection failed\n")

    monkeypatch.setattr(run_isolated.subprocess, "run", run)
    assert run_isolated.main() == 1
    summary = json.loads((output / "results.json").read_text())
    assert summary["totals"] == dict(tests=0, failures=0, errors=0, skipped=0)


@pytest.mark.parametrize("outcome", ["passed", "failed", "timeout"])
def test_parallel_temp_cleanup_preserves_failure_diagnostics(monkeypatch, tmp_path, outcome):
    _, output = configure(monkeypatch, tmp_path, ["test_fixture.py"], "--workers", "2")
    fixtures = []

    def run(command, **kwargs):
        temp_path = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--basetemp=")))
        temp_path.mkdir()
        fixture = temp_path / "image.dcm"
        fixture.write_bytes(b"synthetic fixture")
        fixtures.append(fixture)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 180, output=b"partial output")
        code = int(outcome == "failed")
        write_report(command, failures=code)
        return subprocess.CompletedProcess(command, code, outcome)

    monkeypatch.setattr(run_isolated.subprocess, "run", run)
    assert run_isolated.main() == int(outcome != "passed")
    assert fixtures[0].exists() == (outcome != "passed")
    assert (output / "001-test_fixture.log").exists()
    assert (output / "001-test_fixture.xml").exists() == (outcome != "timeout")


def test_successful_temp_cleanup_tolerates_locked_files(monkeypatch, tmp_path):
    _, output = configure(monkeypatch, tmp_path, ["test_locked.py"], "--workers", "2")
    cleanup_calls = []

    def run(command, **kwargs):
        write_report(command)
        return subprocess.CompletedProcess(command, 0, "passed")

    def cleanup(path, *, ignore_errors):
        assert ignore_errors is True
        cleanup_calls.append(path)

    monkeypatch.setattr(run_isolated.subprocess, "run", run)
    monkeypatch.setattr(run_isolated.shutil, "rmtree", cleanup)
    assert run_isolated.main() == 0
    assert cleanup_calls == [output / "tmp" / "001"]


@pytest.mark.parametrize("workers", ["0", "-1"])
def test_workers_must_be_positive(monkeypatch, tmp_path, workers):
    _, output = configure(monkeypatch, tmp_path, ["test_one.py"], "--workers", workers)
    with pytest.raises(SystemExit) as error:
        run_isolated.main()
    assert error.value.code == 2
    assert not output.exists()

@pytest.mark.parametrize('report', [None, '<testsuites/>', '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>', '<testsuites><testsuite tests="1" failures="1" errors="0" skipped="0"/></testsuites>'])
def test_success_exit_without_successful_test_evidence_fails(monkeypatch, tmp_path, report):
    _, output = configure(monkeypatch, tmp_path, ['test_empty.py'])
    def run(command, **kwargs):
        if report is not None:
            report_path(command).write_text(report)
        return subprocess.CompletedProcess(command, 0, 'nominal success')
    monkeypatch.setattr(run_isolated.subprocess, 'run', run)
    assert run_isolated.main() == 1
    summary = json.loads((output / 'results.json').read_text())
    assert summary['files'][0]['exit_code'] != 0


@pytest.mark.parametrize('required, skipped', [(False, 1), (True, 1), (True, 0)])
def test_required_stage_rejects_skips_but_optional_stage_allows_them(
    monkeypatch, tmp_path, required, skipped,
):
    options = ['--fail-on-skip'] if required else []
    _, output = configure(monkeypatch, tmp_path, ['test_native.py'], *options)

    def run(command, **kwargs):
        report_path(command).write_text(
            f'<testsuites><testsuite tests="2" failures="0" errors="0" skipped="{skipped}"/></testsuites>'
        )
        return subprocess.CompletedProcess(command, 0, 'child finished')

    monkeypatch.setattr(run_isolated.subprocess, 'run', run)
    assert run_isolated.main() == int(required and skipped > 0)
    summary = json.loads((output / 'results.json').read_text())
    assert summary['totals']['skipped'] == skipped
    assert summary['files'][0]['exit_code'] == int(required and skipped > 0)
    log = (output / '001-test_native.log').read_text()
    assert ('Required stage skipped tests' in log) == (required and skipped > 0)
