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


def test_workflow_git_add_paths_match_outputs():
    expected = "git add data/bronze data/silver data/gold data/manifests site/data"
    workflows = [
        ".github/workflows/collect.yml",
        ".github/workflows/collect-frequent.yml",
        ".github/workflows/collect-hourly.yml",
    ]
    for workflow in workflows:
        content = (REPO_ROOT / workflow).read_text(encoding="utf-8")
        assert expected in content, f"{workflow} should add current output paths"

    daily_workflows = [
        ".github/workflows/collect-daily.yml",
        ".github/workflows/daily-summary.yml",
    ]
    for workflow in daily_workflows:
        content = (REPO_ROOT / workflow).read_text(encoding="utf-8")
        assert "git add data/gold data/manifests site/data" in content

    forbidden = ["data/normalized", "data/summaries"]
    for workflow in (REPO_ROOT / ".github/workflows").glob("*.yml"):
        content = workflow.read_text(encoding="utf-8")
        for old_path in forbidden:
            assert old_path not in content, f"{workflow} still references obsolete path {old_path}"
