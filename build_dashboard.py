from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the local 52-week-high dashboard")
    parser.add_argument("--visualization-output", type=Path)
    args = parser.parse_args()

    payload = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    history_path = ROOT / "data" / "history.json"
    if history_path.exists():
        payload["history"] = json.loads(history_path.read_text(encoding="utf-8"))
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = (ROOT / "dashboard.template.html").read_text(encoding="utf-8")
    if "__TRACKER_DATA__" not in template:
        raise RuntimeError("dashboard template data placeholder is missing")
    dashboard = template.replace("__TRACKER_DATA__", embedded)

    output = ROOT / "dashboard.html"
    output.write_text(dashboard, encoding="utf-8")
    print(output)

    publish_dir = ROOT / "publish"
    publish_dir.mkdir(parents=True, exist_ok=True)
    standalone = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="글로벌 증시 종가 기준 52주 신고가 트래커">
  <title>Global 52-Week Highs Tracker</title>
  <style>
    html { color-scheme: light dark; }
    body { margin: 0; padding: 24px; background: light-dark(#eef2f4, #090d12); }
    @media (max-width: 520px) { body { padding: 8px; } }
  </style>
</head>
<body>
""" + dashboard + """
</body>
</html>
"""
    publish_output = publish_dir / "index.html"
    publish_output.write_text(standalone, encoding="utf-8")
    print(publish_output)
    if args.visualization_output:
        args.visualization_output.parent.mkdir(parents=True, exist_ok=True)
        args.visualization_output.write_text(dashboard, encoding="utf-8")
        print(args.visualization_output)


if __name__ == "__main__":
    main()
