# 代理池桌面应用 设计文档

**日期：** 2026-06-26（经 Codex 评审修订）
**技术栈：** Python 3.11+ · PyQt6 · asyncio · SQLite

---

## 一、项目概述

一个 Python + PyQt6 桌面应用，功能：

1. 本地运行 SOCKS5 代理服务器（监听 `127.0.0.1:PORT`，其他应用通过它上网）
2. 代理池管理（添加、验证、导出代理列表）
3. 六种代理切换模式（round-robin / failover / 按次数 / 按时间 / 按场景 / 固定）
4. 自动爬取代理来源（Fofa API、QuaKe API、Hunter API、免费代理站）
5. 代理验证（延迟测试、HTTP 验证、匿名性检测、地区识别）
6. SQLite 持久化存储

---

## 二、架构：单进程 + QThread

```
主进程
├── Qt 主线程（UI）
│   ├── MainWindow
│   ├── ProxyTableModel（QAbstractTableModel）
│   └── 各对话框（添加 / 爬取 / 验证 / 导出）
│
├── SocksServerThread（QThread）
│   └── asyncio event loop → 手写 SOCKS5 CONNECT 服务器
│       └── 出站连接通过 python-socks 走上游代理
│
├── ValidatorThread（QThread）
│   └── asyncio event loop → aiohttp + aiohttp-socks 并发验证
│
└── CrawlerThread（QThread）
    └── asyncio event loop → Fofa / QuaKe / Hunter / 免费站爬取
```

**线程通信原则：**
- 后台线程 → UI：只通过 Qt Signal 发数据，绝不直接操作 QWidget
- UI → 后台线程：通过 `loop.call_soon_threadsafe()` 或 `asyncio.run_coroutine_threadsafe()`
- 停止线程：手动 cancel asyncio task，不依赖 `QThread.quit()`

**AsyncWorkerThread 基类：**

```python
class AsyncWorkerThread(QThread):
    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.task = self.loop.create_task(self.main())
        try:
            self.loop.run_until_complete(self.task)
        finally:
            pending = asyncio.all_tasks(self.loop)
            for t in pending: t.cancel()
            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    def stop(self):
        if hasattr(self, "loop") and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.task.cancel)

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)
```

---

## 三、目录结构

```
ProxyPool/
├── main.py                        # 入口，初始化 QApplication
├── requirements.txt
├── app/
│   ├── ui/
│   │   ├── main_window.py         # 主窗口
│   │   ├── proxy_table.py         # QAbstractTableModel 实现
│   │   └── dialogs/
│   │       ├── add_proxy.py       # 单个添加
│   │       ├── batch_add.py       # 批量添加
│   │       ├── auto_crawl.py      # 自动爬取配置
│   │       ├── batch_manage.py    # 批量管理
│   │       └── export_proxy.py    # 导出代理
│   ├── core/
│   │   ├── worker_thread.py       # AsyncWorkerThread 基类
│   │   ├── socks_server.py        # 本地 SOCKS5 服务器 + 线程
│   │   ├── rotator.py             # 代理切换逻辑
│   │   ├── validator.py           # 代理验证 + 线程
│   │   └── crawlers/
│   │       ├── base.py            # BaseCrawler 抽象类
│   │       ├── fofa.py
│   │       ├── quake.py
│   │       ├── hunter.py
│   │       └── free_sites.py
│   ├── db/
│   │   ├── database.py            # 连接、迁移、Repository API
│   │   └── models.py              # 类型化数据类
│   └── config.py                  # 用户配置读写（platformdirs）
└── data/
    └── proxies.db                 # SQLite 数据库（运行时创建）
```

---

## 四、数据模型

### proxies 表

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `host` | TEXT NOT NULL | |
| `port` | INTEGER NOT NULL | |
| `type` | TEXT NOT NULL | `socks5` / `socks4` / `http` / `https` |
| `username` | TEXT NOT NULL DEFAULT '' | 无认证时为空字符串 |
| `password` | TEXT NOT NULL DEFAULT '' | 见敏感信息策略 |
| `region` | TEXT NOT NULL DEFAULT '' | 地区，如 `CN-广东` |
| `latency` | REAL NOT NULL DEFAULT -1 | 延迟 ms，`-1` 表示未测 |
| `status` | TEXT NOT NULL DEFAULT 'unknown' | `valid` / `invalid` / `unknown` |
| `anonymity` | TEXT NOT NULL DEFAULT '' | `high` / `medium` / `transparent` |
| `supports_rdns` | INTEGER NOT NULL DEFAULT 1 | 是否支持远端域名解析（SOCKS4 可能不支持） |
| `auth_required` | INTEGER NOT NULL DEFAULT 0 | 是否需要认证 |
| `last_checked` | TIMESTAMP | 最近验证时间 |
| `last_success_at` | TIMESTAMP | 最近验证成功时间 |
| `last_failed_at` | TIMESTAMP | 最近验证失败时间 |
| `fail_count` | INTEGER NOT NULL DEFAULT 0 | 历史总失败次数 |
| `consecutive_failures` | INTEGER NOT NULL DEFAULT 0 | 连续失败次数（重置于成功） |
| `use_count` | INTEGER NOT NULL DEFAULT 0 | 被 Rotator 分配次数 |
| `source` | TEXT NOT NULL DEFAULT 'manual' | `fofa` / `quake` / `hunter` / `free` / `manual` |
| `created_at` | TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP | 任意字段变更时更新 |

```sql
-- 唯一约束：username 规范为 NOT NULL DEFAULT ''，避免 COALESCE
CREATE UNIQUE INDEX idx_proxy_identity
ON proxies(host, port, type, username);

CREATE INDEX idx_proxy_status ON proxies(status);
CREATE INDEX idx_proxy_last_checked ON proxies(last_checked);
CREATE INDEX idx_proxy_latency ON proxies(latency);
```

**写入策略：** 使用 `INSERT ... ON CONFLICT(host, port, type, username) DO UPDATE SET ...`，保留原有 `id / created_at / use_count`，不用 `INSERT OR REPLACE`（后者会重置这些字段）。

### proxy_checks 历史表

记录最近 N 次验证结果，用于判断代理稳定性。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `proxy_id` | INTEGER NOT NULL REFERENCES proxies(id) | |
| `checked_at` | TIMESTAMP NOT NULL | |
| `latency` | REAL | |
| `success` | INTEGER NOT NULL | 0 / 1 |
| `error` | TEXT | 失败原因 |
| `endpoint` | TEXT | 验证端点 URL |

保留每个代理最近 20 条，定期清理旧记录。

### app_config 表

| 字段 | 类型 |
|---|---|
| `key` | TEXT PRIMARY KEY |
| `value` | TEXT（JSON 序列化） |

存储内容：监听端口、代理模式及参数、Fofa/QuaKe/Hunter API Key 引用名、查询语法、验证端点、并发数、分页大小。

**敏感信息策略：**
- API Key 和代理密码存系统 **keyring**（`keyring` 库），`app_config` / `proxies` 只存 keyring 引用键
- 日志和导出**永不**打印完整代理 URL（含密码）
- 导出时默认脱敏（`socks5://user:***@host:port`），用户可选明文导出

### SQLite 配置

```python
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA busy_timeout=5000;")
conn.execute("PRAGMA synchronous=NORMAL;")
conn.execute("PRAGMA foreign_keys=ON;")
```

**DB 线程设计：** `database.py` 内部维护单一写线程 + 内部队列，所有写操作串行化。读操作允许在同一 WAL 连接上并发读，但必须通过 Repository API，不允许外部直接开连接。

### 类型化数据类

```python
@dataclass
class Proxy:
    id: int = 0
    host: str = ""
    port: int = 0
    type: str = "socks5"
    username: str = ""
    password: str = ""          # 运行时从 keyring 解密后填入，不持久化明文
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
class ProxyEndpoint:          # Rotator 返回的不可变选择结果
    proxy_id: int
    url: str
    supports_rdns: bool

@dataclass
class CrawlerResult:
    source: str
    candidates: list[ProxyCandidate]
    errors: list[str]
    quota_exhausted: bool = False
```

---

## 五、配置持久化

使用 `platformdirs` 确定用户数据目录（跨平台），配置文件存于 `user_data_dir("ProxyPool")`。

```python
from platformdirs import user_data_dir

DATA_DIR = Path(user_data_dir("ProxyPool", appauthor=False))
DB_PATH  = DATA_DIR / "proxies.db"
```

配置项（存 `app_config` 表）：

| 键 | 默认值 | 说明 |
|---|---|---|
| `listen_port` | `51024` | 本地 SOCKS5 监听端口 |
| `rotation_mode` | `round_robin` | 当前轮换模式 |
| `rotation_params` | `{}` | 模式参数（次数/时间/URL/关键词） |
| `validator_concurrency` | `100` | 验证并发数 |
| `validator_timeout` | `10` | 验证超时秒数 |
| `validator_endpoint` | `https://httpbin.org/ip` | 验证端点（可配置） |
| `validator_endpoint_backup` | `https://ip-api.com/json` | 备用端点 |
| `geo_cache_ttl` | `86400` | 地区识别缓存 TTL（秒） |
| `page_size` | `10` | 代理列表分页大小 |
| `export_redact_password` | `true` | 导出时脱敏密码 |

---

## 六、本地 SOCKS5 服务器

**范围：** 只实现 TCP `CONNECT`，不实现 `UDP ASSOCIATE` / `BIND`。只绑 `127.0.0.1`，无认证。

**关键行为：**
- 无可用上游代理时：**保持 listener 存活**，对新连接返回 SOCKS5 reply `0x05` 失败码，同时 UI 显示「无可用上游代理」状态
- 不支持的 `CMD`（非 CONNECT）：返回标准 SOCKS5 reply `\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00`（command not supported），不直接断连
- 不支持的 `ATYP=4`（IPv6）：返回 `\x05\x08\x00\x01...`（address type not supported）
- 域名（`ATYP=3`）：直接透传给上游代理，不在本地解析，防 DNS 泄漏
- 连接超时、半关闭：两端 writer 都显式 `close()` + `wait_closed()`

```python
async def handle_client(client_r, client_w):
    try:
        # 握手：无认证
        ver, nmethods = await client_r.readexactly(2)
        methods = await client_r.readexactly(nmethods)
        if ver != 5 or 0 not in methods:
            client_w.write(b"\x05\xff"); await client_w.drain(); return
        client_w.write(b"\x05\x00"); await client_w.drain()

        # 解析请求
        ver, cmd, _, atyp = await client_r.readexactly(4)
        if cmd != 1:  # 只支持 CONNECT
            client_w.write(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
            await client_w.drain(); return

        if atyp == 1:
            host = socket.inet_ntoa(await client_r.readexactly(4))
        elif atyp == 3:
            n = (await client_r.readexactly(1))[0]
            host = (await client_r.readexactly(n)).decode("idna")
        elif atyp == 4:
            client_w.write(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
            await client_w.drain(); return
        port = struct.unpack("!H", await client_r.readexactly(2))[0]

        # 从 Rotator 获取上游代理
        endpoint = rotator.on_request_start()
        if endpoint is None:  # 无可用代理
            client_w.write(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
            await client_w.drain(); return

        sock = await Proxy.from_url(endpoint.url).connect(host, port, timeout=8)
        remote_r, remote_w = await asyncio.open_connection(sock=sock)
        client_w.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        await client_w.drain()

        await asyncio.gather(relay(client_r, remote_w), relay(remote_r, client_w))
        rotator.on_request_done(endpoint.proxy_id, success=True)
    except Exception:
        pass
    finally:
        client_w.close()
        with contextlib.suppress(Exception): await client_w.wait_closed()
```

---

## 七、代理轮换器（Rotator）

### 核心原则

- **只影响新连接**：代理切换发生在新 TCP CONNECT 时，不中断已有连接
- 模式切换后**立即生效**
- 无可用代理时 listener 保持存活，`on_request_start()` 返回 `None`
- 内部用 `asyncio.Lock` 保护并发安全（多客户端同时建连）

### 六种模式（UI 名称 → 内部模式）

| UI 名称 | 内部模式 | 切换触发 | 选代理策略 | 附加行为 |
|---|---|---|---|---|
| 轮询代理模式 | `round_robin` | 每次新连接 | 顺序循环所有 `valid` 代理 | 无 |
| — | `failover` | 当前代理连接失败 | 顺序切换到下一个 `valid` | 失败才换 |
| 根据次数更换 | `by_count` | `use_count >= threshold` | 顺序下一个 `valid` | 每次 `use_count + 1` |
| 根据时间更换 | `by_time` | 距上次切换 >= T 分钟 | 顺序下一个 `valid` | 后台定时器触发 |
| 根据场景 | `by_scene` | 访问验证 URL 失败 | 顺序下一个 `valid` | 每 2 分钟自动验证当前代理 |
| 根据关键词 | `by_keyword` | 响应含/不含指定词 | 顺序下一个 `valid` | **仅限明文 HTTP**，HTTPS 隧道不可用 |
| 固定代理 | `fixed` | 不切换 | 延迟最低的 `valid` 代理 | 列表变化时重选最优 |

> **关键词模式限制：** SOCKS5 是纯 TCP 隧道，HTTPS 流量加密透传，Rotator 无法读取响应内容。`by_keyword` 只对**明文 HTTP**（`http://` 请求）生效；对 HTTPS 连接，UI 应灰显或提示不支持。

### 接口

```python
class ProxyRotator:
    async def on_request_start(self) -> ProxyEndpoint | None  # 新连接，返回不可变端点
    async def on_request_done(self, proxy_id: int, success: bool)
    async def on_response_body(self, proxy_id: int, body: bytes)  # by_keyword 专用
    async def force_switch(self)
    def set_mode(self, mode: RotationMode, **params)           # 同步，立即生效
    def get_available_proxies(self) -> list[Proxy]
```

---

## 八、代理验证

**验证顺序（短路）：** 连通性+延迟 → HTTP 验证 → 匿名性 → 地区识别
只对连通成功的代理做后续步骤，节省 API 配额。

```python
async def validate_all(proxies, sem_size=100, progress_signal=None):
    sem = asyncio.Semaphore(sem_size)
    results = []
    done = 0

    async def one(proxy):
        nonlocal done
        async with sem:
            result = await validate_single(proxy)
            done += 1
            if done % 20 == 0 or done == len(proxies):
                progress_signal and progress_signal.emit(done, len(proxies))
            return result

    results = await asyncio.gather(*(one(p) for p in proxies))
    # 批量落库
    await db.batch_upsert_validation_results(results)
    return results
```

**验证步骤：**

1. **连通性 + 延迟**：通过代理 GET 验证端点（默认 `https://httpbin.org/ip`），记录 RTT；失败 → `status=invalid`，后续步骤跳过
2. **HTTP 验证**：检查响应状态码 200
3. **匿名性**：对比响应 IP 与本机 IP → `high`（完全隐藏）/ `medium`（部分透露）/ `transparent`（暴露原 IP）
4. **地区识别**：查询 `ip-api.com/json/{proxy_ip}`，结果缓存 `geo_cache_ttl` 秒（默认 24 小时），避免重复调用

**验证端点：** 可在配置中修改，主端点失败自动降级到备用端点。

---

## 九、爬虫模块

### 统一接口

```python
@dataclass
class ProxyCandidate:
    host: str; port: int; type: str; source: str
    username: str = ""; password: str = ""

class BaseCrawler(ABC):
    name: str
    rate_limit: float = 1.0       # 请求间隔秒数

    @abstractmethod
    async def fetch_page(self, session, query: str, cursor) -> CrawlPage: ...

    async def crawl(self, session, config: dict, limit: int) -> CrawlerResult:
        cursor, seen, errors = None, [], []
        while len(seen) < limit:
            try:
                page = await self.fetch_page(session, config["query"], cursor)
                seen.extend(page.items)
                if page.next_cursor is None: break
                cursor = page.next_cursor
                await asyncio.sleep(self.rate_limit)
            except RateLimited as e:
                await asyncio.sleep(e.retry_after)
            except QuotaExhausted:
                return CrawlerResult(self.name, seen, errors, quota_exhausted=True)
            except Exception as e:
                errors.append(str(e)); break
        return CrawlerResult(self.name, seen, errors)

    async def test_auth(self, session) -> bool: ...  # 验证 API Key 有效性
```

### 各平台 Adapter

**FofaCrawler**
- 查询语法 base64 编码，`fields=ip,port,protocol,country_name`
- 默认语法：`protocol=="socks5" && "Version:5 Method:No Authentication(0x00)"`
- 分页：`page` + `size`；按 `429` / 平台错误码退避

**QuakeCrawler**
- POST JSON，`X-QuakeToken` header 认证
- 分页：`start` + `size`；返回结构需 normalize

**HunterCrawler**
- GET，`api-key` 参数认证
- 分页：`page` + `page_size`，`asset_type=0`

**FreeSitesCrawler**
- 内置 3-5 个站点解析器（`beautifulsoup4` 解析 HTML），各自隔离
- 单站失败不中断整体爬取

### 凭据补全（原"密码破解"）

仅对用户**明确导入且声明拥有授权**的代理（`auth_required=1` 且 `status=invalid`），使用用户自己提供的账号密码列表逐一尝试连接。启用前 UI 显示警告，并要求用户勾选确认框。

### 去重

```python
unique_key = (host, port, type, username)  # username 已规范为 NOT NULL DEFAULT ''
```

所有来源汇总后按此键去重，再批量 `INSERT ... ON CONFLICT DO UPDATE` 落库。

---

## 十、UI 交互

### 主窗口布局

```
┌──────────────────────────────────────────────────────────────────┐
│ [启动代理] [关闭代理]  代理配置：模式[▼] 参数  当前代理: xxx:port     │
│ [单个添加][批量添加][自动爬取][代理验证][批量管理][导出代理]           │
├──────────────────────────────────────────────────────────────────┤
│ # │ Host🔍 │ Port🔍 │ 类型🔍 │ 地区🔍 │ 延时↕ │ 状态↕ │ 匿名性 │ 操作 │
├──────────────────────────────────────────────────────────────────┤
│  （QAbstractTableModel，分页渲染，禁用 QTableWidget 直接承载大数据）  │
├──────────────────────────────────────────────────────────────────┤
│ ◀ 1 ▶                                                10/page ▼   │
└──────────────────────────────────────────────────────────────────┘
```

底部建议增加**事件日志面板**（折叠式），显示爬虫进度、验证结果、代理切换事件，便于排障。

### 模式参数联动

| 模式 | 参数区 |
|---|---|
| 轮询 / Failover | 无 |
| 根据次数 | `设置次数 [30] 次切换` |
| 根据时间 | `每隔 [5] 分钟切换` |
| 根据场景 | `验证URL [__________]` |
| 根据关键词 | `触发词 [____]  必需词 [____]`（⚠️ 仅明文 HTTP 有效） |
| 固定代理 | 无（自动选延迟最低） |

### SOCKS5 状态显示

- 运行中：`代理运行中: socks5://127.0.0.1:51024`（绿色）
- 无可用代理：`运行中（无可用上游代理）`（橙色）—— listener 保持存活
- 已关闭：`代理关闭: socks5://127.0.0.1:51024`（红色）

### 批量添加支持格式

```
socks5://host:port
socks5://user:pass@host:port
host:port          # 默认 socks5
```

### 每行操作列

`[验证]` `[编辑]` `[删除]`

---

## 十一、依赖清单

| 库 | 版本约束 | 用途 |
|---|---|---|
| `PyQt6` | >=6.6 | UI 框架 |
| `python-socks` | >=2.4 | 出站 SOCKS5 客户端连接器 |
| `aiohttp` | >=3.9 | 异步 HTTP（验证、爬虫） |
| `aiohttp-socks` | >=0.8 | aiohttp 通过 SOCKS 代理 |
| `keyring` | >=25 | API Key / 代理密码安全存储 |
| `beautifulsoup4` | >=4.12 | 免费代理站 HTML 解析 |
| `lxml` | >=5.0 | BS4 解析器后端 |
| `platformdirs` | >=4.0 | 跨平台用户数据目录 |
| `pyinstaller` | >=6.0 | 打包为独立可执行文件 |

**开发依赖：**

| 库 | 用途 |
|---|---|
| `pytest` | 测试框架 |
| `pytest-qt` | PyQt6 测试支持 |
| `pytest-asyncio` | asyncio 测试支持 |
| `pytest-mock` | Mock 工具 |

---

## 十二、已知边界与风险

| 类别 | 风险 | 处理方式 |
|---|---|---|
| 功能边界 | UDP 不支持 | MVP 明确不实现，UI 说明 |
| 功能边界 | HTTPS 关键词模式无效 | 隧道透传，UI 灰显并提示 |
| 并发安全 | 多客户端并发切换代理 | Rotator 内部 `asyncio.Lock` |
| 连接生命周期 | 代理切换不断现有连接 | 只在新 CONNECT 时切换 |
| 网络 | 端口占用 | 启动前检测端口，失败时提示更换 |
| 网络 | 无可用代理 | listener 存活，返回 SOCKS5 failure，UI 橙色提示 |
| 渲染性能 | 大量代理渲染 | QAbstractTableModel + 分页，不用 QTableWidget |
| 安全 | API Key / 密码明文 | keyring 存储，日志脱敏，导出默认脱敏 |
| 安全 | 代理 MITM 风险 | UI 提示用户不要通过不可信代理传输敏感凭据 |
| 合规 | 凭据补全滥用 | 要求用户勾选授权确认框，明确仅用于自有代理 |
| 配额 | API 额度耗尽 | `QuotaExhausted` 异常，UI 提示，部分结果仍可用 |
| 维护 | 免费站结构变化 | 各站点解析器独立隔离，单站失败不中断 |
| 数据 | DB 迁移失败 | 版本号存 `PRAGMA user_version`，迁移前备份 DB 文件 |
| 数据 | WAL 文件膨胀 | 定期 `PRAGMA wal_checkpoint(TRUNCATE)` |
| 分发 | 打包问题 | PyInstaller + PyQt6 platform plugins + CA 证书 |
| 分发 | Windows 防火墙 | 只绑 `127.0.0.1` 减少弹窗风险 |
