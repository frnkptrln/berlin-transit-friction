import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]):
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def test_collector_and_build_smoke(tmp_path):
    run(["python", "scripts/collect_snapshot.py", "--no-network"])
    manifests = sorted((REPO_ROOT / "data/manifests").glob("**/*.json"))
    assert manifests, "collect_snapshot.py --no-network must always create a manifest"

    run(["python", "scripts/build_daily_summary.py"])
    assert sorted((REPO_ROOT / "data/gold/daily").glob("*.json")), "daily summary json should be written"

    site_data = REPO_ROOT / "site/data"
    backup = tmp_path / "site_data_backup"
    if site_data.exists():
        shutil.copytree(site_data, backup)
        shutil.rmtree(site_data)

    run(["python", "scripts/build_site_data.py"])
    assert (site_data / "latest.json").exists(), "site latest output should be written"


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
