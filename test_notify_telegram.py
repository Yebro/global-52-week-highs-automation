from __future__ import annotations

import time
import unittest

import notify_telegram as subject


class IssueSelectionTests(unittest.TestCase):
    def test_asia_summary_uses_asia_markets_and_one_trillion_cutoff(self) -> None:
        payload = {
            "highs": [
                {
                    "market_code": "KR",
                    "is_new_high": True,
                    "market_cap_krw": 1_000_000_000_000,
                    "day_return_pct": 5,
                    "symbol": "000001",
                },
                {
                    "market_code": "US",
                    "is_new_high": True,
                    "market_cap_krw": 50_000_000_000_000,
                    "day_return_pct": 10,
                    "symbol": "BIG",
                },
                {
                    "market_code": "JP",
                    "is_new_high": True,
                    "market_cap_krw": 999_999_999_999,
                    "day_return_pct": 20,
                    "symbol": "SMALL",
                },
            ]
        }
        rows = subject.select_summary_rows(payload, slot="asia")
        self.assertEqual([row["symbol"] for row in rows], ["000001"])

    def test_us_summary_uses_us_market_and_ten_trillion_cutoff(self) -> None:
        payload = {
            "highs": [
                {
                    "market_code": "US",
                    "is_new_high": True,
                    "market_cap_krw": 10_000_000_000_000,
                    "day_return_pct": 4,
                    "symbol": "QUALIFY",
                },
                {
                    "market_code": "US",
                    "is_new_high": True,
                    "market_cap_krw": 9_999_999_999_999,
                    "day_return_pct": 8,
                    "symbol": "TOO_SMALL",
                },
                {
                    "market_code": "KR",
                    "is_new_high": True,
                    "market_cap_krw": 20_000_000_000_000,
                    "day_return_pct": 12,
                    "symbol": "WRONG_MARKET",
                },
            ]
        }
        rows = subject.select_summary_rows(payload, slot="us")
        self.assertEqual([row["symbol"] for row in rows], ["QUALIFY"])

    def test_yahoo_symbol_matching_handles_exchange_suffix(self) -> None:
        self.assertTrue(subject._symbols_match("2362.HK", "2362.HK"))
        self.assertTrue(subject._symbols_match("2362.HK", "2362"))
        self.assertFalse(subject._symbols_match("2363.HK", "2362.HK"))

    def test_google_queries_include_english_sources_and_yahoo_symbol(self) -> None:
        queries = subject._build_google_queries(
            "CanSino Biologics",
            "688185",
            "688185.SS",
            "China stock",
            ["CANSINO BIOLOGICS INC"],
        )
        combined = " ".join(queries)
        self.assertIn('"688185.SS"', combined)
        self.assertIn("Reuters", combined)
        self.assertIn('"Yahoo Finance"', combined)
        self.assertIn("Investing.com", combined)
        self.assertIn("CANSINO BIOLOGICS INC", combined)

    def test_rejects_price_movement_without_catalyst(self) -> None:
        self.assertTrue(subject._is_price_only_title("ABC shares surge to a 52-week high"))

    def test_keeps_price_movement_when_title_names_catalyst(self) -> None:
        self.assertFalse(
            subject._is_price_only_title("ABC shares surge after earnings beat and guidance raise")
        )

    def test_reuters_catalyst_outranks_generic_article(self) -> None:
        now = int(time.time())
        aliases = ["ABC Corporation", "ABC"]
        reuters = {
            "title": "ABC wins major supply contract as backlog expands",
            "publisher": "Reuters",
            "published_at": now - 3600,
        }
        generic = {
            "title": "ABC announces a new corporate website",
            "publisher": "Example Blog",
            "published_at": now - 600,
        }
        self.assertGreater(
            subject._candidate_score(reuters, aliases, now),
            subject._candidate_score(generic, aliases, now),
        )

    def test_rejects_unrelated_low_authority_result(self) -> None:
        now = int(time.time())
        unrelated = {
            "title": "China expands non-ferrous recycling capacity",
            "publisher": "Example Industry Blog",
            "published_at": now - 3600,
        }
        self.assertEqual(
            subject._candidate_score(unrelated, ["Jinchuan International"], now),
            -1_000,
        )

    def test_generic_company_word_does_not_create_false_match(self) -> None:
        now = int(time.time())
        unrelated = {
            "title": "Registry launches tools for human-created works",
            "publisher": "Example News",
            "published_at": now - 3600,
        }
        self.assertEqual(
            subject._candidate_score(unrelated, ["HUMAN MADE Inc"], now),
            -1_000,
        )

    def test_exchange_suffix_does_not_match_wrong_taiwan_stock(self) -> None:
        now = int(time.time())
        unrelated = {
            "title": "Aurotek Corporation (6215.TW) analyst insights and recommendations",
            "publisher": "Yahoo Finance Canada",
            "published_at": now - 3600,
        }
        self.assertEqual(
            subject._candidate_score(
                unrelated, ["TA LIANG", "3167.TW"], now
            ),
            -1_000,
        )

    def test_intl_alias_matches_international_title(self) -> None:
        now = int(time.time())
        related = {
            "title": "Jinchuan International meets resumption conditions",
            "publisher": "Moomoo",
            "published_at": now - 3600,
        }
        self.assertGreater(
            subject._candidate_score(related, ["JINCHUAN INTL"], now),
            0,
        )

    def test_positive_catalyst_outranks_earnings_miss(self) -> None:
        now = int(time.time())
        positive = {
            "title": "CanSino vaccine application accepted by regulator",
            "publisher": "BioSpectrum Asia",
            "published_at": now - 86400 * 10,
        }
        negative = {
            "title": "CanSino earnings missed estimates",
            "publisher": "Example Finance",
            "published_at": now - 3600,
        }
        aliases = ["CanSino Biologics"]
        self.assertGreater(
            subject._candidate_score(positive, aliases, now),
            subject._candidate_score(negative, aliases, now),
        )

    def test_google_title_source_suffix_is_removed(self) -> None:
        self.assertEqual(
            subject._normalise_title("ABC raises full-year guidance - Reuters", "Reuters"),
            "ABC raises full-year guidance",
        )

    def test_known_non_english_publisher_name_is_normalised(self) -> None:
        candidates = []
        subject._add_candidate(
            candidates,
            {
                "title": "Company reports strong revenue growth - 富途牛牛",
                "publisher": "富途牛牛",
                "published_at": int(time.time()),
            },
        )
        self.assertEqual(candidates[0]["publisher"], "Moomoo")
        self.assertEqual(candidates[0]["title"], "Company reports strong revenue growth")


if __name__ == "__main__":
    unittest.main()
