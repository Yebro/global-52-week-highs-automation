from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DASHBOARD_URL = os.environ.get(
    "DASHBOARD_URL", "https://global-highs-tracker.paullee0618.chatgpt.site/"
).strip()
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
NEWS_MAX_AGE_DAYS = 90
NEWS_TIMEOUT_SECONDS = 8
NO_NEWS_TEXT = "최근 90일 영어권 기사에서 뚜렷한 개별 상승 근거를 확인하지 못했습니다."
MARKET_SEARCH_HINTS = {
    "US": "US stock",
    "KR": "Korea KOSPI KOSDAQ",
    "JP": "Japan Tokyo stock",
    "CN": "China Shanghai Shenzhen stock",
    "TW": "Taiwan stock",
    "HK": "Hong Kong stock",
}
CATALYST_TERMS = (
    "earnings",
    "revenue",
    "profit",
    "guidance",
    "forecast",
    "contract",
    "order",
    "deal",
    "acquisition",
    "merger",
    "approval",
    "fda",
    "trial",
    "partnership",
    "investment",
    "dividend",
    "buyback",
    "award",
    "tender",
    "launch",
    "expansion",
    "stake",
    "upgrade",
    "rating",
    "price target",
    "license",
    "lawsuit",
    "settlement",
    "patent",
    "restructuring",
    "financing",
    "funding",
    "backlog",
    "production",
    "sales",
    "shipment",
)
POSITIVE_CATALYST_TERMS = (
    "beat",
    "raises",
    "raised",
    "growth",
    "record revenue",
    "record profit",
    "wins",
    "secures",
    "approval",
    "approved",
    "accepted",
    "contract",
    "order",
    "partnership",
    "acquisition",
    "launch",
    "expansion",
    "resumption",
    "resume trading",
    "upgrade",
    "price target raised",
    "buyback",
    "dividend increase",
    "winner",
)
NEGATIVE_CATALYST_TERMS = (
    "missed estimates",
    "misses estimates",
    "profit warning",
    "cuts guidance",
    "downgrade",
    "decline",
    "falls",
    "drops",
    "lawsuit",
    "investigation",
    "no undisclosed material information",
)
PRICE_MOVEMENT_TERMS = (
    "52-week high",
    "52 week high",
    "record high",
    "all-time high",
    "stock rises",
    "stock jumps",
    "stock surges",
    "shares rise",
    "shares jump",
    "shares surge",
    "shares soar",
    "shares rally",
    " surges",
    " soars",
    " jumps",
    " rallies",
    " gains",
    " rises",
    " climbs",
    "limit-up",
    "why is",
    "why did",
    "price movement",
)
LOW_VALUE_TERMS = (
    "stock forecast",
    "stock prediction",
    "technical analysis",
    "should you buy",
    "is it time to buy",
    "top stock to buy",
    "market movers",
    "share price indicate",
    "stocks lower at close",
    "stocks higher at close",
    "analyst insights, price targets",
    "etfs investing in",
)
SOURCE_PRIORITY = {
    "reuters": 70,
    "bloomberg": 65,
    "associated press": 60,
    "company press release": 58,
    "business wire": 55,
    "globenewswire": 55,
    "pr newswire": 55,
    "yahoo finance": 50,
    "investing.com": 48,
    "marketwatch": 45,
    "cnbc": 45,
    "barron's": 45,
    "nikkei asia": 45,
    "the korea herald": 40,
    "the korea times": 40,
    "taipei times": 40,
    "south china morning post": 40,
}
PUBLISHER_ALIASES = {
    "富途牛牛": "Moomoo",
    "조선일보": "ChosunBiz",
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


def _timestamp(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _rss_timestamp(value: object) -> int:
    try:
        return int(parsedate_to_datetime(clean_text(value)).timestamp())
    except (TypeError, ValueError, OverflowError):
        return 0


def _normalise_title(title: object, publisher: object = "") -> str:
    result = clean_text(html.unescape(str(title or "")))
    source = clean_text(publisher)
    if source and result.casefold().endswith(f" - {source}".casefold()):
        result = result[: -(len(source) + 3)].rstrip()
    return result


def _contains_term(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in terms)


def _is_price_only_title(title: str) -> bool:
    if _contains_term(title, LOW_VALUE_TERMS):
        return True
    return _contains_term(title, PRICE_MOVEMENT_TERMS) and not _contains_term(
        title, CATALYST_TERMS
    )


def _source_score(publisher: str) -> int:
    lowered = publisher.casefold()
    return max(
        (score for source, score in SOURCE_PRIORITY.items() if source in lowered),
        default=20,
    )


def _alias_words(value: str) -> set[str]:
    replacements = {
        "intl": "international",
        "corp": "corporation",
        "inc": "incorporated",
        "ltd": "limited",
    }
    ignored = {
        "class",
        "co",
        "company",
        "corporation",
        "group",
        "hk",
        "holding",
        "holdings",
        "human",
        "incorporated",
        "international",
        "limited",
        "made",
        "plc",
        "resources",
        "kq",
        "ks",
        "ss",
        "sz",
        "tw",
        "us",
    }
    words = {
        replacements.get(word, word)
        for word in re.findall(r"[a-z0-9]+", value.casefold())
        if len(word) >= 2 and not word.isdigit()
    }
    return words - ignored


def _candidate_score(candidate: dict, aliases: list[str], now: int) -> int:
    title = clean_text(candidate.get("title"))
    publisher = clean_text(candidate.get("publisher"))
    if not title or _is_price_only_title(title):
        return -1_000

    published_at = _timestamp(candidate.get("published_at"))
    age_days = max(0, (now - published_at) // (24 * 60 * 60)) if published_at else 45
    recency_score = max(0, 45 - min(age_days, 45))
    catalyst_score = 80 if _contains_term(title, CATALYST_TERMS) else 0
    positive_score = 50 if _contains_term(title, POSITIVE_CATALYST_TERMS) else 0
    negative_penalty = 80 if _contains_term(title, NEGATIVE_CATALYST_TERMS) else 0
    title_words = _alias_words(title)
    alias_score = 0
    for alias in aliases:
        meaningful = _alias_words(alias)
        matched = len(meaningful & title_words)
        required = 1
        if meaningful and matched >= required:
            alias_score = 25
            break
    source_score = _source_score(publisher)
    if not alias_score and not (source_score >= 55 and positive_score):
        return -1_000
    return (
        catalyst_score
        + positive_score
        + source_score
        + recency_score
        + alias_score
        - negative_penalty
    )


def _add_candidate(candidates: list[dict], item: dict) -> None:
    raw_publisher = clean_text(item.get("publisher"))
    publisher = PUBLISHER_ALIASES.get(raw_publisher, raw_publisher)
    title = _normalise_title(item.get("title"), raw_publisher)
    if not title:
        return
    candidates.append(
        {
            "title": title,
            "publisher": publisher,
            "published_at": _timestamp(item.get("published_at")),
        }
    )


def _symbols_match(actual: object, expected: str) -> bool:
    actual_symbol = clean_text(actual).upper()
    expected_symbol = clean_text(expected).upper()
    if not actual_symbol or not expected_symbol:
        return False
    return actual_symbol == expected_symbol or actual_symbol.split(".")[0] == expected_symbol.split(".")[0]


def _fetch_yahoo(
    query: str, cutoff: int, expected_symbol: str = ""
) -> tuple[list[dict], list[str]]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "quotesCount": 5,
            "newsCount": 10,
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
        return [], []

    candidates = []
    for item in payload.get("news") or []:
        published_at = _timestamp(item.get("providerPublishTime"))
        if published_at and published_at < cutoff:
            continue
        _add_candidate(
            candidates,
            {
                "title": item.get("title"),
                "publisher": item.get("publisher"),
                "published_at": published_at,
            },
        )

    aliases = []
    for quote in payload.get("quotes") or []:
        if expected_symbol and not _symbols_match(quote.get("symbol"), expected_symbol):
            continue
        aliases.extend(
            clean_text(quote.get(field))
            for field in ("shortname", "longname", "displayName")
            if clean_text(quote.get(field))
        )
    return candidates, aliases


def _build_google_queries(
    search_name: str,
    ticker: str,
    yahoo_symbol: str,
    market_hint: str,
    alternate_names: list[str] | None = None,
) -> list[str]:
    identity = " OR ".join(
        f'"{item}"'
        for item in dict.fromkeys(
            item for item in (search_name, yahoo_symbol, ticker) if clean_text(item)
        )
    )
    catalysts = (
        "earnings OR results OR revenue OR profit OR guidance OR forecast OR "
        "contract OR order OR acquisition OR approval OR partnership OR investment OR "
        "dividend OR buyback OR upgrade OR subsidy OR resumption"
    )
    queries = [
        f'({identity}) {market_hint} when:{NEWS_MAX_AGE_DAYS}d',
        f'"{search_name}" ({catalysts}) when:{NEWS_MAX_AGE_DAYS}d',
        f'({identity}) (Reuters OR Bloomberg OR "Yahoo Finance" OR Investing.com) when:{NEWS_MAX_AGE_DAYS}d',
        f'"{search_name}" (announcement OR filing OR "press release" OR investor relations) when:{NEWS_MAX_AGE_DAYS}d',
    ]
    for alternate in (alternate_names or [])[:2]:
        if alternate.casefold() != search_name.casefold():
            queries.append(f'{alternate} when:{NEWS_MAX_AGE_DAYS}d')
    return queries


def _fetch_google_news(query: str, cutoff: int) -> list[dict]:
    params = urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )
    request = urllib.request.Request(
        f"https://news.google.com/rss/search?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=NEWS_TIMEOUT_SECONDS) as response:
            root = ET.fromstring(response.read())
    except (OSError, urllib.error.HTTPError, ET.ParseError):
        return []

    candidates = []
    for item in root.findall("./channel/item")[:12]:
        published_at = _rss_timestamp(item.findtext("pubDate"))
        if published_at and published_at < cutoff:
            continue
        _add_candidate(
            candidates,
            {
                "title": item.findtext("title"),
                "publisher": item.findtext("source"),
                "published_at": published_at,
            },
        )
    return candidates


def _fetch_bing_news(query: str, cutoff: int) -> list[dict]:
    params = urllib.parse.urlencode(
        {"q": query, "format": "rss", "setlang": "en-US", "cc": "US"}
    )
    request = urllib.request.Request(
        f"https://www.bing.com/news/search?{params}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=NEWS_TIMEOUT_SECONDS) as response:
            root = ET.fromstring(response.read())
    except (OSError, urllib.error.HTTPError, ET.ParseError):
        return []

    candidates = []
    for item in root.findall("./channel/item")[:12]:
        published_at = _rss_timestamp(item.findtext("pubDate"))
        if published_at and published_at < cutoff:
            continue
        publisher = ""
        for child in item:
            if child.tag.rsplit("}", 1)[-1].casefold() == "source":
                publisher = clean_text(child.text)
                break
        _add_candidate(
            candidates,
            {
                "title": item.findtext("title"),
                "publisher": publisher or "Bing News",
                "published_at": published_at,
            },
        )
    return candidates


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    deduped = {}
    for candidate in candidates:
        key = re.sub(r"[^a-z0-9]+", "", clean_text(candidate.get("title")).casefold())
        if key and key not in deduped:
            deduped[key] = candidate
    return list(deduped.values())


def fetch_issue(row: dict) -> str:
    now = int(time.time())
    cutoff = now - NEWS_MAX_AGE_DAYS * 24 * 60 * 60
    name = clean_text(row.get("name"))
    symbol = clean_text(row.get("symbol"))
    yahoo_symbol = clean_text(row.get("yahoo_symbol")) or symbol
    ticker = yahoo_symbol.split(".")[0]
    market_code = clean_text(row.get("market_code"))
    market_hint = MARKET_SEARCH_HINTS.get(market_code, "stock")

    candidates = []
    aliases = [item for item in (name, symbol, yahoo_symbol, ticker) if item]
    for query in dict.fromkeys(
        item for item in (yahoo_symbol, symbol, name) if clean_text(item)
    ):
        yahoo_candidates, yahoo_aliases = _fetch_yahoo(
            query, cutoff, expected_symbol=yahoo_symbol
        )
        candidates.extend(yahoo_candidates)
        aliases.extend(yahoo_aliases)

    aliases = list(dict.fromkeys(clean_text(alias) for alias in aliases if clean_text(alias)))
    english_aliases = [alias for alias in aliases if re.search(r"[A-Za-z]", alias)]
    search_name = max(english_aliases or aliases, key=len, default=name or ticker)
    company_aliases = sorted(
        {
            alias
            for alias in english_aliases
            if len(re.findall(r"[A-Za-z]{3,}", alias)) >= 2
        },
        key=len,
    )
    google_queries = _build_google_queries(
        search_name, ticker, yahoo_symbol, market_hint, company_aliases
    )
    for query in dict.fromkeys(item for item in google_queries if item):
        candidates.extend(_fetch_google_news(query, cutoff))
    bing_name = company_aliases[0] if company_aliases else search_name
    candidates.extend(
        _fetch_bing_news(f"{bing_name} {ticker}", cutoff)
    )

    ranked = sorted(
        _dedupe_candidates(candidates),
        key=lambda candidate: _candidate_score(candidate, aliases, now),
        reverse=True,
    )
    for candidate in ranked:
        if _candidate_score(candidate, aliases, now) < 45:
            continue
        title = truncate(candidate["title"], 140)
        publisher = truncate(candidate.get("publisher", ""), 35)
        return f"{title} ({publisher})" if publisher else title
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
