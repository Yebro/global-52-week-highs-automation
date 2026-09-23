from __future__ import annotations

import argparse
import json
import math
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

import FinanceDataReader as fdr
import pandas as pd
import requests


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
LATEST_PATH = DATA_DIR / "latest.json"
UNIVERSE_PATH = DATA_DIR / "universe.csv"
SCREENED_PATH = DATA_DIR / "screened.csv"
HISTORY_PATH = DATA_DIR / "history.json"

MARKET_LABELS = {
    "US": "미국",
    "KR": "한국",
    "JP": "일본",
    "CN": "중국",
    "TW": "대만",
    "HK": "홍콩",
}

MARKET_ORDER = ["US", "KR", "JP", "CN", "TW", "HK"]

MARKET_CLOCK = {
    "US": ("America/New_York", clock_time(16, 20)),
    "KR": ("Asia/Seoul", clock_time(15, 50)),
    "JP": ("Asia/Tokyo", clock_time(15, 50)),
    "CN": ("Asia/Shanghai", clock_time(15, 20)),
    "TW": ("Asia/Taipei", clock_time(13, 50)),
    "HK": ("Asia/Hong_Kong", clock_time(16, 20)),
}

TRBC_SECTORS = {
    "50": "에너지",
    "51": "소재",
    "52": "산업재",
    "53": "경기소비재",
    "54": "필수소비재",
    "55": "금융",
    "56": "헬스케어",
    "57": "IT",
    "58": "커뮤니케이션",
    "59": "유틸리티",
    "60": "부동산",
}

MARKET_CAP_MIN_KRW = 300_000_000_000

FX_SYMBOLS = {
    "USD": "KRW=X",
    "JPY": "JPYKRW=X",
    "CNY": "CNYKRW=X",
    "TWD": "TWDKRW=X",
    "HKD": "HKDKRW=X",
}

GICS_SECTORS = {
    "Information Technology": "IT",
    "Communication Services": "커뮤니케이션",
    "Consumer Discretionary": "경기소비재",
    "Consumer Staples": "필수소비재",
    "Health Care": "헬스케어",
    "Healthcare": "헬스케어",
    "Industrials": "산업재",
    "Materials": "소재",
    "Financials": "금융",
    "Energy": "에너지",
    "Utilities": "유틸리티",
    "Real Estate": "부동산",
}

TW_SECTORS = {
    "01": "소재", "02": "필수소비재", "03": "소재", "04": "경기소비재",
    "05": "산업재", "06": "소재", "08": "소재", "09": "소재",
    "10": "소재", "11": "소재", "12": "경기소비재", "14": "산업재",
    "15": "산업재", "16": "경기소비재", "17": "금융", "18": "경기소비재",
    "19": "기타", "20": "산업재", "21": "소재", "22": "헬스케어",
    "23": "에너지", "24": "IT", "25": "IT", "26": "IT",
    "27": "IT", "28": "IT", "29": "IT", "30": "IT",
    "31": "IT", "32": "커뮤니케이션", "33": "필수소비재",
    "34": "경기소비재", "35": "에너지", "36": "IT", "37": "경기소비재",
}


@dataclass(frozen=True)
class PriceRecord:
    yahoo_symbol: str
    as_of: str
    close: float
    prior_high: float
    breakout_date: str
    breakout_close: float
    breakout_pct: float
    is_high: bool
    was_high_previous: bool
    history_days: int
    currency: str


def clean_text(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def trbc_sector(code: object) -> str:
    text = clean_text(code)
    return TRBC_SECTORS.get(text[:2], "기타")


def korean_sector(industry: object, products: object = "") -> str:
    text = f"{clean_text(industry)} {clean_text(products)}".lower()
    rules = [
        ("금융", ["은행", "금융", "보험", "증권", "신탁", "신용조합", "투자기관"]),
        ("헬스케어", ["의약", "의료", "바이오", "병원", "헬스", "진단", "치과"]),
        ("IT", ["반도체", "전자부품", "컴퓨터", "소프트웨어", "정보서비스", "통신장비", "디스플레이", "광학", "데이터", "시스템", "게임"]),
        ("커뮤니케이션", ["방송", "전기 통신", "무선 통신", "출판", "콘텐츠", "영화", "오디오", "광고"]),
        ("에너지", ["석유", "천연가스", "석탄", "연료", "원유"]),
        ("유틸리티", ["전기업", "전력", "수도", "폐기물", "환경 정화"]),
        ("부동산", ["부동산", "리츠"]),
        ("소재", ["화학", "철강", "금속", "광물", "시멘트", "유리", "종이", "펄프", "고무", "플라스틱", "목재", "비금속"]),
        ("필수소비재", ["식품", "음료", "담배", "생활용품", "농업", "어업", "축산", "곡물"]),
        ("경기소비재", ["자동차", "섬유", "의복", "신발", "소매", "도매", "숙박", "음식점", "여행", "레저", "스포츠", "가구", "화장품", "교육"]),
        ("산업재", ["기계", "장비", "건설", "운송", "창고", "항공", "조선", "철도", "엔지니어링", "임대", "보안", "서비스"]),
    ]
    for sector, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return sector
    return "기타"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_frame(name: str, fetcher: Callable[[], pd.DataFrame], refresh: bool) -> pd.DataFrame:
    path = CACHE_DIR / f"{name}.csv"
    if path.exists() and not refresh:
        age = datetime.now().timestamp() - path.stat().st_mtime
        if age < 24 * 60 * 60:
            return pd.read_csv(path, dtype=str, keep_default_na=False)
    try:
        frame = fetcher()
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        return frame.astype(str).replace("nan", "")
    except Exception:
        if path.exists():
            print(f"[warning] {name}: live listing failed; cached copy used", file=sys.stderr)
            return pd.read_csv(path, dtype=str, keep_default_na=False)
        raise


def fetch_naver_global_listing(exchange: str) -> pd.DataFrame:
    exchange_map = {
        "NASDAQ": "NASDAQ",
        "NYSE": "NYSE",
        "AMEX": "AMEX",
        "TSE": "TOKYO",
        "SSE": "SHANGHAI",
        "SZSE": "SHENZHEN",
        "HKEX": "HONG_KONG",
    }
    naver_exchange = exchange_map[exchange]
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    rows = []
    for page in range(1, 120):
        url = f"http://api.stock.naver.com/stock/exchange/{naver_exchange}/marketValue"
        response = session.get(url, params={"page": page, "pageSize": 60}, headers=headers, timeout=60)
        response.raise_for_status()
        stocks = response.json().get("stocks") or []
        if not stocks:
            break
        for stock in stocks:
            industry = stock.get("industryCodeType") or {}
            currency = stock.get("currencyType") or {}
            rows.append({
                "Symbol": stock.get("symbolCode", ""),
                "Name": stock.get("stockNameEng", ""),
                "IndustryCode": industry.get("code", ""),
                "Industry": industry.get("industryGroupKor", ""),
                "MarketCapLocal": stock.get("marketValueRaw", ""),
                "MarketCapKrwText": stock.get("marketValueKrwHangeul", ""),
                "Currency": currency.get("code", ""),
            })
    return pd.DataFrame(rows)


def global_listing(market: str, market_code: str, exchange: str, suffix: str, refresh: bool) -> pd.DataFrame:
    frame = cache_frame(f"naver_{exchange.lower()}_market_cap", lambda: fetch_naver_global_listing(exchange), refresh)
    frame = frame.rename(columns={
        "Symbol": "symbol", "Name": "name", "IndustryCode": "industry_code",
        "Industry": "industry", "MarketCapLocal": "market_cap_local",
        "MarketCapKrwText": "market_cap_krw_text", "Currency": "currency",
    })
    for column in ["symbol", "name", "industry_code", "industry", "market_cap_local", "market_cap_krw_text", "currency"]:
        if column not in frame:
            frame[column] = ""
    frame = frame[["symbol", "name", "industry_code", "industry", "market_cap_local", "market_cap_krw_text", "currency"]].copy()
    frame["symbol"] = frame["symbol"].map(clean_text)
    frame["industry_code"] = frame["industry_code"].map(clean_text)
    frame["market_cap_local"] = pd.to_numeric(frame["market_cap_local"].str.replace(",", "", regex=False), errors="coerce")
    frame = frame[(frame["symbol"] != "") & (frame["industry_code"] != "")]
    frame["market"] = market_code
    frame["exchange"] = exchange
    frame["sector"] = frame["industry_code"].map(trbc_sector)
    if suffix == "US":
        frame["yahoo_symbol"] = frame["symbol"].str.replace(".", "-", regex=False)
    elif suffix == "HK":
        frame["yahoo_symbol"] = frame["symbol"].map(lambda value: f"{str(int(value)):0>4}.HK" if value.isdigit() else f"{value}.HK")
    else:
        frame["yahoo_symbol"] = frame["symbol"].map(lambda value: f"{value}.{suffix}")
    frame["shares_outstanding"] = pd.NA
    return frame[["market", "exchange", "symbol", "yahoo_symbol", "name", "sector", "industry", "market_cap_local", "currency", "shares_outstanding"]]


def us_universe(refresh: bool) -> pd.DataFrame:
    nasdaq = global_listing("US", "US", "NASDAQ", "US", refresh)
    nyse = global_listing("US-NYSE", "US", "NYSE", "US", refresh)
    cap_master = pd.concat([nasdaq, nyse], ignore_index=True).drop_duplicates("yahoo_symbol")
    cap_lookup = cap_master.set_index("yahoo_symbol")[["market_cap_local", "currency", "shares_outstanding"]]
    sp = cache_frame("sp500", lambda: fdr.StockListing("S&P500"), refresh)
    sp = sp.rename(columns={"Symbol": "symbol", "Name": "name", "Sector": "source_sector", "Industry": "industry"})
    for column in ["symbol", "name", "source_sector", "industry"]:
        if column not in sp:
            sp[column] = ""
    sp = sp[["symbol", "name", "source_sector", "industry"]].copy()
    sp["symbol"] = sp["symbol"].map(clean_text)
    sp = sp[sp["symbol"] != ""]
    sp["market"] = "US"
    sp["exchange"] = "S&P500"
    sp["yahoo_symbol"] = sp["symbol"].str.replace(".", "-", regex=False)
    sp["sector"] = sp["source_sector"].map(lambda value: GICS_SECTORS.get(clean_text(value), "기타"))
    sp = sp.join(cap_lookup, on="yahoo_symbol")
    sp = sp[["market", "exchange", "symbol", "yahoo_symbol", "name", "sector", "industry", "market_cap_local", "currency", "shares_outstanding"]]
    combined = pd.concat([nasdaq, sp], ignore_index=True)
    return combined.drop_duplicates("yahoo_symbol", keep="first")


def korea_universe(refresh: bool) -> pd.DataFrame:
    parts = []
    for exchange, suffix in [("KOSPI", "KS"), ("KOSDAQ", "KQ")]:
        frame = cache_frame(exchange.lower(), lambda exchange=exchange: fdr.StockListing(f"{exchange}-DESC"), refresh)
        frame = frame.rename(columns={"Code": "symbol", "Name": "name", "Industry": "industry", "Products": "products"})
        for column in ["symbol", "name", "industry", "products"]:
            if column not in frame:
                frame[column] = ""
        frame = frame[["symbol", "name", "industry", "products"]].copy()
        frame["symbol"] = frame["symbol"].map(lambda value: clean_text(value).zfill(6))
        frame = frame[frame["symbol"].str.fullmatch(r"[0-9A-Z]{6}", na=False)]
        frame["market"] = "KR"
        frame["exchange"] = exchange
        frame["yahoo_symbol"] = frame["symbol"].map(lambda value: f"{value}.{suffix}")
        frame["sector"] = frame.apply(lambda row: korean_sector(row["industry"], row["products"]), axis=1)
        cap_frame = cache_frame(f"{exchange.lower()}_market_cap", lambda exchange=exchange: fdr.StockListing(exchange), refresh)
        cap_frame = cap_frame.rename(columns={
            "Code": "symbol",
            "Marcap": "market_cap_local",
            "Stocks": "shares_outstanding",
        })
        if "shares_outstanding" not in cap_frame:
            cap_frame["shares_outstanding"] = pd.NA
        cap_frame["symbol"] = cap_frame["symbol"].map(lambda value: clean_text(value).zfill(6))
        cap_frame["market_cap_local"] = pd.to_numeric(cap_frame["market_cap_local"].astype(str).str.replace(",", "", regex=False), errors="coerce")
        cap_frame["shares_outstanding"] = pd.to_numeric(
            cap_frame["shares_outstanding"].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )
        frame = frame.merge(
            cap_frame[["symbol", "market_cap_local", "shares_outstanding"]],
            on="symbol",
            how="left",
        )
        frame["currency"] = "KRW"
        parts.append(frame[["market", "exchange", "symbol", "yahoo_symbol", "name", "sector", "industry", "market_cap_local", "currency", "shares_outstanding"]])
    return pd.concat(parts, ignore_index=True).drop_duplicates("yahoo_symbol")


def china_universe(refresh: bool) -> pd.DataFrame:
    sse = global_listing("CN-SSE", "CN", "SSE", "SS", refresh)
    szse = global_listing("CN-SZSE", "CN", "SZSE", "SZ", refresh)
    return pd.concat([sse, szse], ignore_index=True).drop_duplicates("yahoo_symbol")


def taiwan_universe(refresh: bool) -> pd.DataFrame:
    def fetch_twse() -> pd.DataFrame:
        response = requests.get("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", timeout=60)
        response.raise_for_status()
        return pd.DataFrame(response.json())

    def fetch_tpex() -> pd.DataFrame:
        response = requests.get("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", timeout=60)
        response.raise_for_status()
        return pd.DataFrame(response.json())

    twse = cache_frame("twse", fetch_twse, refresh)
    twse = twse.rename(columns={"公司代號": "symbol", "公司簡稱": "name", "英文簡稱": "english_name", "產業別": "industry_code", "已發行普通股數或TDR原股發行股數": "shares_outstanding"})
    twse["symbol"] = twse["symbol"].map(clean_text)
    twse["name"] = twse["name"].map(clean_text)
    twse["english_name"] = twse["english_name"].map(clean_text)
    twse["name"] = twse["english_name"].where(twse["english_name"] != "", twse["name"])
    twse["industry_code"] = twse["industry_code"].map(clean_text)
    twse["market"] = "TW"
    twse["exchange"] = "TWSE"
    twse["yahoo_symbol"] = twse["symbol"].map(lambda value: f"{value}.TW")
    twse["sector"] = twse["industry_code"].map(lambda value: TW_SECTORS.get(value.zfill(2), "기타"))
    twse["industry"] = twse["industry_code"]
    twse["shares_outstanding"] = pd.to_numeric(twse["shares_outstanding"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    twse["market_cap_local"] = pd.NA
    twse["currency"] = "TWD"

    tpex = cache_frame("tpex", fetch_tpex, refresh)
    tpex = tpex.rename(columns={"SecuritiesCompanyCode": "symbol", "CompanyAbbreviation": "name", "Symbol": "english_name", "SecuritiesIndustryCode": "industry_code", "IssueShares": "shares_outstanding"})
    tpex["symbol"] = tpex["symbol"].map(clean_text)
    tpex["name"] = tpex["name"].map(clean_text)
    tpex["english_name"] = tpex["english_name"].map(clean_text)
    tpex["name"] = tpex["english_name"].where(tpex["english_name"] != "", tpex["name"])
    tpex["industry_code"] = tpex["industry_code"].map(clean_text)
    tpex["market"] = "TW"
    tpex["exchange"] = "TPEx"
    tpex["yahoo_symbol"] = tpex["symbol"].map(lambda value: f"{value}.TWO")
    tpex["sector"] = tpex["industry_code"].map(lambda value: TW_SECTORS.get(value.zfill(2), "기타"))
    tpex["industry"] = tpex["industry_code"]
    tpex["shares_outstanding"] = pd.to_numeric(tpex["shares_outstanding"].astype(str).str.replace(",", "", regex=False), errors="coerce")
    tpex["market_cap_local"] = pd.NA
    tpex["currency"] = "TWD"

    columns = ["market", "exchange", "symbol", "yahoo_symbol", "name", "sector", "industry", "market_cap_local", "currency", "shares_outstanding"]
    combined = pd.concat([twse[columns], tpex[columns]], ignore_index=True)
    return combined[(combined["symbol"] != "") & combined["symbol"].str.match(r"^[0-9A-Z]+$")].drop_duplicates("yahoo_symbol")


def build_universe(markets: Iterable[str], refresh: bool) -> pd.DataFrame:
    builders: dict[str, Callable[[bool], pd.DataFrame]] = {
        "US": us_universe,
        "KR": korea_universe,
        "JP": lambda value: global_listing("JP", "JP", "TSE", "T", value),
        "CN": china_universe,
        "TW": taiwan_universe,
        "HK": lambda value: global_listing("HK", "HK", "HKEX", "HK", value),
    }
    frames = []
    for market in markets:
        print(f"[listing] {MARKET_LABELS[market]}")
        frame = builders[market](refresh)
        frame["market_name"] = MARKET_LABELS[market]
        frames.append(frame)
        print(f"  {len(frame):,} symbols")
    universe = pd.concat(frames, ignore_index=True)
    universe = universe.drop_duplicates(["market", "yahoo_symbol"], keep="first")
    return universe.sort_values(["market", "yahoo_symbol"]).reset_index(drop=True)


def chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def closing_high_flags(values: list[tuple[str, float]]) -> list[bool]:
    """Mark closes that equal or exceed the prior maximum of up to 251 sessions."""
    flags = [False] * len(values)
    max_queue: deque[int] = deque()
    for index, (_, close) in enumerate(values):
        first_allowed = index - 251
        while max_queue and max_queue[0] < first_allowed:
            max_queue.popleft()
        if index >= 19 and max_queue:
            prior_high = values[max_queue[0]][1]
            flags[index] = close >= prior_high * (1 - 1e-10)
        while max_queue and values[max_queue[-1]][1] <= close:
            max_queue.pop()
        max_queue.append(index)
    return flags


def current_breakout_metrics(
    values: list[tuple[str, float]], high_flags: list[bool]
) -> tuple[str, float, float]:
    """Return performance since the first 52-week high in the latest 365 days."""
    current_date, current_close = values[-1]
    if not high_flags[-1]:
        return current_date, current_close, 0.0
    cutoff_date = (datetime.fromisoformat(current_date).date() - timedelta(days=365)).isoformat()
    breakout_index = next(
        index
        for index, (trade_date, _) in enumerate(values)
        if trade_date >= cutoff_date and high_flags[index]
    )
    breakout_date, breakout_close = values[breakout_index]
    breakout_pct = (current_close / breakout_close - 1) * 100
    return breakout_date, breakout_close, breakout_pct


def parse_price_result(result: dict, market: str, now_utc: datetime) -> PriceRecord | None:
    symbol = clean_text(result.get("symbol"))
    responses = result.get("response") or []
    if not symbol or not responses:
        return None
    response = responses[0] or {}
    timestamps = response.get("timestamp") or []
    indicators = response.get("indicators") or {}
    quote_list = indicators.get("quote") or []
    if not timestamps or not quote_list:
        return None
    closes = quote_list[0].get("close") or []
    meta = response.get("meta") or {}
    tz_name, completed_after = MARKET_CLOCK[market]
    market_tz = ZoneInfo(tz_name)
    local_now = now_utc.astimezone(market_tz)
    values: list[tuple[str, float]] = []
    for stamp, close in zip(timestamps, closes):
        if close is None:
            continue
        try:
            price = float(close)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        date = datetime.fromtimestamp(int(stamp), tz=timezone.utc).astimezone(market_tz).date()
        if date == local_now.date() and local_now.time() < completed_after:
            continue
        values.append((date.isoformat(), price))

    regular_price = meta.get("regularMarketPrice")
    regular_stamp = meta.get("regularMarketTime")
    try:
        regular_price = float(regular_price)
        regular_date = datetime.fromtimestamp(int(regular_stamp), tz=timezone.utc).astimezone(market_tz).date()
        regular_is_complete = regular_date < local_now.date() or local_now.time() >= completed_after
        if math.isfinite(regular_price) and regular_price > 0 and regular_is_complete:
            regular_pair = (regular_date.isoformat(), regular_price)
            if values and regular_pair[0] == values[-1][0]:
                values[-1] = regular_pair
            elif not values or regular_pair[0] > values[-1][0]:
                values.append(regular_pair)
    except (TypeError, ValueError, OSError):
        pass

    if len(values) < 20:
        return None
    current_date, current_close = values[-1]
    prior_values = [value for _, value in values[max(0, len(values) - 252):-1]]
    if not prior_values:
        return None
    prior_high = max(prior_values)
    high_flags = closing_high_flags(values)
    is_high = high_flags[-1]
    was_high_previous = high_flags[-2]
    breakout_date, breakout_close, breakout_pct = current_breakout_metrics(values, high_flags)
    return PriceRecord(
        yahoo_symbol=symbol,
        as_of=current_date,
        close=current_close,
        prior_high=prior_high,
        breakout_date=breakout_date,
        breakout_close=breakout_close,
        breakout_pct=breakout_pct,
        is_high=is_high,
        was_high_previous=was_high_previous,
        history_days=min(len(values), 253),
        currency=clean_text(meta.get("currency")),
    )


def request_spark(symbols: list[str], timeout: int = 45) -> list[dict]:
    url = "https://query1.finance.yahoo.com/v7/finance/spark"
    params = {"symbols": ",".join(symbols), "range": "2y", "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code == 400 and len(symbols) > 1:
                midpoint = len(symbols) // 2
                return request_spark(symbols[:midpoint], timeout) + request_spark(symbols[midpoint:], timeout)
            if response.status_code == 429:
                raise RuntimeError("Yahoo rate limit (429)")
            response.raise_for_status()
            payload = response.json()
            return (payload.get("spark") or {}).get("result") or []
        except Exception as error:
            last_error = error
            time.sleep(1 + attempt)
    if len(symbols) > 1:
        midpoint = len(symbols) // 2
        return request_spark(symbols[:midpoint], timeout) + request_spark(symbols[midpoint:], timeout)
    print(f"[warning] price request failed for {symbols[0]}: {last_error}", file=sys.stderr)
    return []


def collect_prices(universe: pd.DataFrame, workers: int, chunk_size: int) -> dict[str, PriceRecord]:
    now_utc = datetime.now(timezone.utc)
    groups = []
    market_by_symbol: dict[str, str] = {}
    for market, frame in universe.groupby("market", sort=False):
        symbols = frame["yahoo_symbol"].drop_duplicates().tolist()
        market_by_symbol.update({symbol: market for symbol in symbols})
        groups.extend((market, batch) for batch in chunks(symbols, chunk_size))
    records: dict[str, PriceRecord] = {}
    completed = 0
    total = len(groups)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(request_spark, batch): (market, batch) for market, batch in groups}
        for future in as_completed(future_map):
            market, batch = future_map[future]
            try:
                results = future.result()
            except Exception as error:
                print(f"[warning] price batch failed ({market}, {len(batch)}): {error}", file=sys.stderr)
                results = []
            for result in results:
                symbol = clean_text(result.get("symbol"))
                result_market = market_by_symbol.get(symbol, market)
                record = parse_price_result(result, result_market, now_utc)
                if record:
                    records[f"{result_market}|{record.yahoo_symbol}"] = record
            completed += 1
            if completed == 1 or completed % 10 == 0 or completed == total:
                print(f"[prices] {completed}/{total} batches · {len(records):,} symbols")
    return records


def fetch_naver_recent_activity(symbol: str, target_date: str, timeout: int = 30) -> tuple[float, float] | None:
    url = "https://fchart.stock.naver.com/sise.nhn"
    params = {"symbol": symbol, "timeframe": "day", "count": 15, "requestType": 0}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    for attempt in range(2):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            text = response.content.decode("euc-kr", errors="replace")
            if "?>" in text:
                text = text.split("?>", 1)[1]
            root = ET.fromstring(text)
            rows: list[tuple[str, float]] = []
            for item in root.iter("item"):
                parts = clean_text(item.attrib.get("data")).split("|")
                if len(parts) < 6:
                    continue
                try:
                    rows.append((parts[0], float(parts[5])))
                except (TypeError, ValueError):
                    continue
            compact_target_date = target_date.replace("-", "")
            target_index = next((index for index, row in enumerate(rows) if row[0] == compact_target_date), None)
            if target_index is None or target_index == 0:
                return None
            return rows[target_index][1], rows[target_index - 1][1]
        except Exception:
            if attempt == 0:
                time.sleep(1)
    return None


def validate_korean_trading_activity(
    universe: pd.DataFrame, prices: dict[str, PriceRecord], workers: int
) -> dict[str, PriceRecord]:
    symbol_lookup = {
        row.yahoo_symbol: row.symbol
        for row in universe[universe["market"] == "KR"].itertuples(index=False)
    }
    candidates = []
    for key, record in prices.items():
        market, yahoo_symbol = key.split("|", 1)
        if market == "KR" and (record.is_high or record.was_high_previous):
            symbol = symbol_lookup.get(yahoo_symbol)
            if symbol:
                candidates.append((key, symbol, record))
    cleared_current = 0
    cleared_previous = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(fetch_naver_recent_activity, symbol, record.as_of): (key, record)
            for key, symbol, record in candidates
        }
        for future in as_completed(future_map):
            key, record = future_map[future]
            try:
                activity = future.result()
            except Exception:
                activity = None
            if activity is None:
                continue
            current_volume, previous_volume = activity
            current_is_high = record.is_high and current_volume > 0
            previous_was_high = record.was_high_previous and previous_volume > 0
            cleared_current += int(record.is_high and not current_is_high)
            cleared_previous += int(record.was_high_previous and not previous_was_high)
            if current_is_high != record.is_high or previous_was_high != record.was_high_previous:
                updates = {
                    "is_high": current_is_high,
                    "was_high_previous": previous_was_high,
                }
                if not current_is_high:
                    updates.update(
                        breakout_date=record.as_of,
                        breakout_close=record.close,
                        breakout_pct=0.0,
                    )
                prices[key] = replace(record, **updates)
    print(
        f"[kr-activity] {len(candidates):,} high candidates checked · "
        f"{cleared_current:,} current / {cleared_previous:,} previous zero-volume flags cleared"
    )
    return prices


def rounded(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def fetch_fx_rates() -> tuple[dict[str, float], str]:
    rates = {"KRW": 1.0}
    results = request_spark(list(FX_SYMBOLS.values()), timeout=45)
    reverse_symbols = {symbol: currency for currency, symbol in FX_SYMBOLS.items()}
    timestamps = []
    for result in results:
        currency = reverse_symbols.get(clean_text(result.get("symbol")))
        responses = result.get("response") or []
        if not currency or not responses:
            continue
        meta = (responses[0] or {}).get("meta") or {}
        try:
            price = float(meta.get("regularMarketPrice"))
            stamp = int(meta.get("regularMarketTime"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and price > 0:
            rates[currency] = price
            timestamps.append(stamp)
    missing = [currency for currency in FX_SYMBOLS if currency not in rates]
    if missing:
        raise RuntimeError(f"Missing KRW FX rates: {', '.join(missing)}")
    fx_as_of = datetime.fromtimestamp(max(timestamps), tz=timezone.utc).astimezone(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    return rates, fx_as_of


def positive_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def market_cap_krw_for(row: object, record: PriceRecord | None, fx_rates: dict[str, float]) -> float | None:
    currency = clean_text(getattr(row, "currency", "")) or (record.currency if record else "")
    fx_rate = fx_rates.get(currency)
    if not fx_rate:
        return None
    local_cap = positive_number(getattr(row, "market_cap_local", None))
    if local_cap is None:
        shares = positive_number(getattr(row, "shares_outstanding", None))
        if shares and record:
            local_cap = shares * record.close
    return local_cap * fx_rate if local_cap else None


def build_payload(universe: pd.DataFrame, prices: dict[str, PriceRecord], fx_rates: dict[str, float], fx_as_of: str) -> dict:
    market_stats = {}
    high_rows = []
    screened_rows = []
    global_sector_counts: Counter[str] = Counter()
    total_previous_highs = 0

    for market in MARKET_ORDER:
        market_universe = universe[universe["market"] == market]
        if market_universe.empty:
            continue
        stats_sector: Counter[str] = Counter()
        dates: Counter[str] = Counter()
        priced_count = 0
        eligible_count = 0
        excluded_small_cap = 0
        excluded_unknown_cap = 0
        previous_highs = 0
        high_count = 0
        new_high_count = 0
        for row in market_universe.itertuples(index=False):
            record = prices.get(f"{market}|{row.yahoo_symbol}")
            market_cap_krw = market_cap_krw_for(row, record, fx_rates)
            if market_cap_krw is None:
                excluded_unknown_cap += 1
                continue
            if market != "KR" and market_cap_krw < MARKET_CAP_MIN_KRW:
                excluded_small_cap += 1
                continue
            eligible_count += 1
            if not record:
                continue
            priced_count += 1
            dates[record.as_of] += 1
            previous_highs += int(record.was_high_previous)
            breakout_days = (
                datetime.fromisoformat(record.as_of).date()
                - datetime.fromisoformat(record.breakout_date).date()
            ).days
            screened = {
                "market": MARKET_LABELS[market],
                "market_code": market,
                "exchange": row.exchange,
                "symbol": row.symbol,
                "yahoo_symbol": row.yahoo_symbol,
                "name": row.name,
                "sector": row.sector or "기타",
                "industry": row.industry,
                "as_of": record.as_of,
                "close": rounded(record.close),
                "prior_high": rounded(record.prior_high),
                "breakout_date": record.breakout_date,
                "breakout_close": rounded(record.breakout_close),
                "breakout_pct": rounded(record.breakout_pct, 3),
                "breakout_days": breakout_days,
                "is_high": record.is_high,
                "was_high_previous": record.was_high_previous,
                "is_new_high": record.is_high and not record.was_high_previous,
                "history_days": record.history_days,
                "currency": record.currency,
                "market_cap_krw": round(market_cap_krw),
                "market_cap_krw_eok": rounded(market_cap_krw / 100_000_000, 1),
            }
            screened_rows.append(screened)
            if record.is_high:
                high_count += 1
                new_high_count += int(not record.was_high_previous)
                stats_sector[screened["sector"]] += 1
                global_sector_counts[screened["sector"]] += 1
                high_rows.append(screened)
        total_previous_highs += previous_highs
        as_of = dates.most_common(1)[0][0] if dates else ""
        market_stats[market] = {
            "name": MARKET_LABELS[market],
            "raw_universe": int(len(market_universe)),
            "universe": eligible_count,
            "screened": priced_count,
            "coverage_pct": rounded(priced_count / eligible_count * 100, 1) if eligible_count else 0,
            "excluded_small_cap": excluded_small_cap,
            "excluded_unknown_market_cap": excluded_unknown_cap,
            "highs": high_count,
            "new_highs": new_high_count,
            "previous_highs": previous_highs,
            "delta": high_count - previous_highs,
            "ratio_pct": rounded(high_count / priced_count * 100, 2) if priced_count else 0,
            "as_of": as_of,
            "sectors": dict(stats_sector.most_common()),
        }

    high_rows.sort(key=lambda row: (row["breakout_pct"], row["close"]), reverse=True)
    screened_rows.sort(key=lambda row: (row["market_code"], row["yahoo_symbol"]))
    SCREENED_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(screened_rows).to_csv(SCREENED_PATH, index=False, encoding="utf-8-sig")

    total_screened = sum(item["screened"] for item in market_stats.values())
    total_universe = sum(item["universe"] for item in market_stats.values())
    total_raw_universe = sum(item["raw_universe"] for item in market_stats.values())
    total_excluded_small_cap = sum(item["excluded_small_cap"] for item in market_stats.values())
    total_excluded_unknown_cap = sum(item["excluded_unknown_market_cap"] for item in market_stats.values())
    total_highs = len(high_rows)
    total_new_highs = sum(item["new_highs"] for item in market_stats.values())
    collected_at = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    return {
        "meta": {
            "actual_data": True,
            "collected_at": collected_at,
            "rule": "최근 완료 거래일 종가가 직전 최대 251거래일 종가 최고치 이상",
            "short_history_rule": "상장 52주 미만 종목은 상장 이후, 최소 20거래일 필요",
            "breakout_return_rule": "최신 종가를 최근 365일 내 최초 52주 신고가 종가와 비교한 누적 수익률",
            "breakout_days_rule": "최초 신고가 기준일부터 최신 종가 기준일까지의 달력일수",
            "market_cap_rule": "한국은 시가총액 제한 없음, 기타 시장은 원화 환산 시가총액 3,000억원 이상, 시가총액 미확인 종목 제외",
            "market_cap_min_krw": MARKET_CAP_MIN_KRW,
            "market_cap_exempt_markets": ["KR"],
            "fx_rates_krw": fx_rates,
            "fx_as_of": fx_as_of,
            "price_source": "Yahoo Finance daily close via spark endpoint",
            "listing_sources": "FinanceDataReader/Naver, S&P 500 listing, TWSE OpenAPI, TPEx OpenAPI",
        },
        "summary": {
            "raw_universe": total_raw_universe,
            "universe": total_universe,
            "screened": total_screened,
            "coverage_pct": rounded(total_screened / total_universe * 100, 1) if total_universe else 0,
            "excluded_small_cap": total_excluded_small_cap,
            "excluded_unknown_market_cap": total_excluded_unknown_cap,
            "highs": total_highs,
            "new_highs": total_new_highs,
            "previous_highs": total_previous_highs,
            "delta": total_highs - total_previous_highs,
            "ratio_pct": rounded(total_highs / total_screened * 100, 2) if total_screened else 0,
            "top_sector": global_sector_counts.most_common(1)[0][0] if global_sector_counts else "-",
            "top_sector_count": global_sector_counts.most_common(1)[0][1] if global_sector_counts else 0,
        },
        "markets": market_stats,
        "sectors": dict(global_sector_counts.most_common()),
        "highs": high_rows,
    }


def update_history(payload: dict) -> list[dict]:
    history: list[dict] = []
    if HISTORY_PATH.exists():
        try:
            loaded = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                history = [item for item in loaded if isinstance(item, dict) and item.get("date")]
        except (json.JSONDecodeError, OSError):
            history = []

    snapshot = {
        "date": payload["meta"]["collected_at"][:10],
        "total": int(payload["summary"]["highs"]),
        "markets": {
            code: {
                "highs": int(stats["highs"]),
                "new_highs": int(stats["new_highs"]),
                "as_of": stats["as_of"],
            }
            for code, stats in payload["markets"].items()
        },
    }
    by_date = {item["date"]: item for item in history}
    by_date[snapshot["date"]] = snapshot
    history = [by_date[date] for date in sorted(by_date)][-365:]
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return history


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Global close-based 52-week high screener")
    parser.add_argument("--markets", default=",".join(MARKET_ORDER), help="Comma-separated market codes: US,KR,JP,CN,TW,HK")
    parser.add_argument("--refresh-listings", action="store_true", help="Ignore listing cache")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0, help="Testing limit per market")
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    args = parse_args()
    markets = [item.strip().upper() for item in args.markets.split(",") if item.strip()]
    invalid = [item for item in markets if item not in MARKET_ORDER]
    if invalid:
        raise SystemExit(f"Unknown markets: {', '.join(invalid)}")
    ensure_dirs()
    universe = build_universe(markets, args.refresh_listings)
    if args.limit:
        universe = universe.groupby("market", group_keys=False).head(args.limit).reset_index(drop=True)
    universe.to_csv(UNIVERSE_PATH, index=False, encoding="utf-8-sig")
    print(f"[universe] {len(universe):,} symbols")
    prices = collect_prices(universe, max(1, args.workers), max(1, args.chunk_size))
    prices = validate_korean_trading_activity(universe, prices, max(1, args.workers))
    fx_rates, fx_as_of = fetch_fx_rates()
    print(f"[fx] {fx_rates}")
    payload = build_payload(universe, prices, fx_rates, fx_as_of)
    payload["history"] = update_history(payload)
    LATEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"[done] {LATEST_PATH}")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
