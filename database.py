import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg
from psycopg.rows import dict_row


FREE_WINNER_LIMIT = 5
PREMIUM_YEARS_DEFAULT = 1
_DB_INITIALIZED = False


class DatabaseNotConfigured(RuntimeError):
    pass


class QuotaExceeded(RuntimeError):
    pass


@dataclass
class User:
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]
    plan: str
    premium_expires_at: Optional[datetime]
    free_winner_requests_used: int

    @property
    def is_premium(self) -> bool:
        return (
            self.plan == "premium"
            and self.premium_expires_at is not None
            and self.premium_expires_at > datetime.now(timezone.utc)
        )

    @property
    def remaining_free_requests(self) -> int:
        return max(FREE_WINNER_LIMIT - self.free_winner_requests_used, 0)


def _load_local_env() -> None:
    env_path = Path(__file__).with_name(".env.local")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _database_url() -> str:
    _load_local_env()
    for name in ("DATABASE_URL", "POSTGRES_URL", "SUPABASE_DB_URL"):
        url = os.environ.get(name, "").strip()
        if url:
            return _clean_database_url(url)
    raise DatabaseNotConfigured("DATABASE_URL, POSTGRES_URL, or SUPABASE_DB_URL is not configured")


def _clean_database_url(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    allowed = {
        "application_name",
        "connect_timeout",
        "gssencmode",
        "keepalives",
        "keepalives_count",
        "keepalives_idle",
        "keepalives_interval",
        "sslcert",
        "sslcompression",
        "sslcrl",
        "sslkey",
        "sslmode",
        "sslrootcert",
        "target_session_attrs",
    }
    query = urlencode(
        [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key in allowed]
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _connect():
    return psycopg.connect(_database_url(), autocommit=True, row_factory=dict_row)


def init_db() -> None:
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                plan TEXT NOT NULL DEFAULT 'free'
                    CHECK (plan IN ('free', 'premium')),
                premium_expires_at TIMESTAMPTZ,
                free_winner_requests_used INTEGER NOT NULL DEFAULT 0
                    CHECK (free_winner_requests_used >= 0),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS winner_requests (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL REFERENCES users(telegram_id),
                consultation_reference TEXT,
                org_acronyme TEXT NOT NULL DEFAULT '',
                consultation_url TEXT NOT NULL,
                consultation_object TEXT,
                success BOOLEAN NOT NULL DEFAULT FALSE,
                quota_consumed BOOLEAN NOT NULL DEFAULT FALSE,
                lot_count INTEGER NOT NULL DEFAULT 0,
                estimated_price NUMERIC,
                average_offer_price NUMERIC,
                reference_price NUMERIC,
                winner_name TEXT,
                winner_price NUMERIC,
                error_message TEXT,
                result_snapshot JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_actions (
                id BIGSERIAL PRIMARY KEY,
                admin_telegram_id BIGINT,
                target_telegram_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                payload JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    _DB_INITIALIZED = True


def upsert_telegram_user(tg_user: dict) -> User:
    init_db()
    telegram_id = int(tg_user["id"])
    username = tg_user.get("username")
    first_name = tg_user.get("first_name")
    with _connect() as conn:
        row = conn.execute(
            """
            INSERT INTO users (telegram_id, username, first_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (telegram_id) DO UPDATE SET
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                updated_at = NOW()
            RETURNING telegram_id, username, first_name, plan,
                premium_expires_at, free_winner_requests_used
            """,
            (telegram_id, username, first_name),
        ).fetchone()
    return _row_to_user(row)


def get_user(telegram_id: int) -> Optional[User]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT telegram_id, username, first_name, plan,
                premium_expires_at, free_winner_requests_used
            FROM users
            WHERE telegram_id = %s
            """,
            (telegram_id,),
        ).fetchone()
    return _row_to_user(row) if row else None


def count_users() -> int:
    init_db()
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()
    return int(row["total"])


def list_telegram_user_ids() -> list[int]:
    init_db()
    with _connect() as conn:
        rows = conn.execute("SELECT telegram_id FROM users ORDER BY created_at DESC").fetchall()
    return [int(row["telegram_id"]) for row in rows]


def can_create_winner_request(user: User) -> bool:
    return user.is_premium or user.free_winner_requests_used < FREE_WINNER_LIMIT


def record_winner_request(
    telegram_id: int,
    *,
    consultation_reference: Optional[str],
    org_acronyme: str,
    consultation_url: str,
    consultation_object: Optional[str],
    success: bool,
    quota_consumed: bool,
    lot_count: int,
    estimated_price: Optional[float],
    average_offer_price: Optional[float],
    reference_price: Optional[float],
    winner_name: Optional[str],
    winner_price: Optional[float],
    error_message: Optional[str],
    result_snapshot: Optional[dict[str, Any]],
) -> User:
    init_db()
    with _connect() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                UPDATE users
                SET free_winner_requests_used = CASE
                        WHEN %s
                         AND NOT (
                            plan = 'premium'
                            AND premium_expires_at IS NOT NULL
                            AND premium_expires_at > NOW()
                         )
                        THEN free_winner_requests_used + 1
                        ELSE free_winner_requests_used
                    END,
                    updated_at = NOW()
                WHERE telegram_id = %s
                  AND (
                    NOT %s
                    OR (
                        plan = 'premium'
                        AND premium_expires_at IS NOT NULL
                        AND premium_expires_at > NOW()
                    )
                    OR free_winner_requests_used < %s
                  )
                RETURNING telegram_id, username, first_name, plan,
                    premium_expires_at, free_winner_requests_used
                """,
                (quota_consumed, telegram_id, quota_consumed, FREE_WINNER_LIMIT),
            ).fetchone()
            if row is None:
                raise QuotaExceeded("Free winner request limit exceeded")

            conn.execute(
                """
                INSERT INTO winner_requests (
                    telegram_id, consultation_reference, org_acronyme, consultation_url,
                    consultation_object, success, quota_consumed, lot_count,
                    estimated_price, average_offer_price, reference_price, winner_name,
                    winner_price, error_message, result_snapshot
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    telegram_id,
                    consultation_reference,
                    org_acronyme or "",
                    consultation_url,
                    consultation_object,
                    success,
                    quota_consumed,
                    lot_count,
                    estimated_price,
                    average_offer_price,
                    reference_price,
                    winner_name,
                    winner_price,
                    error_message[:800] if error_message else None,
                    json.dumps(result_snapshot or {}),
                ),
            )
    return _row_to_user(row)


def grant_premium(telegram_id: int, years: int = PREMIUM_YEARS_DEFAULT, admin_telegram_id: Optional[int] = None) -> User:
    init_db()
    years = max(1, years)
    with _connect() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                INSERT INTO users (telegram_id, plan, premium_expires_at)
                VALUES (%s, 'premium', NOW() + (%s || ' years')::interval)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    plan = 'premium',
                    premium_expires_at = CASE
                        WHEN users.premium_expires_at IS NOT NULL
                         AND users.premium_expires_at > NOW()
                        THEN users.premium_expires_at + (%s || ' years')::interval
                        ELSE NOW() + (%s || ' years')::interval
                    END,
                    updated_at = NOW()
                RETURNING telegram_id, username, first_name, plan,
                    premium_expires_at, free_winner_requests_used
                """,
                (telegram_id, years, years, years),
            ).fetchone()
            _record_admin_action(
                conn,
                admin_telegram_id=admin_telegram_id,
                target_telegram_id=telegram_id,
                action="grant_premium",
                payload={"years": years},
            )
    return _row_to_user(row)


def set_free(telegram_id: int, admin_telegram_id: Optional[int] = None) -> User:
    init_db()
    with _connect() as conn:
        with conn.transaction():
            row = conn.execute(
                """
                INSERT INTO users (telegram_id, plan)
                VALUES (%s, 'free')
                ON CONFLICT (telegram_id) DO UPDATE SET
                    plan = 'free',
                    premium_expires_at = NULL,
                    updated_at = NOW()
                RETURNING telegram_id, username, first_name, plan,
                    premium_expires_at, free_winner_requests_used
                """,
                (telegram_id,),
            ).fetchone()
            _record_admin_action(
                conn,
                admin_telegram_id=admin_telegram_id,
                target_telegram_id=telegram_id,
                action="set_free",
                payload={},
            )
    return _row_to_user(row)


def _record_admin_action(conn, *, admin_telegram_id: Optional[int], target_telegram_id: int, action: str, payload: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO admin_actions (admin_telegram_id, target_telegram_id, action, payload)
        VALUES (%s, %s, %s, %s::jsonb)
        """,
        (admin_telegram_id, target_telegram_id, action, json.dumps(payload)),
    )


def _row_to_user(row) -> User:
    return User(
        telegram_id=row["telegram_id"],
        username=row["username"],
        first_name=row["first_name"],
        plan=row["plan"],
        premium_expires_at=row["premium_expires_at"],
        free_winner_requests_used=row["free_winner_requests_used"],
    )
