from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
KST = ZoneInfo("Asia/Seoul")


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether a scheduled market update should publish")
    parser.add_argument("--slot", choices=("asia", "us", "manual"), required=True)
    args = parser.parse_args()

    payload = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    markets = payload.get("markets", {})
    now_kst = datetime.now(KST)

    if args.slot == "manual":
        should_publish = True
        reason = "manual run"
    elif args.slot == "asia":
        target = now_kst.date().isoformat()
        open_markets = [code for code in ("KR", "JP") if markets.get(code, {}).get("as_of") == target]
        should_publish = bool(open_markets)
        reason = f"Asia target {target}; completed: {','.join(open_markets) or 'none'}"
    else:
        target = (now_kst.date() - timedelta(days=1)).isoformat()
        us_as_of = markets.get("US", {}).get("as_of", "")
        should_publish = us_as_of == target
        reason = f"US target {target}; completed: {us_as_of or 'none'}"

    write_output("should_publish", str(should_publish).lower())
    write_output("reason", reason)
    print(reason)


if __name__ == "__main__":
    main()

