import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], output_root: Path):
    """Run a pipeline script with its writes redirected away from the repo."""
    env = {**os.environ, "TRANSIT_FRICTION_OUTPUT_ROOT": str(output_root)}
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env)


def test_collector_and_build_smoke(tmp_path):
    run(["python", "scripts/collect_snapshot.py", "--no-network"], tmp_path)
    manifests = sorted((tmp_path / "data/manifests").glob("**/*.json"))
    assert manifests, "collect_snapshot.py --no-network must always create a manifest"

    run(["python", "scripts/build_daily_summary.py"], tmp_path)
    assert sorted(
        (tmp_path / "data/gold/daily").glob("*.json")
    ), "daily summary json should be written"

    run(["python", "scripts/build_site_data.py"], tmp_path)
    assert (tmp_path / "site/data/latest.json").exists(), (
        "site latest output should be written"
    )


def test_the_test_suite_does_not_write_into_the_repository(tmp_path):
    """Output paths must follow the override, or tests pollute the working tree."""
    env = {**os.environ, "TRANSIT_FRICTION_OUTPUT_ROOT": str(tmp_path)}
    probe = subprocess.run(
        [
            "python",
            "-c",
            "import sys; sys.path.insert(0, 'src');"
            " from transit_friction import config;"
            " print(config.DATA_DIR); print(config.SITE_DATA_DIR)",
        ],
        cwd=REPO_ROOT,
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    data_dir, site_dir = probe.stdout.split()
    assert data_dir == str(tmp_path / "data")
    assert site_dir == str(tmp_path / "site" / "data")


def test_legacy_collection_workflows_are_paused():
    workflows = [
        ".github/workflows/collect.yml",
        ".github/workflows/collect-frequent.yml",
        ".github/workflows/collect-hourly.yml",
        ".github/workflows/collect-daily.yml",
        ".github/workflows/collect-static.yml",
        ".github/workflows/daily-summary.yml",
    ]
    for workflow in workflows:
        content = (REPO_ROOT / workflow).read_text(encoding="utf-8")
        assert "schedule:" not in content, f"{workflow} must not be scheduled"
        assert "cron:" not in content, f"{workflow} must not contain a cron trigger"
        assert "contents: write" not in content, f"{workflow} must be read-only"
        assert "git add" not in content, f"{workflow} must not commit data"

    forbidden = ["data/normalized", "data/summaries"]
    for workflow in (REPO_ROOT / ".github/workflows").glob("*.yml"):
        content = workflow.read_text(encoding="utf-8")
        for old_path in forbidden:
            assert old_path not in content, f"{workflow} still references obsolete path {old_path}"
