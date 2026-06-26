# 代理池桌面应用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个 Python + PyQt6 桌面代理池管理工具，内置本地 SOCKS5 服务器、六种代理轮换模式、多源爬取和代理验证功能。

**Architecture:** 单进程多 QThread 架构：Qt 主线程负责 UI，SocksServerThread / ValidatorThread / CrawlerThread 各持独立 asyncio event loop，通过 Qt Signal 与主线程通信。SQLite（WAL 模式）单写线程 + Repository API 统一访问。

**Tech Stack:** Python 3.11+, PyQt6 >=6.6, python-socks >=2.4, aiohttp >=3.9, aiohttp-socks >=0.8, keyring >=25, beautifulsoup4 >=4.12, lxml >=5.0, platformdirs >=4.0

## Global Constraints

- Python 3.11+ 语法（`X | Y` 联合类型，`match` 语句可用）
- 所有后台线程通过 Qt Signal 回 UI，绝不直接操作 QWidget
- SQLite 写操作串行化到单一 DB 线程队列；读操作通过 Repository API
- 代理密码和 API Key 存系统 keyring，不写 SQLite 明文
- 日志和导出永不打印含密码的完整代理 URL
- 数据库路径：`platformdirs.user_data_dir("ProxyPool") / "proxies.db"`
- 测试命令：`pytest tests/ -v`

---

## File Map

```
ProxyPool/
├── main.py
├── requirements.txt
├── requirements-dev.txt
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   └── database.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── worker_thread.py
│   │   ├── rotator.py
│   │   ├── socks_server.py
│   │   ├── validator.py
│   │   └── crawlers/
│   │       ├── __init__.py
│   │       ├── base.py
│   │       ├── fofa.py
│   │       ├── quake.py
│   │       ├── hunter.py
│   │       └── free_sites.py
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py
│       ├── proxy_table.py
│       └── dialogs/
│           ├── __init__.py
│           ├── add_proxy.py
│           ├── batch_add.py
│           ├── auto_crawl.py
│           ├── batch_manage.py
│           └── export_proxy.py
└── tests/
    ├── conftest.py
    ├── test_models.py
    ├── test_database.py
    ├── test_rotator.py
    ├── test_socks_server.py
    ├── test_validator.py
    └── test_crawlers.py
```

---

### Task 1: 项目骨架与依赖

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `main.py`
- Create: `app/__init__.py`、`app/db/__init__.py`、`app/core/__init__.py`、`app/ui/__init__.py`、`app/core/crawlers/__init__.py`、`app/ui/dialogs/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Produces: `main()` 入口函数，所有包 `__init__.py`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p app/db app/core/crawlers app/ui/dialogs tests
touch app/__init__.py app/db/__init__.py app/core/__init__.py
touch app/ui/__init__.py app/core/crawlers/__init__.py app/ui/dialogs/__init__.py
```

- [ ] **Step 2: 写 requirements.txt**

```
PyQt6>=6.6.0
python-socks>=2.4.0
aiohttp>=3.9.0
aiohttp-socks>=0.8.0
keyring>=25.0.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
platformdirs>=4.0.0
```

- [ ] **Step 3: 写 requirements-dev.txt**

```
pytest>=8.0.0
pytest-qt>=4.4.0
pytest-asyncio>=0.23.0
pytest-mock>=3.12.0
```

- [ ] **Step 4: 安装依赖**

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

Expected: 无报错，所有包安装成功。

- [ ] **Step 5: 写 main.py**

```python
import sys
from PyQt6.QtWidgets import QApplication


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ProxyPool")
    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: 写 tests/conftest.py**

```python
import pytest
import asyncio


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

- [ ] **Step 7: 验证 pytest 可运行**

```bash
pytest tests/ -v --collect-only
```

Expected: `no tests ran`，无 ImportError。

- [ ] **Step 8: Commit**

```bash
git init
git add .
git commit -m "chore: project scaffold and dependencies"
```

---

### Task 2: 数据模型

**Files:**
- Create: `app/db/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `Proxy`, `ValidationResult`, `ProxyEndpoint`, `ProxyCandidate`, `CrawlerResult` dataclasses

- [ ] **Step 1: 写 tests/test_models.py**

```python
from app.db.models import Proxy, ProxyEndpoint, ValidationResult, ProxyCandidate, CrawlerResult


def test_proxy_url_no_auth():
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    assert p.url == "socks5://1.2.3.4:1080"


def test_proxy_url_with_auth():
    p = Proxy(host="1.2.3.4", port=1080, type="socks5", username="u", password="p")
    assert p.url == "socks5://u:p@1.2.3.4:1080"


def test_proxy_redacted_url():
    p = Proxy(host="1.2.3.4", port=1080, type="socks5", username="u", password="secret")
    assert p.redacted_url == "socks5://u:***@1.2.3.4:1080"
    assert "secret" not in p.redacted_url


def test_proxy_endpoint_immutable():
    ep = ProxyEndpoint(proxy_id=1, url="socks5://1.2.3.4:1080", supports_rdns=True)
    assert ep.proxy_id == 1


def test_validation_result_defaults():
    r = ValidationResult(proxy_id=1, success=False, latency=-1, anonymity="", region="")
    assert r.error == ""


def test_crawler_result_not_exhausted():
    r = CrawlerResult(source="fofa", candidates=[], errors=[])
    assert r.quota_exhausted is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_models.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models'`

- [ ] **Step 3: 写 app/db/models.py**

```python
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Proxy:
    id: int = 0
    host: str = ""
    port: int = 0
    type: str = "socks5"
    username: str = ""
    password: str = ""
    region: str = ""
    latency: float = -1
    status: str = "unknown"
    anonymity: str = ""
    supports_rdns: bool = True
    auth_required: bool = False
    use_count: int = 0
    fail_count: int = 0
    consecutive_failures: int = 0
    source: str = "manual"

    @property
    def url(self) -> str:
        if self.username:
            return f"{self.type}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.type}://{self.host}:{self.port}"

    @property
    def redacted_url(self) -> str:
        if self.username:
            return f"{self.type}://{self.username}:***@{self.host}:{self.port}"
        return f"{self.type}://{self.host}:{self.port}"


@dataclass(frozen=True)
class ProxyEndpoint:
    proxy_id: int
    url: str
    supports_rdns: bool


@dataclass
class ValidationResult:
    proxy_id: int
    success: bool
    latency: float
    anonymity: str
    region: str
    error: str = ""
    endpoint: str = ""


@dataclass
class ProxyCandidate:
    host: str
    port: int
    type: str
    source: str
    username: str = ""
    password: str = ""


@dataclass
class CrawlerResult:
    source: str
    candidates: list[ProxyCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    quota_exhausted: bool = False
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_models.py -v
```

Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/db/models.py tests/test_models.py
git commit -m "feat: data models (Proxy, ValidationResult, ProxyEndpoint, etc.)"
```

---

### Task 3: 数据库层

**Files:**
- Create: `app/db/database.py`
- Create: `tests/test_database.py`

**Interfaces:**
- Consumes: `Proxy`, `ValidationResult` from `app.db.models`
- Produces: `Database` 类，方法：`initialize()`, `upsert_proxy(p)`, `upsert_proxies(proxies)`, `get_all_proxies()`, `get_proxy(id)`, `delete_proxy(id)`, `update_validation(result)`, `add_check_history(proxy_id, result)`, `get_config(key, default)`, `set_config(key, value)`

- [ ] **Step 1: 写 tests/test_database.py**

```python
import pytest
import tempfile
from pathlib import Path
from app.db.database import Database
from app.db.models import Proxy, ValidationResult


@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialize()
    yield d
    d.close()


def test_upsert_and_get_proxy(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5", source="manual")
    db.upsert_proxy(p)
    rows = db.get_all_proxies()
    assert len(rows) == 1
    assert rows[0].host == "1.2.3.4"
    assert rows[0].id > 0


def test_upsert_deduplicates(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    db.upsert_proxy(p)
    assert len(db.get_all_proxies()) == 1


def test_upsert_preserves_use_count(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    stored = db.get_all_proxies()[0]
    stored.use_count = 5
    db.upsert_proxy(stored)
    assert db.get_all_proxies()[0].use_count == 5


def test_delete_proxy(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    pid = db.get_all_proxies()[0].id
    db.delete_proxy(pid)
    assert db.get_all_proxies() == []


def test_update_validation(db):
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    db.upsert_proxy(p)
    pid = db.get_all_proxies()[0].id
    result = ValidationResult(proxy_id=pid, success=True, latency=120.5,
                              anonymity="high", region="CN-广东")
    db.update_validation(result)
    updated = db.get_proxy(pid)
    assert updated.status == "valid"
    assert updated.latency == 120.5
    assert updated.region == "CN-广东"


def test_config_get_set(db):
    db.set_config("listen_port", 51024)
    assert db.get_config("listen_port", 0) == 51024


def test_config_default(db):
    assert db.get_config("missing_key", "default") == "default"
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_database.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 写 app/db/database.py**

```python
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from app.db.models import Proxy, ValidationResult


_CREATE_PROXIES = """
CREATE TABLE IF NOT EXISTS proxies (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    host                TEXT NOT NULL,
    port                INTEGER NOT NULL,
    type                TEXT NOT NULL,
    username            TEXT NOT NULL DEFAULT '',
    password            TEXT NOT NULL DEFAULT '',
    region              TEXT NOT NULL DEFAULT '',
    latency             REAL NOT NULL DEFAULT -1,
    status              TEXT NOT NULL DEFAULT 'unknown',
    anonymity           TEXT NOT NULL DEFAULT '',
    supports_rdns       INTEGER NOT NULL DEFAULT 1,
    auth_required       INTEGER NOT NULL DEFAULT 0,
    use_count           INTEGER NOT NULL DEFAULT 0,
    fail_count          INTEGER NOT NULL DEFAULT 0,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    source              TEXT NOT NULL DEFAULT 'manual',
    last_checked        TIMESTAMP,
    last_success_at     TIMESTAMP,
    last_failed_at      TIMESTAMP,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

_CREATE_INDEXES = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_proxy_identity
    ON proxies(host, port, type, username);
CREATE INDEX IF NOT EXISTS idx_proxy_status ON proxies(status);
CREATE INDEX IF NOT EXISTS idx_proxy_latency ON proxies(latency);
CREATE INDEX IF NOT EXISTS idx_proxy_last_checked ON proxies(last_checked);
"""

_CREATE_CHECKS = """
CREATE TABLE IF NOT EXISTS proxy_checks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    proxy_id    INTEGER NOT NULL REFERENCES proxies(id) ON DELETE CASCADE,
    checked_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    latency     REAL,
    success     INTEGER NOT NULL,
    error       TEXT NOT NULL DEFAULT '',
    endpoint    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_checks_proxy ON proxy_checks(proxy_id, checked_at);
"""

_CREATE_CONFIG = """
CREATE TABLE IF NOT EXISTS app_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def _row_to_proxy(row: sqlite3.Row) -> Proxy:
    return Proxy(
        id=row["id"], host=row["host"], port=row["port"], type=row["type"],
        username=row["username"], password=row["password"], region=row["region"],
        latency=row["latency"], status=row["status"], anonymity=row["anonymity"],
        supports_rdns=bool(row["supports_rdns"]),
        auth_required=bool(row["auth_required"]),
        use_count=row["use_count"], fail_count=row["fail_count"],
        consecutive_failures=row["consecutive_failures"], source=row["source"],
    )


class Database:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def initialize(self):
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(
            _CREATE_PROXIES + _CREATE_INDEXES + _CREATE_CHECKS + _CREATE_CONFIG
        )
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Proxy CRUD ──────────────────────────────────────────────────────────

    def upsert_proxy(self, p: Proxy) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO proxies(host, port, type, username, password, region,
                    latency, status, anonymity, supports_rdns, auth_required,
                    use_count, fail_count, consecutive_failures, source, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(host, port, type, username) DO UPDATE SET
                    password=excluded.password,
                    region=CASE WHEN excluded.region!='' THEN excluded.region ELSE region END,
                    latency=CASE WHEN excluded.latency!=-1 THEN excluded.latency ELSE latency END,
                    status=CASE WHEN excluded.status!='unknown' THEN excluded.status ELSE status END,
                    anonymity=CASE WHEN excluded.anonymity!='' THEN excluded.anonymity ELSE anonymity END,
                    supports_rdns=excluded.supports_rdns,
                    auth_required=excluded.auth_required,
                    use_count=MAX(use_count, excluded.use_count),
                    fail_count=MAX(fail_count, excluded.fail_count),
                    consecutive_failures=excluded.consecutive_failures,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (p.host, p.port, p.type, p.username, "", p.region,
                 p.latency, p.status, p.anonymity,
                 int(p.supports_rdns), int(p.auth_required),
                 p.use_count, p.fail_count, p.consecutive_failures,
                 p.source, now),
            )
            self._conn.commit()
            return cur.lastrowid or self._get_id(p.host, p.port, p.type, p.username)

    def upsert_proxies(self, proxies: list[Proxy]):
        for p in proxies:
            self.upsert_proxy(p)

    def _get_id(self, host, port, type_, username) -> int:
        row = self._conn.execute(
            "SELECT id FROM proxies WHERE host=? AND port=? AND type=? AND username=?",
            (host, port, type_, username)
        ).fetchone()
        return row["id"] if row else 0

    def get_all_proxies(self, status: str | None = None,
                        page: int = 1, page_size: int = 0) -> list[Proxy]:
        query = "SELECT * FROM proxies"
        params: list = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY id"
        if page_size > 0:
            query += " LIMIT ? OFFSET ?"
            params += [page_size, (page - 1) * page_size]
        rows = self._conn.execute(query, params).fetchall()
        return [_row_to_proxy(r) for r in rows]

    def get_proxy(self, proxy_id: int) -> Proxy | None:
        row = self._conn.execute(
            "SELECT * FROM proxies WHERE id=?", (proxy_id,)
        ).fetchone()
        return _row_to_proxy(row) if row else None

    def count_proxies(self, status: str | None = None) -> int:
        if status:
            return self._conn.execute(
                "SELECT COUNT(*) FROM proxies WHERE status=?", (status,)
            ).fetchone()[0]
        return self._conn.execute("SELECT COUNT(*) FROM proxies").fetchone()[0]

    def delete_proxy(self, proxy_id: int):
        with self._lock:
            self._conn.execute("DELETE FROM proxies WHERE id=?", (proxy_id,))
            self._conn.commit()

    def delete_proxies(self, proxy_ids: list[int]):
        with self._lock:
            self._conn.executemany(
                "DELETE FROM proxies WHERE id=?", [(i,) for i in proxy_ids]
            )
            self._conn.commit()

    # ── Validation ───────────────────────────────────────────────────────────

    def update_validation(self, result: ValidationResult):
        now = datetime.now(timezone.utc).isoformat()
        status = "valid" if result.success else "invalid"
        with self._lock:
            if result.success:
                self._conn.execute(
                    """UPDATE proxies SET status=?, latency=?, anonymity=?,
                       region=CASE WHEN ?!='' THEN ? ELSE region END,
                       last_checked=?, last_success_at=?,
                       consecutive_failures=0, updated_at=?
                       WHERE id=?""",
                    (status, result.latency, result.anonymity,
                     result.region, result.region, now, now, now, result.proxy_id),
                )
            else:
                self._conn.execute(
                    """UPDATE proxies SET status=?, last_checked=?, last_failed_at=?,
                       fail_count=fail_count+1,
                       consecutive_failures=consecutive_failures+1,
                       updated_at=? WHERE id=?""",
                    (status, now, now, now, result.proxy_id),
                )
            self._conn.execute(
                """INSERT INTO proxy_checks(proxy_id, latency, success, error, endpoint)
                   VALUES(?,?,?,?,?)""",
                (result.proxy_id, result.latency, int(result.success),
                 result.error, result.endpoint),
            )
            self._conn.execute(
                """DELETE FROM proxy_checks WHERE proxy_id=? AND id NOT IN (
                   SELECT id FROM proxy_checks WHERE proxy_id=?
                   ORDER BY checked_at DESC LIMIT 20)""",
                (result.proxy_id, result.proxy_id),
            )
            self._conn.commit()

    def increment_use_count(self, proxy_id: int):
        with self._lock:
            self._conn.execute(
                "UPDATE proxies SET use_count=use_count+1 WHERE id=?", (proxy_id,)
            )
            self._conn.commit()

    # ── Config ────────────────────────────────────────────────────────────────

    def get_config(self, key: str, default=None):
        row = self._conn.execute(
            "SELECT value FROM app_config WHERE key=?", (key,)
        ).fetchone()
        if row is None:
            return default
        return json.loads(row["value"])

    def set_config(self, key: str, value):
        with self._lock:
            self._conn.execute(
                "INSERT INTO app_config(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
            self._conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_database.py -v
```

Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add app/db/database.py tests/test_database.py
git commit -m "feat: SQLite database layer with Repository API"
```

---

### Task 4: 配置管理

**Files:**
- Create: `app/config.py`

**Interfaces:**
- Consumes: `Database` from `app.db.database`
- Produces: `Config` 类，属性：`listen_port`, `rotation_mode`, `rotation_params`, `validator_concurrency`, `validator_timeout`, `validator_endpoint`, `validator_endpoint_backup`, `page_size`, `export_redact_password`；方法：`save()`

- [ ] **Step 1: 写 app/config.py**

```python
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from pathlib import Path
import platformdirs
from app.db.database import Database

DATA_DIR = Path(platformdirs.user_data_dir("ProxyPool", appauthor=False))
DB_PATH = DATA_DIR / "proxies.db"

_DEFAULTS: dict = {
    "listen_port": 51024,
    "rotation_mode": "round_robin",
    "rotation_params": {},
    "validator_concurrency": 100,
    "validator_timeout": 10,
    "validator_endpoint": "https://httpbin.org/ip",
    "validator_endpoint_backup": "https://ip-api.com/json",
    "geo_cache_ttl": 86400,
    "page_size": 10,
    "export_redact_password": True,
}


@dataclass
class Config:
    _db: Database = field(repr=False)

    listen_port: int = 51024
    rotation_mode: str = "round_robin"
    rotation_params: dict = field(default_factory=dict)
    validator_concurrency: int = 100
    validator_timeout: int = 10
    validator_endpoint: str = "https://httpbin.org/ip"
    validator_endpoint_backup: str = "https://ip-api.com/json"
    geo_cache_ttl: int = 86400
    page_size: int = 10
    export_redact_password: bool = True

    @classmethod
    def load(cls, db: Database) -> "Config":
        c = cls(_db=db)
        for key, default in _DEFAULTS.items():
            setattr(c, key, db.get_config(key, default))
        return c

    def save(self):
        for key in _DEFAULTS:
            self._db.set_config(key, getattr(self, key))
```

- [ ] **Step 2: 验证可导入**

```bash
python -c "from app.config import Config, DB_PATH; print(DB_PATH)"
```

Expected: 打印出用户数据目录路径，无报错。

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "feat: config persistence with platformdirs"
```

---

### Task 5: AsyncWorkerThread 基类

**Files:**
- Create: `app/core/worker_thread.py`

**Interfaces:**
- Produces: `AsyncWorkerThread(QThread)` 基类，方法：`run()`, `stop()`, `submit(coro)`；子类需实现 `async main(self)`

- [ ] **Step 1: 写 app/core/worker_thread.py**

```python
from __future__ import annotations
import asyncio
from PyQt6.QtCore import QThread, pyqtSignal


class AsyncWorkerThread(QThread):
    error_occurred = pyqtSignal(str)

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._main_task = self.loop.create_task(self.main())
        try:
            self.loop.run_until_complete(self._main_task)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            pending = asyncio.all_tasks(self.loop)
            for t in pending:
                t.cancel()
            self.loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def stop(self):
        if hasattr(self, "loop") and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self._main_task.cancel)

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def main(self):
        raise NotImplementedError
```

- [ ] **Step 2: 验证可导入**

```bash
python -c "from app.core.worker_thread import AsyncWorkerThread; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/core/worker_thread.py
git commit -m "feat: AsyncWorkerThread base class"
```

---

### Task 6: 代理轮换器（Rotator）

**Files:**
- Create: `app/core/rotator.py`
- Create: `tests/test_rotator.py`

**Interfaces:**
- Consumes: `Proxy`, `ProxyEndpoint` from `app.db.models`
- Produces: `RotationMode` enum；`ProxyRotator` 类，方法：`async on_request_start() -> ProxyEndpoint | None`, `async on_request_done(proxy_id, success)`, `async on_response_body(proxy_id, body)`, `async force_switch()`, `set_mode(mode, **params)`, `load_proxies(proxies)`, `get_current() -> Proxy | None`

- [ ] **Step 1: 写 tests/test_rotator.py**

```python
import asyncio
import pytest
from app.core.rotator import ProxyRotator, RotationMode
from app.db.models import Proxy


def make_proxy(id_, latency=100.0, status="valid"):
    return Proxy(id=id_, host=f"1.2.3.{id_}", port=1080, type="socks5",
                 status=status, latency=latency)


@pytest.fixture
def rotator():
    r = ProxyRotator()
    r.load_proxies([make_proxy(1), make_proxy(2), make_proxy(3)])
    return r


@pytest.mark.asyncio
async def test_round_robin_cycles(rotator):
    rotator.set_mode(RotationMode.ROUND_ROBIN)
    ids = [ep.proxy_id for ep in
           [await rotator.on_request_start() for _ in range(4)]]
    assert ids[:3] == [1, 2, 3]
    assert ids[3] == 1  # 循环


@pytest.mark.asyncio
async def test_fixed_selects_lowest_latency(rotator):
    rotator.load_proxies([
        make_proxy(1, latency=200),
        make_proxy(2, latency=50),
        make_proxy(3, latency=150),
    ])
    rotator.set_mode(RotationMode.FIXED)
    ep = await rotator.on_request_start()
    assert ep.proxy_id == 2


@pytest.mark.asyncio
async def test_returns_none_when_no_valid_proxies(rotator):
    rotator.load_proxies([make_proxy(1, status="invalid")])
    ep = await rotator.on_request_start()
    assert ep is None


@pytest.mark.asyncio
async def test_by_count_switches_after_threshold(rotator):
    rotator.set_mode(RotationMode.BY_COUNT, threshold=2)
    ep1 = await rotator.on_request_start()
    await rotator.on_request_done(ep1.proxy_id, success=True)
    ep2 = await rotator.on_request_start()
    await rotator.on_request_done(ep2.proxy_id, success=True)
    ep3 = await rotator.on_request_start()  # 达到阈值，切换
    assert ep3.proxy_id != ep1.proxy_id


@pytest.mark.asyncio
async def test_failover_switches_on_failure(rotator):
    rotator.set_mode(RotationMode.FAILOVER)
    ep1 = await rotator.on_request_start()
    await rotator.on_request_done(ep1.proxy_id, success=False)
    ep2 = await rotator.on_request_start()
    assert ep2.proxy_id != ep1.proxy_id
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_rotator.py -v
```

Expected: FAIL — ImportError

- [ ] **Step 3: 写 app/core/rotator.py**

```python
from __future__ import annotations
import asyncio
import time
from enum import Enum
from app.db.models import Proxy, ProxyEndpoint


class RotationMode(Enum):
    ROUND_ROBIN = "round_robin"
    FAILOVER = "failover"
    BY_COUNT = "by_count"
    BY_TIME = "by_time"
    BY_SCENE = "by_scene"
    BY_KEYWORD = "by_keyword"
    FIXED = "fixed"


class ProxyRotator:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._proxies: list[Proxy] = []
        self._index: int = 0
        self._mode = RotationMode.ROUND_ROBIN
        self._params: dict = {}
        self._request_count: int = 0
        self._last_switch_time: float = time.monotonic()
        self._trigger_word: str = ""
        self._required_word: str = ""
        self._on_no_proxy = None  # callback

    def load_proxies(self, proxies: list[Proxy]):
        valid = [p for p in proxies if p.status == "valid"]
        self._proxies = valid
        if self._mode == RotationMode.FIXED:
            self._pick_fixed()

    def set_mode(self, mode: RotationMode, **params):
        self._mode = mode
        self._params = params
        self._index = 0
        self._request_count = 0
        self._last_switch_time = time.monotonic()
        if mode == RotationMode.FIXED:
            self._pick_fixed()
        if "trigger_word" in params:
            self._trigger_word = params["trigger_word"]
        if "required_word" in params:
            self._required_word = params["required_word"]

    def _pick_fixed(self):
        if not self._proxies:
            return
        self._index = min(
            range(len(self._proxies)),
            key=lambda i: self._proxies[i].latency if self._proxies[i].latency >= 0 else float("inf")
        )

    def _available(self) -> list[Proxy]:
        return [p for p in self._proxies if p.status == "valid"]

    def _current_endpoint(self) -> ProxyEndpoint | None:
        avail = self._available()
        if not avail:
            return None
        idx = self._index % len(avail)
        p = avail[idx]
        return ProxyEndpoint(proxy_id=p.id, url=p.url, supports_rdns=p.supports_rdns)

    async def on_request_start(self) -> ProxyEndpoint | None:
        async with self._lock:
            avail = self._available()
            if not avail:
                return None

            if self._mode == RotationMode.ROUND_ROBIN:
                ep = self._make_ep(avail, self._index % len(avail))
                self._index += 1
                return ep

            if self._mode == RotationMode.BY_TIME:
                interval = self._params.get("interval_minutes", 5) * 60
                if time.monotonic() - self._last_switch_time >= interval:
                    self._index = (self._index + 1) % len(avail)
                    self._last_switch_time = time.monotonic()

            return self._make_ep(avail, self._index % len(avail))

    @staticmethod
    def _make_ep(avail: list[Proxy], idx: int) -> ProxyEndpoint:
        p = avail[idx]
        return ProxyEndpoint(proxy_id=p.id, url=p.url, supports_rdns=p.supports_rdns)

    async def on_request_done(self, proxy_id: int, success: bool):
        async with self._lock:
            avail = self._available()
            if not avail:
                return
            idx = self._index % len(avail)

            if self._mode == RotationMode.FAILOVER and not success:
                self._index = (idx + 1) % len(avail)

            elif self._mode == RotationMode.BY_COUNT:
                self._request_count += 1
                threshold = self._params.get("threshold", 30)
                if self._request_count >= threshold:
                    self._index = (idx + 1) % len(avail)
                    self._request_count = 0

            elif self._mode == RotationMode.BY_SCENE and not success:
                self._index = (idx + 1) % len(avail)

    async def on_response_body(self, proxy_id: int, body: bytes):
        """BY_KEYWORD 模式：仅对明文 HTTP 响应调用。"""
        async with self._lock:
            avail = self._available()
            if not avail:
                return
            text = body.decode("utf-8", errors="ignore")
            should_switch = False
            if self._trigger_word and self._trigger_word in text:
                should_switch = True
            if self._required_word and self._required_word not in text:
                should_switch = True
            if should_switch:
                self._index = (self._index + 1) % len(avail)

    async def force_switch(self):
        async with self._lock:
            avail = self._available()
            if avail:
                self._index = (self._index + 1) % len(avail)

    def get_current(self) -> Proxy | None:
        avail = self._available()
        if not avail:
            return None
        return avail[self._index % len(avail)]
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_rotator.py -v
```

Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/rotator.py tests/test_rotator.py
git commit -m "feat: ProxyRotator with 6 rotation modes"
```

---

### Task 7: 本地 SOCKS5 服务器

**Files:**
- Create: `app/core/socks_server.py`
- Create: `tests/test_socks_server.py`

**Interfaces:**
- Consumes: `ProxyRotator` from `app.core.rotator`; `AsyncWorkerThread` from `app.core.worker_thread`
- Produces: `SocksServerThread(AsyncWorkerThread)`，signals: `status_changed(str)`, `client_connected(str)`；方法：`start_server(port)`, `stop()`

- [ ] **Step 1: 写 tests/test_socks_server.py**

```python
import asyncio
import struct
import socket
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.socks_server import build_socks5_reply, parse_address


@pytest.mark.asyncio
async def test_parse_ipv4():
    # ATYP=1, 4 bytes IP, 2 bytes port
    data = socket.inet_aton("1.2.3.4") + struct.pack("!H", 8080)

    async def fake_read(n):
        return data[:n]

    reader = AsyncMock()
    reader.readexactly = AsyncMock(side_effect=[
        bytes([1]),          # atyp
        socket.inet_aton("1.2.3.4"),
        struct.pack("!H", 8080),
    ])
    # 直接测试 parse_address
    host, port = await parse_address(1, reader)
    assert host == "1.2.3.4"
    assert port == 8080


@pytest.mark.asyncio
async def test_parse_domain():
    reader = AsyncMock()
    reader.readexactly = AsyncMock(side_effect=[
        bytes([3]),          # atyp
        bytes([10]),         # domain length
        b"example.com",
        struct.pack("!H", 443),
    ])
    host, port = await parse_address(3, reader)
    assert host == "example.com"
    assert port == 443


def test_build_reply_success():
    reply = build_socks5_reply(0x00)
    assert reply[0] == 5
    assert reply[1] == 0x00


def test_build_reply_failure():
    reply = build_socks5_reply(0x04)
    assert reply[1] == 0x04
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_socks_server.py -v
```

Expected: FAIL — ImportError

- [ ] **Step 3: 写 app/core/socks_server.py**

```python
from __future__ import annotations
import asyncio
import contextlib
import socket
import struct
from PyQt6.QtCore import pyqtSignal
from app.core.worker_thread import AsyncWorkerThread
from app.core.rotator import ProxyRotator

try:
    from python_socks.async_.asyncio import Proxy
except ImportError:
    Proxy = None


def build_socks5_reply(code: int) -> bytes:
    return bytes([5, code, 0, 1, 0, 0, 0, 0, 0, 0])


async def parse_address(atyp: int, reader: asyncio.StreamReader) -> tuple[str, int]:
    if atyp == 1:
        host = socket.inet_ntoa(await reader.readexactly(4))
    elif atyp == 3:
        n = (await reader.readexactly(1))[0]
        host = (await reader.readexactly(n)).decode("idna")
    elif atyp == 4:
        raise ValueError("ipv6_unsupported")
    else:
        raise ValueError(f"unknown_atyp:{atyp}")
    port = struct.unpack("!H", await reader.readexactly(2))[0]
    return host, port


async def relay(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


class SocksServerThread(AsyncWorkerThread):
    status_changed = pyqtSignal(str)   # "running" | "stopped" | "no_upstream"
    client_connected = pyqtSignal(str) # "host:port"

    def __init__(self, rotator: ProxyRotator, port: int = 51024):
        super().__init__()
        self._rotator = rotator
        self._port = port
        self._server: asyncio.AbstractServer | None = None

    async def main(self):
        self._server = await asyncio.start_server(
            self._handle_client, "127.0.0.1", self._port
        )
        self.status_changed.emit("running")
        async with self._server:
            await self._server.serve_forever()
        self.status_changed.emit("stopped")

    async def _handle_client(
        self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter
    ):
        try:
            # Greeting
            ver, nmethods = await client_r.readexactly(2)
            methods = await client_r.readexactly(nmethods)
            if ver != 5 or 0 not in methods:
                client_w.write(b"\x05\xff")
                await client_w.drain()
                return
            client_w.write(b"\x05\x00")
            await client_w.drain()

            # Request
            ver, cmd, _, atyp = await client_r.readexactly(4)
            if cmd != 1:
                client_w.write(build_socks5_reply(0x07))
                await client_w.drain()
                return

            try:
                host, port = await parse_address(atyp, client_r)
            except ValueError as e:
                code = 0x08 if "ipv6" in str(e) or "atyp" in str(e) else 0x01
                client_w.write(build_socks5_reply(code))
                await client_w.drain()
                return

            # Select upstream proxy
            endpoint = await self._rotator.on_request_start()
            if endpoint is None:
                self.status_changed.emit("no_upstream")
                client_w.write(build_socks5_reply(0x04))
                await client_w.drain()
                return

            self.client_connected.emit(f"{host}:{port}")

            # Connect via upstream
            try:
                sock = await Proxy.from_url(endpoint.url).connect(
                    dest_host=host, dest_port=port, timeout=8
                )
            except Exception:
                await self._rotator.on_request_done(endpoint.proxy_id, success=False)
                client_w.write(build_socks5_reply(0x05))
                await client_w.drain()
                return

            remote_r, remote_w = await asyncio.open_connection(sock=sock)
            client_w.write(build_socks5_reply(0x00))
            await client_w.drain()

            await asyncio.gather(
                relay(client_r, remote_w),
                relay(remote_r, client_w),
            )
            await self._rotator.on_request_done(endpoint.proxy_id, success=True)

        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            with contextlib.suppress(Exception):
                client_w.close()
                await client_w.wait_closed()
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_socks_server.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/socks_server.py tests/test_socks_server.py
git commit -m "feat: SOCKS5 server with upstream proxy rotation"
```

---

### Task 8: 代理验证器

**Files:**
- Create: `app/core/validator.py`
- Create: `tests/test_validator.py`

**Interfaces:**
- Consumes: `Proxy`, `ValidationResult` from models; `AsyncWorkerThread`
- Produces: `ValidatorThread(AsyncWorkerThread)`，signals: `progress(int, int)`, `result_ready(ValidationResult)`, `finished()`；`validate_single(proxy, endpoint, timeout) -> ValidationResult`

- [ ] **Step 1: 写 tests/test_validator.py**

```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.validator import validate_single
from app.db.models import Proxy, ValidationResult


def make_proxy():
    return Proxy(id=1, host="1.2.3.4", port=1080, type="socks5")


@pytest.mark.asyncio
async def test_validate_success():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"origin": "9.8.7.6"})
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.validator.aiohttp.ClientSession", return_value=mock_session), \
         patch("app.core.validator.ProxyConnector"), \
         patch("app.core.validator._get_local_ip", return_value="1.1.1.1"):
        result = await validate_single(make_proxy(), "https://httpbin.org/ip", 10)

    assert result.success is True
    assert result.latency >= 0
    assert result.anonymity == "high"


@pytest.mark.asyncio
async def test_validate_connection_error():
    with patch("app.core.validator.aiohttp.ClientSession") as mock_cls, \
         patch("app.core.validator.ProxyConnector"):
        mock_cls.return_value.__aenter__ = AsyncMock(side_effect=Exception("refused"))
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await validate_single(make_proxy(), "https://httpbin.org/ip", 10)

    assert result.success is False
    assert result.error != ""
```

- [ ] **Step 2: 运行确认失败**

```bash
pytest tests/test_validator.py -v
```

Expected: FAIL — ImportError

- [ ] **Step 3: 写 app/core/validator.py**

```python
from __future__ import annotations
import asyncio
import time
from PyQt6.QtCore import pyqtSignal
import aiohttp
from aiohttp_socks import ProxyConnector
from app.core.worker_thread import AsyncWorkerThread
from app.db.models import Proxy, ValidationResult

_local_ip_cache: str | None = None


async def _get_local_ip() -> str:
    global _local_ip_cache
    if _local_ip_cache:
        return _local_ip_cache
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://httpbin.org/ip", timeout=aiohttp.ClientTimeout(total=5)) as r:
                data = await r.json()
                _local_ip_cache = data.get("origin", "")
                return _local_ip_cache
    except Exception:
        return ""


async def validate_single(
    proxy: Proxy,
    endpoint: str,
    timeout: int,
    backup_endpoint: str = "",
) -> ValidationResult:
    connector = ProxyConnector.from_url(proxy.url)
    client_timeout = aiohttp.ClientTimeout(total=timeout, sock_connect=timeout // 2)
    t0 = time.monotonic()
    try:
        async with aiohttp.ClientSession(connector=connector, timeout=client_timeout) as session:
            async with session.get(endpoint) as resp:
                latency = round((time.monotonic() - t0) * 1000, 1)
                if resp.status != 200:
                    return ValidationResult(proxy_id=proxy.id, success=False,
                                            latency=-1, anonymity="", region="",
                                            error=f"http_{resp.status}", endpoint=endpoint)
                try:
                    data = await resp.json(content_type=None)
                    proxy_ip = data.get("origin", "") or data.get("ip", "")
                except Exception:
                    proxy_ip = ""

        local_ip = await _get_local_ip()
        if not proxy_ip:
            anonymity = ""
        elif local_ip and local_ip in proxy_ip:
            anonymity = "transparent"
        elif proxy_ip == proxy.host:
            anonymity = "medium"
        else:
            anonymity = "high"

        region = await _get_region(proxy_ip)
        return ValidationResult(proxy_id=proxy.id, success=True, latency=latency,
                                anonymity=anonymity, region=region, endpoint=endpoint)
    except Exception as e:
        if backup_endpoint and backup_endpoint != endpoint:
            return await validate_single(proxy, backup_endpoint, timeout)
        return ValidationResult(proxy_id=proxy.id, success=False,
                                latency=-1, anonymity="", region="",
                                error=type(e).__name__, endpoint=endpoint)


_geo_cache: dict[str, str] = {}


async def _get_region(ip: str) -> str:
    if not ip or ip in _geo_cache:
        return _geo_cache.get(ip, "")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"http://ip-api.com/json/{ip}?fields=country,regionName",
                             timeout=aiohttp.ClientTimeout(total=5)) as r:
                data = await r.json()
                region = f"{data.get('country','')} {data.get('regionName','')}".strip()
                _geo_cache[ip] = region
                return region
    except Exception:
        return ""


class ValidatorThread(AsyncWorkerThread):
    progress = pyqtSignal(int, int)           # done, total
    result_ready = pyqtSignal(object)         # ValidationResult
    finished = pyqtSignal()

    def __init__(self, proxies: list[Proxy], endpoint: str,
                 backup_endpoint: str, timeout: int, concurrency: int):
        super().__init__()
        self._proxies = proxies
        self._endpoint = endpoint
        self._backup = backup_endpoint
        self._timeout = timeout
        self._concurrency = concurrency

    async def main(self):
        sem = asyncio.Semaphore(self._concurrency)
        total = len(self._proxies)
        done = 0

        async def one(proxy):
            nonlocal done
            async with sem:
                result = await validate_single(proxy, self._endpoint,
                                               self._timeout, self._backup)
                done += 1
                if done % 20 == 0 or done == total:
                    self.progress.emit(done, total)
                self.result_ready.emit(result)
                return result

        await asyncio.gather(*(one(p) for p in self._proxies))
        self.finished.emit()
```

- [ ] **Step 4: 运行测试**

```bash
pytest tests/test_validator.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/validator.py tests/test_validator.py
git commit -m "feat: proxy validator with anonymity and region detection"
```

---

### Task 9: 爬虫模块（BaseCrawler + Fofa + QuaKe + Hunter + FreeSites）

**Files:**
- Create: `app/core/crawlers/base.py`
- Create: `app/core/crawlers/fofa.py`
- Create: `app/core/crawlers/quake.py`
- Create: `app/core/crawlers/hunter.py`
- Create: `app/core/crawlers/free_sites.py`
- Create: `tests/test_crawlers.py`

**Interfaces:**
- Produces: `BaseCrawler` ABC；`FofaCrawler`, `QuakeCrawler`, `HunterCrawler`, `FreeSitesCrawler`

- [ ] **Step 1: 写 app/core/crawlers/base.py**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import asyncio
import aiohttp
from app.db.models import ProxyCandidate, CrawlerResult


class RateLimited(Exception):
    def __init__(self, retry_after: float = 5.0):
        self.retry_after = retry_after


class QuotaExhausted(Exception):
    pass


@dataclass
class CrawlPage:
    items: list[ProxyCandidate]
    next_cursor: object | None = None


class BaseCrawler(ABC):
    name: str = "base"
    rate_limit: float = 1.0

    @abstractmethod
    async def fetch_page(self, session: aiohttp.ClientSession,
                         query: str, cursor: object) -> CrawlPage: ...

    async def test_auth(self, session: aiohttp.ClientSession) -> bool:
        return True

    async def crawl(self, session: aiohttp.ClientSession,
                    config: dict, limit: int) -> CrawlerResult:
        cursor, seen, errors = None, [], []
        query = config.get("query", "")
        while len(seen) < limit:
            try:
                page = await self.fetch_page(session, query, cursor)
                seen.extend(page.items)
                if page.next_cursor is None:
                    break
                cursor = page.next_cursor
                await asyncio.sleep(self.rate_limit)
            except RateLimited as e:
                await asyncio.sleep(e.retry_after)
            except QuotaExhausted:
                return CrawlerResult(self.name, seen, errors, quota_exhausted=True)
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")
                break
        return CrawlerResult(self.name, seen, errors)
```

- [ ] **Step 2: 写 app/core/crawlers/fofa.py**

```python
from __future__ import annotations
import base64
import aiohttp
from app.core.crawlers.base import BaseCrawler, CrawlPage, RateLimited, QuotaExhausted
from app.db.models import ProxyCandidate

_DEFAULT_QUERY = 'protocol=="socks5" && "Version:5 Method:No Authentication(0x00)"'


class FofaCrawler(BaseCrawler):
    name = "fofa"
    rate_limit = 1.0

    def __init__(self, api_key: str, page_size: int = 100):
        self._api_key = api_key
        self._page_size = min(page_size, 10000)

    async def test_auth(self, session: aiohttp.ClientSession) -> bool:
        url = "https://fofa.info/api/v1/info/my"
        async with session.get(url, params={"key": self._api_key}) as r:
            data = await r.json()
            return data.get("error") is False or "email" in data

    async def fetch_page(self, session, query, cursor) -> CrawlPage:
        page = cursor or 1
        q_b64 = base64.b64encode(query.encode()).decode()
        params = {
            "key": self._api_key,
            "qbase64": q_b64,
            "fields": "ip,port,protocol,country_name",
            "size": self._page_size,
            "page": page,
        }
        async with session.get("https://fofa.info/api/v1/search/all", params=params) as r:
            if r.status == 429:
                raise RateLimited(retry_after=10.0)
            data = await r.json()
            if data.get("error"):
                msg = data.get("errmsg", "")
                if "quota" in msg.lower():
                    raise QuotaExhausted()
                raise Exception(msg)
            results = data.get("results", [])
            candidates = []
            for row in results:
                if len(row) < 2:
                    continue
                try:
                    candidates.append(ProxyCandidate(
                        host=row[0], port=int(row[1]),
                        type=row[2] if len(row) > 2 else "socks5",
                        source="fofa",
                    ))
                except (ValueError, IndexError):
                    continue
            next_cursor = page + 1 if len(results) == self._page_size else None
            return CrawlPage(items=candidates, next_cursor=next_cursor)
```

- [ ] **Step 3: 写 app/core/crawlers/quake.py**

```python
from __future__ import annotations
import aiohttp
from app.core.crawlers.base import BaseCrawler, CrawlPage, RateLimited, QuotaExhausted
from app.db.models import ProxyCandidate

_DEFAULT_QUERY = 'service:socks5 AND country:"CN"'


class QuakeCrawler(BaseCrawler):
    name = "quake"
    rate_limit = 1.0

    def __init__(self, api_key: str, page_size: int = 100):
        self._api_key = api_key
        self._page_size = page_size

    async def fetch_page(self, session, query, cursor) -> CrawlPage:
        start = cursor or 0
        payload = {"query": query, "start": start, "size": self._page_size,
                   "ignore_cache": False}
        async with session.post(
            "https://quake.360.net/api/v3/search/quake_service",
            json=payload,
            headers={"X-QuakeToken": self._api_key},
        ) as r:
            if r.status == 429:
                raise RateLimited(retry_after=10.0)
            data = await r.json()
            if data.get("code") != 0:
                msg = data.get("message", "")
                if "quota" in msg.lower():
                    raise QuotaExhausted()
                raise Exception(msg)
            items = data.get("data", [])
            candidates = []
            for item in items:
                try:
                    ip = item["ip"]
                    port = int(item["port"])
                    candidates.append(ProxyCandidate(
                        host=ip, port=port, type="socks5", source="quake"
                    ))
                except (KeyError, ValueError):
                    continue
            next_cursor = start + self._page_size if len(items) == self._page_size else None
            return CrawlPage(items=candidates, next_cursor=next_cursor)
```

- [ ] **Step 4: 写 app/core/crawlers/hunter.py**

```python
from __future__ import annotations
import aiohttp
from app.core.crawlers.base import BaseCrawler, CrawlPage, RateLimited, QuotaExhausted
from app.db.models import ProxyCandidate


class HunterCrawler(BaseCrawler):
    name = "hunter"
    rate_limit = 2.0

    def __init__(self, api_key: str, page_size: int = 100):
        self._api_key = api_key
        self._page_size = page_size

    async def fetch_page(self, session, query, cursor) -> CrawlPage:
        page = cursor or 1
        params = {
            "api-key": self._api_key,
            "search": query,
            "page": page,
            "page_size": self._page_size,
            "asset_type": 0,
        }
        async with session.get(
            "https://hunter.qianxin.com/openApi/search", params=params
        ) as r:
            if r.status == 429:
                raise RateLimited(retry_after=15.0)
            data = await r.json()
            code = data.get("code", -1)
            if code == 40205:
                raise QuotaExhausted()
            if code != 200:
                raise Exception(data.get("message", f"code={code}"))
            arr = data.get("data", {}).get("arr", [])
            candidates = []
            for item in arr:
                try:
                    candidates.append(ProxyCandidate(
                        host=item["ip"], port=int(item["port"]),
                        type="socks5", source="hunter"
                    ))
                except (KeyError, ValueError):
                    continue
            next_cursor = page + 1 if len(arr) == self._page_size else None
            return CrawlPage(items=candidates, next_cursor=next_cursor)
```

- [ ] **Step 5: 写 app/core/crawlers/free_sites.py**

```python
from __future__ import annotations
import aiohttp
from bs4 import BeautifulSoup
from app.core.crawlers.base import BaseCrawler, CrawlPage
from app.db.models import ProxyCandidate


async def _fetch_html(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as r:
        return await r.text()


async def _parse_proxyscrape(session: aiohttp.ClientSession,
                              proto: str) -> list[ProxyCandidate]:
    url = (f"https://api.proxyscrape.com/v3/free-proxy-list/get"
           f"?request=displayproxies&protocol={proto}&timeout=10000&country=all")
    try:
        text = await _fetch_html(session, url)
        results = []
        for line in text.strip().splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            host, port_s = line.rsplit(":", 1)
            try:
                results.append(ProxyCandidate(host=host, port=int(port_s),
                                              type=proto, source="free"))
            except ValueError:
                continue
        return results
    except Exception:
        return []


async def _parse_socks_proxy_net(session: aiohttp.ClientSession,
                                 proto: str) -> list[ProxyCandidate]:
    url = f"https://www.socks-proxy.net/"
    try:
        html = await _fetch_html(session, url)
        soup = BeautifulSoup(html, "lxml")
        results = []
        for row in soup.select("table tbody tr"):
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cols) < 2:
                continue
            try:
                results.append(ProxyCandidate(host=cols[0], port=int(cols[1]),
                                              type="socks5", source="free"))
            except ValueError:
                continue
        return results
    except Exception:
        return []


class FreeSitesCrawler(BaseCrawler):
    name = "free"
    rate_limit = 0.0

    def __init__(self, proxy_type: str = "socks5", limit: int = 20):
        self._proxy_type = proxy_type
        self._limit = limit

    async def fetch_page(self, session, query, cursor) -> CrawlPage:
        results: list[ProxyCandidate] = []
        parsers = [
            _parse_proxyscrape(session, self._proxy_type),
            _parse_socks_proxy_net(session, self._proxy_type),
        ]
        for coro in parsers:
            try:
                results.extend(await coro)
            except Exception:
                continue
        # deduplicate within free sites
        seen: set[tuple] = set()
        unique = []
        for c in results:
            key = (c.host, c.port, c.type)
            if key not in seen:
                seen.add(key)
                unique.append(c)
        return CrawlPage(items=unique[:self._limit], next_cursor=None)
```

- [ ] **Step 6: 写 tests/test_crawlers.py**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.crawlers.fofa import FofaCrawler
from app.core.crawlers.base import QuotaExhausted


@pytest.fixture
def fofa():
    return FofaCrawler(api_key="test_key", page_size=10)


@pytest.mark.asyncio
async def test_fofa_fetch_page_success(fofa):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "error": False,
        "results": [["1.2.3.4", "1080", "socks5", "China"]],
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp)

    page = await fofa.fetch_page(session, "test query", None)
    assert len(page.items) == 1
    assert page.items[0].host == "1.2.3.4"
    assert page.items[0].port == 1080


@pytest.mark.asyncio
async def test_fofa_quota_exhausted(fofa):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "error": True, "errmsg": "Quota exceeded"
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp)

    with pytest.raises(QuotaExhausted):
        await fofa.fetch_page(session, "test", None)


@pytest.mark.asyncio
async def test_fofa_crawl_deduplicates():
    crawler = FofaCrawler(api_key="key", page_size=2)
    from app.db.models import ProxyCandidate
    from app.core.crawlers.base import CrawlPage

    call_count = 0

    async def fake_fetch(session, query, cursor):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CrawlPage(
                items=[ProxyCandidate("1.2.3.4", 1080, "socks5", "fofa"),
                       ProxyCandidate("1.2.3.5", 1080, "socks5", "fofa")],
                next_cursor=2,
            )
        return CrawlPage(items=[], next_cursor=None)

    crawler.fetch_page = fake_fetch
    result = await crawler.crawl(MagicMock(), {"query": "test"}, limit=10)
    assert len(result.candidates) == 2
    assert result.quota_exhausted is False
```

- [ ] **Step 7: 运行测试**

```bash
pytest tests/test_crawlers.py -v
```

Expected: 3 passed

- [ ] **Step 8: Commit**

```bash
git add app/core/crawlers/ tests/test_crawlers.py
git commit -m "feat: crawlers for Fofa, QuaKe, Hunter, FreeSites"
```

---

### Task 10: ProxyTableModel（Qt 表格模型）

**Files:**
- Create: `app/ui/proxy_table.py`

**Interfaces:**
- Consumes: `Proxy` from models; `Database`
- Produces: `ProxyTableModel(QAbstractTableModel)`，方法：`load_page(page, page_size)`, `refresh()`, `total_count() -> int`；`COLUMNS` 常量

- [ ] **Step 1: 写 app/ui/proxy_table.py**

```python
from __future__ import annotations
from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from app.db.models import Proxy

COLUMNS = ["#", "Host", "Port", "类型", "地区", "延时(ms)", "状态", "匿名性", "操作"]
_STATUS_DISPLAY = {"valid": "✓ 有效", "invalid": "✗ 无效", "unknown": "? 未知"}
_ANON_DISPLAY = {"high": "高匿", "medium": "匿名", "transparent": "透明", "": "-"}


class ProxyTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._proxies: list[Proxy] = []
        self._page = 1
        self._page_size = 10
        self._total = 0

    def load(self, proxies: list[Proxy], total: int, page: int, page_size: int):
        self.beginResetModel()
        self._proxies = proxies
        self._total = total
        self._page = page
        self._page_size = page_size
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._proxies)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p = self._proxies[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            offset = (self._page - 1) * self._page_size
            values = [
                offset + index.row() + 1,
                p.host, p.port, p.type, p.region or "-",
                f"{p.latency:.0f}" if p.latency >= 0 else "-",
                _STATUS_DISPLAY.get(p.status, p.status),
                _ANON_DISPLAY.get(p.anonymity, p.anonymity or "-"),
                "",  # 操作列由 delegate 处理
            ]
            return str(values[col])
        if role == Qt.ItemDataRole.UserRole:
            return p  # 返回完整 Proxy 对象
        return None

    def get_proxy(self, row: int) -> Proxy | None:
        if 0 <= row < len(self._proxies):
            return self._proxies[row]
        return None

    @property
    def total_count(self) -> int:
        return self._total
```

- [ ] **Step 2: 验证可导入**

```bash
python -c "from app.ui.proxy_table import ProxyTableModel, COLUMNS; print(COLUMNS)"
```

Expected: 打印列名列表，无报错。

- [ ] **Step 3: Commit**

```bash
git add app/ui/proxy_table.py
git commit -m "feat: ProxyTableModel with pagination"
```

---

### Task 11: 添加代理对话框（单个 + 批量）

**Files:**
- Create: `app/ui/dialogs/add_proxy.py`
- Create: `app/ui/dialogs/batch_add.py`

**Interfaces:**
- Produces: `AddProxyDialog(QDialog)` 返回 `Proxy | None`；`BatchAddDialog(QDialog)` 返回 `list[Proxy]`

- [ ] **Step 1: 写 app/ui/dialogs/add_proxy.py**

```python
from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QDialogButtonBox, QVBoxLayout, QCheckBox,
)
from app.db.models import Proxy


class AddProxyDialog(QDialog):
    def __init__(self, parent=None, proxy: Proxy | None = None):
        super().__init__(parent)
        self.setWindowTitle("添加代理" if proxy is None else "编辑代理")
        self._proxy = proxy

        self._type = QComboBox()
        self._type.addItems(["socks5", "socks4", "http", "https"])
        self._host = QLineEdit()
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(1080)
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._validate_now = QCheckBox("立即验证")

        form = QFormLayout()
        form.addRow("类型", self._type)
        form.addRow("Host", self._host)
        form.addRow("Port", self._port)
        form.addRow("用户名", self._username)
        form.addRow("密码", self._password)
        form.addRow("", self._validate_now)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        if proxy:
            self._type.setCurrentText(proxy.type)
            self._host.setText(proxy.host)
            self._port.setValue(proxy.port)
            self._username.setText(proxy.username)

    def get_proxy(self) -> Proxy | None:
        host = self._host.text().strip()
        if not host:
            return None
        return Proxy(
            id=self._proxy.id if self._proxy else 0,
            host=host,
            port=self._port.value(),
            type=self._type.currentText(),
            username=self._username.text().strip(),
            password=self._password.text(),
            source="manual",
        )

    def should_validate(self) -> bool:
        return self._validate_now.isChecked()
```

- [ ] **Step 2: 写 app/ui/dialogs/batch_add.py**

```python
from __future__ import annotations
import re
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QLabel,
    QDialogButtonBox, QComboBox, QHBoxLayout,
)
from app.db.models import Proxy

_URL_RE = re.compile(
    r"^(?P<type>socks5|socks4|https?)"
    r"://(?:(?P<user>[^:@]+):(?P<pass>[^@]+)@)?"
    r"(?P<host>[^:]+):(?P<port>\d+)$"
)
_PLAIN_RE = re.compile(r"^(?P<host>[^:]+):(?P<port>\d+)$")


def parse_proxy_line(line: str, default_type: str = "socks5") -> Proxy | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    m = _URL_RE.match(line)
    if m:
        return Proxy(
            host=m["host"], port=int(m["port"]), type=m["type"],
            username=m["user"] or "", password=m["pass"] or "", source="manual",
        )
    m = _PLAIN_RE.match(line)
    if m:
        return Proxy(host=m["host"], port=int(m["port"]),
                     type=default_type, source="manual")
    return None


class BatchAddDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量添加代理")
        self.resize(520, 400)

        self._default_type = QComboBox()
        self._default_type.addItems(["socks5", "socks4", "http"])

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("默认类型:"))
        type_row.addWidget(self._default_type)
        type_row.addStretch()

        self._text = QTextEdit()
        self._text.setPlaceholderText(
            "每行一个代理，支持格式：\n"
            "socks5://host:port\n"
            "socks5://user:pass@host:port\n"
            "host:port"
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(type_row)
        layout.addWidget(QLabel("代理列表:"))
        layout.addWidget(self._text)
        layout.addWidget(buttons)

    def get_proxies(self) -> list[Proxy]:
        dtype = self._default_type.currentText()
        proxies = []
        for line in self._text.toPlainText().splitlines():
            p = parse_proxy_line(line, dtype)
            if p:
                proxies.append(p)
        return proxies
```

- [ ] **Step 3: 验证解析逻辑**

```bash
python -c "
from app.ui.dialogs.batch_add import parse_proxy_line
p = parse_proxy_line('socks5://user:pass@1.2.3.4:1080')
assert p.host == '1.2.3.4' and p.username == 'user'
p2 = parse_proxy_line('1.2.3.4:1080')
assert p2.type == 'socks5'
print('ok')
"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add app/ui/dialogs/add_proxy.py app/ui/dialogs/batch_add.py
git commit -m "feat: add proxy and batch add dialogs"
```

---

### Task 12: 自动爬取对话框

**Files:**
- Create: `app/ui/dialogs/auto_crawl.py`

**Interfaces:**
- Produces: `AutoCrawlDialog(QDialog)`，`get_config() -> dict`（含 fofa/quake/hunter/free/bruteforce 各自的启用状态、查询数、API key、查询语法）

- [ ] **Step 1: 写 app/ui/dialogs/auto_crawl.py**

```python
from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QCheckBox, QLineEdit, QSpinBox, QComboBox, QLabel,
    QDialogButtonBox, QPushButton, QScrollArea, QWidget,
)
from PyQt6.QtCore import Qt
import keyring


_SERVICE = "ProxyPool"
_FOFA_DEFAULT = 'protocol=="socks5" && "Version:5 Method:No Authentication(0x00)"'
_QUAKE_DEFAULT = 'service:socks5 AND country:"CN"'
_HUNTER_DEFAULT = "socks5"


class SourceRow(QWidget):
    def __init__(self, name: str, key_label: str,
                 default_query: str, default_count: int, parent=None):
        super().__init__(parent)
        self._name = name
        self._enabled = QCheckBox("启用")
        self._count = QSpinBox()
        self._count.setRange(1, 50000)
        self._count.setValue(default_count)
        self._key = QLineEdit()
        self._key.setPlaceholderText(f"{key_label} (存储于系统 keyring)")
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        saved_key = keyring.get_password(_SERVICE, f"{name}_api_key") or ""
        if saved_key:
            self._key.setText(saved_key)
            self._enabled.setChecked(True)
        self._query = QLineEdit(default_query)

        top = QHBoxLayout()
        top.addWidget(QLabel(name.upper()))
        top.addWidget(self._enabled)
        top.addWidget(QLabel("查询数量"))
        top.addWidget(self._count)
        top.addWidget(QLabel(f"{key_label}"))
        top.addWidget(self._key)
        top.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(QLabel(f"{name.upper()} 语法"))
        layout.addWidget(self._query)

    def save_key(self):
        val = self._key.text().strip()
        if val:
            keyring.set_password(_SERVICE, f"{self._name}_api_key", val)

    def config(self) -> dict:
        return {
            "enabled": self._enabled.isChecked(),
            "limit": self._count.value(),
            "api_key": self._key.text().strip(),
            "query": self._query.text().strip(),
        }


class AutoCrawlDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自动爬取")
        self.resize(680, 580)

        self._fofa = SourceRow("fofa", "FofaKey", _FOFA_DEFAULT, 10000)
        self._quake = SourceRow("quake", "QuaKeKey", _QUAKE_DEFAULT, 300)
        self._hunter = SourceRow("hunter", "HunterKey", _HUNTER_DEFAULT, 200)

        # 免费代理
        free_box = QGroupBox("免费代理")
        self._free_enabled = QCheckBox("启用")
        self._free_count = QSpinBox()
        self._free_count.setRange(1, 200)
        self._free_count.setValue(20)
        self._free_type = QComboBox()
        self._free_type.addItems(["socks5", "socks4", "http"])
        free_row = QHBoxLayout()
        free_row.addWidget(self._free_enabled)
        free_row.addWidget(QLabel("查询数量"))
        free_row.addWidget(self._free_count)
        free_row.addWidget(QLabel("代理类型"))
        free_row.addWidget(self._free_type)
        free_row.addStretch()
        free_box.setLayout(free_row)

        # 凭据补全
        brute_box = QGroupBox("凭据补全")
        self._brute_enabled = QCheckBox("未启用")
        self._brute_warn = QLabel(
            "启用后将对所有代理尝试已有凭据，仅用于您拥有授权的代理"
        )
        self._brute_warn.setStyleSheet("color: orange;")
        self._brute_confirm = QCheckBox("我确认上述代理均属于我或我有权限测试")
        brute_layout = QVBoxLayout()
        brute_layout.addWidget(self._brute_enabled)
        brute_layout.addWidget(self._brute_warn)
        brute_layout.addWidget(self._brute_confirm)
        brute_box.setLayout(brute_layout)
        self._brute_enabled.toggled.connect(
            lambda checked: self._brute_confirm.setEnabled(checked)
        )

        buttons = QDialogButtonBox()
        save_btn = QPushButton("保存并爬取")
        cancel_btn = QPushButton("取消")
        save_btn.setStyleSheet("background:#27ae60;color:white;")
        cancel_btn.setStyleSheet("background:#e74c3c;color:white;")
        buttons.addButton(save_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(cancel_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        content = QWidget()
        vbox = QVBoxLayout(content)
        vbox.addWidget(self._fofa)
        vbox.addWidget(self._quake)
        vbox.addWidget(self._hunter)
        vbox.addWidget(free_box)
        vbox.addWidget(brute_box)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)

        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

    def _on_accept(self):
        for src in [self._fofa, self._quake, self._hunter]:
            src.save_key()
        self.accept()

    def get_config(self) -> dict:
        return {
            "fofa": self._fofa.config(),
            "quake": self._quake.config(),
            "hunter": self._hunter.config(),
            "free": {
                "enabled": self._free_enabled.isChecked(),
                "limit": self._free_count.value(),
                "proxy_type": self._free_type.currentText(),
            },
            "bruteforce": {
                "enabled": (self._brute_enabled.isChecked()
                            and self._brute_confirm.isChecked()),
            },
        }
```

- [ ] **Step 2: Commit**

```bash
git add app/ui/dialogs/auto_crawl.py
git commit -m "feat: auto crawl configuration dialog"
```

---

### Task 13: 批量管理 + 导出对话框

**Files:**
- Create: `app/ui/dialogs/batch_manage.py`
- Create: `app/ui/dialogs/export_proxy.py`

- [ ] **Step 1: 写 app/ui/dialogs/batch_manage.py**

```python
from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QDialogButtonBox,
)
from PyQt6.QtCore import pyqtSignal


class BatchManageDialog(QDialog):
    delete_selected = pyqtSignal()
    delete_invalid = pyqtSignal()
    reset_status = pyqtSignal()
    validate_selected = pyqtSignal()

    def __init__(self, selected_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("批量管理")
        self._label = QLabel(f"已选中 {selected_count} 个代理")

        btn_del_sel = QPushButton("删除选中")
        btn_del_inv = QPushButton("删除所有无效")
        btn_reset = QPushButton("重置状态为未知")
        btn_validate = QPushButton("验证选中")

        btn_del_sel.clicked.connect(lambda: (self.delete_selected.emit(), self.accept()))
        btn_del_inv.clicked.connect(lambda: (self.delete_invalid.emit(), self.accept()))
        btn_reset.clicked.connect(lambda: (self.reset_status.emit(), self.accept()))
        btn_validate.clicked.connect(lambda: (self.validate_selected.emit(), self.accept()))

        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        for btn in [btn_del_sel, btn_del_inv, btn_reset, btn_validate]:
            layout.addWidget(btn)
        layout.addWidget(close)
```

- [ ] **Step 2: 写 app/ui/dialogs/export_proxy.py**

```python
from __future__ import annotations
import csv
import json
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QComboBox, QCheckBox,
    QDialogButtonBox, QLabel, QFileDialog,
)
from app.db.models import Proxy


class ExportDialog(QDialog):
    def __init__(self, proxies: list[Proxy], parent=None):
        super().__init__(parent)
        self.setWindowTitle("导出代理")
        self._proxies = proxies

        self._fmt = QComboBox()
        self._fmt.addItems(["txt (host:port)", "txt (url)", "csv", "json"])
        self._valid_only = QCheckBox("仅导出有效代理")
        self._valid_only.setChecked(True)
        self._redact = QCheckBox("脱敏密码（推荐）")
        self._redact.setChecked(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._export)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("导出格式:"))
        layout.addWidget(self._fmt)
        layout.addWidget(self._valid_only)
        layout.addWidget(self._redact)
        layout.addWidget(buttons)

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存文件", "", "All Files (*)")
        if not path:
            return
        proxies = self._proxies
        if self._valid_only.isChecked():
            proxies = [p for p in proxies if p.status == "valid"]
        redact = self._redact.isChecked()
        fmt = self._fmt.currentText()
        _write(Path(path), proxies, fmt, redact)
        self.accept()


def _write(path: Path, proxies: list[Proxy], fmt: str, redact: bool):
    if fmt.startswith("txt (host"):
        path.write_text("\n".join(f"{p.host}:{p.port}" for p in proxies), encoding="utf-8")
    elif fmt.startswith("txt (url"):
        lines = [p.redacted_url if redact else p.url for p in proxies]
        path.write_text("\n".join(lines), encoding="utf-8")
    elif fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["host", "port", "type", "username", "password",
                        "region", "latency", "status", "anonymity"])
            for p in proxies:
                w.writerow([p.host, p.port, p.type, p.username,
                            "***" if redact else p.password,
                            p.region, p.latency, p.status, p.anonymity])
    elif fmt == "json":
        data = []
        for p in proxies:
            d = {"host": p.host, "port": p.port, "type": p.type,
                 "username": p.username, "region": p.region,
                 "latency": p.latency, "status": p.status}
            if not redact:
                d["password"] = p.password
            data.append(d)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 3: Commit**

```bash
git add app/ui/dialogs/batch_manage.py app/ui/dialogs/export_proxy.py
git commit -m "feat: batch manage and export dialogs"
```

---

### Task 14: 主窗口

**Files:**
- Create: `app/ui/main_window.py`

**Interfaces:**
- Consumes: 所有 core 模块、db 模块、UI 组件
- Produces: `MainWindow(QMainWindow)` — 完整应用主窗口

- [ ] **Step 1: 写 app/ui/main_window.py**

```python
from __future__ import annotations
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QTableView,
    QHeaderView, QAbstractItemView, QLineEdit, QTextEdit,
    QSplitter, QStatusBar, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer
from app.config import Config, DB_PATH
from app.db.database import Database
from app.db.models import Proxy, ValidationResult
from app.core.rotator import ProxyRotator, RotationMode
from app.core.socks_server import SocksServerThread
from app.core.validator import ValidatorThread
from app.ui.proxy_table import ProxyTableModel
from app.ui.dialogs.add_proxy import AddProxyDialog
from app.ui.dialogs.batch_add import BatchAddDialog
from app.ui.dialogs.auto_crawl import AutoCrawlDialog
from app.ui.dialogs.batch_manage import BatchManageDialog
from app.ui.dialogs.export_proxy import ExportDialog


_MODE_LABELS = [
    ("轮询代理模式", RotationMode.ROUND_ROBIN),
    ("Failover 模式", RotationMode.FAILOVER),
    ("根据次数更换", RotationMode.BY_COUNT),
    ("根据时间更换", RotationMode.BY_TIME),
    ("根据场景切换", RotationMode.BY_SCENE),
    ("根据关键词", RotationMode.BY_KEYWORD),
    ("固定代理", RotationMode.FIXED),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ProxyPool")
        self.resize(1100, 700)

        self._db = Database(DB_PATH)
        self._db.initialize()
        self._config = Config.load(self._db)
        self._rotator = ProxyRotator()
        self._socks_thread: SocksServerThread | None = None
        self._validator_thread: ValidatorThread | None = None

        self._build_ui()
        self._refresh_table()

    # ── UI Construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addLayout(self._build_top_bar())
        root.addLayout(self._build_action_bar())

        self._table = QTableView()
        self._model = ProxyTableModel()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setPlaceholderText("事件日志...")

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._table)
        splitter.addWidget(self._log)
        splitter.setSizes([550, 120])
        root.addWidget(splitter)

        root.addLayout(self._build_pagination())

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._update_status("stopped")

    def _build_top_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._btn_start = QPushButton("启动代理")
        self._btn_start.setStyleSheet("background:#27ae60;color:white;padding:6px 14px;")
        self._btn_stop = QPushButton("关闭代理")
        self._btn_stop.setStyleSheet("background:#7f8c8d;color:white;padding:6px 14px;")
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)

        self._mode_combo = QComboBox()
        for label, _ in _MODE_LABELS:
            self._mode_combo.addItem(label)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self._param_label = QLabel("次数:")
        self._param_spin = QSpinBox()
        self._param_spin.setRange(1, 9999)
        self._param_spin.setValue(self._config.rotation_params.get("threshold", 30))
        self._param_input = QLineEdit()
        self._param_input.setPlaceholderText("验证URL / 关键词...")
        self._param_input.setVisible(False)

        self._current_proxy_label = QLabel("当前代理: None")

        row.addWidget(self._btn_start)
        row.addWidget(self._btn_stop)
        row.addWidget(QLabel("模式:"))
        row.addWidget(self._mode_combo)
        row.addWidget(self._param_label)
        row.addWidget(self._param_spin)
        row.addWidget(self._param_input)
        row.addStretch()
        row.addWidget(self._current_proxy_label)
        return row

    def _build_action_bar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        btns = [
            ("单个添加", self._on_add_single),
            ("批量添加", self._on_add_batch),
            ("自动爬取", self._on_auto_crawl),
            ("代理验证", self._on_validate),
            ("批量管理", self._on_batch_manage),
            ("导出代理", self._on_export),
        ]
        for label, slot in btns:
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        return row

    def _build_pagination(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._btn_prev = QPushButton("◀")
        self._page_label = QLabel("1")
        self._btn_next = QPushButton("▶")
        self._page_size_combo = QComboBox()
        for s in [10, 20, 50, 100]:
            self._page_size_combo.addItem(f"{s} / page", s)
        self._btn_prev.clicked.connect(self._prev_page)
        self._btn_next.clicked.connect(self._next_page)
        self._page_size_combo.currentIndexChanged.connect(self._refresh_table)
        row.addStretch()
        row.addWidget(self._btn_prev)
        row.addWidget(self._page_label)
        row.addWidget(self._btn_next)
        row.addWidget(self._page_size_combo)
        return row

    # ── State ────────────────────────────────────────────────────────────────

    def _current_page(self) -> int:
        try:
            return int(self._page_label.text())
        except ValueError:
            return 1

    def _current_page_size(self) -> int:
        return self._page_size_combo.currentData() or 10

    def _refresh_table(self):
        page = self._current_page()
        size = self._current_page_size()
        proxies = self._db.get_all_proxies(page=page, page_size=size)
        total = self._db.count_proxies()
        self._model.load(proxies, total, page, size)
        self._rotator.load_proxies(self._db.get_all_proxies(status="valid"))
        cur = self._rotator.get_current()
        self._current_proxy_label.setText(f"当前代理: {cur.host}:{cur.port}" if cur else "当前代理: None")

    def _prev_page(self):
        p = max(1, self._current_page() - 1)
        self._page_label.setText(str(p))
        self._refresh_table()

    def _next_page(self):
        size = self._current_page_size()
        total = self._db.count_proxies()
        max_page = max(1, (total + size - 1) // size)
        p = min(max_page, self._current_page() + 1)
        self._page_label.setText(str(p))
        self._refresh_table()

    def _log_event(self, msg: str):
        self._log.append(msg)

    def _update_status(self, state: str):
        port = self._config.listen_port
        if state == "running":
            self._status_bar.showMessage(
                f"代理运行中: socks5://127.0.0.1:{port}", 0
            )
            self._status_bar.setStyleSheet("color: green;")
        elif state == "no_upstream":
            self._status_bar.showMessage(
                f"运行中（无可用上游代理）: socks5://127.0.0.1:{port}", 0
            )
            self._status_bar.setStyleSheet("color: orange;")
        else:
            self._status_bar.showMessage(f"代理关闭: socks5://127.0.0.1:{port}", 0)
            self._status_bar.setStyleSheet("color: red;")

    # ── SOCKS Server ─────────────────────────────────────────────────────────

    def _on_start(self):
        if self._socks_thread and self._socks_thread.isRunning():
            return
        self._socks_thread = SocksServerThread(self._rotator, self._config.listen_port)
        self._socks_thread.status_changed.connect(self._update_status)
        self._socks_thread.client_connected.connect(
            lambda s: self._log_event(f"[连接] {s}")
        )
        self._socks_thread.start()
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._log_event(f"[服务器] 启动于 127.0.0.1:{self._config.listen_port}")

    def _on_stop(self):
        if self._socks_thread:
            self._socks_thread.stop()
            self._socks_thread.wait(3000)
            self._socks_thread = None
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._update_status("stopped")
        self._log_event("[服务器] 已关闭")

    # ── Rotation Mode ─────────────────────────────────────────────────────────

    def _on_mode_changed(self, idx: int):
        _, mode = _MODE_LABELS[idx]
        show_spin = mode in (RotationMode.BY_COUNT,)
        show_time = mode in (RotationMode.BY_TIME,)
        show_input = mode in (RotationMode.BY_SCENE, RotationMode.BY_KEYWORD)
        self._param_spin.setVisible(show_spin or show_time)
        self._param_label.setVisible(show_spin or show_time)
        self._param_input.setVisible(show_input)
        if show_spin:
            self._param_label.setText("次数:")
        elif show_time:
            self._param_label.setText("分钟:")
        params = {}
        if show_spin:
            params["threshold"] = self._param_spin.value()
        elif show_time:
            params["interval_minutes"] = self._param_spin.value()
        elif show_input:
            params["trigger_word"] = self._param_input.text()
        self._rotator.set_mode(mode, **params)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_add_single(self):
        dlg = AddProxyDialog(self)
        if dlg.exec():
            p = dlg.get_proxy()
            if p:
                self._db.upsert_proxy(p)
                self._log_event(f"[添加] {p.host}:{p.port}")
                self._refresh_table()

    def _on_add_batch(self):
        dlg = BatchAddDialog(self)
        if dlg.exec():
            proxies = dlg.get_proxies()
            self._db.upsert_proxies(proxies)
            self._log_event(f"[批量添加] {len(proxies)} 个代理")
            self._refresh_table()

    def _on_auto_crawl(self):
        dlg = AutoCrawlDialog(self)
        if dlg.exec():
            config = dlg.get_config()
            self._log_event(f"[爬取] 配置: {config}")
            # CrawlerThread 启动（Task 15 补充）

    def _on_validate(self):
        all_proxies = self._db.get_all_proxies()
        if not all_proxies:
            QMessageBox.information(self, "提示", "没有可验证的代理")
            return
        self._validator_thread = ValidatorThread(
            proxies=all_proxies,
            endpoint=self._config.validator_endpoint,
            backup_endpoint=self._config.validator_endpoint_backup,
            timeout=self._config.validator_timeout,
            concurrency=self._config.validator_concurrency,
        )
        self._validator_thread.result_ready.connect(self._on_validation_result)
        self._validator_thread.progress.connect(
            lambda done, total: self._log_event(f"[验证] {done}/{total}")
        )
        self._validator_thread.finished.connect(self._refresh_table)
        self._validator_thread.start()
        self._log_event(f"[验证] 开始验证 {len(all_proxies)} 个代理")

    def _on_validation_result(self, result: ValidationResult):
        self._db.update_validation(result)

    def _on_batch_manage(self):
        selected = self._table.selectedIndexes()
        count = len(set(i.row() for i in selected))
        dlg = BatchManageDialog(count, self)
        dlg.delete_invalid.connect(self._delete_invalid)
        dlg.exec()

    def _delete_invalid(self):
        invalid = [p for p in self._db.get_all_proxies() if p.status == "invalid"]
        self._db.delete_proxies([p.id for p in invalid])
        self._log_event(f"[管理] 删除 {len(invalid)} 个无效代理")
        self._refresh_table()

    def _on_export(self):
        proxies = self._db.get_all_proxies()
        dlg = ExportDialog(proxies, self)
        dlg.exec()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._on_stop()
        self._db.close()
        event.accept()
```

- [ ] **Step 2: 验证启动（需要显示器，CI 环境跳过）**

```bash
python main.py &
sleep 3 && kill %1 || true
```

Expected: 无 ImportError，进程正常退出。

- [ ] **Step 3: Commit**

```bash
git add app/ui/main_window.py
git commit -m "feat: main window with proxy table, controls, and all dialogs"
```

---

### Task 15: CrawlerThread 集成

**Files:**
- Create: `app/core/crawler_thread.py`
- Modify: `app/ui/main_window.py` (补充 `_on_auto_crawl` 内 CrawlerThread 启动)

**Interfaces:**
- Produces: `CrawlerThread(AsyncWorkerThread)`，signals: `found(int)`, `finished(list[ProxyCandidate])`, `log(str)`

- [ ] **Step 1: 写 app/core/crawler_thread.py**

```python
from __future__ import annotations
import asyncio
import aiohttp
from PyQt6.QtCore import pyqtSignal
from app.core.worker_thread import AsyncWorkerThread
from app.core.crawlers.fofa import FofaCrawler
from app.core.crawlers.quake import QuakeCrawler
from app.core.crawlers.hunter import HunterCrawler
from app.core.crawlers.free_sites import FreeSitesCrawler
from app.db.models import ProxyCandidate


class CrawlerThread(AsyncWorkerThread):
    found = pyqtSignal(int)                    # 累计发现数量
    finished = pyqtSignal(list)                # list[ProxyCandidate]
    log = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self._config = config

    async def main(self):
        all_candidates: list[ProxyCandidate] = []
        seen: set[tuple] = set()

        async with aiohttp.ClientSession() as session:
            tasks = []
            cfg = self._config

            if cfg.get("fofa", {}).get("enabled"):
                fc = FofaCrawler(cfg["fofa"]["api_key"])
                tasks.append(fc.crawl(session, cfg["fofa"], cfg["fofa"]["limit"]))

            if cfg.get("quake", {}).get("enabled"):
                qc = QuakeCrawler(cfg["quake"]["api_key"])
                tasks.append(qc.crawl(session, cfg["quake"], cfg["quake"]["limit"]))

            if cfg.get("hunter", {}).get("enabled"):
                hc = HunterCrawler(cfg["hunter"]["api_key"])
                tasks.append(hc.crawl(session, cfg["hunter"], cfg["hunter"]["limit"]))

            if cfg.get("free", {}).get("enabled"):
                free_cfg = cfg["free"]
                fc2 = FreeSitesCrawler(free_cfg.get("proxy_type", "socks5"),
                                       free_cfg.get("limit", 20))
                tasks.append(fc2.crawl(session, {}, free_cfg.get("limit", 20)))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for result in results:
                if isinstance(result, Exception):
                    self.log.emit(f"[爬虫] 错误: {result}")
                    continue
                for c in result.candidates:
                    key = (c.host, c.port, c.type, c.username)
                    if key not in seen:
                        seen.add(key)
                        all_candidates.append(c)
                if result.quota_exhausted:
                    self.log.emit(f"[爬虫] {result.source} 额度已耗尽")
                self.found.emit(len(all_candidates))

        self.finished.emit(all_candidates)
```

- [ ] **Step 2: 修改 main_window.py 中 `_on_auto_crawl`**

在 `app/ui/main_window.py` 中，将：

```python
    def _on_auto_crawl(self):
        dlg = AutoCrawlDialog(self)
        if dlg.exec():
            config = dlg.get_config()
            self._log_event(f"[爬取] 配置: {config}")
            # CrawlerThread 启动（Task 15 补充）
```

替换为：

```python
    def _on_auto_crawl(self):
        dlg = AutoCrawlDialog(self)
        if dlg.exec():
            config = dlg.get_config()
            from app.core.crawler_thread import CrawlerThread
            self._crawler_thread = CrawlerThread(config)
            self._crawler_thread.found.connect(
                lambda n: self._log_event(f"[爬取] 已发现 {n} 个候选代理")
            )
            self._crawler_thread.log.connect(self._log_event)
            self._crawler_thread.finished.connect(self._on_crawl_finished)
            self._crawler_thread.start()
            self._log_event("[爬取] 开始爬取...")

    def _on_crawl_finished(self, candidates: list):
        from app.db.models import Proxy
        proxies = [
            Proxy(host=c.host, port=c.port, type=c.type,
                  username=c.username, source=c.source)
            for c in candidates
        ]
        self._db.upsert_proxies(proxies)
        self._log_event(f"[爬取] 完成，新增/更新 {len(proxies)} 个代理")
        self._refresh_table()
```

- [ ] **Step 3: 运行全量测试**

```bash
pytest tests/ -v
```

Expected: 全部通过，无失败。

- [ ] **Step 4: Commit**

```bash
git add app/core/crawler_thread.py app/ui/main_window.py
git commit -m "feat: CrawlerThread integrating all crawl sources"
```

---

### Task 16: 最终验收

- [ ] **Step 1: 全量测试**

```bash
pytest tests/ -v --tb=short
```

Expected: 全部通过。

- [ ] **Step 2: 启动应用，手动验证**

```bash
python main.py
```

检查清单：
- [ ] 主窗口正常显示，列表为空（No Data）
- [ ] 单个添加代理 → 代理出现在列表中
- [ ] 批量添加 `1.2.3.4:1080` → 正常解析
- [ ] 模式切换 → 参数区随之变化
- [ ] 启动代理 → 状态栏变绿，显示 `socks5://127.0.0.1:51024`
- [ ] 关闭代理 → 状态栏变红
- [ ] 导出 → 生成文件，内容正确，密码脱敏

- [ ] **Step 3: 最终 Commit**

```bash
git add -A
git commit -m "chore: final integration and manual verification"
```
