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


if __name__ == "__main__":
    unittest.main()
