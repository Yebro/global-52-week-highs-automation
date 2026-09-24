from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DASHBOARD_URL = "https://global-highs-tracker.paullee0618.chatgpt.site/"
MARKET_LABELS = (
    ("US", "미국"),
    ("KR", "한국"),
    ("JP", "일본"),
    ("CN", "중국"),
    ("TW", "대만"),
    ("HK", "홍콩"),
)


def build_message(payload: dict) -> str:
    markets = payload.get("markets", {})
    total_highs = sum(int(markets.get(code, {}).get("highs", 0)) for code, _ in MARKET_LABELS)
    total_new = sum(int(markets.get(code, {}).get("new_highs", 0)) for code, _ in MARKET_LABELS)
    market_counts = " · ".join(
        f"{label} {int(markets.get(code, {}).get('highs', 0))}"
        for code, label in MARKET_LABELS
    )
    collected_at = payload.get("meta", {}).get("collected_at", "확인 불가")
    return (
        "✅ 52주 신고가 업데이트 완료\n"
        f"수집 시각: {collected_at}\n"
        f"신고가: {total_highs}개 · 신규: {total_new}개\n"
        f"{market_counts}\n"
        f"{DASHBOARD_URL}"
    )


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("Telegram notification skipped: repository secrets are not configured.")
        return

    payload = json.loads((ROOT / "data" / "latest.json").read_text(encoding="utf-8"))
    body = json.dumps(
        {"chat_id": chat_id, "text": build_message(payload), "disable_web_page_preview": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram API returned HTTP {error.code}: {detail}") from error

    if not result.get("ok"):
        raise RuntimeError(f"Telegram API rejected the notification: {result}")
    print("Telegram notification sent.")


if __name__ == "__main__":
    main()
