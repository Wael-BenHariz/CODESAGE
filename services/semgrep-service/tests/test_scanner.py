"""run_semgrep exit-code handling + command assembly (fake semgrep binary).

The fake script behaves per ``FAKE_SEMGREP_MODE`` and records its argv, so
the real subprocess/exit-code code paths run without semgrep installed.
"""

import asyncio
import json
import stat
from types import SimpleNamespace

import pytest

from app import config, scanner

FAKE_SCRIPT = """#!/usr/bin/env python3
import json, os, sys, time

mode = os.environ.get("FAKE_SEMGREP_MODE", "findings")
with open(os.environ["FAKE_SEMGREP_ARGV"], "w") as fh:
    json.dump(sys.argv, fh)

if mode == "no_findings":
    print(json.dumps({"results": [], "errors": []}))
    sys.exit(0)
if mode == "findings":
    print(json.dumps({
        "results": [{
            "check_id": "python.lang.security.audit.eval-used",
            "path": "app.py",
            "start": {"line": 9, "col": 12},
        }],
        "errors": [],
    }))
    sys.exit(1)
if mode == "crash":
    print("rule parse exploded", file=sys.stderr)
    sys.exit(3)
if mode == "badjson":
    print("sorry, here is prose instead of JSON")
    sys.exit(1)
if mode == "empty_ok":
    sys.exit(0)
if mode == "slow":
    time.sleep(30)
    sys.exit(0)
sys.exit(0)
"""


@pytest.fixture
def fake_semgrep(tmp_path, monkeypatch) -> SimpleNamespace:
    binary = tmp_path / "fake-semgrep"
    binary.write_text(FAKE_SCRIPT)
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    argv_log = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_SEMGREP_ARGV", str(argv_log))
    monkeypatch.setattr(config, "SEMGREP_BINARY", str(binary))

    def run(timeout: int = 10, languages=None):
        return asyncio.run(
            scanner.run_semgrep(tmp_path, timeout=timeout, languages=languages)
        )

    def argv() -> list[str]:
        return json.loads(argv_log.read_text())

    return SimpleNamespace(run=run, argv=argv, tmp=tmp_path)


def test_exit_0_no_findings_is_success(fake_semgrep, monkeypatch):
    monkeypatch.setenv("FAKE_SEMGREP_MODE", "no_findings")
    result = fake_semgrep.run()
    assert result == {"results": [], "errors": []}


def test_exit_1_with_findings_is_success_not_error(fake_semgrep, monkeypatch):
    monkeypatch.setenv("FAKE_SEMGREP_MODE", "findings")
    result = fake_semgrep.run()
    assert result["results"][0]["check_id"] == ("python.lang.security.audit.eval-used")


def test_exit_ge_2_raises_scan_error_with_stderr(fake_semgrep, monkeypatch):
    monkeypatch.setenv("FAKE_SEMGREP_MODE", "crash")
    with pytest.raises(scanner.ScanError, match="exit 3") as exc:
        fake_semgrep.run()
    assert "rule parse exploded" in str(exc.value)


def test_exit_1_invalid_json_raises_scan_error(fake_semgrep, monkeypatch):
    monkeypatch.setenv("FAKE_SEMGREP_MODE", "badjson")
    with pytest.raises(scanner.ScanError, match="invalid JSON"):
        fake_semgrep.run()


def test_exit_0_empty_stdout_tolerated_as_empty_report(fake_semgrep, monkeypatch):
    monkeypatch.setenv("FAKE_SEMGREP_MODE", "empty_ok")
    result = fake_semgrep.run()
    assert result == {"results": [], "errors": []}


def test_hard_timeout_kills_slow_scan(fake_semgrep, monkeypatch):
    monkeypatch.setenv("FAKE_SEMGREP_MODE", "slow")
    monkeypatch.setattr(config, "KILL_GRACE_SECONDS", 0)
    with pytest.raises(scanner.ScanTimeout, match="hard limit"):
        fake_semgrep.run(timeout=1)


def test_missing_binary_raises_scan_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SEMGREP_BINARY", "/nonexistent/definitely-not-semgrep")
    with pytest.raises(scanner.ScanError, match="failed to launch"):
        asyncio.run(scanner.run_semgrep(tmp_path, timeout=5))


def test_command_assembly_for_oss_only_scan(fake_semgrep, monkeypatch):
    monkeypatch.setenv("FAKE_SEMGREP_MODE", "no_findings")
    fake_semgrep.run(timeout=45, languages=["python"])
    argv = fake_semgrep.argv()

    assert argv[0] == str(config.SEMGREP_BINARY)
    assert argv[1:3] == ["scan", "--json"]
    assert "--metrics=off" in argv
    assert "--disable-version-check" in argv
    assert argv[argv.index("--timeout") + 1] == "45"
    assert argv[argv.index("--config") + 1] == str(config.SEMGREP_RULES_DIR)
    includes = [argv[i + 1] for i, a in enumerate(argv) if a == "--include"]
    assert "*.py" in includes
    assert "**/*.py" in includes
    assert argv[-1] == str(fake_semgrep.tmp)


def test_command_without_language_filter_has_no_includes(fake_semgrep, monkeypatch):
    monkeypatch.setenv("FAKE_SEMGREP_MODE", "no_findings")
    fake_semgrep.run()
    assert "--include" not in fake_semgrep.argv()


def test_build_command_rejects_unknown_language(tmp_path):
    with pytest.raises(ValueError, match="unsupported language"):
        scanner.build_command(tmp_path, 10, languages=["cobol"])


def test_language_filter_expands_all_requested_languages(tmp_path):
    command = scanner.build_command(tmp_path, 10, languages=["python", "java"])
    includes = [command[i + 1] for i, a in enumerate(command) if a == "--include"]
    assert "*.py" in includes and "*.java" in includes
