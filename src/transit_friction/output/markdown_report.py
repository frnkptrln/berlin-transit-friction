def build_markdown(date_str: str, summary: dict) -> str:
    lines = [
        f"# Transit Friction Daily Summary — {date_str}",
        "",
        f"- Total events: **{summary['total_events']}**",
        "",
        "## Events by category",
    ]
    for k, v in summary["by_category"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Events by mode"]
    for k, v in summary["by_mode"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Top affected lines"]
    for k, v in summary["top_affected_lines"]:
        lines.append(f"- {k}: {v}")
    lines += ["", "## Notable severe events"]
    for e in summary["notable_severe_events"][:10]:
        lines.append(f"- {e.get('title','(no title)')} ({e.get('line') or 'n/a'})")
    lines += ["", "## Data limitations", "- Data may be incomplete due to source/API outages or endpoint variability."]
    return "\n".join(lines)
