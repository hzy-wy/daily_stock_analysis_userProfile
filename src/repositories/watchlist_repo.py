"""Repository for user-owned product watchlists."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import delete, func, select

from src.services.identity_service import current_user_scope
from src.storage import DatabaseManager, UserWatchlistRecord


class UserWatchlistRepository:
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager.get_instance()

    @staticmethod
    def _require_user_id() -> str:
        user_id = current_user_scope()
        if not user_id:
            raise RuntimeError("Authenticated user scope is required")
        return user_id

    def list_codes(self) -> List[str]:
        user_id = self._require_user_id()
        with self.db.get_session() as session:
            return list(
                session.scalars(
                    select(UserWatchlistRecord.display_code)
                    .where(UserWatchlistRecord.user_id == user_id)
                    .order_by(UserWatchlistRecord.sort_order, UserWatchlistRecord.id)
                ).all()
            )

    def add(self, *, normalized_code: str, display_code: str) -> None:
        user_id = self._require_user_id()
        with self.db.get_session() as session:
            existing = session.scalar(
                select(UserWatchlistRecord.id).where(
                    UserWatchlistRecord.user_id == user_id,
                    UserWatchlistRecord.stock_code == normalized_code,
                )
            )
            if existing:
                return
            next_order = int(
                session.scalar(
                    select(func.coalesce(func.max(UserWatchlistRecord.sort_order), -1)).where(
                        UserWatchlistRecord.user_id == user_id
                    )
                )
                or 0
            ) + 1
            session.add(
                UserWatchlistRecord(
                    user_id=user_id,
                    stock_code=normalized_code,
                    display_code=display_code,
                    sort_order=next_order,
                )
            )
            session.commit()

    def remove(self, *, normalized_code: str) -> None:
        user_id = self._require_user_id()
        with self.db.get_session() as session:
            session.execute(
                delete(UserWatchlistRecord).where(
                    UserWatchlistRecord.user_id == user_id,
                    UserWatchlistRecord.stock_code == normalized_code,
                )
            )
            session.commit()
