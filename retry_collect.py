from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime

from schedule_gate import KST, ROOT, evaluate_postcheck, write_output


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect market data with one-minute retries")
    parser.add_argument("--slot", choices=("asia", "us", "manual"), required=True)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--interval-seconds", type=int, default=60)
    args = parser.parse_args()

    attempts = 1 if args.slot == "manual" else max(1, args.attempts)
    last_reason = "collection not attempted"
    last_error: subprocess.CalledProcessError | None = None

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        print(f"Collection attempt {attempt}/{attempts}", flush=True)
        try:
            subprocess.run([sys.executable, str(ROOT / "collect.py")], cwd=ROOT, check=True)
            last_error = None
            should_publish, last_reason = evaluate_postcheck(args.slot, datetime.now(KST))
            print(f"{last_reason}; publish: {str(should_publish).lower()}", flush=True)
            if should_publish:
                write_output("should_publish", "true")
                write_output("reason", last_reason)
                return
        except subprocess.CalledProcessError as error:
            last_error = error
            last_reason = f"collection attempt {attempt} failed with exit code {error.returncode}"
            print(last_reason, flush=True)

        if attempt < attempts:
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, args.interval_seconds - elapsed))

    write_output("should_publish", "false")
    write_output("reason", last_reason)
    if last_error is not None:
        raise SystemExit(last_error.returncode)


if __name__ == "__main__":
    main()
