from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import collect


class RelativeStrengthTests(unittest.TestCase):
    def test_build_payload_calculates_five_day_relative_strength(self) -> None:
        universe = pd.DataFrame(
            [
                {
                    "market": "US",
                    "exchange": "NASDAQ",
                    "symbol": "ABC",
                    "yahoo_symbol": "ABC",
                    "name": "ABC Corporation",
                    "sector": "IT",
                    "industry": "Software",
                    "market_cap_local": 1_000_000_000,
                    "currency": "USD",
                    "shares_outstanding": 10_000_000,
                }
            ]
        )
        prices = {
            "US|ABC": collect.PriceRecord(
                yahoo_symbol="ABC",
                as_of="2026-10-20",
                close=100.0,
                day_return_pct=2.0,
                return_5d_pct=8.0,
                prior_high=110.0,
                breakout_date="2026-10-20",
                breakout_close=100.0,
                breakout_pct=0.0,
                is_high=False,
                was_high_previous=False,
                history_days=253,
                latest_volume=1_000_000,
                currency="USD",
            )
        }
        benchmarks = {
            "US:NASDAQ": {
                "symbol": "^IXIC",
                "name": "NASDAQ Composite",
                "as_of": "2026-10-20",
                "return_5d_pct": 2.5,
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(collect, "SCREENED_PATH", Path(temp_dir) / "screened.csv"):
                payload = collect.build_payload(
                    universe,
                    prices,
                    {"USD": 1_400.0},
                    "2026-10-20T00:00:00+09:00",
                    benchmarks,
                )

        row = payload["relative_strength"][0]
        self.assertEqual(row["benchmark_name"], "NASDAQ Composite")
        self.assertEqual(row["return_5d_pct"], 8.0)
        self.assertEqual(row["benchmark_return_5d_pct"], 2.5)
        self.assertEqual(row["relative_strength_5d_pct"], 5.5)

    def test_relative_strength_excludes_zero_volume_and_stale_prices(self) -> None:
        universe = pd.DataFrame(
            [
                {
                    "market": "US", "exchange": "NASDAQ", "symbol": symbol,
                    "yahoo_symbol": symbol, "name": symbol, "sector": "IT",
                    "industry": "Software", "market_cap_local": 1_000_000_000,
                    "currency": "USD", "shares_outstanding": 10_000_000,
                }
                for symbol in ("ACTIVE", "HALTED", "STALE")
            ]
        )

        def price(symbol: str, as_of: str, latest_volume: float) -> collect.PriceRecord:
            return collect.PriceRecord(
                yahoo_symbol=symbol, as_of=as_of, close=100.0,
                day_return_pct=2.0, return_5d_pct=8.0, prior_high=110.0,
                breakout_date=as_of, breakout_close=100.0, breakout_pct=0.0,
                is_high=False, was_high_previous=False, history_days=253,
                latest_volume=latest_volume, currency="USD",
            )

        prices = {
            "US|ACTIVE": price("ACTIVE", "2026-10-20", 1_000_000),
            "US|HALTED": price("HALTED", "2026-10-20", 0),
            "US|STALE": price("STALE", "2026-10-17", 500_000),
        }
        benchmarks = {
            "US:NASDAQ": {
                "symbol": "^IXIC", "name": "NASDAQ Composite",
                "as_of": "2026-10-20", "return_5d_pct": 2.5,
            }
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(collect, "SCREENED_PATH", Path(temp_dir) / "screened.csv"):
                payload = collect.build_payload(
                    universe, prices, {"USD": 1_400.0},
                    "2026-10-20T00:00:00+09:00", benchmarks,
                )

        self.assertEqual([row["symbol"] for row in payload["relative_strength"]], ["ACTIVE"])

    def test_korean_relative_strength_uses_naver_overlay(self) -> None:
        universe = pd.DataFrame(
            [
                {
                    "market": "KR", "exchange": "KOSPI", "symbol": "005930",
                    "yahoo_symbol": "005930.KS", "name": "삼성전자", "sector": "IT",
                    "industry": "반도체", "market_cap_local": 500_000_000_000_000,
                    "currency": "KRW", "shares_outstanding": 1,
                }
            ]
        )
        prices = {
            "KR|005930.KS": collect.PriceRecord(
                yahoo_symbol="005930.KS", as_of="2026-10-20", close=100.0,
                day_return_pct=1.0, return_5d_pct=-99.0, prior_high=110.0,
                breakout_date="2026-10-20", breakout_close=100.0, breakout_pct=0.0,
                is_high=False, was_high_previous=False, history_days=253,
                latest_volume=0, currency="KRW",
            )
        }
        benchmarks = {
            "KR:KOSPI": {
                "symbol": "KOSPI", "name": "KOSPI", "as_of": "2026-10-20",
                "return_5d_pct": -2.0, "source": "Naver Finance domestic index daily OHLCV",
            }
        }
        relative_prices = {
            "KR|005930.KS": collect.RelativePriceRecord(
                as_of="2026-10-20", return_5d_pct=5.0,
                latest_volume=10_000_000,
                source="Naver Finance domestic daily OHLCV",
            )
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(collect, "SCREENED_PATH", Path(temp_dir) / "screened.csv"):
                payload = collect.build_payload(
                    universe, prices, {"KRW": 1.0},
                    "2026-10-20T00:00:00+09:00", benchmarks, relative_prices,
                )

        row = payload["relative_strength"][0]
        self.assertEqual(row["symbol"], "005930")
        self.assertEqual(row["return_5d_pct"], 5.0)
        self.assertEqual(row["relative_strength_5d_pct"], 7.0)
        self.assertIn("Naver Finance", row["price_source"])


if __name__ == "__main__":
    unittest.main()
