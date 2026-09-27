from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
KST = ZoneInfo("Asia/Seoul")
PUBLISHED_SESSIONS = ROOT / "data" / "published_sessions.json"


def write_output(name: str, value: str) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            output.write(f"{name}={value}\n")
    else:
        print(f"{name}={value}")


def target_date(slot: str, now_kst: datetime) -> str:
    if slot == "us":
        return (now_kst.date() - timedelta(days=1)).isoformat()
    return now_kst.date().isoformat()


def load_published_sessions() -> dict[str, str]:
    if not PUBLISHED_SESSIONS.exists():
        return {}
    return json.loads(PUBLISHED_SESSIONS.read_text(encoding="utf-8"))


def evaluate_postcheck(slot: str, now_kst: datetime | None = None) -> tuple[bool, str]:
    now_kst = now_kst or datetime.now(KST)
    target = target_date(slot, now_kst)
    payload = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    markets = payload.get("markets", {})

    if slot == "manual":
        return True, "manual run"
    if slot == "asia":
        open_markets = [code for code in ("KR", "JP") if markets.get(code, {}).get("as_of") == target]
        return bool(open_markets), f"Asia target {target}; completed: {','.join(open_markets) or 'none'}"

    us_as_of = markets.get("US", {}).get("as_of", "")
    return us_as_of == target, f"US target {target}; completed: {us_as_of or 'none'}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether a scheduled market update should publish")
    parser.add_argument("--slot", choices=("asia", "us", "manual"), required=True)
    parser.add_argument("--phase", choices=("precheck", "postcheck", "mark"), default="postcheck")
    args = parser.parse_args()

    now_kst = datetime.now(KST)
    target = target_date(args.slot, now_kst)

    write_output("slot", args.slot)

    if args.phase == "precheck":
        published = load_published_sessions().get(args.slot) == target
        should_collect = args.slot == "manual" or not published
        write_output("should_collect", str(should_collect).lower())
        reason = f"{args.slot} target {target}; already published: {str(published).lower()}"
        write_output("reason", reason)
        print(reason)
        return

    if args.phase == "mark":
        if args.slot != "manual":
            sessions = load_published_sessions()
            sessions[args.slot] = target
            PUBLISHED_SESSIONS.write_text(
                json.dumps(sessions, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        reason = f"{args.slot} target {target}; marked published"
        write_output("reason", reason)
        print(reason)
        return

    should_publish, reason = evaluate_postcheck(args.slot, now_kst)

    write_output("should_publish", str(should_publish).lower())
    reason = f"{reason}; publish: {str(should_publish).lower()}"

    write_output("reason", reason)
    print(reason)


if __name__ == "__main__":
    main()
