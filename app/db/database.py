"""SQLite database layer for ProxyPool."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import keyring

from app.db.models import Proxy, ValidationResult

_KEYRING_SERVICE = "ProxyPool"


def _keyring_key(host: str, port: int, type_: str, username: str) -> str:
    return f"proxy|{host}|{port}|{type_}|{username}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_proxy(row: sqlite3.Row) -> Proxy:
    host, port, type_, username = row["host"], row["port"], row["type"], row["username"]
    password = ""
    if username:
        password = keyring.get_password(_KEYRING_SERVICE, _keyring_key(host, port, type_, username)) or ""
    return Proxy(
        id=row["id"],
        host=host,
        port=port,
        type=type_,
        username=username,
        password=password,
        region=row["region"],
        latency=row["latency"],
        status=row["status"],
        anonymity=row["anonymity"],
        supports_rdns=bool(row["supports_rdns"]),
        auth_required=bool(row["auth_required"]),
        use_count=row["use_count"],
        fail_count=row["fail_count"],
        consecutive_failures=row["consecutive_failures"],
        source=row["source"],
    )


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._write_lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._create_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _create_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS proxies (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                host                 TEXT NOT NULL,
                port                 INTEGER NOT NULL,
                type                 TEXT NOT NULL,
                username             TEXT NOT NULL DEFAULT '',
                password             TEXT NOT NULL DEFAULT '',
                region               TEXT NOT NULL DEFAULT '',
                latency              REAL NOT NULL DEFAULT -1,
                status               TEXT NOT NULL DEFAULT 'unknown',
                anonymity            TEXT NOT NULL DEFAULT '',
                supports_rdns        INTEGER NOT NULL DEFAULT 1,
                auth_required        INTEGER NOT NULL DEFAULT 0,
                use_count            INTEGER NOT NULL DEFAULT 0,
                fail_count           INTEGER NOT NULL DEFAULT 0,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                source               TEXT NOT NULL DEFAULT 'manual',
                last_checked         TIMESTAMP,
                last_success_at      TIMESTAMP,
                last_failed_at       TIMESTAMP,
                created_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_proxy_identity
                ON proxies(host, port, type, username);

            CREATE TABLE IF NOT EXISTS proxy_checks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                proxy_id   INTEGER NOT NULL REFERENCES proxies(id) ON DELETE CASCADE,
                checked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                latency    REAL,
                success    INTEGER NOT NULL,
                error      TEXT NOT NULL DEFAULT '',
                endpoint   TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS app_config (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Proxy CRUD
    # ------------------------------------------------------------------ #

    def upsert_proxy(self, p: Proxy) -> int:
        assert self._conn is not None
        now = _now_iso()
        # Store password in keyring; SQLite column stays empty.
        if p.username and p.password:
            keyring.set_password(_KEYRING_SERVICE, _keyring_key(p.host, p.port, p.type, p.username), p.password)
        with self._write_lock:
            cur = self._conn.execute(
                """
                INSERT INTO proxies(
                    host, port, type, username, password, region,
                    latency, status, anonymity, supports_rdns, auth_required,
                    use_count, fail_count, consecutive_failures, source, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(host, port, type, username) DO UPDATE SET
                    region               = CASE WHEN excluded.region     != ''       THEN excluded.region     ELSE region     END,
                    latency              = CASE WHEN excluded.latency    != -1       THEN excluded.latency    ELSE latency    END,
                    status               = CASE WHEN excluded.status     != 'unknown' THEN excluded.status    ELSE status     END,
                    anonymity            = CASE WHEN excluded.anonymity  != ''       THEN excluded.anonymity  ELSE anonymity  END,
                    supports_rdns        = excluded.supports_rdns,
                    auth_required        = excluded.auth_required,
                    use_count            = MAX(use_count, excluded.use_count),
                    fail_count           = MAX(fail_count, excluded.fail_count),
                    consecutive_failures = excluded.consecutive_failures,
                    source               = excluded.source,
                    updated_at           = excluded.updated_at
                """,
                (
                    p.host, p.port, p.type, p.username, "", p.region,
                    p.latency, p.status, p.anonymity,
                    int(p.supports_rdns), int(p.auth_required),
                    p.use_count, p.fail_count, p.consecutive_failures,
                    p.source, now,
                ),
            )
            self._conn.commit()
            # lastrowid is 0 on a DO UPDATE that touched no row; fetch real id.
            if cur.lastrowid:
                return cur.lastrowid
            row = self._conn.execute(
                "SELECT id FROM proxies WHERE host=? AND port=? AND type=? AND username=?",
                (p.host, p.port, p.type, p.username),
            ).fetchone()
            return row["id"] if row else 0

    def upsert_proxies(self, proxies: list[Proxy]) -> None:
        for p in proxies:
            self.upsert_proxy(p)

    def get_all_proxies(
        self,
        status: str | None = None,
        page: int = 1,
        page_size: int = 0,
    ) -> list[Proxy]:
        assert self._conn is not None
        if status is not None:
            sql = "SELECT * FROM proxies WHERE status=? ORDER BY id"
            params: tuple = (status,)
        else:
            sql = "SELECT * FROM proxies ORDER BY id"
            params = ()
        if page_size > 0:
            offset = (page - 1) * page_size
            sql += f" LIMIT {page_size} OFFSET {offset}"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_proxy(r) for r in rows]

    def get_proxy(self, proxy_id: int) -> Proxy | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM proxies WHERE id=?", (proxy_id,)
        ).fetchone()
        return _row_to_proxy(row) if row else None

    def count_proxies(self, status: str | None = None) -> int:
        assert self._conn is not None
        if status is not None:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM proxies WHERE status=?", (status,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM proxies").fetchone()
        return row[0] if row else 0

    def delete_proxy(self, proxy_id: int) -> None:
        assert self._conn is not None
        with self._write_lock:
            self._conn.execute("DELETE FROM proxies WHERE id=?", (proxy_id,))
            self._conn.commit()

    def delete_proxies(self, proxy_ids: list[int]) -> None:
        assert self._conn is not None
        if not proxy_ids:
            return
        placeholders = ",".join("?" * len(proxy_ids))
        with self._write_lock:
            self._conn.execute(
                f"DELETE FROM proxies WHERE id IN ({placeholders})", proxy_ids
            )
            self._conn.commit()

    def reset_proxy_status(self, proxy_ids: list[int]) -> None:
        assert self._conn is not None
        if not proxy_ids:
            return
        placeholders = ",".join("?" * len(proxy_ids))
        with self._write_lock:
            self._conn.execute(
                f"UPDATE proxies SET status='unknown', updated_at=? WHERE id IN ({placeholders})",
                [_now_iso(), *proxy_ids],
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def update_validation(self, result: ValidationResult) -> None:
        assert self._conn is not None
        now = _now_iso()
        with self._write_lock:
            if result.success:
                self._conn.execute(
                    """
                    UPDATE proxies SET
                        status               = 'valid',
                        latency              = ?,
                        anonymity            = CASE WHEN ? != '' THEN ? ELSE anonymity END,
                        region               = CASE WHEN ? != '' THEN ? ELSE region END,
                        last_success_at      = ?,
                        last_checked         = ?,
                        consecutive_failures = 0,
                        updated_at           = ?
                    WHERE id = ?
                    """,
                    (
                        result.latency,
                        result.anonymity, result.anonymity,
                        result.region, result.region,
                        now, now, now,
                        result.proxy_id,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE proxies SET
                        status               = 'invalid',
                        last_failed_at       = ?,
                        last_checked         = ?,
                        fail_count           = fail_count + 1,
                        consecutive_failures = consecutive_failures + 1,
                        updated_at           = ?
                    WHERE id = ?
                    """,
                    (now, now, now, result.proxy_id),
                )

            self._conn.execute(
                """
                INSERT INTO proxy_checks(proxy_id, checked_at, latency, success, error, endpoint)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (
                    result.proxy_id, now,
                    result.latency if result.success else None,
                    int(result.success),
                    result.error,
                    result.endpoint,
                ),
            )

            # Keep only the latest 20 records per proxy.
            self._conn.execute(
                """
                DELETE FROM proxy_checks
                WHERE proxy_id = ?
                  AND id NOT IN (
                      SELECT id FROM proxy_checks
                      WHERE proxy_id = ?
                      ORDER BY id DESC
                      LIMIT 20
                  )
                """,
                (result.proxy_id, result.proxy_id),
            )
            self._conn.commit()

    def increment_use_count(self, proxy_id: int) -> None:
        assert self._conn is not None
        with self._write_lock:
            self._conn.execute(
                "UPDATE proxies SET use_count = use_count + 1, updated_at = ? WHERE id = ?",
                (_now_iso(), proxy_id),
            )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #

    def get_config(self, key: str, default=None):
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM app_config WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def set_config(self, key: str, value) -> None:
        assert self._conn is not None
        serialized = json.dumps(value)
        with self._write_lock:
            self._conn.execute(
                """
                INSERT INTO app_config(key, value) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, serialized),
            )
            self._conn.commit()
