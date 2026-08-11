# -*- coding: utf-8 -*-
"""Regression tests for the explainable portfolio trader profile."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src.config import Config
from src.services.portfolio_service import PortfolioService
from src.storage import DatabaseManager


def _reset_runtime() -> None:
    DatabaseManager.reset_instance()
    Config.reset_instance()


def test_trader_profile_uses_full_account_ledger_and_exposes_confidence():
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "profile.db"
        env_path = Path(temp_dir) / ".env"
        env_path.write_text(
            f"STOCK_LIST=600519\nGEMINI_API_KEY=test\nADMIN_AUTH_ENABLED=false\nDATABASE_PATH={db_path}\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(env_path)
        os.environ["DATABASE_PATH"] = str(db_path)
        _reset_runtime()
        try:
            service = PortfolioService()
            account = service.create_account(
                name="Profile",
                broker="Demo",
                market="cn",
                base_currency="CNY",
            )
            account_id = account["id"]
            trades = [
                (date(2026, 1, 1), "buy", 100, 10.0),
                (date(2026, 1, 5), "buy", 50, 9.0),
                (date(2026, 1, 10), "sell", 50, 12.0),
                (date(2026, 1, 15), "buy", 50, 11.0),
                (date(2026, 1, 20), "sell", 50, 8.0),
                (date(2026, 1, 25), "buy", 50, 7.0),
                (date(2026, 2, 1), "sell", 50, 9.0),
                (date(2026, 2, 10), "buy", 50, 8.0),
            ]
            for trade_date, side, quantity, price in trades:
                service.record_trade(
                    account_id=account_id,
                    symbol="600519",
                    trade_date=trade_date,
                    side=side,
                    quantity=quantity,
                    price=price,
                    market="cn",
                    currency="CNY",
                )

            supporting_snapshot = {
                "currency": "CNY",
                "accounts": [
                    {
                        "base_currency": "CNY",
                        "positions": [
                            {"market_value_base": 1500.0, "holding_days": 40},
                            {"market_value_base": 500.0, "holding_days": 10},
                        ],
                    }
                ],
            }
            with patch.object(service, "get_portfolio_snapshot", return_value=supporting_snapshot):
                profile = service.get_trader_profile(
                    account_id=account_id,
                    as_of=date(2026, 2, 15),
                )

            assert profile["scope"] == "account"
            assert profile["sample"]["trade_count"] == 8
            assert profile["sample"]["observation_days"] == 41
            assert profile["status"] == "ready"
            assert profile["confidence"] in {"low", "medium", "high"}
            dimensions = {item["key"]: item for item in profile["dimensions"]}
            assert set(dimensions) == {
                "activity",
                "short_horizon",
                "concentration",
                "scale_in",
                "profit_taking",
                "sizing_consistency",
            }
            assert dimensions["concentration"]["score"] == 75
            assert dimensions["profit_taking"]["available"] is True
            assert dimensions["scale_in"]["evidence"]["scale_in_ratio_pct"] > 0
            assert profile["methodology_version"] == "portfolio-style-v1"
        finally:
            _reset_runtime()
            os.environ.pop("ENV_FILE", None)
            os.environ.pop("DATABASE_PATH", None)
