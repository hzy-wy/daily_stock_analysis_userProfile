# -*- coding: utf-8 -*-
"""Tests for the reviewed portfolio screenshot import boundary."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from src.services.portfolio_image_import_service import PortfolioImageImportService


class PortfolioImageImportServiceTestCase(unittest.TestCase):
    def test_parse_image_normalizes_trades_and_preserves_review_warnings(self) -> None:
        importer = MagicMock()
        service = PortfolioImageImportService(importer=importer)
        vision_payload = {
            "trades": [
                {
                    "trade_date": "2026-07-29",
                    "symbol": "600693.SH",
                    "stock_name": "东百集团",
                    "side": "卖出",
                    "quantity": -200,
                    "price": 9.10,
                    "fee": 0,
                    "tax": 0,
                    "currency": "CNY",
                    "confidence": "high",
                    "warning": "费用未显示，请核对",
                },
                {
                    "trade_date": "2026-07-29",
                    "symbol": "600693",
                    "stock_name": "东百集团",
                    "side": "建仓",
                    "quantity": 200,
                    "price": 8.67,
                    "fee": 0,
                    "tax": 0,
                    "currency": "CNY",
                    "confidence": "high",
                },
            ],
            "warnings": ["顶部盈亏字段已忽略"],
        }

        with patch(
            "src.services.portfolio_image_import_service.run_vision_prompt_on_image",
            return_value=json.dumps(vision_payload, ensure_ascii=False),
        ):
            parsed = service.parse_image(content=b"same-screenshot", mime_type="image/png")

        self.assertEqual(parsed["record_count"], 2)
        self.assertEqual([item["side"] for item in parsed["records"]], ["buy", "sell"])
        self.assertEqual(parsed["records"][0]["symbol"], "600693")
        self.assertEqual(parsed["records"][1]["quantity"], 200.0)
        self.assertIn("顶部盈亏字段已忽略", parsed["warnings"])
        self.assertEqual(len(parsed["source_hash"]), 64)

    def test_parse_image_skips_rows_without_required_trade_fields(self) -> None:
        service = PortfolioImageImportService(importer=MagicMock())
        vision_payload = {
            "trades": [
                {
                    "trade_date": "2026-07-29",
                    "symbol": "600693",
                    "side": "buy",
                    "quantity": 200,
                    "price": 0,
                }
            ],
            "warnings": [],
        }

        with patch(
            "src.services.portfolio_image_import_service.run_vision_prompt_on_image",
            return_value=json.dumps(vision_payload),
        ):
            parsed = service.parse_image(content=b"bad-row", mime_type="image/png")

        self.assertEqual(parsed["records"], [])
        self.assertIn("成交价必须大于 0", parsed["warnings"][0])

    def test_parse_image_resolves_name_only_screenshot_from_local_index(self) -> None:
        service = PortfolioImageImportService(importer=MagicMock())
        vision_payload = {
            "trades": [
                {
                    "trade_date": "2026-07-29",
                    "symbol": None,
                    "stock_name": "东百集团",
                    "side": "buy",
                    "quantity": 200,
                    "price": 8.67,
                    "fee": 0,
                    "tax": 0,
                    "currency": "CNY",
                    "confidence": "high",
                }
            ],
            "warnings": [],
        }

        with patch(
            "src.services.portfolio_image_import_service.run_vision_prompt_on_image",
            return_value=json.dumps(vision_payload, ensure_ascii=False),
        ):
            parsed = service.parse_image(content=b"name-only-screenshot", mime_type="image/png")

        self.assertEqual(parsed["record_count"], 1)
        self.assertEqual(parsed["records"][0]["symbol"], "600693")
        self.assertEqual(parsed["records"][0]["stock_name"], "东百集团")

    def test_commit_records_sorts_same_day_buy_before_sell(self) -> None:
        importer = MagicMock()
        importer.commit_normalized_trade_records.return_value = {
            "account_id": 7,
            "record_count": 2,
            "inserted_count": 2,
            "duplicate_count": 0,
            "failed_count": 0,
            "dry_run": False,
            "errors": [],
        }
        service = PortfolioImageImportService(importer=importer)
        source_hash = "a" * 64
        records = [
            {
                "trade_date": "2026-07-29",
                "symbol": "600693",
                "side": "sell",
                "quantity": 200,
                "price": 9.10,
                "fee": 0,
                "tax": 0,
                "currency": "CNY",
                "confidence": "high",
                "source_index": 0,
            },
            {
                "trade_date": "2026-07-29",
                "symbol": "600693",
                "side": "buy",
                "quantity": 200,
                "price": 8.67,
                "fee": 0,
                "tax": 0,
                "currency": "CNY",
                "confidence": "high",
                "source_index": 1,
            },
        ]

        result = service.commit_records(
            account_id=7,
            source_hash=source_hash,
            records=records,
        )

        self.assertEqual(result["inserted_count"], 2)
        committed_records = importer.commit_normalized_trade_records.call_args.kwargs["records"]
        self.assertEqual([item["side"] for item in committed_records], ["buy", "sell"])
        self.assertTrue(all(len(item["dedup_hash"]) == 64 for item in committed_records))


if __name__ == "__main__":
    unittest.main()
