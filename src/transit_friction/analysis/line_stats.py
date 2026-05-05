from collections import Counter

def line_stats(events):
    c = Counter(e.get("line") for e in events if e.get("line"))
    return [{"line": k, "events": v} for k, v in c.most_common()]
