from collections import Counter

def summarize_events(events):
    by_category = Counter(e.get("category") for e in events)
    by_mode = Counter(e.get("mode") for e in events if e.get("mode"))
    by_line = Counter(e.get("line") for e in events if e.get("line"))
    severe = [e for e in events if int(e.get("severity", 0)) >= 3][:20]
    return {
        "total_events": len(events),
        "by_category": dict(by_category),
        "by_mode": dict(by_mode),
        "by_line": dict(by_line),
        "top_affected_lines": by_line.most_common(10),
        "notable_severe_events": severe,
    }
