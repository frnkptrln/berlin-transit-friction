import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "shadow_ledger.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "brokenlifts_homepage.html"


def run(*args: str) -> str:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=REPO_ROOT, check=True,
        capture_output=True, text=True,
    ).stdout


def observe(root: Path) -> None:
    # Exit code 2 means the source was not current (the fixture is dated); the
    # observation is still recorded, which is all these tests need.
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "accessibility_shadow.py"),
         "--root", str(root), "--input-html", str(FIXTURE)],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode in (0, 2), result.stderr


def test_publish_copies_durable_layers_not_the_raw_buffer_and_is_idempotent(tmp_path):
    shadow, ledger = tmp_path / "shadow", tmp_path / "ledger"
    observe(shadow)
    assert (shadow / "raw").is_dir(), "the observation must stage a raw buffer"

    first = json.loads(run("publish", "--shadow", str(shadow), "--ledger", str(ledger)))
    assert first["changed_files"] >= 2  # run log and README at least
    assert first["runs_logged"] == 1
    assert (ledger / "runs.jsonl").is_file()
    assert (ledger / "README.md").is_file()
    assert not (ledger / "raw").exists(), "the 7-day raw layer never reaches the ledger"

    second = json.loads(run("publish", "--shadow", str(shadow), "--ledger", str(ledger)))
    assert second["changed_files"] == 0, "publishing the same tree twice must change nothing"

    observe(shadow)
    third = json.loads(run("publish", "--shadow", str(shadow), "--ledger", str(ledger)))
    assert third["runs_logged"] == 2 and third["changed_files"] >= 1


def test_restore_fills_only_a_cold_tree(tmp_path):
    shadow, ledger, cold = tmp_path / "shadow", tmp_path / "ledger", tmp_path / "cold"
    observe(shadow)
    (shadow / "events").mkdir(exist_ok=True)
    (shadow / "events" / "marker.txt").write_text("sealed partition stand-in\n")
    run("publish", "--shadow", str(shadow), "--ledger", str(ledger))

    out = run("restore", "--ledger", str(ledger), "--shadow", str(cold))
    assert "restored" in out
    assert (cold / "events" / "marker.txt").read_text() == "sealed partition stand-in\n"
    assert not (cold / "raw").exists() and not (cold / "runs.jsonl").exists()

    again = run("restore", "--ledger", str(ledger), "--shadow", str(cold))
    assert "nothing restored" in again, "a warm tree is left alone"
