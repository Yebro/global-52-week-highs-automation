from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


DASHBOARD_URL = "https://global-highs-tracker.paullee0618.chatgpt.site/"


def request_json(
    url: str,
    *,
    method: str = "GET",
    data: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    body = None if data is None else json.dumps(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = {"message": detail}
        return error.code, payload


def discover_chat_id(bot_token: str) -> str:
    _, payload = request_json(
        f"https://api.telegram.org/bot{bot_token}/getUpdates",
        method="POST",
        data={"timeout": 0, "allowed_updates": ["message"]},
    )
    if not payload.get("ok"):
        raise RuntimeError("Telegram could not read the bot's recent messages.")

    candidates = []
    for update in payload.get("result", []):
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        is_start = str(message.get("text", "")).split("@", 1)[0] == "/start"
        candidates.append((is_start, int(update.get("update_id", 0)), str(chat_id)))

    if not candidates:
        raise RuntimeError("No Telegram message was found. Open the bot and send /start, then rerun setup.")
    candidates.sort(reverse=True)
    return candidates[0][2]


def send_test_message(bot_token: str, chat_id: str, *, show_chat_id: bool) -> None:
    if show_chat_id:
        text = (
            "✅ 52주 신고가 트래커가 봇과 연결되었습니다.\n"
            f"채팅 ID: {chat_id}\n"
            "이 숫자를 GitHub의 TELEGRAM_CHAT_ID 변수에 저장하세요."
        )
    else:
        text = f"✅ 52주 신고가 트래커 알림 연결 완료\n{DASHBOARD_URL}"
    _, payload = request_json(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        method="POST",
        data={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )
    if not payload.get("ok"):
        raise RuntimeError("Telegram rejected the test notification.")


def main() -> None:
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    configured_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    chat_id = configured_chat_id or discover_chat_id(bot_token)
    print(f"::add-mask::{chat_id}")
    send_test_message(bot_token, chat_id, show_chat_id=not configured_chat_id)
    print("Telegram setup completed and a test notification was sent.")


if __name__ == "__main__":
    main()
