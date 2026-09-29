# """
# Хранилище: сессии пользователей, история оценок и запуски анализа.
#
# Витрина рейтинга в базе не лежит — она пересобирается из выгрузки в память.
# В базу попадает только то, что должно пережить перезапуск сервиса.
# """
# from __future__ import annotations
#
# import json
# from contextlib import contextmanager
# from datetime import datetime, timezone
#
# from sqlalchemy import (JSON, DateTime, Float, ForeignKey, Integer, String, Text,
#                         create_engine, select)
# from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
#
# from backend.config import DATABASE_URL
#
# engine = create_engine(
#     DATABASE_URL,
#     echo=False,
#     future=True,
#     connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
# )
# SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
#
#
# class Base(DeclarativeBase):
#     pass
#
#
# def utcnow() -> datetime:
#     return datetime.now(timezone.utc)
#
#
# class User(Base):
#     __tablename__ = "users"
#
#     id: Mapped[str] = mapped_column(String(64), primary_key=True)
#     provider: Mapped[str] = mapped_column(String(32), default="yandex_id")
#     provider_user_id: Mapped[str] = mapped_column(String(128), index=True)
#     login: Mapped[str] = mapped_column(String(128))
#     display_name: Mapped[str] = mapped_column(String(255))
#     email: Mapped[str | None] = mapped_column(String(255), nullable=True)
#     avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
#
#     def to_dict(self) -> dict:
#         return {
#             "id": self.id, "login": self.login, "display_name": self.display_name,
#             "email": self.email, "avatar_url": self.avatar_url, "provider": self.provider,
#         }
#
#
# class UserSession(Base):
#     """Сессия. Токен платформы хранится ровно столько, сколько живёт сессия."""
#     __tablename__ = "sessions"
#
#     token: Mapped[str] = mapped_column(String(128), primary_key=True)
#     user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
#     created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
#     expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
#     yandex_token: Mapped[str | None] = mapped_column(Text, nullable=True)
#     sourcecraft_token: Mapped[str | None] = mapped_column(Text, nullable=True)
#
#
# class ScoreHistory(Base):
#     """Точка истории Repo Health Score: пишется при каждом пересчёте."""
#     __tablename__ = "score_history"
#
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
#     full_path: Mapped[str] = mapped_column(String(512), index=True)
#     analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
#     total: Mapped[float | None] = mapped_column(Float, nullable=True)
#     categories: Mapped[dict] = mapped_column(JSON, default=dict)
#     formula_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
#
#
# class AnalysisRun(Base):
#     """Запуск анализа по требованию из личного кабинета."""
#     __tablename__ = "analyses"
#
#     id: Mapped[str] = mapped_column(String(64), primary_key=True)
#     user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
#     repo_full_path: Mapped[str] = mapped_column(String(512), index=True)
#     status: Mapped[str] = mapped_column(String(32), default="queued")
#     progress: Mapped[int] = mapped_column(Integer, default=0)
#     stages: Mapped[list] = mapped_column(JSON, default=list)
#     started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
#     finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
#     error: Mapped[str | None] = mapped_column(Text, nullable=True)
#     report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
#
#     def to_dict(self) -> dict:
#         return {
#             "id": self.id,
#             "repo_full_path": self.repo_full_path,
#             "status": self.status,
#             "progress": self.progress,
#             "stages": self.stages or [],
#             "started_at": _iso(self.started_at),
#             "finished_at": _iso(self.finished_at),
#             "error": self.error,
#             "report": self.report,
#         }
#
#
# def _iso(value: datetime | None) -> str | None:
#     if value is None:
#         return None
#     if value.tzinfo is None:
#         value = value.replace(tzinfo=timezone.utc)
#     return value.isoformat()
#
#
# def init_db() -> None:
#     Base.metadata.create_all(engine)
#
#
# @contextmanager
# def session_scope() -> Session:
#     session = SessionLocal()
#     try:
#         yield session
#         session.commit()
#     except Exception:
#         session.rollback()
#         raise
#     finally:
#         session.close()
#
#
# def history_for(full_path: str, limit: int = 60) -> list[dict]:
#     """История оценок репозитория, от старых к новым."""
#     with session_scope() as session:
#         rows = session.scalars(
#             select(ScoreHistory)
#             .where(ScoreHistory.full_path == full_path)
#             .order_by(ScoreHistory.analyzed_at.desc())
#             .limit(limit)
#         ).all()
#     return [{"analyzed_at": _iso(r.analyzed_at), "total": r.total} for r in reversed(rows)]
#
#
# def save_history(points: list[dict]) -> int:
#     """Массовая запись точек истории после пересчёта."""
#     if not points:
#         return 0
#     with session_scope() as session:
#         session.bulk_insert_mappings(ScoreHistory, points)
#     return len(points)
#
#
# def json_default(value):
#     """Датафреймовые типы numpy не сериализуются JSON-ом напрямую."""
#     try:
#         return value.item()
#     except AttributeError:
#         return json.JSONEncoder().default(value)



"""
Хранилище: сессии пользователей, история оценок и запуски анализа.

Витрина рейтинга в базе не лежит — она пересобирается из выгрузки в память.
В базу попадает только то, что должно пережить перезапуск сервиса.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (JSON, DateTime, Float, ForeignKey, Integer, String, Text,
                        create_engine, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from backend.config import DATABASE_URL

# Надежное извлечение пути к SQLite из DATABASE_URL и создание директории
if DATABASE_URL.startswith("sqlite"):
    db_file_path = DATABASE_URL.replace("sqlite:////", "/").replace("sqlite:///", "")
    if db_file_path and db_file_path != ":memory:":
        db_path = Path(db_file_path)
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            db_path = Path("repo_health.db")
            db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="yandex_id")
    provider_user_id: Mapped[str] = mapped_column(String(128), index=True)
    login: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "login": self.login, "display_name": self.display_name,
            "email": self.email, "avatar_url": self.avatar_url, "provider": self.provider,
        }


class UserSession(Base):
    """Сессия. Токен платформы хранится ровно столько, сколько живёт сессия."""
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    yandex_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    sourcecraft_token: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScoreHistory(Base):
    """Точка истории Repo Health Score: пишется при каждом пересчёте."""
    __tablename__ = "score_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_path: Mapped[str] = mapped_column(String(512), index=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    categories: Mapped[dict] = mapped_column(JSON, default=dict)
    formula_version: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AnalysisRun(Base):
    """Запуск анализа по требованию из личного кабинета."""
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    repo_full_path: Mapped[str] = mapped_column(String(512), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stages: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "repo_full_path": self.repo_full_path,
            "status": self.status,
            "progress": self.progress,
            "stages": self.stages or [],
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "error": self.error,
            "report": self.report,
        }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def init_db() -> None:
    Base.metadata.create_all(engine)


@contextmanager
def session_scope() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def history_for(full_path: str, limit: int = 60) -> list[dict]:
    """История оценок репозитория, от старых к новым."""
    with session_scope() as session:
        rows = session.scalars(
            select(ScoreHistory)
            .where(ScoreHistory.full_path == full_path)
            .order_by(ScoreHistory.analyzed_at.desc())
            .limit(limit)
        ).all()
    return [{"analyzed_at": _iso(r.analyzed_at), "total": r.total} for r in reversed(rows)]


def save_history(points: list[dict]) -> int:
    """Массовая запись точек истории после пересчёта."""
    if not points:
        return 0
    with session_scope() as session:
        session.bulk_insert_mappings(ScoreHistory, points)
    return len(points)


def json_default(value):
    """Датафреймовые типы numpy не сериализуются JSON-ом напрямую."""
    try:
        return value.item()
    except AttributeError:
        return json.JSONEncoder().default(value)