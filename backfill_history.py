from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_PATTERN = re.compile(
    r'<script type="application/json" id="ht-actual-data">(.*?)</script>',
    re.DOTALL,
)


def snapshot(date: str, payload: dict) -> dict | None:
    markets = payload.get("markets")
    if not isinstance(markets, dict) or not markets:
        return None
    values = {}
    for code, stats in markets.items():
        if not isinstance(stats, dict) or "highs" not in stats:
            continue
        values[code] = {
            "highs": int(stats.get("highs", 0)),
            "new_highs": int(stats.get("new_highs", 0)),
            "as_of": stats.get("as_of", ""),
        }
    if not values:
        return None
    return {
        "date": date,
        "total": int(payload.get("summary", {}).get("highs", sum(item["highs"] for item in values.values()))),
        "markets": values,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill market-high history from published dashboard revisions")
    parser.add_argument("--git", required=True, help="Absolute path to git executable")
    args = parser.parse_args()

    repo = ROOT / "publish"
    rows = subprocess.check_output(
        [args.git, "-C", str(repo), "log", "--format=%H|%as", "--reverse"],
        text=True,
        encoding="utf-8",
    ).splitlines()
    by_date: dict[str, dict] = {}
    for row in rows:
        commit, date = row.split("|", 1)
        html = subprocess.check_output(
            [args.git, "-C", str(repo), "show", f"{commit}:index.html"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        match = DATA_PATTERN.search(html)
        if not match:
            continue
        try:
            item = snapshot(date, json.loads(match.group(1)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if item:
            by_date[date] = item

    latest_path = ROOT / "data" / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    current = snapshot(latest["meta"]["collected_at"][:10], latest)
    if current:
        by_date[current["date"]] = current

    history = [by_date[date] for date in sorted(by_date)]
    history_path = ROOT / "data" / "history.json"
    history_path.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    latest["history"] = history
    latest_path.write_text(json.dumps(latest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(json.dumps({"points": len(history), "from": history[0]["date"], "to": history[-1]["date"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
