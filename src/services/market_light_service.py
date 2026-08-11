# -*- coding: utf-8 -*-
"""Market Light snapshot service for structured alerts."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Dict, Optional

from sqlalchemy import desc

from src.config import get_config
from src.core.market_review import MARKET_REVIEW_HISTORY_CODE, MARKET_REVIEW_REPORT_TYPE
from src.core.market_profile import get_profile
from src.market_analyzer import MarketAnalyzer, MarketIndex, MarketOverview
from src.schemas.market_light import MarketLightSnapshot
from src.storage import AnalysisHistory, DatabaseManager


logger = logging.getLogger(__name__)

MARKET_LIGHT_REGIONS = frozenset({"cn", "hk", "us", "jp", "kr"})
MARKET_LIGHT_ALERT_REGIONS = frozenset({"cn", "hk", "us"})
MARKET_LIGHT_HISTORY_BATCH_SIZE = 100

_DASHBOARD_BLOCKS = ("indices", "breadth", "sectors", "concepts")
_DASHBOARD_EXECUTOR = ThreadPoolExecutor(
    max_workers=8,
    thread_name_prefix="market-dashboard",
)
_DASHBOARD_STATE_LOCK = Lock()


@dataclass(frozen=True)
class _DashboardBlockResult:
    value: Any
    usable: bool
    trade_date: str
    message: Optional[str] = None


@dataclass(frozen=True)
class _DashboardCacheEntry:
    value: Any
    trade_date: str
    updated_at: datetime
    updated_monotonic: float


_DASHBOARD_CACHE: Dict[tuple[str, str], _DashboardCacheEntry] = {}
_DASHBOARD_INFLIGHT: Dict[tuple[str, str], Future[_DashboardBlockResult]] = {}
_DASHBOARD_PERSISTED_LOADED: set[str] = set()


def normalize_market_region(region: str) -> str:
    value = str(region or "").strip().lower()
    if value not in MARKET_LIGHT_REGIONS:
        raise ValueError(f"market target must be one of cn, hk, us, jp, kr: {region}")
    return value


def normalize_market_alert_region(region: str) -> str:
    value = str(region or "").strip().lower()
    if value not in MARKET_LIGHT_ALERT_REGIONS:
        raise ValueError(f"market alert target must be one of cn, hk, us: {region}")
    return value


def build_current_snapshot(region: str) -> Dict[str, Any]:
    """Build the current structured Market Light snapshot without LLM review."""

    normalized_region = normalize_market_region(region)
    analyzer = MarketAnalyzer(region=normalized_region)
    overview = analyzer.get_market_overview()
    return analyzer.build_market_light_snapshot(overview)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _fetch_market_dashboard_block(region: str, block: str) -> _DashboardBlockResult:
    """Fetch one dashboard dimension independently.

    Each worker owns its ``MarketAnalyzer`` and ``DataFetcherManager`` instance so
    concurrent dimensions never share mutable provider state.
    """

    trade_date = datetime.now().strftime("%Y-%m-%d")
    try:
        analyzer = MarketAnalyzer(region=region)
        manager = analyzer.data_manager

        if block == "indices":
            indices = []
            for item in manager.get_main_indices(region=region) or []:
                if not isinstance(item, dict):
                    continue
                current = _to_float(item.get("current"))
                if current <= 0:
                    continue
                indices.append(
                    MarketIndex(
                        code=str(item.get("code") or ""),
                        name=str(item.get("name") or item.get("code") or ""),
                        current=current,
                        change=_to_float(item.get("change")),
                        change_pct=_to_float(item.get("change_pct")),
                        open=_to_float(item.get("open")),
                        high=_to_float(item.get("high")),
                        low=_to_float(item.get("low")),
                        prev_close=_to_float(item.get("prev_close")),
                        volume=_to_float(item.get("volume")),
                        amount=_to_float(item.get("amount")),
                        amplitude=_to_float(item.get("amplitude")),
                    )
                )
            return _DashboardBlockResult(
                value=indices,
                usable=bool(indices),
                trade_date=trade_date,
                message=None if indices else "指数数据源返回空结果",
            )

        if block == "breadth":
            raw = manager.get_market_stats(purpose=f"market_dashboard:{region}") or {}
            breadth = {
                "up_count": _to_int(raw.get("up_count")),
                "down_count": _to_int(raw.get("down_count")),
                "flat_count": _to_int(raw.get("flat_count")),
                "limit_up_count": _to_int(raw.get("limit_up_count")),
                "limit_down_count": _to_int(raw.get("limit_down_count")),
                "total_amount": _to_float(raw.get("total_amount")),
            }
            usable = bool(
                breadth["up_count"]
                or breadth["down_count"]
                or breadth["flat_count"]
                or breadth["limit_up_count"]
                or breadth["limit_down_count"]
                or breadth["total_amount"]
            )
            return _DashboardBlockResult(
                value=breadth,
                usable=usable,
                trade_date=trade_date,
                message=None if usable else "市场宽度数据源返回空结果",
            )

        if block == "sectors":
            top, bottom = manager.get_sector_rankings(8)
            value = (list(top or []), list(bottom or []))
            return _DashboardBlockResult(
                value=value,
                usable=bool(value[0] or value[1]),
                trade_date=trade_date,
                message=None if value[0] or value[1] else "行业板块数据源返回空结果",
            )

        if block == "concepts":
            top, bottom = manager.get_concept_rankings(8)
            value = (list(top or []), list(bottom or []))
            return _DashboardBlockResult(
                value=value,
                usable=bool(value[0] or value[1]),
                trade_date=trade_date,
                message=None if value[0] or value[1] else "概念题材数据源返回空结果",
            )

        raise ValueError(f"unknown dashboard block: {block}")
    except Exception as exc:
        logger.exception(
            "Market dashboard block failed region=%s block=%s",
            region,
            block,
        )
        return _DashboardBlockResult(
            value=None,
            usable=False,
            trade_date=trade_date,
            message=f"数据源调用失败（{type(exc).__name__}）",
        )


def _finish_market_dashboard_block(
    key: tuple[str, str],
    future: Future[_DashboardBlockResult],
) -> None:
    try:
        result = future.result()
    except Exception:
        logger.exception("Market dashboard worker crashed key=%s", key)
        result = None

    now = datetime.now().astimezone()
    now_monotonic = time.monotonic()
    with _DASHBOARD_STATE_LOCK:
        if _DASHBOARD_INFLIGHT.get(key) is future:
            _DASHBOARD_INFLIGHT.pop(key, None)
        # Empty/failed refreshes must not erase the last known successful value.
        if result is not None and result.usable:
            _DASHBOARD_CACHE[key] = _DashboardCacheEntry(
                value=result.value,
                trade_date=result.trade_date,
                updated_at=now,
                updated_monotonic=now_monotonic,
            )


def _start_market_dashboard_block(
    region: str,
    block: str,
) -> Future[_DashboardBlockResult]:
    key = (region, block)
    with _DASHBOARD_STATE_LOCK:
        current = _DASHBOARD_INFLIGHT.get(key)
        if current is not None:
            return current
        future = _DASHBOARD_EXECUTOR.submit(_fetch_market_dashboard_block, region, block)
        _DASHBOARD_INFLIGHT[key] = future
    future.add_done_callback(lambda completed: _finish_market_dashboard_block(key, completed))
    return future


def _read_market_dashboard_cache(region: str, block: str) -> Optional[_DashboardCacheEntry]:
    with _DASHBOARD_STATE_LOCK:
        return _DASHBOARD_CACHE.get((region, block))


def _parse_dashboard_history_datetime(value: Any, fallback: Any) -> datetime:
    parsed: Optional[datetime] = None
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    if parsed is None and isinstance(fallback, datetime):
        parsed = fallback
    if parsed is None:
        parsed = datetime.now().astimezone()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone()


def _load_persisted_market_dashboard_cache(region: str) -> None:
    """Warm the process cache from the latest structured market-review history.

    This gives a restarted server an auditable last-known result instead of an
    empty dashboard while live providers are slow.  The regular stale TTL still
    applies, and the frontend labels these values as stale.
    """

    with _DASHBOARD_STATE_LOCK:
        if region in _DASHBOARD_PERSISTED_LOADED:
            return

    try:
        db = DatabaseManager.get_instance()
        with db.get_session() as session:
            rows = (
                session.query(AnalysisHistory)
                .filter(
                    AnalysisHistory.code == MARKET_REVIEW_HISTORY_CODE,
                    AnalysisHistory.report_type == MARKET_REVIEW_REPORT_TYPE,
                )
                .order_by(desc(AnalysisHistory.created_at), desc(AnalysisHistory.id))
                .limit(50)
                .all()
            )

        for row in rows:
            raw_context = getattr(row, "context_snapshot", None)
            try:
                context = json.loads(raw_context) if isinstance(raw_context, str) else raw_context
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(context, dict):
                continue
            payload = context.get("market_review_payload")
            if not isinstance(payload, dict):
                continue
            markets = payload.get("markets")
            if isinstance(markets, dict):
                payload = markets.get(region)
            elif str(payload.get("region") or "").strip().lower() != region:
                continue
            if not isinstance(payload, dict):
                continue

            trade_date = str(payload.get("date") or "").strip()
            if not trade_date:
                continue
            updated_at = _parse_dashboard_history_datetime(
                payload.get("generated_at"),
                getattr(row, "created_at", None),
            )
            age_seconds = max(
                0.0,
                (datetime.now().astimezone() - updated_at).total_seconds(),
            )
            # A synthetic negative monotonic value is intentional when the
            # persisted record predates this process; only the delta is used.
            updated_monotonic = time.monotonic() - age_seconds
            recovered: Dict[str, Any] = {}

            indices = []
            for item in payload.get("indices") or []:
                if not isinstance(item, dict):
                    continue
                current = _to_float(item.get("current"))
                if current <= 0:
                    continue
                indices.append(
                    MarketIndex(
                        code=str(item.get("code") or ""),
                        name=str(item.get("name") or item.get("code") or ""),
                        current=current,
                        change=_to_float(item.get("change")),
                        change_pct=_to_float(item.get("change_pct")),
                        open=_to_float(item.get("open")),
                        high=_to_float(item.get("high")),
                        low=_to_float(item.get("low")),
                        prev_close=_to_float(item.get("prev_close")),
                        volume=_to_float(item.get("volume")),
                        amount=_to_float(item.get("amount")),
                        amplitude=_to_float(item.get("amplitude")),
                    )
                )
            if indices:
                recovered["indices"] = indices

            raw_breadth = payload.get("breadth")
            if isinstance(raw_breadth, dict):
                breadth = {
                    "up_count": _to_int(raw_breadth.get("up_count")),
                    "down_count": _to_int(raw_breadth.get("down_count")),
                    "flat_count": _to_int(raw_breadth.get("flat_count")),
                    "limit_up_count": _to_int(raw_breadth.get("limit_up_count")),
                    "limit_down_count": _to_int(raw_breadth.get("limit_down_count")),
                    "total_amount": _to_float(raw_breadth.get("total_amount")),
                }
                if any(breadth.values()):
                    recovered["breadth"] = breadth

            for block, payload_key in (("sectors", "sectors"), ("concepts", "concepts")):
                raw_rankings = payload.get(payload_key)
                if not isinstance(raw_rankings, dict):
                    continue
                ranking_value = (
                    list(raw_rankings.get("top") or []),
                    list(raw_rankings.get("bottom") or []),
                )
                if ranking_value[0] or ranking_value[1]:
                    recovered[block] = ranking_value

            if recovered:
                with _DASHBOARD_STATE_LOCK:
                    for block, value in recovered.items():
                        _DASHBOARD_CACHE.setdefault(
                            (region, block),
                            _DashboardCacheEntry(
                                value=value,
                                trade_date=trade_date,
                                updated_at=updated_at,
                                updated_monotonic=updated_monotonic,
                            ),
                        )
                break
    except Exception:
        # A missing/locked history database must not block the live dashboard path.
        logger.warning(
            "Unable to warm market dashboard from persisted history region=%s",
            region,
            exc_info=True,
        )
        return

    with _DASHBOARD_STATE_LOCK:
        _DASHBOARD_PERSISTED_LOADED.add(region)


def clear_market_dashboard_cache_for_tests() -> None:
    """Clear dashboard state for deterministic unit tests."""

    with _DASHBOARD_STATE_LOCK:
        _DASHBOARD_CACHE.clear()
        _DASHBOARD_INFLIGHT.clear()
        _DASHBOARD_PERSISTED_LOADED.clear()


def build_market_dashboard(region: str) -> Dict[str, Any]:
    """Build a bounded, partially available homepage market dashboard.

    Index, breadth, sector and concept blocks refresh concurrently.  The HTTP
    request waits only for the configured total budget; slow dimensions continue
    in the background and a later request can reuse the completed result.  A
    failed refresh never replaces the last successful cache entry.
    """

    normalized_region = normalize_market_region(region)
    _load_persisted_market_dashboard_cache(normalized_region)
    config = get_config()
    profile = get_profile(normalized_region)
    fetch_budget = max(
        0.5,
        float(getattr(config, "market_dashboard_fetch_budget_seconds", 8.0)),
    )
    fresh_ttl = max(
        0,
        int(getattr(config, "market_dashboard_cache_ttl_seconds", 60)),
    )
    stale_ttl = max(
        fresh_ttl,
        int(getattr(config, "market_dashboard_stale_ttl_seconds", 604800)),
    )
    supported = {
        "indices": True,
        "breadth": bool(profile.has_market_stats),
        "sectors": bool(profile.has_sector_rankings),
        "concepts": bool(profile.has_sector_rankings),
    }

    started_at = time.monotonic()
    futures: Dict[str, Future[_DashboardBlockResult]] = {}
    has_displayable_cache = False
    for block in _DASHBOARD_BLOCKS:
        if not supported[block]:
            continue
        cached = _read_market_dashboard_cache(normalized_region, block)
        cache_age = (
            max(0.0, started_at - cached.updated_monotonic)
            if cached is not None
            else None
        )
        if cache_age is not None and cache_age <= stale_ttl:
            has_displayable_cache = True
        cache_is_fresh = (
            cache_age is not None
            and fresh_ttl > 0
            and cache_age <= fresh_ttl
        )
        if not cache_is_fresh:
            futures[block] = _start_market_dashboard_block(normalized_region, block)

    if futures:
        # A stale/partial dashboard is already useful and explicitly labelled;
        # do not make the browser wait the full cold-start budget for its refresh.
        wait_timeout = min(fetch_budget, 0.25) if has_displayable_cache else fetch_budget
        wait(tuple(futures.values()), timeout=wait_timeout)

    now = datetime.now().astimezone()
    now_monotonic = time.monotonic()
    values: Dict[str, Any] = {}
    block_states: Dict[str, Dict[str, Any]] = {}
    used_entries: list[_DashboardCacheEntry] = []

    for block in _DASHBOARD_BLOCKS:
        if not supported[block]:
            block_states[block] = {
                "status": "unsupported",
                "updated_at": None,
                "age_seconds": None,
                "message": "当前市场的数据源不提供该维度",
            }
            continue

        cached = _read_market_dashboard_cache(normalized_region, block)
        age = (
            max(0.0, now_monotonic - cached.updated_monotonic)
            if cached is not None
            else None
        )
        future = futures.get(block)
        failure_message = None
        if future is not None and future.done():
            try:
                result = future.result()
                failure_message = result.message if not result.usable else None
            except Exception as exc:
                failure_message = f"数据源调用失败（{type(exc).__name__}）"

        if cached is not None and age is not None and age <= stale_ttl:
            is_fresh = fresh_ttl > 0 and age <= fresh_ttl
            values[block] = cached.value
            used_entries.append(cached)
            block_states[block] = {
                "status": "fresh" if is_fresh else "stale",
                "updated_at": cached.updated_at.isoformat(),
                "age_seconds": round(age, 1),
                "message": None
                if is_fresh
                else (
                    "后台刷新仍在进行，当前显示最近一次成功数据"
                    if future is not None and not future.done()
                    else failure_message or "当前显示最近一次成功数据"
                ),
            }
            continue

        pending = future is not None and not future.done()
        block_states[block] = {
            "status": "refreshing" if pending else "unavailable",
            "updated_at": None,
            "age_seconds": None,
            "message": (
                "外部数据源仍在后台刷新"
                if pending
                else failure_message or "暂未取得可靠数据"
            ),
        }

    breadth_value = values.get("breadth") or {}
    sector_value = values.get("sectors") or ([], [])
    concept_value = values.get("concepts") or ([], [])
    index_value = list(values.get("indices") or [])

    trade_date = (
        max(entry.trade_date for entry in used_entries)
        if used_entries
        else datetime.now().strftime("%Y-%m-%d")
    )
    overview = MarketOverview(
        date=trade_date,
        indices=index_value,
        up_count=_to_int(breadth_value.get("up_count")),
        down_count=_to_int(breadth_value.get("down_count")),
        flat_count=_to_int(breadth_value.get("flat_count")),
        limit_up_count=_to_int(breadth_value.get("limit_up_count")),
        limit_down_count=_to_int(breadth_value.get("limit_down_count")),
        total_amount=_to_float(breadth_value.get("total_amount")),
        top_sectors=list(sector_value[0] or []),
        bottom_sectors=list(sector_value[1] or []),
        top_concepts=list(concept_value[0] or []),
        bottom_concepts=list(concept_value[1] or []),
    )
    analyzer = MarketAnalyzer(region=normalized_region, config=config)
    market_light = analyzer.build_market_light_snapshot(overview)

    def normalize_ranking(items: Any) -> list[Dict[str, Any]]:
        normalized: list[Dict[str, Any]] = []
        for item in list(items or [])[:8]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            raw_change = item.get("change_pct")
            try:
                change_pct = float(raw_change) if raw_change is not None else None
            except (TypeError, ValueError):
                change_pct = None
            normalized.append(
                {
                    "name": name,
                    "change_pct": change_pct,
                    "source": str(item.get("source") or "").strip() or None,
                }
            )
        return normalized

    indices = []
    for item in overview.indices:
        indices.append(
            {
                "code": str(item.code),
                "name": str(item.name),
                "current": float(item.current or 0.0),
                "change": float(item.change or 0.0),
                "change_pct": float(item.change_pct or 0.0),
                "open": float(item.open) if item.open is not None else None,
                "high": float(item.high) if item.high is not None else None,
                "low": float(item.low) if item.low is not None else None,
                "prev_close": float(item.prev_close) if item.prev_close is not None else None,
                "volume": float(item.volume) if item.volume is not None else None,
                "amount": float(item.amount) if item.amount is not None else None,
                "amplitude": float(item.amplitude) if item.amplitude is not None else None,
            }
        )

    supported_states = [block_states[name]["status"] for name in _DASHBOARD_BLOCKS if supported[name]]
    available_states = {"fresh", "stale"}
    has_any_data = any(state in available_states for state in supported_states)
    if not has_any_data:
        data_status = "unavailable"
    elif all(state == "fresh" for state in supported_states):
        data_status = "ok"
    elif all(state in available_states for state in supported_states) and any(
        state == "stale" for state in supported_states
    ):
        data_status = "stale"
    else:
        data_status = "partial"

    if data_status != "ok":
        market_light["data_quality"] = (
            "unavailable" if data_status == "unavailable" else "partial"
        )

    data_updated_at = (
        max(entry.updated_at for entry in used_entries).isoformat()
        if used_entries
        else None
    )
    breadth_available = "breadth" in values
    sector_available = "sectors" in values
    concept_available = "concepts" in values

    return {
        "region": normalized_region,
        "trade_date": overview.date,
        "generated_at": now.isoformat(),
        "data_updated_at": data_updated_at,
        "data_status": data_status,
        "is_stale": any(state == "stale" for state in supported_states),
        "refreshing": any(not future.done() for future in futures.values()),
        "blocks": block_states,
        "indices": indices,
        "breadth": {
            "available": breadth_available,
            "up_count": int(overview.up_count or 0),
            "down_count": int(overview.down_count or 0),
            "flat_count": int(overview.flat_count or 0),
            "limit_up_count": int(overview.limit_up_count or 0),
            "limit_down_count": int(overview.limit_down_count or 0),
            "total_amount": float(overview.total_amount or 0.0),
        },
        "rankings": {
            "available": sector_available or concept_available,
            "top_sectors": normalize_ranking(overview.top_sectors),
            "bottom_sectors": normalize_ranking(overview.bottom_sectors),
            "top_concepts": normalize_ranking(overview.top_concepts),
            "bottom_concepts": normalize_ranking(overview.bottom_concepts),
        },
        "market_light": market_light,
        "coverage": {
            "indices": bool(indices),
            "breadth": breadth_available,
            "sector_rankings": sector_available,
            "concept_rankings": concept_available,
        },
        "source_label": "configured_market_data_provider_chain",
    }


def load_previous_snapshot(
    region: str,
    *,
    before_trade_date: str,
    db_manager: Optional[DatabaseManager] = None,
    limit: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Load the latest persisted Market Light snapshot before ``before_trade_date``.

    Legacy market-review history rows without ``market_light_snapshots[region]`` are
    skipped while scanning newer rows.
    """

    normalized_region = normalize_market_region(region)
    cutoff = str(before_trade_date or "").strip()
    if not cutoff:
        return None

    db = db_manager or DatabaseManager.get_instance()
    best_trade_date: Optional[str] = None
    best_snapshot: Optional[Dict[str, Any]] = None
    invalid_target_error: Optional[Exception] = None

    with db.get_session() as session:
        query = (
            session.query(AnalysisHistory)
            .filter(
                AnalysisHistory.code == MARKET_REVIEW_HISTORY_CODE,
                AnalysisHistory.report_type == MARKET_REVIEW_REPORT_TYPE,
            )
            .order_by(desc(AnalysisHistory.created_at), desc(AnalysisHistory.id))
        )
        if limit is not None:
            query = query.limit(limit)
        for row in query.yield_per(MARKET_LIGHT_HISTORY_BATCH_SIZE):
            snapshot = _extract_region_snapshot(row.context_snapshot, normalized_region)
            if snapshot is None:
                continue
            trade_date = str(snapshot.get("trade_date") or "").strip()
            if not trade_date or trade_date >= cutoff:
                continue
            if best_trade_date is None or trade_date > best_trade_date:
                best_trade_date = trade_date
                best_snapshot = None
                invalid_target_error = None
            elif trade_date < best_trade_date:
                continue
            try:
                candidate = MarketLightSnapshot.model_validate(snapshot).model_dump()
            except Exception as exc:
                logger.warning(
                    "invalid persisted market light snapshot: row_id=%s region=%s trade_date=%s error=%s",
                    getattr(row, "id", "?"),
                    normalized_region,
                    trade_date,
                    exc,
                )
                if best_snapshot is None:
                    invalid_target_error = exc
                continue
            if best_snapshot is None:
                best_snapshot = candidate

    if best_snapshot is not None:
        return best_snapshot
    if best_trade_date is not None and invalid_target_error is not None:
        raise ValueError(
            f"invalid persisted market light snapshot for {normalized_region} on {best_trade_date}"
        ) from invalid_target_error
    return None


def _extract_region_snapshot(raw_context_snapshot: Any, region: str) -> Optional[Dict[str, Any]]:
    if not raw_context_snapshot:
        return None
    try:
        payload = (
            json.loads(raw_context_snapshot)
            if isinstance(raw_context_snapshot, str)
            else raw_context_snapshot
        )
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    snapshots = payload.get("market_light_snapshots")
    if not isinstance(snapshots, dict):
        return None
    snapshot = snapshots.get(region)
    return snapshot if isinstance(snapshot, dict) else None
