"""Run the full Qt regression suite in isolated processes with per-file logs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET


COUNT_KEYS = ("tests", "failures", "errors", "skipped")


def run_file(indexed_path, *, root, output, env, timeout, parallel):
    index, path = indexed_path
    name = str(path.relative_to(root))
    prefix = output / f"{index:03d}-{path.stem}"
    report = prefix.with_suffix(".xml")
    report.unlink(missing_ok=True)
    command = [sys.executable, "-m", "pytest", str(path), "-q", "--tb=short",
               "-o", "faulthandler_timeout=90", f"--junitxml={report}"]
    if parallel:
        temp_directory = output / "tmp" / f"{index:03d}"
        command.append(f"--basetemp={temp_directory}")
    try:
        completed = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout)
        code, log = completed.returncode, completed.stdout
    except subprocess.TimeoutExpired as error:
        log = error.stdout or b""
        if isinstance(log, bytes):
            log = log.decode("utf-8", errors="replace")
        code = 124
        log += f"\nTimed out after {timeout} seconds: {name}\n"
    except OSError as error:
        code, log = 1, f"Could not start pytest for {name}: {error}\n"
    counts = {}
    if report.exists():
        try:
            for suite in ET.parse(report).getroot().iter("testsuite"):
                for key in COUNT_KEYS:
                    counts[key] = counts.get(key, 0) + int(suite.get(key, "0"))
        except (ET.ParseError, ValueError) as error:
            code = code or 1
            counts = {}
            log += f"\nCould not read JUnit report for {name}: {error}\n"
    prefix.with_suffix(".log").write_text(log, encoding="utf-8")
    return dict(file=name, exit_code=code, counts=counts), log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path, default=Path("build/test-results"))
    parser.add_argument("--workers", type=int, default=1,
                        help="Maximum simultaneous pytest processes (default: 1)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    files = [path.resolve() for path in
             (args.files or sorted((root / "tests").rglob("test_*.py")))]
    if not files or args.timeout <= 0 or args.workers <= 0:
        parser.error("Tests, a positive per-file timeout, and positive workers are required")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.workers > 1:
        (output / "tmp").mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
    results = []
    totals = dict.fromkeys(COUNT_KEYS, 0)
    run = partial(run_file, root=root, output=output, env=env,
                  timeout=args.timeout, parallel=args.workers > 1)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        completed = executor.map(run, enumerate(files, 1))
        for index, path in enumerate(files, 1):
            print(f"[{index}/{len(files)}] {path.relative_to(root)}", flush=True)
            result, log = next(completed)
            print(log, flush=True)
            for key, value in result["counts"].items():
                totals[key] += value
            results.append(result)
            (output / "results.json").write_text(
                json.dumps(dict(files=results, totals=totals), indent=2), encoding="utf-8")
    failed = [item["file"] for item in results if item["exit_code"] != 0]
    print(f"Files: {len(files)}; unsuccessful: {len(failed)}; totals: {totals}", flush=True)
    if failed:
        print("Unsuccessful files:\n" + "\n".join(failed), flush=True)
    return int(bool(failed))


if __name__ == "__main__":
    raise SystemExit(main())
