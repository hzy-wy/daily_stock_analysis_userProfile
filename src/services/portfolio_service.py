# -*- coding: utf-8 -*-
"""Portfolio service for P0 account/events/snapshot workflow."""

from __future__ import annotations

import json
import logging
import math
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from data_provider.base import canonical_stock_code, normalize_stock_code
from src.config import get_config
from src.core.trading_calendar import count_market_sessions
from src.data.stock_index_loader import get_index_stock_name
from src.data.stock_mapping import STOCK_NAME_MAP, is_meaningful_stock_name
from src.repositories.portfolio_repo import (
    DuplicateTradeDedupHashError,
    DuplicateTradeUidError,
    PortfolioBusyError as RepoPortfolioBusyError,
    PortfolioRepository,
)

logger = logging.getLogger(__name__)

PortfolioBusyError = RepoPortfolioBusyError

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional dependency path
    yf = None

EPS = 1e-8
VALID_MARKETS = {"cn", "hk", "us", "jp", "kr", "tw"}
PARTIAL_VALUATION_MARKETS = {"jp", "kr", "tw"}
VALID_COST_METHODS = {"fifo", "avg"}
VALID_SIDES = {"buy", "sell"}
VALID_CASH_DIRECTIONS = {"in", "out"}
VALID_CORPORATE_ACTIONS = {"cash_dividend", "split_adjustment"}
PORTFOLIO_FX_REFRESH_DISABLED_REASON = "portfolio_fx_update_disabled"
PORTFOLIO_REALTIME_QUOTE_MAX_WORKERS = 4


def _portfolio_limitations_for_market(market: str) -> List[str]:
    """Return explicit snapshot limitations for markets with partial valuation semantics."""

    if market not in PARTIAL_VALUATION_MARKETS:
        return []
    return [
        "realtime_quote_best_effort",
        "fx_and_cost_basis_partial",
        "sector_and_risk_metrics_limited",
    ]


def _merge_portfolio_limitations(*groups: Iterable[str]) -> List[str]:
    merged: List[str] = []
    seen: Set[str] = set()
    for group in groups:
        for item in group:
            if item and item not in seen:
                seen.add(item)
                merged.append(item)
    return merged


class PortfolioConflictError(Exception):
    """Raised when request conflicts with existing portfolio state."""


class PortfolioOversellError(ValueError):
    """Raised when a sell would exceed the available position quantity."""

    def __init__(
        self,
        *,
        symbol: str,
        trade_date: Optional[date],
        requested_quantity: float,
        available_quantity: float,
    ) -> None:
        self.symbol = symbol
        self.trade_date = trade_date
        self.requested_quantity = float(requested_quantity)
        self.available_quantity = max(0.0, float(available_quantity))
        date_hint = f" on {trade_date.isoformat()}" if trade_date is not None else ""
        super().__init__(
            "Oversell detected for "
            f"{symbol}{date_hint}: requested={round(self.requested_quantity, 8)}, "
            f"available={round(self.available_quantity, 8)}"
        )


@dataclass
class _AvgState:
    quantity: float = 0.0
    total_cost: float = 0.0


@dataclass
class _HoldingCycleState:
    """Net invested capital for one continuous end-of-day holding cycle."""

    quantity: float = 0.0
    net_cost: float = 0.0
    start_date: Optional[date] = None


@dataclass(frozen=True)
class _ResolvedPositionPrice:
    price: float
    source: str
    price_date: Optional[date]
    is_stale: bool
    is_available: bool
    provider: Optional[str] = None


class PortfolioService:
    """Business logic for account CRUD, event writes, and snapshot replay."""

    def __init__(self, repo: Optional[PortfolioRepository] = None):
        self.repo = repo or PortfolioRepository()

    # ------------------------------------------------------------------
    # Account CRUD
    # ------------------------------------------------------------------
    def create_account(
        self,
        *,
        name: str,
        broker: Optional[str],
        market: str,
        base_currency: str,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        name_norm = (name or "").strip()
        if not name_norm:
            raise ValueError("name is required")
        market_norm = self._normalize_market(market)
        base_currency_norm = self._normalize_currency(base_currency)
        row = self.repo.create_account(
            name=name_norm,
            broker=(broker or "").strip() or None,
            market=market_norm,
            base_currency=base_currency_norm,
            owner_id=(owner_id or "").strip() or None,
        )
        return self._account_to_dict(row)

    def list_accounts(self, include_inactive: bool = False) -> List[Dict[str, Any]]:
        rows = self.repo.list_accounts(include_inactive=include_inactive)
        return [self._account_to_dict(r) for r in rows]

    def update_account(
        self,
        account_id: int,
        *,
        name: Optional[str] = None,
        broker: Optional[str] = None,
        market: Optional[str] = None,
        base_currency: Optional[str] = None,
        owner_id: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        fields: Dict[str, Any] = {}
        if name is not None:
            name_norm = name.strip()
            if not name_norm:
                raise ValueError("name is required")
            fields["name"] = name_norm
        if broker is not None:
            fields["broker"] = broker.strip() or None
        if market is not None:
            fields["market"] = self._normalize_market(market)
        if base_currency is not None:
            fields["base_currency"] = self._normalize_currency(base_currency)
        if owner_id is not None:
            fields["owner_id"] = owner_id.strip() or None
        if is_active is not None:
            fields["is_active"] = bool(is_active)
        if not fields:
            raise ValueError("No fields provided for update")

        row = self.repo.update_account(account_id, fields)
        if row is None:
            return None
        return self._account_to_dict(row)

    def deactivate_account(self, account_id: int) -> bool:
        return self.repo.deactivate_account(account_id)

    # ------------------------------------------------------------------
    # Event writes
    # ------------------------------------------------------------------
    def record_trade(
        self,
        *,
        account_id: int,
        symbol: str,
        trade_date: date,
        side: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        tax: float = 0.0,
        market: Optional[str] = None,
        currency: Optional[str] = None,
        trade_uid: Optional[str] = None,
        dedup_hash: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        side_norm = (side or "").strip().lower()
        if side_norm not in VALID_SIDES:
            raise ValueError("side must be buy or sell")
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be > 0")
        if fee < 0 or tax < 0:
            raise ValueError("fee and tax must be >= 0")
        symbol_norm = self._normalize_symbol_for_storage(symbol)
        if not symbol_norm:
            raise ValueError("symbol is required")
        trade_uid_norm = (trade_uid or "").strip() or None
        dedup_hash_norm = (dedup_hash or "").strip() or None
        try:
            with self.repo.portfolio_write_session() as session:
                account = self._require_active_account_in_session(session=session, account_id=account_id)
                market_norm = self._normalize_market(market or account.market)
                currency_norm = self._normalize_currency(currency or self._default_currency_for_market(market_norm))
                self._validate_trade_identity(
                    account_id=account_id,
                    trade_uid=trade_uid_norm,
                    dedup_hash=dedup_hash_norm,
                    session=session,
                )
                if side_norm == "sell":
                    self._validate_sell_quantity(
                        account_id=account_id,
                        symbol=symbol,
                        market=market_norm,
                        currency=currency_norm,
                        trade_date=trade_date,
                        quantity=float(quantity),
                        session=session,
                    )
                row = self.repo.add_trade_in_session(
                    session=session,
                    account_id=account_id,
                    trade_uid=trade_uid_norm,
                    symbol=symbol_norm,
                    market=market_norm,
                    currency=currency_norm,
                    trade_date=trade_date,
                    side=side_norm,
                    quantity=float(quantity),
                    price=float(price),
                    fee=float(fee),
                    tax=float(tax),
                    note=(note or "").strip() or None,
                    dedup_hash=dedup_hash_norm,
                )
                return {"id": int(row.id)}
        except (DuplicateTradeUidError, DuplicateTradeDedupHashError) as exc:
            raise PortfolioConflictError(str(exc)) from exc

    def record_cash_ledger(
        self,
        *,
        account_id: int,
        event_date: date,
        direction: str,
        amount: float,
        currency: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        direction_norm = (direction or "").strip().lower()
        if direction_norm not in VALID_CASH_DIRECTIONS:
            raise ValueError("direction must be in or out")
        if amount <= 0:
            raise ValueError("amount must be > 0")
        with self.repo.portfolio_write_session() as session:
            account = self._require_active_account_in_session(session=session, account_id=account_id)
            currency_norm = self._normalize_currency(currency or account.base_currency)
            row = self.repo.add_cash_ledger_in_session(
                session=session,
                account_id=account_id,
                event_date=event_date,
                direction=direction_norm,
                amount=float(amount),
                currency=currency_norm,
                note=(note or "").strip() or None,
            )
            return {"id": int(row.id)}

    def record_corporate_action(
        self,
        *,
        account_id: int,
        symbol: str,
        effective_date: date,
        action_type: str,
        market: Optional[str] = None,
        currency: Optional[str] = None,
        cash_dividend_per_share: Optional[float] = None,
        split_ratio: Optional[float] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        action_type_norm = (action_type or "").strip().lower()
        if action_type_norm not in VALID_CORPORATE_ACTIONS:
            raise ValueError("action_type must be cash_dividend or split_adjustment")

        if action_type_norm == "cash_dividend":
            if cash_dividend_per_share is None or cash_dividend_per_share < 0:
                raise ValueError("cash_dividend_per_share must be >= 0 for cash_dividend")
        if action_type_norm == "split_adjustment":
            if split_ratio is None or split_ratio <= 0:
                raise ValueError("split_ratio must be > 0 for split_adjustment")
        with self.repo.portfolio_write_session() as session:
            account = self._require_active_account_in_session(session=session, account_id=account_id)
            market_norm = self._normalize_market(market or account.market)
            currency_norm = self._normalize_currency(currency or self._default_currency_for_market(market_norm))
            symbol_norm = self._normalize_symbol_for_storage(symbol)
            if not symbol_norm:
                raise ValueError("symbol is required")
            row = self.repo.add_corporate_action_in_session(
                session=session,
                account_id=account_id,
                symbol=symbol_norm,
                market=market_norm,
                currency=currency_norm,
                effective_date=effective_date,
                action_type=action_type_norm,
                cash_dividend_per_share=cash_dividend_per_share,
                split_ratio=split_ratio,
                note=(note or "").strip() or None,
            )
            return {"id": int(row.id)}

    def delete_trade_event(self, trade_id: int) -> bool:
        with self.repo.portfolio_write_session() as session:
            return self.repo.delete_trade_in_session(session=session, trade_id=trade_id)

    def delete_cash_ledger_event(self, entry_id: int) -> bool:
        with self.repo.portfolio_write_session() as session:
            return self.repo.delete_cash_ledger_in_session(session=session, entry_id=entry_id)

    def delete_corporate_action_event(self, action_id: int) -> bool:
        with self.repo.portfolio_write_session() as session:
            return self.repo.delete_corporate_action_in_session(session=session, action_id=action_id)

    def list_trade_events(
        self,
        *,
        account_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        if account_id is not None:
            self._require_active_account(account_id)
        page, page_size = self._validate_paging(page=page, page_size=page_size)
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must be <= date_to")

        symbol_filters: Optional[List[str]] = None
        if symbol is not None and symbol.strip():
            symbol_filters = self._build_symbol_filter_values(symbol)
            if not symbol_filters:
                raise ValueError("symbol is invalid")

        side_norm: Optional[str] = None
        if side is not None and side.strip():
            side_norm = side.strip().lower()
            if side_norm not in VALID_SIDES:
                raise ValueError("side must be buy or sell")

        rows, total = self.repo.query_trades(
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            symbols=symbol_filters,
            side=side_norm,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._trade_row_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def get_trader_profile(
        self,
        *,
        account_id: Optional[int] = None,
        as_of: Optional[date] = None,
        cost_method: str = "fifo",
    ) -> Dict[str, Any]:
        """Build a deterministic, explainable trader-style profile.

        Scores describe behavioural tendencies, not investing skill.  The full
        active trade ledger is used so pagination cannot change the result.
        """

        as_of_date = as_of or date.today()
        method = self._normalize_cost_method(cost_method)
        if account_id is not None:
            self._require_active_account(account_id)

        trades = [
            row
            for row in self.repo.list_trade_history(account_id=account_id)
            if row.trade_date is not None and row.trade_date <= as_of_date
        ]
        snapshot = self.get_portfolio_snapshot(
            account_id=account_id,
            as_of=as_of_date,
            cost_method=method,
            include_realtime=False,
        )

        trade_count = len(trades)
        buy_count = sum(1 for row in trades if str(row.side).lower() == "buy")
        sell_count = sum(1 for row in trades if str(row.side).lower() == "sell")
        unique_symbols = len({(int(row.account_id), str(row.symbol)) for row in trades})
        first_trade_date = trades[0].trade_date if trades else None
        last_trade_date = trades[-1].trade_date if trades else None
        observation_days = (
            (last_trade_date - first_trade_date).days + 1
            if first_trade_date is not None and last_trade_date is not None
            else 0
        )

        effective_days = max(30, observation_days or 0)
        trades_per_30d = (trade_count * 30.0 / effective_days) if trade_count else 0.0
        activity_score = self._profile_score(
            100.0 * math.log1p(trades_per_30d) / math.log1p(12.0)
        ) if trade_count else None

        lots: Dict[Tuple[int, str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        open_quantities: Dict[Tuple[int, str, str, str], float] = defaultdict(float)
        holding_days_samples: List[float] = []
        matched_sell_results: List[float] = []
        scale_in_count = 0
        trade_notionals: List[float] = []
        unmatched_sell_count = 0

        for row in trades:
            side = str(row.side or "").strip().lower()
            quantity = max(0.0, float(row.quantity or 0.0))
            price = max(0.0, float(row.price or 0.0))
            fee = max(0.0, float(row.fee or 0.0))
            tax = max(0.0, float(row.tax or 0.0))
            if quantity <= EPS or price <= EPS or side not in VALID_SIDES:
                continue
            key = (
                int(row.account_id),
                self._normalize_symbol_for_position(row.symbol),
                self._normalize_market(row.market),
                self._normalize_currency(row.currency),
            )
            trade_notionals.append(quantity * price + fee + tax)
            if side == "buy":
                if open_quantities[key] > EPS:
                    scale_in_count += 1
                lots[key].append(
                    {
                        "quantity": quantity,
                        "unit_cost": (quantity * price + fee + tax) / quantity,
                        "trade_date": row.trade_date,
                    }
                )
                open_quantities[key] += quantity
                continue

            remaining = quantity
            matched_cost = 0.0
            matched_quantity = 0.0
            while remaining > EPS and lots[key]:
                lot = lots[key][0]
                matched = min(remaining, float(lot["quantity"]))
                matched_cost += matched * float(lot["unit_cost"])
                matched_quantity += matched
                holding_days_samples.append(max(0, (row.trade_date - lot["trade_date"]).days))
                lot["quantity"] = float(lot["quantity"]) - matched
                remaining -= matched
                if float(lot["quantity"]) <= EPS:
                    lots[key].pop(0)
            open_quantities[key] = max(0.0, open_quantities[key] - matched_quantity)
            if matched_quantity > EPS:
                allocated_exit_cost = (fee + tax) * (matched_quantity / quantity)
                matched_sell_results.append(matched_quantity * price - allocated_exit_cost - matched_cost)
            if remaining > EPS:
                unmatched_sell_count += 1

        current_holding_days: List[float] = []
        position_values: List[float] = []
        for account in snapshot.get("accounts") or []:
            for position in account.get("positions") or []:
                local_value = max(0.0, float(position.get("market_value_base") or 0.0))
                value, _, _ = self._convert_amount(
                    amount=local_value,
                    from_currency=str(account.get("base_currency") or snapshot.get("currency") or "CNY"),
                    to_currency=str(snapshot.get("currency") or "CNY"),
                    as_of_date=as_of_date,
                )
                if value > EPS:
                    position_values.append(value)
                days = position.get("holding_days")
                if days is not None:
                    current_holding_days.append(max(0.0, float(days)))

        horizon_samples = holding_days_samples + current_holding_days
        median_holding_days = statistics.median(horizon_samples) if horizon_samples else None
        short_horizon_score = (
            self._profile_score(
                100.0 - 100.0 * math.log1p(median_holding_days) / math.log1p(120.0)
            )
            if median_holding_days is not None
            else None
        )

        total_position_value = sum(position_values)
        top_weight_pct = (
            max(position_values) / total_position_value * 100.0
            if total_position_value > EPS and position_values
            else None
        )
        concentration_score = self._profile_score(top_weight_pct) if top_weight_pct is not None else None

        scale_in_ratio = (scale_in_count / buy_count * 100.0) if buy_count >= 2 else None
        profit_take_ratio = (
            sum(1 for result in matched_sell_results if result > 0) / len(matched_sell_results) * 100.0
            if len(matched_sell_results) >= 2
            else None
        )
        size_cv: Optional[float] = None
        sizing_consistency_score: Optional[int] = None
        if len(trade_notionals) >= 3 and statistics.mean(trade_notionals) > EPS:
            size_cv = statistics.pstdev(trade_notionals) / statistics.mean(trade_notionals)
            sizing_consistency_score = self._profile_score(100.0 / (1.0 + size_cv))

        confidence_score = self._profile_score(
            sum(
                [
                    min(45.0, trade_count / 30.0 * 45.0),
                    min(25.0, observation_days / 180.0 * 25.0),
                    min(20.0, unique_symbols / 5.0 * 20.0),
                    min(10.0, len(matched_sell_results) / 10.0 * 10.0),
                ]
            )
        )
        confidence = "high" if confidence_score >= 75 else "medium" if confidence_score >= 45 else "low"
        status = "ready" if trade_count >= 8 and observation_days >= 14 else "forming"

        dimensions = [
            self._profile_dimension("activity", activity_score, {"trades_per_30d": trades_per_30d}),
            self._profile_dimension("short_horizon", short_horizon_score, {"median_holding_days": median_holding_days}),
            self._profile_dimension("concentration", concentration_score, {"top_weight_pct": top_weight_pct}),
            self._profile_dimension(
                "scale_in",
                self._profile_score(scale_in_ratio) if scale_in_ratio is not None else None,
                {"scale_in_ratio_pct": scale_in_ratio},
            ),
            self._profile_dimension(
                "profit_taking",
                self._profile_score(profit_take_ratio) if profit_take_ratio is not None else None,
                {"profitable_sell_ratio_pct": profit_take_ratio},
            ),
            self._profile_dimension("sizing_consistency", sizing_consistency_score, {"trade_size_cv": size_cv}),
        ]
        available_dimensions = [item for item in dimensions if item["available"]]
        archetype = self._resolve_profile_archetype(available_dimensions)

        limitations: List[str] = []
        if status == "forming":
            limitations.append("insufficient_observation_window")
        if unmatched_sell_count:
            limitations.append("unmatched_sell_history")
        if not position_values:
            limitations.append("no_current_positions_for_concentration")

        return {
            "scope": "account" if account_id is not None else "all_accounts",
            "account_id": account_id,
            "as_of": as_of_date.isoformat(),
            "status": status,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "archetype": archetype,
            "sample": {
                "trade_count": trade_count,
                "buy_count": buy_count,
                "sell_count": sell_count,
                "unique_symbols": unique_symbols,
                "observation_days": observation_days,
                "first_trade_date": first_trade_date.isoformat() if first_trade_date else None,
                "last_trade_date": last_trade_date.isoformat() if last_trade_date else None,
            },
            "dimensions": dimensions,
            "limitations": limitations,
            "methodology_version": "portfolio-style-v1",
        }

    @staticmethod
    def _profile_score(value: Optional[float]) -> Optional[int]:
        if value is None or not math.isfinite(float(value)):
            return None
        return int(round(max(0.0, min(100.0, float(value)))))

    @staticmethod
    def _profile_dimension(key: str, score: Optional[int], evidence: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "key": key,
            "score": score,
            "available": score is not None,
            "evidence": {
                name: round(float(value), 4) if isinstance(value, (int, float)) and value is not None else value
                for name, value in evidence.items()
            },
        }

    @staticmethod
    def _resolve_profile_archetype(dimensions: List[Dict[str, Any]]) -> str:
        scores = {item["key"]: int(item["score"]) for item in dimensions if item.get("score") is not None}
        if len(scores) < 3:
            return "forming"
        if scores.get("activity", 0) >= 65 and scores.get("short_horizon", 0) >= 65:
            return "active_short_term"
        if scores.get("concentration", 0) >= 70 and scores.get("scale_in", 0) >= 55:
            return "concentrated_builder"
        if scores.get("short_horizon", 100) <= 35 and scores.get("activity", 100) <= 45:
            return "patient_holder"
        if scores.get("sizing_consistency", 0) >= 70:
            return "systematic_balanced"
        return "adaptive_balanced"

    def list_cash_ledger_events(
        self,
        *,
        account_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        direction: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        if account_id is not None:
            self._require_active_account(account_id)
        page, page_size = self._validate_paging(page=page, page_size=page_size)
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must be <= date_to")

        direction_norm: Optional[str] = None
        if direction is not None and direction.strip():
            direction_norm = direction.strip().lower()
            if direction_norm not in VALID_CASH_DIRECTIONS:
                raise ValueError("direction must be in or out")

        rows, total = self.repo.query_cash_ledger(
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            direction=direction_norm,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._cash_ledger_row_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def list_corporate_action_events(
        self,
        *,
        account_id: Optional[int] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        symbol: Optional[str] = None,
        action_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        if account_id is not None:
            self._require_active_account(account_id)
        page, page_size = self._validate_paging(page=page, page_size=page_size)
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ValueError("date_from must be <= date_to")

        symbol_filters: Optional[List[str]] = None
        if symbol is not None and symbol.strip():
            symbol_filters = self._build_symbol_filter_values(symbol)
            if not symbol_filters:
                raise ValueError("symbol is invalid")

        action_norm: Optional[str] = None
        if action_type is not None and action_type.strip():
            action_norm = action_type.strip().lower()
            if action_norm not in VALID_CORPORATE_ACTIONS:
                raise ValueError("action_type must be cash_dividend or split_adjustment")

        rows, total = self.repo.query_corporate_actions(
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            symbols=symbol_filters,
            action_type=action_norm,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [self._corporate_action_row_to_dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    # ------------------------------------------------------------------
    # Snapshot replay
    # ------------------------------------------------------------------
    def get_portfolio_snapshot(
        self,
        *,
        account_id: Optional[int] = None,
        as_of: Optional[date] = None,
        cost_method: str = "fifo",
        include_realtime: bool = True,
    ) -> Dict[str, Any]:
        as_of_date = as_of or date.today()
        method = self._normalize_cost_method(cost_method)

        if account_id is not None:
            account = self._require_active_account(account_id)
            account_rows = [account]
        else:
            account_rows = self.repo.list_accounts(include_inactive=False)

        accounts_payload: List[Dict[str, Any]] = []
        aggregate_currency = "CNY"
        aggregate = {
            "total_cash": 0.0,
            "total_market_value": 0.0,
            "total_equity": 0.0,
            "holding_pnl": 0.0,
            "daily_pnl": 0.0,
            "daily_pnl_complete": True,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fee_total": 0.0,
            "tax_total": 0.0,
            "fx_stale": False,
            "limitations": [],
        }

        for account in account_rows:
            account_snapshot = self._replay_account(
                account=account,
                as_of_date=as_of_date,
                cost_method=method,
                include_realtime=include_realtime,
            )

            self.repo.replace_positions_lots_and_snapshot(
                account_id=account.id,
                snapshot_date=as_of_date,
                cost_method=method,
                base_currency=account.base_currency,
                total_cash=account_snapshot["total_cash"],
                total_market_value=account_snapshot["total_market_value"],
                total_equity=account_snapshot["total_equity"],
                unrealized_pnl=account_snapshot["unrealized_pnl"],
                realized_pnl=account_snapshot["realized_pnl"],
                fee_total=account_snapshot["fee_total"],
                tax_total=account_snapshot["tax_total"],
                fx_stale=account_snapshot["fx_stale"],
                payload=json.dumps(account_snapshot["payload"], ensure_ascii=False),
                positions=account_snapshot["positions_cache"],
                lots=account_snapshot["lots_cache"],
                valuation_currency=account.base_currency,
            )

            accounts_payload.append(account_snapshot["public"])
            aggregate["limitations"] = _merge_portfolio_limitations(
                aggregate["limitations"],
                account_snapshot["public"].get("limitations", []),
            )

            cash_cny, stale_cash, _ = self._convert_amount(
                amount=account_snapshot["total_cash"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            mv_cny, stale_mv, _ = self._convert_amount(
                amount=account_snapshot["total_market_value"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            eq_cny, stale_eq, _ = self._convert_amount(
                amount=account_snapshot["total_equity"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            holding_cny, stale_holding, _ = self._convert_amount(
                amount=account_snapshot["holding_pnl"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            daily_pnl = account_snapshot["daily_pnl"]
            if daily_pnl is None:
                aggregate["daily_pnl_complete"] = False
                daily_cny = 0.0
                stale_daily = False
            else:
                daily_cny, stale_daily, _ = self._convert_amount(
                    amount=daily_pnl,
                    from_currency=account.base_currency,
                    to_currency=aggregate_currency,
                    as_of_date=as_of_date,
                )
            realized_cny, stale_realized, _ = self._convert_amount(
                amount=account_snapshot["realized_pnl"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            unrealized_cny, stale_unrealized, _ = self._convert_amount(
                amount=account_snapshot["unrealized_pnl"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            fee_cny, stale_fee, _ = self._convert_amount(
                amount=account_snapshot["fee_total"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )
            tax_cny, stale_tax, _ = self._convert_amount(
                amount=account_snapshot["tax_total"],
                from_currency=account.base_currency,
                to_currency=aggregate_currency,
                as_of_date=as_of_date,
            )

            aggregate["total_cash"] += cash_cny
            aggregate["total_market_value"] += mv_cny
            aggregate["total_equity"] += eq_cny
            aggregate["holding_pnl"] += holding_cny
            aggregate["daily_pnl"] += daily_cny
            aggregate["realized_pnl"] += realized_cny
            aggregate["unrealized_pnl"] += unrealized_cny
            aggregate["fee_total"] += fee_cny
            aggregate["tax_total"] += tax_cny
            aggregate["fx_stale"] = aggregate["fx_stale"] or any(
                [
                    stale_cash,
                    stale_mv,
                    stale_eq,
                    stale_holding,
                    stale_daily,
                    stale_realized,
                    stale_unrealized,
                    stale_fee,
                    stale_tax,
                ]
            )

        return {
            "as_of": as_of_date.isoformat(),
            "cost_method": method,
            "currency": aggregate_currency,
            "account_count": len(account_rows),
            "total_cash": round(aggregate["total_cash"], 6),
            "total_market_value": round(aggregate["total_market_value"], 6),
            "total_equity": round(aggregate["total_equity"], 6),
            "holding_pnl": round(aggregate["holding_pnl"], 6),
            "daily_pnl": (
                round(aggregate["daily_pnl"], 6)
                if aggregate["daily_pnl_complete"]
                else None
            ),
            "realized_pnl": round(aggregate["realized_pnl"], 6),
            "unrealized_pnl": round(aggregate["unrealized_pnl"], 6),
            "fee_total": round(aggregate["fee_total"], 6),
            "tax_total": round(aggregate["tax_total"], 6),
            "fx_stale": aggregate["fx_stale"],
            "data_quality": "partial" if aggregate["limitations"] else "ok",
            "limitations": aggregate["limitations"],
            "accounts": accounts_payload,
        }

    def refresh_fx_rates(
        self,
        *,
        account_id: Optional[int] = None,
        as_of: Optional[date] = None,
    ) -> Dict[str, Any]:
        """Refresh account FX pairs online with stale fallback when fetch fails."""
        as_of_date = as_of or date.today()
        config = get_config()
        refresh_enabled = bool(getattr(config, "portfolio_fx_update_enabled", True))
        if account_id is not None:
            account_rows = [self._require_active_account(account_id)]
        else:
            account_rows = self.repo.list_accounts(include_inactive=False)

        summary = {
            "as_of": as_of_date.isoformat(),
            "account_count": len(account_rows),
            "refresh_enabled": refresh_enabled,
            "disabled_reason": None if refresh_enabled else PORTFOLIO_FX_REFRESH_DISABLED_REASON,
            "pair_count": 0,
            "updated_count": 0,
            "stale_count": 0,
            "error_count": 0,
        }
        for account in account_rows:
            item = self._refresh_account_fx_rates(
                account=account,
                as_of_date=as_of_date,
                refresh_enabled=refresh_enabled,
            )
            summary["pair_count"] += item["pair_count"]
            summary["updated_count"] += item["updated_count"]
            summary["stale_count"] += item["stale_count"]
            summary["error_count"] += item["error_count"]
        return summary

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _validate_trade_identity(
        self,
        *,
        account_id: int,
        trade_uid: Optional[str],
        dedup_hash: Optional[str],
        session: Optional[Any] = None,
    ) -> None:
        if trade_uid and self._has_trade_uid(account_id=account_id, trade_uid=trade_uid, session=session):
            raise PortfolioConflictError(f"Duplicate trade_uid for account_id={account_id}: {trade_uid}")
        if dedup_hash and self._has_trade_dedup_hash(account_id=account_id, dedup_hash=dedup_hash, session=session):
            raise PortfolioConflictError(f"Duplicate dedup_hash for account_id={account_id}: {dedup_hash}")

    def _validate_sell_quantity(
        self,
        *,
        account_id: int,
        symbol: str,
        market: str,
        currency: str,
        trade_date: date,
        quantity: float,
        session: Optional[Any] = None,
    ) -> None:
        key = (
            self._normalize_symbol_for_position(symbol),
            self._normalize_market(market),
            self._normalize_currency(currency),
        )
        available_quantity = self._calculate_available_quantity(
            account_id=account_id,
            key=key,
            as_of_date=trade_date,
            session=session,
        )
        if available_quantity + EPS < quantity:
            raise PortfolioOversellError(
                symbol=key[0],
                trade_date=trade_date,
                requested_quantity=quantity,
                available_quantity=available_quantity,
            )

    def _calculate_available_quantity(
        self,
        *,
        account_id: int,
        key: Tuple[str, str, str],
        as_of_date: date,
        session: Optional[Any] = None,
    ) -> float:
        if session is None:
            trades = self.repo.list_trades(account_id, as_of=as_of_date)
            corporate_actions = self.repo.list_corporate_actions(account_id, as_of=as_of_date)
        else:
            trades = self.repo.list_trades_in_session(session=session, account_id=account_id, as_of=as_of_date)
            corporate_actions = self.repo.list_corporate_actions_in_session(
                session=session,
                account_id=account_id,
                as_of=as_of_date,
            )

        events = []
        for row in corporate_actions:
            event_key = (
                self._normalize_symbol_for_position(row.symbol),
                self._normalize_market(row.market),
                self._normalize_currency(row.currency),
            )
            if event_key == key:
                events.append(("corp", row.effective_date, row.id, row))
        for row in trades:
            event_key = (
                self._normalize_symbol_for_position(row.symbol),
                self._normalize_market(row.market),
                self._normalize_currency(row.currency),
            )
            if event_key == key:
                events.append(("trade", row.trade_date, row.id, row))

        # Quantity validation only depends on position-changing events for one symbol.
        # Cash ledger entries do not affect shares held, so we keep the same corp->trade
        # ordering as full replay without pulling unrelated cash events into this path.
        events.sort(key=self._replay_event_sort_key)

        quantity_held = 0.0
        for event_type, event_date, _, event in events:
            if event_type == "corp":
                action_type = (event.action_type or "").strip().lower()
                if action_type != "split_adjustment":
                    continue
                split_ratio = float(event.split_ratio or 0.0)
                if split_ratio <= 0:
                    raise ValueError(f"Invalid split_ratio for {key[0]}")
                if abs(split_ratio - 1.0) <= EPS:
                    continue
                quantity_held *= split_ratio
                continue

            qty = float(event.quantity or 0.0)
            if qty <= 0:
                raise ValueError(f"Invalid trade quantity for {key[0]}")
            side = (event.side or "").strip().lower()
            if side == "buy":
                quantity_held += qty
                continue
            if side != "sell":
                raise ValueError(f"Unsupported trade side: {event.side}")
            if quantity_held + EPS < qty:
                raise PortfolioOversellError(
                    symbol=key[0],
                    trade_date=event_date,
                    requested_quantity=qty,
                    available_quantity=quantity_held,
                )
            quantity_held -= qty
            if quantity_held <= EPS:
                quantity_held = 0.0

        return quantity_held

    def _build_holding_cycle_states(
        self,
        *,
        trades: Iterable[Any],
        corporate_actions: Iterable[Any],
    ) -> Dict[Tuple[str, str, str], _HoldingCycleState]:
        """Build broker-style diluted costs without resetting on an intraday round trip.

        Trade rows only carry a trading date, not an execution timestamp.  We therefore
        treat all trades for one symbol on one date as an end-of-day batch.  Buys are
        replayed before sells, and a holding cycle ends only when the end-of-day
        quantity is zero.  This keeps same-day sell-then-buy T trades in the existing
        holding cycle while preserving the strict FIFO/AVG accounting fields.
        """

        events: List[Tuple[str, date, int, Any]] = []
        for row in trades:
            events.append(("trade", row.trade_date, row.id, row))
        for row in corporate_actions:
            if (row.action_type or "").strip().lower() == "split_adjustment":
                events.append(("corp", row.effective_date, row.id, row))
        events.sort(key=self._replay_event_sort_key)

        states: Dict[Tuple[str, str, str], _HoldingCycleState] = defaultdict(_HoldingCycleState)
        active_date: Optional[date] = None
        touched_keys: Set[Tuple[str, str, str]] = set()

        def finish_day() -> None:
            for touched_key in touched_keys:
                state = states[touched_key]
                if state.quantity <= EPS:
                    state.quantity = 0.0
                    state.net_cost = 0.0
                    state.start_date = None

        for event_type, event_date, _, event in events:
            if active_date is not None and event_date != active_date:
                finish_day()
                touched_keys = set()
            active_date = event_date

            key = (
                self._normalize_symbol_for_position(event.symbol),
                self._normalize_market(event.market),
                self._normalize_currency(event.currency),
            )
            state = states[key]
            touched_keys.add(key)

            if event_type == "corp":
                split_ratio = float(event.split_ratio or 0.0)
                if split_ratio <= 0:
                    raise ValueError(f"Invalid split_ratio for {key[0]}")
                if abs(split_ratio - 1.0) > EPS:
                    state.quantity *= split_ratio
                continue

            qty = float(event.quantity or 0.0)
            price = float(event.price or 0.0)
            fee = float(event.fee or 0.0)
            tax = float(event.tax or 0.0)
            if qty <= 0 or price <= 0:
                raise ValueError(f"Invalid trade quantity or price for {event.symbol}")

            gross = qty * price
            side = (event.side or "").strip().lower()
            if side == "buy":
                if state.start_date is None:
                    state.start_date = event_date
                state.quantity += qty
                state.net_cost += gross + fee + tax
            elif side == "sell":
                if state.quantity + EPS < qty:
                    raise PortfolioOversellError(
                        symbol=key[0],
                        trade_date=event_date,
                        requested_quantity=qty,
                        available_quantity=state.quantity,
                    )
                state.quantity -= qty
                state.net_cost -= gross - fee - tax
            else:
                raise ValueError(f"Unsupported trade side: {event.side}")

        if active_date is not None:
            finish_day()
        return dict(states)

    def _replay_account(
        self,
        *,
        account: Any,
        as_of_date: date,
        cost_method: str,
        include_realtime: bool,
    ) -> Dict[str, Any]:
        trades = self.repo.list_trades(account.id, as_of=as_of_date)
        cash_ledger = self.repo.list_cash_ledger(account.id, as_of=as_of_date)
        corporate_actions = self.repo.list_corporate_actions(account.id, as_of=as_of_date)

        events = []
        for row in cash_ledger:
            events.append(("cash", row.event_date, row.id, row))
        for row in trades:
            events.append(("trade", row.trade_date, row.id, row))
        for row in corporate_actions:
            events.append(("corp", row.effective_date, row.id, row))

        # Same-day deterministic ordering: cash -> corporate action -> buy -> sell.
        # Trade rows contain dates but no reliable execution timestamps, so database
        # insertion order must not decide whether a position is temporarily flat.
        events.sort(key=self._replay_event_sort_key)

        cash_balances: Dict[str, float] = defaultdict(float)
        fees_total_base = 0.0
        taxes_total_base = 0.0
        realized_pnl_base = 0.0
        fx_stale = False

        fifo_lots: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
        avg_state: Dict[Tuple[str, str, str], _AvgState] = defaultdict(_AvgState)

        for event_type, event_date, _, event in events:
            if event_type == "cash":
                currency = self._normalize_currency(event.currency)
                amount = float(event.amount or 0.0)
                if event.direction == "in":
                    cash_balances[currency] += amount
                elif event.direction == "out":
                    cash_balances[currency] -= amount
                else:
                    raise ValueError(f"Unsupported cash direction: {event.direction}")
                continue

            if event_type == "trade":
                key = (
                    self._normalize_symbol_for_position(event.symbol),
                    self._normalize_market(event.market),
                    self._normalize_currency(event.currency),
                )
                qty = float(event.quantity or 0.0)
                price = float(event.price or 0.0)
                fee = float(event.fee or 0.0)
                tax = float(event.tax or 0.0)
                if qty <= 0 or price <= 0:
                    raise ValueError(f"Invalid trade quantity or price for {event.symbol}")

                gross = qty * price
                side = (event.side or "").lower().strip()
                if side == "buy":
                    cash_balances[key[2]] -= (gross + fee + tax)
                    if cost_method == "fifo":
                        unit_cost = (gross + fee + tax) / qty
                        fifo_lots[key].append(
                            {
                                "symbol": key[0],
                                "market": key[1],
                                "currency": key[2],
                                "open_date": event_date,
                                "remaining_quantity": qty,
                                "unit_cost": unit_cost,
                                "source_trade_id": event.id,
                            }
                        )
                    else:
                        state = avg_state[key]
                        state.quantity += qty
                        state.total_cost += (gross + fee + tax)
                elif side == "sell":
                    cash_balances[key[2]] += (gross - fee - tax)
                    proceeds_net = gross - fee - tax
                    if cost_method == "fifo":
                        cost_basis = self._consume_fifo_lots(
                            fifo_lots[key],
                            qty,
                            key[0],
                            event_date,
                        )
                    else:
                        cost_basis = self._consume_avg_position(
                            avg_state[key],
                            qty,
                            key[0],
                            event_date,
                        )
                    realized_local = proceeds_net - cost_basis
                    realized_base, stale_realized, _ = self._convert_amount(
                        amount=realized_local,
                        from_currency=key[2],
                        to_currency=account.base_currency,
                        as_of_date=event_date,
                    )
                    realized_pnl_base += realized_base
                    fx_stale = fx_stale or stale_realized
                else:
                    raise ValueError(f"Unsupported trade side: {event.side}")

                fee_base, stale_fee, _ = self._convert_amount(
                    amount=fee,
                    from_currency=key[2],
                    to_currency=account.base_currency,
                    as_of_date=event_date,
                )
                tax_base, stale_tax, _ = self._convert_amount(
                    amount=tax,
                    from_currency=key[2],
                    to_currency=account.base_currency,
                    as_of_date=event_date,
                )
                fees_total_base += fee_base
                taxes_total_base += tax_base
                fx_stale = fx_stale or stale_fee or stale_tax
                continue

            if event_type == "corp":
                key = (
                    self._normalize_symbol_for_position(event.symbol),
                    self._normalize_market(event.market),
                    self._normalize_currency(event.currency),
                )
                action_type = (event.action_type or "").strip().lower()
                if action_type == "cash_dividend":
                    per_share = float(event.cash_dividend_per_share or 0.0)
                    if per_share <= 0:
                        continue
                    qty_held = self._held_quantity(
                        key=key,
                        cost_method=cost_method,
                        fifo_lots=fifo_lots,
                        avg_state=avg_state,
                    )
                    if qty_held > EPS:
                        cash_balances[key[2]] += qty_held * per_share
                elif action_type == "split_adjustment":
                    split_ratio = float(event.split_ratio or 0.0)
                    if split_ratio <= 0:
                        raise ValueError(f"Invalid split_ratio for {event.symbol}")
                    if abs(split_ratio - 1.0) <= EPS:
                        continue
                    if cost_method == "fifo":
                        for lot in fifo_lots[key]:
                            lot["remaining_quantity"] *= split_ratio
                            lot["unit_cost"] /= split_ratio
                    else:
                        state = avg_state[key]
                        state.quantity *= split_ratio
                else:
                    raise ValueError(f"Unsupported corporate action type: {event.action_type}")

        holding_cycle_states = self._build_holding_cycle_states(
            trades=trades,
            corporate_actions=corporate_actions,
        )
        position_rows, lot_rows, market_value_base, total_cost_base, stale_pos = self._build_positions(
            account=account,
            as_of_date=as_of_date,
            cost_method=cost_method,
            fifo_lots=fifo_lots,
            avg_state=avg_state,
            holding_cycle_states=holding_cycle_states,
            include_realtime=include_realtime,
        )
        fx_stale = fx_stale or stale_pos

        total_cash_base = 0.0
        for currency, amount in cash_balances.items():
            converted, stale, _ = self._convert_amount(
                amount=amount,
                from_currency=currency,
                to_currency=account.base_currency,
                as_of_date=as_of_date,
            )
            total_cash_base += converted
            fx_stale = fx_stale or stale

        unrealized_pnl_base = market_value_base - total_cost_base
        total_equity_base = total_cash_base + market_value_base
        metric_fx_stale = self._enrich_position_dashboard_metrics(
            account=account,
            as_of_date=as_of_date,
            trades=trades,
            corporate_actions=corporate_actions,
            positions=position_rows,
            total_equity_base=total_equity_base,
        )
        fx_stale = fx_stale or metric_fx_stale
        holding_pnl_base = sum(
            float(position.get("holding_pnl_base") or 0.0)
            for position in position_rows
        )
        daily_pnl_values = [
            position.get("daily_pnl_base")
            for position in position_rows
        ]
        daily_pnl_base = (
            sum(float(value or 0.0) for value in daily_pnl_values)
            if all(value is not None for value in daily_pnl_values)
            else None
        )
        position_limitations = [
            limitation
            for position in position_rows
            for limitation in position.get("limitations", [])
        ]
        limitations = _merge_portfolio_limitations(
            _portfolio_limitations_for_market(account.market),
            position_limitations,
        )

        account_payload = {
            "account_id": account.id,
            "account_name": account.name,
            "owner_id": account.owner_id,
            "broker": account.broker,
            "market": account.market,
            "base_currency": account.base_currency,
            "as_of": as_of_date.isoformat(),
            "cost_method": cost_method,
            "total_cash": round(total_cash_base, 6),
            "total_market_value": round(market_value_base, 6),
            "total_equity": round(total_equity_base, 6),
            "holding_pnl": round(holding_pnl_base, 6),
            "daily_pnl": (
                round(daily_pnl_base, 6)
                if daily_pnl_base is not None
                else None
            ),
            "realized_pnl": round(realized_pnl_base, 6),
            "unrealized_pnl": round(unrealized_pnl_base, 6),
            "fee_total": round(fees_total_base, 6),
            "tax_total": round(taxes_total_base, 6),
            "fx_stale": fx_stale,
            "data_quality": "partial" if limitations else "ok",
            "limitations": limitations,
            "positions": position_rows,
        }

        return {
            "public": account_payload,
            "payload": account_payload,
            "positions_cache": position_rows,
            "lots_cache": lot_rows,
            "total_cash": float(total_cash_base),
            "total_market_value": float(market_value_base),
            "total_equity": float(total_equity_base),
            "holding_pnl": float(holding_pnl_base),
            "daily_pnl": (
                float(daily_pnl_base)
                if daily_pnl_base is not None
                else None
            ),
            "realized_pnl": float(realized_pnl_base),
            "unrealized_pnl": float(unrealized_pnl_base),
            "fee_total": float(fees_total_base),
            "tax_total": float(taxes_total_base),
            "fx_stale": fx_stale,
        }

    def _build_positions(
        self,
        *,
        account: Any,
        as_of_date: date,
        cost_method: str,
        fifo_lots: Dict[Tuple[str, str, str], List[Dict[str, Any]]],
        avg_state: Dict[Tuple[str, str, str], _AvgState],
        holding_cycle_states: Optional[Dict[Tuple[str, str, str], _HoldingCycleState]] = None,
        include_realtime: bool = True,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float, float, bool]:
        position_rows: List[Dict[str, Any]] = []
        lot_rows: List[Dict[str, Any]] = []
        market_value_base = 0.0
        total_cost_base = 0.0
        fx_stale = False

        keys: Iterable[Tuple[str, str, str]]
        if cost_method == "fifo":
            keys = list(fifo_lots.keys())
        else:
            keys = list(avg_state.keys())

        active_symbols: List[str] = []
        if include_realtime and as_of_date == date.today():
            for key in sorted(keys):
                symbol, _, _ = key
                if cost_method == "fifo":
                    qty = sum(
                        float(lot["remaining_quantity"])
                        for lot in fifo_lots[key]
                        if lot["remaining_quantity"] > EPS
                    )
                else:
                    qty = float(avg_state[key].quantity)
                if qty > EPS:
                    active_symbols.append(symbol)
        realtime_prices = (
            self._prefetch_realtime_position_prices(active_symbols)
            if active_symbols
            else None
        )

        for key in sorted(keys):
            symbol, market, currency = key

            if cost_method == "fifo":
                active_lots = [lot for lot in fifo_lots[key] if lot["remaining_quantity"] > EPS]
                qty = sum(float(lot["remaining_quantity"]) for lot in active_lots)
                if qty <= EPS:
                    continue
                total_cost = sum(float(lot["remaining_quantity"]) * float(lot["unit_cost"]) for lot in active_lots)
                avg_cost = total_cost / qty
                lot_rows.extend(active_lots)
            else:
                state = avg_state[key]
                qty = float(state.quantity)
                total_cost = float(state.total_cost)
                if qty <= EPS:
                    continue
                avg_cost = total_cost / qty
                lot_rows.append(
                    {
                        "symbol": symbol,
                        "market": market,
                        "currency": currency,
                        "open_date": as_of_date,
                        "remaining_quantity": qty,
                        "unit_cost": avg_cost,
                        "source_trade_id": None,
                    }
                )

            holding_state = (holding_cycle_states or {}).get(key)
            if holding_state is not None and abs(float(holding_state.quantity) - qty) <= EPS:
                holding_total_cost = float(holding_state.net_cost)
                holding_cycle_start_date = holding_state.start_date
            else:
                holding_total_cost = total_cost
                holding_cycle_start_date = None
            holding_avg_cost = holding_total_cost / qty

            price_info = self._resolve_position_price(
                symbol=symbol,
                as_of_date=as_of_date,
                realtime_prices=realtime_prices,
                include_realtime=include_realtime,
            )
            last_price = price_info.price
            limitations = _portfolio_limitations_for_market(market)

            if price_info.is_available:
                local_market_value = qty * float(last_price)
                market_base, stale_market, _ = self._convert_amount(
                    amount=local_market_value,
                    from_currency=currency,
                    to_currency=account.base_currency,
                    as_of_date=as_of_date,
                )
                cost_base, stale_cost, _ = self._convert_amount(
                    amount=total_cost,
                    from_currency=currency,
                    to_currency=account.base_currency,
                    as_of_date=as_of_date,
                )
                holding_cost_base, stale_holding_cost, _ = self._convert_amount(
                    amount=holding_total_cost,
                    from_currency=currency,
                    to_currency=account.base_currency,
                    as_of_date=as_of_date,
                )
                unrealized_base = market_base - cost_base
                holding_pnl_base = market_base - holding_cost_base
                fx_stale = fx_stale or stale_market or stale_cost or stale_holding_cost
            else:
                market_base = 0.0
                cost_base = 0.0
                holding_cost_base = 0.0
                unrealized_base = 0.0
                holding_pnl_base = 0.0

            unrealized_pct = None
            if abs(cost_base) > EPS:
                unrealized_pct = unrealized_base / cost_base * 100.0
            holding_pnl_pct = None
            if holding_cost_base > EPS:
                holding_pnl_pct = holding_pnl_base / holding_cost_base * 100.0

            position_rows.append(
                {
                    "symbol": symbol,
                    "market": market,
                    "currency": currency,
                    "quantity": round(qty, 8),
                    "avg_cost": round(avg_cost, 8),
                    "total_cost": round(total_cost, 8),
                    "last_price": round(float(last_price), 8),
                    "market_value_base": round(market_base, 8),
                    "unrealized_pnl_base": round(unrealized_base, 8),
                    "unrealized_pnl_pct": round(unrealized_pct, 8) if unrealized_pct is not None else None,
                    "holding_avg_cost": round(holding_avg_cost, 8),
                    "holding_total_cost": round(holding_total_cost, 8),
                    "holding_pnl_base": round(holding_pnl_base, 8),
                    "holding_pnl_pct": round(holding_pnl_pct, 8) if holding_pnl_pct is not None else None,
                    "holding_cycle_start_date": (
                        holding_cycle_start_date.isoformat()
                        if holding_cycle_start_date is not None
                        else None
                    ),
                    "valuation_currency": account.base_currency,
                    "price_source": price_info.source,
                    "price_provider": price_info.provider,
                    "price_date": price_info.price_date.isoformat() if price_info.price_date else None,
                    "price_stale": price_info.is_stale,
                    "price_available": price_info.is_available,
                    "data_quality": "partial" if limitations else "ok",
                    "limitations": limitations,
                }
            )

            market_value_base += market_base
            total_cost_base += cost_base

        return position_rows, lot_rows, market_value_base, total_cost_base, fx_stale

    def _enrich_position_dashboard_metrics(
        self,
        *,
        account: Any,
        as_of_date: date,
        trades: Iterable[Any],
        corporate_actions: Iterable[Any],
        positions: List[Dict[str, Any]],
        total_equity_base: float,
    ) -> bool:
        """Add broker-style position fields used by the account dashboard."""

        today_trade_stats: Dict[Tuple[str, str, str], Dict[str, float]] = defaultdict(
            lambda: {
                "buy_quantity": 0.0,
                "sell_quantity": 0.0,
                "buy_cash": 0.0,
                "sell_cash": 0.0,
            }
        )
        for trade in trades:
            if trade.trade_date != as_of_date:
                continue
            key = (
                self._normalize_symbol_for_position(trade.symbol),
                self._normalize_market(trade.market),
                self._normalize_currency(trade.currency),
            )
            stats = today_trade_stats[key]
            quantity = float(trade.quantity or 0.0)
            gross = quantity * float(trade.price or 0.0)
            fee = float(trade.fee or 0.0)
            tax = float(trade.tax or 0.0)
            side = str(trade.side or "").strip().lower()
            if side == "buy":
                stats["buy_quantity"] += quantity
                stats["buy_cash"] += gross + fee + tax
            elif side == "sell":
                stats["sell_quantity"] += quantity
                stats["sell_cash"] += gross - fee - tax

        today_dividends: Dict[Tuple[str, str, str], float] = defaultdict(float)
        split_keys: Set[Tuple[str, str, str]] = set()
        for action in corporate_actions:
            if action.effective_date != as_of_date:
                continue
            key = (
                self._normalize_symbol_for_position(action.symbol),
                self._normalize_market(action.market),
                self._normalize_currency(action.currency),
            )
            action_type = str(action.action_type or "").strip().lower()
            if action_type == "cash_dividend":
                today_dividends[key] += float(action.cash_dividend_per_share or 0.0)
            elif action_type == "split_adjustment":
                split_keys.add(key)

        metric_fx_stale = False
        for position in positions:
            key = (
                str(position.get("symbol") or ""),
                str(position.get("market") or ""),
                str(position.get("currency") or ""),
            )
            quantity = float(position.get("quantity") or 0.0)
            stats = today_trade_stats.get(key, {})
            bought_today = float(stats.get("buy_quantity") or 0.0)
            sold_today = float(stats.get("sell_quantity") or 0.0)

            if key[1] == "cn":
                available_quantity = max(0.0, quantity - bought_today)
            else:
                available_quantity = quantity
            position["available_quantity"] = round(min(quantity, available_quantity), 8)

            holding_start_raw = position.get("holding_cycle_start_date")
            holding_start = date.fromisoformat(holding_start_raw) if holding_start_raw else None
            position["holding_days"] = (
                count_market_sessions(key[1], holding_start, as_of_date)
                if holding_start is not None
                else None
            )

            last_price = float(position.get("last_price") or 0.0)
            holding_avg_cost = float(position.get("holding_avg_cost") or 0.0)
            position["break_even_pct"] = (
                round(max(0.0, (holding_avg_cost / last_price - 1.0) * 100.0), 8)
                if last_price > EPS and holding_avg_cost > EPS
                else None
            )
            position["position_weight_pct"] = (
                round(float(position.get("market_value_base") or 0.0) / total_equity_base * 100.0, 8)
                if total_equity_base > EPS
                else None
            )
            position["stock_name"] = self._resolve_local_stock_name(key[0])

            position["daily_pnl_base"] = None
            position["daily_pnl_pct"] = None
            if (
                key in split_keys
                or not bool(position.get("price_available"))
                or position.get("price_date") != as_of_date.isoformat()
            ):
                continue

            previous_close = self.repo.get_latest_close_with_date(
                symbol=key[0],
                as_of=as_of_date - timedelta(days=1),
            )
            if previous_close is None:
                continue
            previous_close_price, _ = previous_close
            opening_quantity = max(0.0, quantity - bought_today + sold_today)
            opening_market_value = opening_quantity * float(previous_close_price)
            closing_market_value = quantity * last_price
            dividend_cash = opening_quantity * today_dividends.get(key, 0.0)
            buy_cash = float(stats.get("buy_cash") or 0.0)
            sell_cash = float(stats.get("sell_cash") or 0.0)
            daily_pnl_local = (
                closing_market_value
                - opening_market_value
                + sell_cash
                - buy_cash
                + dividend_cash
            )
            daily_pnl_base, stale_daily, _ = self._convert_amount(
                amount=daily_pnl_local,
                from_currency=key[2],
                to_currency=account.base_currency,
                as_of_date=as_of_date,
            )
            metric_fx_stale = metric_fx_stale or stale_daily
            net_new_position_cash = max(0.0, buy_cash - sell_cash)
            daily_denominator = opening_market_value + net_new_position_cash
            if daily_denominator <= EPS:
                daily_denominator = buy_cash
            position["daily_pnl_base"] = round(daily_pnl_base, 8)
            position["daily_pnl_pct"] = (
                round(daily_pnl_local / daily_denominator * 100.0, 8)
                if daily_denominator > EPS
                else None
            )

        return metric_fx_stale

    @staticmethod
    def _resolve_local_stock_name(symbol: str) -> Optional[str]:
        """Resolve a name without triggering online stock-name providers."""

        normalized = normalize_stock_code(symbol)
        name = STOCK_NAME_MAP.get(normalized) or get_index_stock_name(normalized)
        return str(name).strip() if is_meaningful_stock_name(name, normalized) else None

    @staticmethod
    def _replay_event_sort_key(item: Tuple[str, date, int, Any]) -> Tuple[date, int, int, int]:
        """Return stable end-of-day replay order independent of insertion order."""

        event_type, event_date, event_id, event = item
        event_priority = {"cash": 0, "corp": 1, "trade": 2}
        side_priority = 0
        if event_type == "trade":
            side = (getattr(event, "side", "") or "").strip().lower()
            side_priority = {"buy": 0, "sell": 1}.get(side, 2)
        return event_date, event_priority[event_type], side_priority, event_id

    def _resolve_position_price(
        self,
        *,
        symbol: str,
        as_of_date: date,
        realtime_prices: Optional[Dict[str, Tuple[Optional[float], Optional[str]]]] = None,
        include_realtime: bool = True,
    ) -> _ResolvedPositionPrice:
        today = date.today()

        if include_realtime and as_of_date == today:
            if realtime_prices is None:
                realtime_price, provider = self._fetch_realtime_position_price(symbol)
            else:
                realtime_price, provider = realtime_prices.get(symbol, (None, None))
            if realtime_price is not None and realtime_price > 0:
                return _ResolvedPositionPrice(
                    price=float(realtime_price),
                    source="realtime_quote",
                    price_date=today,
                    is_stale=False,
                    is_available=True,
                    provider=provider,
                )

        close = self.repo.get_latest_close_with_date(symbol=symbol, as_of=as_of_date)
        if close is not None:
            close_price, close_date = close
            if close_price > 0:
                return _ResolvedPositionPrice(
                    price=float(close_price),
                    source="history_close",
                    price_date=close_date,
                    is_stale=close_date < as_of_date,
                    is_available=True,
                )

        return _ResolvedPositionPrice(
            price=0.0,
            source="missing",
            price_date=None,
            is_stale=True,
            is_available=False,
        )

    def _prefetch_realtime_position_prices(
        self,
        symbols: Iterable[str],
    ) -> Dict[str, Tuple[Optional[float], Optional[str]]]:
        unique_symbols = sorted({symbol for symbol in symbols if symbol})
        if not unique_symbols:
            return {}

        # Bulk prefetch (when applicable) only warms the fetcher-module-level realtime cache;
        # the manager itself is discarded so per-symbol workers cannot serialize through its
        # per-fetcher call locks when individual reads still need a live fetch (e.g. mixed
        # markets, cache miss, or bulk source returning fewer rows than requested).
        if len(unique_symbols) >= 5:
            try:
                from data_provider.base import DataFetcherManager

                DataFetcherManager().prefetch_realtime_quotes(unique_symbols)
            except Exception as exc:
                logger.warning("Failed to prefetch realtime portfolio quotes: %s", exc)

        if len(unique_symbols) == 1:
            symbol = unique_symbols[0]
            return {symbol: self._fetch_realtime_position_price(symbol)}

        results: Dict[str, Tuple[Optional[float], Optional[str]]] = {}
        max_workers = min(PORTFOLIO_REALTIME_QUOTE_MAX_WORKERS, len(unique_symbols))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="portfolio-quote") as executor:
            futures = {
                executor.submit(self._fetch_realtime_position_price, symbol): symbol
                for symbol in unique_symbols
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:  # pragma: no cover - defensive guard for patched fetchers
                    logger.warning("Failed to prefetch realtime portfolio price for %s: %s", symbol, exc)
                    results[symbol] = (None, None)

        return results

    @staticmethod
    def _fetch_realtime_position_price(symbol: str) -> Tuple[Optional[float], Optional[str]]:
        try:
            from data_provider.base import DataFetcherManager

            fetcher_manager = DataFetcherManager()
            quote = fetcher_manager.get_realtime_quote(symbol, log_final_failure=False)
        except Exception as exc:
            logger.warning("Failed to fetch realtime portfolio price for %s: %s", symbol, exc)
            return None, None

        if quote is None:
            return None, None

        price = getattr(quote, "price", None)
        try:
            numeric_price = float(price)
        except (TypeError, ValueError):
            return None, None

        if numeric_price <= 0:
            return None, None

        source = getattr(quote, "source", None)
        provider = getattr(source, "value", None) or (str(source) if source is not None else None)
        return numeric_price, provider

    @staticmethod
    def _normalize_symbol_for_storage(symbol: str) -> str:
        return canonical_stock_code(symbol)

    @staticmethod
    def _normalize_symbol_for_position(symbol: str) -> str:
        if not (symbol or "").strip():
            return ""

        raw = canonical_stock_code(symbol)
        if len(raw) >= 8 and raw[:2] in {"SH", "SZ", "BJ"} and raw[2:].isdigit():
            return raw

        if "." in raw:
            base, suffix = raw.rsplit(".", 1)
            if base.isdigit() and suffix in {"SH", "SS", "SZ", "BJ"}:
                exchange = "SH" if suffix == "SS" else suffix
                return f"{exchange}{base}"

        return canonical_stock_code(normalize_stock_code(symbol))

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        """
        Canonicalization for symbol filtering with exchange-qualified input preservation.

        Keep explicit A-share exchange annotations (SH/SZ/BJ) intact to avoid collapsing
        different exchange variants of the same 6-digit core code.
        """
        raw = canonical_stock_code(symbol)
        if not raw:
            return ""

        if len(raw) >= 8 and raw[:2] in {"SH", "SZ", "BJ"} and raw[2:].isdigit():
            return raw

        if "." in raw:
            base, suffix = raw.rsplit(".", 1)
            if base.isdigit() and suffix in {"SH", "SS", "SZ", "BJ"}:
                exchange = "SH" if suffix == "SS" else suffix
                return f"{exchange}{base}"

        return canonical_stock_code(normalize_stock_code(symbol))

    @classmethod
    def _build_symbol_filter_values(cls, symbol: str) -> List[str]:
        original = (symbol or "").strip().upper()
        normalized = cls._normalize_symbol(original)
        if not normalized:
            return []

        seen: Set[str] = set()
        values: List[str] = []

        def _add(value: Optional[str]) -> None:
            candidate = (value or "").strip().upper()
            if candidate and candidate not in seen:
                seen.add(candidate)
                values.append(candidate)

        _add(original)
        _add(normalized)

        if normalized.startswith("HK"):
            hk_digits = normalized[2:]
            if hk_digits.isdigit() and len(hk_digits) == 5:
                legacy_hk_digits = str(int(hk_digits))
                _add(f"HK{hk_digits}")
                _add(f"HK{legacy_hk_digits}")
                _add(f"{hk_digits}.HK")
                _add(f"{legacy_hk_digits}.HK")
            return values

        explicit_exchange: Optional[str] = None
        if len(original) >= 8 and original[:2] in {"SH", "SZ", "BJ"} and original[2:].isdigit():
            explicit_exchange = original[:2]
            explicit_code = original[2:]
        elif "." in original:
            base, suffix = original.rsplit(".", 1)
            if base.isdigit() and suffix in {"SH", "SS", "SZ", "BJ"}:
                explicit_exchange = "SH" if suffix == "SS" else suffix
                explicit_code = base
            else:
                explicit_code = None
        else:
            explicit_code = None

        if normalized.isdigit():
            if len(normalized) == 6:
                exchanges = [explicit_exchange] if explicit_exchange else ["SH", "SZ", "BJ"]
                for exchange in exchanges:
                    if exchange is None:
                        continue
                    _add(f"{exchange}{normalized}")
                    _add(f"{normalized}.{'SS' if exchange == 'SH' else exchange}")
                    if exchange == "SH":
                        _add(f"{normalized}.SH")
            return values

        if explicit_exchange is not None and explicit_code is not None and explicit_code.isdigit():
            if len(explicit_code) == 6:
                _add(f"{explicit_exchange}{explicit_code}")
                _add(f"{explicit_code}.{'SS' if explicit_exchange == 'SH' else explicit_exchange}")
                if explicit_exchange == "SH":
                    _add(f"{explicit_code}.SH")
            elif len(normalized) == 5:
                _add(f"HK{normalized}")
                _add(f"{normalized}.HK")

        return values

    @staticmethod
    def _consume_fifo_lots(
        lots: List[Dict[str, Any]],
        quantity: float,
        symbol: str,
        trade_date: Optional[date] = None,
    ) -> float:
        remaining = quantity
        cost_basis = 0.0
        while remaining > EPS:
            if not lots:
                raise PortfolioOversellError(
                    symbol=symbol,
                    trade_date=trade_date,
                    requested_quantity=quantity,
                    available_quantity=quantity - remaining,
                )
            head = lots[0]
            take = min(remaining, float(head["remaining_quantity"]))
            cost_basis += take * float(head["unit_cost"])
            head["remaining_quantity"] = float(head["remaining_quantity"]) - take
            remaining -= take
            if head["remaining_quantity"] <= EPS:
                lots.pop(0)
        return cost_basis

    @staticmethod
    def _consume_avg_position(
        state: _AvgState,
        quantity: float,
        symbol: str,
        trade_date: Optional[date] = None,
    ) -> float:
        if state.quantity + EPS < quantity:
            raise PortfolioOversellError(
                symbol=symbol,
                trade_date=trade_date,
                requested_quantity=quantity,
                available_quantity=state.quantity,
            )
        if state.quantity <= EPS:
            raise PortfolioOversellError(
                symbol=symbol,
                trade_date=trade_date,
                requested_quantity=quantity,
                available_quantity=0.0,
            )
        avg_cost = state.total_cost / state.quantity
        cost_basis = avg_cost * quantity
        state.quantity -= quantity
        state.total_cost -= cost_basis
        if state.quantity <= EPS:
            state.quantity = 0.0
            state.total_cost = 0.0
        return cost_basis

    @staticmethod
    def _held_quantity(
        *,
        key: Tuple[str, str, str],
        cost_method: str,
        fifo_lots: Dict[Tuple[str, str, str], List[Dict[str, Any]]],
        avg_state: Dict[Tuple[str, str, str], _AvgState],
    ) -> float:
        if cost_method == "fifo":
            return sum(float(lot["remaining_quantity"]) for lot in fifo_lots.get(key, []))
        return float(avg_state.get(key, _AvgState()).quantity)

    def _convert_amount(
        self,
        *,
        amount: float,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
    ) -> Tuple[float, bool, str]:
        from_norm = self._normalize_currency(from_currency)
        to_norm = self._normalize_currency(to_currency)
        if abs(amount) <= EPS:
            return 0.0, False, "zero"
        if from_norm == to_norm:
            return float(amount), False, "identity"

        direct = self.repo.get_latest_fx_rate(
            from_currency=from_norm,
            to_currency=to_norm,
            as_of=as_of_date,
        )
        if direct is not None and direct.rate > 0:
            return float(amount) * float(direct.rate), bool(direct.is_stale), "direct_rate"

        inverse = self.repo.get_latest_fx_rate(
            from_currency=to_norm,
            to_currency=from_norm,
            as_of=as_of_date,
        )
        if inverse is not None and inverse.rate > 0:
            return float(amount) / float(inverse.rate), bool(inverse.is_stale), "inverse_rate"

        # P0 fallback: keep pipeline available even when FX cache is missing.
        return float(amount), True, "fallback_1_to_1"

    def convert_amount(
        self,
        *,
        amount: float,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
    ) -> Tuple[float, bool, str]:
        """Public conversion entry for cross-service consumers."""
        return self._convert_amount(
            amount=amount,
            from_currency=from_currency,
            to_currency=to_currency,
            as_of_date=as_of_date,
        )

    def _list_account_refresh_fx_currencies(
        self,
        *,
        account: Any,
        as_of_date: date,
        strict: bool = True,
    ) -> List[str]:
        """Return distinct non-base currencies participating in refresh for one account."""
        base_currency = self._normalize_currency(account.base_currency)
        currencies: Set[str] = set()
        rows = list(self.repo.list_trades(account.id, as_of=as_of_date))
        rows.extend(self.repo.list_cash_ledger(account.id, as_of=as_of_date))
        for row in rows:
            try:
                currency = self._normalize_currency(row.currency)
            except ValueError:
                if strict:
                    raise
                logger.warning(
                    "Skip invalid FX refresh currency for account %s on %s: %r",
                    account.id,
                    as_of_date.isoformat(),
                    getattr(row, "currency", None),
                )
                continue
            if currency != base_currency:
                currencies.add(currency)
        return sorted(currencies)

    def _refresh_account_fx_rates(
        self,
        *,
        account: Any,
        as_of_date: date,
        refresh_enabled: bool,
    ) -> Dict[str, int]:
        """Refresh FX pairs for one account and keep stale fallback on failures."""
        refresh_currencies = self._list_account_refresh_fx_currencies(
            account=account,
            as_of_date=as_of_date,
            strict=refresh_enabled,
        )
        if not refresh_enabled:
            return {
                "pair_count": len(refresh_currencies),
                "updated_count": 0,
                "stale_count": 0,
                "error_count": 0,
            }

        base_currency = self._normalize_currency(account.base_currency)
        summary = {
            "pair_count": len(refresh_currencies),
            "updated_count": 0,
            "stale_count": 0,
            "error_count": 0,
        }
        for from_currency in refresh_currencies:
            try:
                rate = self._fetch_fx_rate_from_yfinance(
                    from_currency=from_currency,
                    to_currency=base_currency,
                    as_of_date=as_of_date,
                )
                if rate is not None and rate > 0:
                    self.repo.save_fx_rate(
                        from_currency=from_currency,
                        to_currency=base_currency,
                        rate_date=as_of_date,
                        rate=rate,
                        source="yfinance",
                        is_stale=False,
                    )
                    summary["updated_count"] += 1
                    continue
            except Exception as exc:
                logger.warning(
                    "FX online fetch failed for %s/%s on %s: %s",
                    from_currency,
                    base_currency,
                    as_of_date.isoformat(),
                    exc,
                )

            fallback = self.repo.get_latest_fx_rate(
                from_currency=from_currency,
                to_currency=base_currency,
                as_of=as_of_date,
            )
            if fallback is not None and float(fallback.rate or 0.0) > 0:
                self.repo.save_fx_rate(
                    from_currency=from_currency,
                    to_currency=base_currency,
                    rate_date=as_of_date,
                    rate=float(fallback.rate),
                    source=(fallback.source or "cache_fallback"),
                    is_stale=True,
                )
                summary["stale_count"] += 1
            else:
                summary["error_count"] += 1
        return summary

    @staticmethod
    def _fetch_fx_rate_from_yfinance(
        *,
        from_currency: str,
        to_currency: str,
        as_of_date: date,
    ) -> Optional[float]:
        """Fetch latest available FX close rate around as_of date."""
        if yf is None:
            return None
        symbol = f"{from_currency}{to_currency}=X"
        ticker = yf.Ticker(symbol)
        history = ticker.history(
            start=(as_of_date - timedelta(days=7)).isoformat(),
            end=(as_of_date + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
        )
        if history is None or history.empty or "Close" not in history:
            return None
        close = history["Close"].dropna()
        if close.empty:
            return None
        value = float(close.iloc[-1])
        if value <= 0:
            return None
        return value

    def _require_active_account(self, account_id: int) -> Any:
        account = self.repo.get_account(account_id, include_inactive=False)
        if account is None:
            raise ValueError(f"Active account not found: {account_id}")
        return account

    def _require_active_account_in_session(self, *, session: Any, account_id: int) -> Any:
        account = self.repo.get_account_in_session(
            session=session,
            account_id=account_id,
            include_inactive=False,
        )
        if account is None:
            raise ValueError(f"Active account not found: {account_id}")
        return account

    def _has_trade_uid(self, *, account_id: int, trade_uid: str, session: Optional[Any] = None) -> bool:
        if session is None:
            return self.repo.has_trade_uid(account_id, trade_uid)
        return self.repo.has_trade_uid_in_session(session=session, account_id=account_id, trade_uid=trade_uid)

    def _has_trade_dedup_hash(
        self,
        *,
        account_id: int,
        dedup_hash: str,
        session: Optional[Any] = None,
    ) -> bool:
        if session is None:
            return self.repo.has_trade_dedup_hash(account_id, dedup_hash)
        return self.repo.has_trade_dedup_hash_in_session(
            session=session,
            account_id=account_id,
            dedup_hash=dedup_hash,
        )

    @staticmethod
    def _account_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "broker": row.broker,
            "market": row.market,
            "base_currency": row.base_currency,
            "is_active": bool(row.is_active),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    @staticmethod
    def _trade_row_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "account_id": int(row.account_id),
            "trade_uid": row.trade_uid,
            "symbol": row.symbol,
            "market": row.market,
            "currency": row.currency,
            "trade_date": row.trade_date.isoformat() if row.trade_date else "",
            "side": row.side,
            "quantity": float(row.quantity),
            "price": float(row.price),
            "fee": float(row.fee),
            "tax": float(row.tax),
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _cash_ledger_row_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "account_id": int(row.account_id),
            "event_date": row.event_date.isoformat() if row.event_date else "",
            "direction": row.direction,
            "amount": float(row.amount),
            "currency": row.currency,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _corporate_action_row_to_dict(row: Any) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "account_id": int(row.account_id),
            "symbol": row.symbol,
            "market": row.market,
            "currency": row.currency,
            "effective_date": row.effective_date.isoformat() if row.effective_date else "",
            "action_type": row.action_type,
            "cash_dividend_per_share": (
                float(row.cash_dividend_per_share) if row.cash_dividend_per_share is not None else None
            ),
            "split_ratio": float(row.split_ratio) if row.split_ratio is not None else None,
            "note": row.note,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _validate_paging(*, page: int, page_size: int) -> Tuple[int, int]:
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be in [1, 100]")
        return page, page_size

    @staticmethod
    def _normalize_market(value: str) -> str:
        market = (value or "").strip().lower()
        if market not in VALID_MARKETS:
            raise ValueError("market must be one of: cn, hk, us, jp, kr, tw")
        return market

    @staticmethod
    def _normalize_currency(value: str) -> str:
        currency = (value or "").strip().upper()
        if not currency:
            raise ValueError("currency is required")
        return currency

    @staticmethod
    def _normalize_cost_method(value: str) -> str:
        method = (value or "").strip().lower()
        if method not in VALID_COST_METHODS:
            raise ValueError("cost_method must be fifo or avg")
        return method

    @staticmethod
    def _default_currency_for_market(market: str) -> str:
        if market == "hk":
            return "HKD"
        if market == "us":
            return "USD"
        return "CNY"
