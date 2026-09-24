from __future__ import annotations

import html
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
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
SUMMARY_MIN_MARKET_CAP_KRW = 1_000_000_000_000
SUMMARY_LIMIT = 10
LIMITED_MARKETS = {"CN", "HK", "TW"}
LIMITED_MARKET_MAX = 2
NEWS_MAX_AGE_DAYS = 14
NEWS_TIMEOUT_SECONDS = 8
NO_NEWS_TEXT = "최근 공개 뉴스에서 뚜렷한 개별 이슈를 확인하지 못했습니다."
NEWS_LOCALES = {
    "US": ("en-US", "US", "US:en"),
    "KR": ("ko", "KR", "KR:ko"),
    "JP": ("ja", "JP", "JP:ja"),
    "CN": ("zh-CN", "CN", "CN:zh-Hans"),
    "TW": ("zh-TW", "TW", "TW:zh-Hant"),
    "HK": ("zh-HK", "HK", "HK:zh-Hant"),
}


def clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split())


def truncate(text: str, limit: int) -> str:
    text = clean_text(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def format_market_cap(value: object) -> str:
    try:
        trillion = float(value) / 1_000_000_000_000
    except (TypeError, ValueError):
        return "확인 불가"
    return f"{trillion:.1f}조원"


def fetch_issue(row: dict) -> str:
    cutoff = int(time.time()) - NEWS_MAX_AGE_DAYS * 24 * 60 * 60
    queries = [clean_text(row.get("name")), clean_text(row.get("symbol"))]
    for query in dict.fromkeys(item for item in queries if item):
        params = urllib.parse.urlencode(
            {
                "q": query,
                "quotesCount": 1,
                "newsCount": 6,
                "enableFuzzyQuery": "false",
                "region": "US",
                "lang": "en-US",
            }
        )
        request = urllib.request.Request(
            f"https://query1.finance.yahoo.com/v1/finance/search?{params}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=NEWS_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError):
            continue

        for item in payload.get("news") or []:
            try:
                published_at = int(item.get("providerPublishTime") or 0)
            except (TypeError, ValueError):
                published_at = 0
            if published_at and published_at < cutoff:
                continue
            title = truncate(item.get("title", ""), 120)
            publisher = truncate(item.get("publisher", ""), 35)
            if title:
                return f"{title} ({publisher})" if publisher else title

    name = clean_text(row.get("name"))
    if name:
        symbol = clean_text(row.get("symbol"))
        language, country, edition = NEWS_LOCALES.get(
            clean_text(row.get("market_code")), NEWS_LOCALES["US"]
        )
        params = urllib.parse.urlencode(
            {
                "q": f'"{name}" {symbol} when:{NEWS_MAX_AGE_DAYS}d',
                "hl": language,
                "gl": country,
                "ceid": edition,
            }
        )
        request = urllib.request.Request(
            f"https://news.google.com/rss/search?{params}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=NEWS_TIMEOUT_SECONDS) as response:
                root = ET.fromstring(response.read())
            item = root.find("./channel/item")
            if item is not None:
                title = truncate(html.unescape(item.findtext("title") or ""), 140)
                if title:
                    return title
        except (OSError, urllib.error.HTTPError, ET.ParseError):
            pass
    return NO_NEWS_TEXT


def safe_fetch_issue(row: dict) -> str:
    try:
        return fetch_issue(row)
    except Exception:
        return NO_NEWS_TEXT


def select_summary_rows(payload: dict) -> list[dict]:
    candidates = []
    for row in payload.get("highs", []):
        try:
            market_cap = float(row.get("market_cap_krw", 0))
            day_return = float(row.get("day_return_pct"))
        except (TypeError, ValueError):
            continue
        if row.get("is_new_high") and market_cap >= SUMMARY_MIN_MARKET_CAP_KRW:
            candidates.append({**row, "day_return_pct": day_return})
    candidates.sort(key=lambda row: row["day_return_pct"], reverse=True)
    selected = []
    limited_counts = {market: 0 for market in LIMITED_MARKETS}
    for row in candidates:
        market_code = clean_text(row.get("market_code"))
        if market_code in LIMITED_MARKETS:
            if limited_counts[market_code] >= LIMITED_MARKET_MAX:
                continue
            limited_counts[market_code] += 1
        selected.append(row)
        if len(selected) == SUMMARY_LIMIT:
            break
    return selected


def build_summary(payload: dict) -> str:
    rows = select_summary_rows(payload)
    if not rows:
        return (
            "\n\n📌 핵심 요약\n"
            "시가총액 1조원 이상 신규 52주 신고가 기업 중 당일 수익률을 계산할 수 있는 종목이 없습니다."
        )

    header = (
        "\n\n📌 핵심 요약\n"
        "신규 52주 신고가 · 시총 1조원 이상 · 당일 수익률순"
    )
    blocks = []
    with ThreadPoolExecutor(max_workers=min(5, len(rows))) as executor:
        issues = list(executor.map(safe_fetch_issue, rows))
    for index, (row, issue) in enumerate(zip(rows, issues), start=1):
        name = truncate(clean_text(row.get("name")) or clean_text(row.get("symbol")), 70)
        market = clean_text(row.get("market")) or "시장 미확인"
        ticker = clean_text(row.get("symbol"))
        market_with_ticker = f"{market} ({ticker})" if ticker else market
        sector = clean_text(row.get("sector")) or "기타"
        market_cap = format_market_cap(row.get("market_cap_krw"))
        day_return = float(row["day_return_pct"])
        blocks.append(
            f"{index}. {name}\n"
            f"시장: {market_with_ticker}\n"
            f"섹터: {sector}\n"
            f"시총: {market_cap}\n"
            f"수익률: {day_return:+.2f}%\n"
            f"이슈: {issue}"
        )
    return "\n\n".join([header, *blocks])


def build_message(payload: dict, *, include_issues: bool = True) -> str:
    markets = payload.get("markets", {})
    total_highs = sum(int(markets.get(code, {}).get("highs", 0)) for code, _ in MARKET_LABELS)
    total_new = sum(int(markets.get(code, {}).get("new_highs", 0)) for code, _ in MARKET_LABELS)
    market_counts = " · ".join(
        f"{label} {int(markets.get(code, {}).get('highs', 0))}"
        for code, label in MARKET_LABELS
    )
    collected_at = payload.get("meta", {}).get("collected_at", "확인 불가")
    message = (
        "✅ 52주 신고가 업데이트 완료\n"
        f"수집 시각: {collected_at}\n"
        f"신고가: {total_highs}개 · 신규: {total_new}개\n"
        f"{market_counts}\n"
        f"{DASHBOARD_URL}"
    )
    if include_issues:
        message += build_summary(payload)
    return message


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
