# -*- coding: utf-8 -*-
"""Recognize portfolio trade screenshots and commit reviewed records."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from data_provider.base import canonical_stock_code, normalize_stock_code
from src.data.stock_index_loader import get_stock_name_index_map
from src.data.stock_mapping import STOCK_NAME_MAP
from src.services.image_stock_extractor import run_vision_prompt_on_image
from src.services.portfolio_import_service import PortfolioImportService

logger = logging.getLogger(__name__)

PORTFOLIO_TRADE_IMAGE_PROMPT = """你是券商交易截图的结构化识别器。请只提取截图中逐笔展示的证券买卖交易，
不要把浮动盈亏、当日参考盈亏、实现盈亏、市值、总资产、持仓数量、仓位或行情价格误识别成交易。

识别规则：
1. “买入”和“建仓”统一输出 side="buy"；“卖出”和“清仓”统一输出 side="sell"。
2. quantity 必须输出绝对值正数，即使截图中的卖出数量带负号。
3. fee 和 tax 仅在截图明确标注属于该笔交易时填写；未显示时填 0，并在 warning 中说明“费用未显示，请核对”。
4. 截图右侧单独以红/蓝色显示的数字，若没有“费用/税费”标签，通常是盈亏，禁止当作 fee 或 tax。
5. 不得推算、补全或编造看不清的数据。若截图只显示证券名称、没有证券代码，保留准确的 stock_name 并令 symbol=null，
   由系统在本地股票索引中做唯一匹配；禁止模型凭知识猜代码。日期、方向、数量、价格无法确认，或代码与名称都无法确认时，
   不输出该笔交易，只把原因加入顶层 warnings。
6. 同一张图可能包含同一证券的多笔交易，也可能包含多个证券；每笔都单独输出。

仅返回有效 JSON 对象，不要 Markdown，不要解释。格式：
{
  "trades": [
    {
      "trade_date": "YYYY-MM-DD",
      "symbol": "600693",
      "stock_name": "东百集团",
      "side": "buy",
      "quantity": 200,
      "price": 8.67,
      "fee": 0,
      "tax": 0,
      "currency": "CNY",
      "confidence": "high",
      "warning": "费用未显示，请核对"
    }
  ],
  "warnings": []
}

confidence 只能是 high、medium、low。若没有可靠交易记录，返回 {"trades":[],"warnings":["未识别到可靠的逐笔交易"]}。"""

_VALID_CONFIDENCE = frozenset({"high", "medium", "low"})
_VALID_SIDE_MAP = {
    "buy": "buy",
    "b": "buy",
    "买": "buy",
    "买入": "buy",
    "建仓": "buy",
    "sell": "sell",
    "s": "sell",
    "卖": "sell",
    "卖出": "sell",
    "清仓": "sell",
}


class PortfolioImageImportService:
    """Parse trade screenshots, then commit only user-reviewed normalized rows."""

    def __init__(self, *, importer: Optional[PortfolioImportService] = None):
        self.importer = importer or PortfolioImportService()

    def parse_image(self, *, content: bytes, mime_type: str) -> Dict[str, Any]:
        raw = run_vision_prompt_on_image(
            content,
            mime_type,
            prompt=PORTFOLIO_TRADE_IMAGE_PROMPT,
            max_tokens=4096,
        )
        parsed = self._parse_json_object(raw)
        source_hash = hashlib.sha256(content).hexdigest()
        records: List[Dict[str, Any]] = []
        warnings = self._string_list(parsed.get("warnings"))

        raw_trades = parsed.get("trades")
        if not isinstance(raw_trades, list):
            raise ValueError("图片识别结果缺少 trades 数组")

        for index, raw_trade in enumerate(raw_trades):
            try:
                record = self._normalize_trade(
                    raw_trade,
                    source_hash=source_hash,
                    source_index=index,
                )
                records.append(record)
            except ValueError as exc:
                warnings.append(f"第 {index + 1} 条已跳过：{exc}")

        records.sort(
            key=lambda item: (
                item["trade_date"],
                0 if item["side"] == "buy" else 1,
                int(item["source_index"]),
            )
        )
        if not records and not warnings:
            warnings.append("未识别到可靠的逐笔交易")
        return {
            "source_hash": source_hash,
            "record_count": len(records),
            "records": records,
            "warnings": warnings[:50],
        }

    def commit_records(
        self,
        *,
        account_id: int,
        source_hash: str,
        records: List[Dict[str, Any]],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        source_hash_norm = (source_hash or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", source_hash_norm):
            raise ValueError("source_hash 无效，请重新识别图片")
        if not records:
            raise ValueError("没有可导入的交易记录")

        normalized: List[Dict[str, Any]] = []
        for index, item in enumerate(records):
            source_index_value = item.get("source_index", item.get("sourceIndex", index))
            try:
                source_index = int(source_index_value)
            except (TypeError, ValueError):
                source_index = index
            if source_index < 0:
                source_index = index
            normalized.append(
                self._normalize_trade(
                    item,
                    source_hash=source_hash_norm,
                    source_index=source_index,
                )
            )
        normalized.sort(
            key=lambda item: (
                item["trade_date"],
                0 if item["side"] == "buy" else 1,
                int(item["source_index"]),
            )
        )
        return self.importer.commit_normalized_trade_records(
            account_id=account_id,
            source=f"image_import:{source_hash_norm[:12]}",
            records=normalized,
            dry_run=dry_run,
        )

    @classmethod
    def _normalize_trade(
        cls,
        item: Any,
        *,
        source_hash: str,
        source_index: int,
    ) -> Dict[str, Any]:
        if not isinstance(item, dict):
            raise ValueError("记录不是对象")

        trade_date_obj = cls._parse_date(item.get("trade_date") or item.get("tradeDate"))
        stock_name = str(item.get("stock_name") or item.get("stockName") or "").strip() or None
        symbol = cls._normalize_symbol(
            item.get("symbol") or item.get("code"),
            stock_name=stock_name,
        )
        side = cls._normalize_side(item.get("side"))
        quantity = abs(cls._number(item.get("quantity"), "数量"))
        if quantity <= 0:
            raise ValueError("数量必须大于 0")
        price = cls._positive_number(item.get("price"), "成交价")
        fee = cls._non_negative_number(item.get("fee", 0), "手续费")
        tax = cls._non_negative_number(item.get("tax", 0), "税费")
        currency = str(item.get("currency") or "").strip().upper() or None
        if currency is not None and not re.fullmatch(r"[A-Z]{3,8}", currency):
            raise ValueError("币种格式无效")

        confidence = str(item.get("confidence") or "medium").strip().lower()
        if confidence not in _VALID_CONFIDENCE:
            confidence = "medium"
        warning = str(item.get("warning") or "").strip() or None

        dedup_payload = "|".join(
            [
                source_hash,
                str(source_index),
                trade_date_obj.isoformat(),
                symbol,
                side,
                f"{quantity:.8f}",
                f"{price:.8f}",
                f"{fee:.8f}",
                f"{tax:.8f}",
            ]
        )
        return {
            "trade_date": trade_date_obj,
            "symbol": symbol,
            "stock_name": stock_name,
            "side": side,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "tax": tax,
            "currency": currency,
            "confidence": confidence,
            "warning": warning,
            "source_index": source_index,
            "dedup_hash": hashlib.sha256(dedup_payload.encode("utf-8")).hexdigest(),
        }

    @staticmethod
    def _parse_json_object(raw: str) -> Dict[str, Any]:
        cleaned = (raw or "").strip()
        for prefix in ("```json", "```"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :].strip()
                break
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json

                parsed = repair_json(cleaned, return_objects=True)
            except Exception as exc:
                raise ValueError("图片识别结果不是有效 JSON，请重试") from exc
        if not isinstance(parsed, dict):
            raise ValueError("图片识别结果必须是 JSON 对象")
        return parsed

    @staticmethod
    def _parse_date(value: Any) -> date:
        text = str(value or "").strip().replace("/", "-")
        try:
            return date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("交易日期无效") from exc

    @classmethod
    def _normalize_symbol(
        cls,
        value: Any,
        *,
        stock_name: Optional[str] = None,
    ) -> str:
        normalized = cls._canonical_valid_symbol(value)
        if normalized:
            return normalized
        resolved = cls._resolve_symbol_from_name(stock_name)
        if resolved:
            return resolved
        if str(value or "").strip():
            raise ValueError("证券代码无效，且证券名称无法在本地索引唯一匹配")
        raise ValueError("证券代码缺失，且证券名称无法在本地索引唯一匹配")

    @staticmethod
    def _canonical_valid_symbol(value: Any) -> Optional[str]:
        normalized = canonical_stock_code(normalize_stock_code(str(value or "").strip()))
        if (
            re.fullmatch(r"\d{5,6}", normalized)
            or re.fullmatch(r"HK\d{5}", normalized)
            or re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", normalized)
        ):
            return normalized
        return None

    @classmethod
    def _resolve_symbol_from_name(cls, stock_name: Optional[str]) -> Optional[str]:
        """Resolve an exact stock name only when the local index has one code."""

        target = str(stock_name or "").strip()
        if not target:
            return None

        candidates: set[str] = set()
        for code, name in STOCK_NAME_MAP.items():
            if str(name or "").strip() != target:
                continue
            normalized = cls._canonical_valid_symbol(code)
            if normalized:
                candidates.add(normalized)
        for code, name in get_stock_name_index_map().items():
            if str(name or "").strip() != target:
                continue
            normalized = cls._canonical_valid_symbol(code)
            if normalized:
                candidates.add(normalized)
        return next(iter(candidates)) if len(candidates) == 1 else None

    @staticmethod
    def _normalize_side(value: Any) -> str:
        normalized = _VALID_SIDE_MAP.get(str(value or "").strip().lower())
        if normalized:
            return normalized
        raise ValueError("买卖方向无效")

    @staticmethod
    def _positive_number(value: Any, label: str) -> float:
        number = PortfolioImageImportService._number(value, label)
        if number <= 0:
            raise ValueError(f"{label}必须大于 0")
        return number

    @staticmethod
    def _non_negative_number(value: Any, label: str) -> float:
        number = PortfolioImageImportService._number(value, label)
        if number < 0:
            raise ValueError(f"{label}不能小于 0")
        return number

    @staticmethod
    def _number(value: Any, label: str) -> float:
        try:
            return float(str(value if value is not None else 0).replace(",", "").strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}格式无效") from exc

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]
