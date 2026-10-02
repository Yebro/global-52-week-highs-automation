from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime

from cloud_storage import publish_site, restore_state, save_state
from notify_telegram import main as notify_telegram
from schedule_gate import KST, ROOT, evaluate_postcheck, load_published_sessions, target_date


def collect_until_ready(slot: str, attempts: int, interval_seconds: int) -> bool:
    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        print(f"Collection attempt {attempt}/{attempts}", flush=True)
        try:
            subprocess.run([sys.executable, str(ROOT / "collect.py")], cwd=ROOT, check=True)
            last_error = None
            should_publish, reason = evaluate_postcheck(slot, datetime.now(KST))
            print(f"{reason}; publish: {str(should_publish).lower()}", flush=True)
            if should_publish:
                return True
        except subprocess.CalledProcessError as error:
            last_error = error
            print(
                f"Collection attempt {attempt} failed with exit code {error.returncode}",
                flush=True,
            )

        if attempt < attempts:
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval_seconds - elapsed))

    if last_error is not None:
        raise SystemExit(last_error.returncode)
    return False


def mark_published(slot: str, now_kst: datetime) -> None:
    if slot == "manual":
        return
    sessions = load_published_sessions()
    sessions[slot] = target_date(slot, now_kst)
    destination = ROOT / "data" / "published_sessions.json"
    destination.write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the tracker as a Cloud Run Job")
    parser.add_argument("--slot", choices=("asia", "us", "manual"), required=True)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()

    restore_state()
    now_kst = datetime.now(KST)
    target = target_date(args.slot, now_kst)
    if args.slot != "manual" and load_published_sessions().get(args.slot) == target:
        print(f"{args.slot} target {target} was already published; exiting.", flush=True)
        return

    attempts = 1 if args.slot == "manual" else max(1, args.attempts)
    if not collect_until_ready(args.slot, attempts, args.interval_seconds):
        print(f"No completed {args.slot} market session was available; exiting.", flush=True)
        return

    subprocess.run([sys.executable, str(ROOT / "build_dashboard.py")], cwd=ROOT, check=True)
    publish_site()
    notify_telegram()
    mark_published(args.slot, datetime.now(KST))
    save_state()
    print("Cloud Run update completed.", flush=True)


if __name__ == "__main__":
    main()
