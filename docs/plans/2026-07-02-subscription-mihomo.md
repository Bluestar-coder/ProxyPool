# 机场订阅支持（mihomo 内核）实现计划

Created: 2026-07-02
Author: liu892981282@gmail.com
Agent: Claude Code
Status: VERIFIED
Approved: Yes
Iterations: 0
Worktree: No
Type: Feature

## Summary

**Goal:** 用户可通过新增的"订阅"对话框输入机场订阅链接，应用自动解析 Clash YAML 格式的节点列表，借助 mihomo 内核批量测试延时，并将有效节点以 `source="subscription"` 写入现有代理数据库。

## Out of Scope

- 订阅代理通过现有 SOCKS5 旋转器转发流量（mihomo 不作为常驻 sidecar）
- 对非 Clash YAML 格式的个人 URI 行（vmess://、trojan://、ss://）的解析
- 现有"全部验证"按钮对 VMess/Trojan 类型代理的处理（会因 aiohttp-socks 不支持该协议而报 InvalidURL；行为与现有对 broken proxies 的处理一致，不影响正常 SOCKS5 代理）

## Approach

**Chosen:** 独立 `SubscriptionThread`（同 `ValidatorThread` 架构），临时启动 mihomo 子进程，通过 REST API `/proxies/{name}/delay` 批量测速，测完即关。

**Why:** 不需要 mihomo 常驻，资源占用最小；与现有 `AsyncWorkerThread` 模式完全一致，代码结构清晰；mihomo 子进程隔离，崩溃不影响主进程（舍弃了 mihomo 作为 sidecar 带来的低延时复用，但一次性测速场景无需该优势）。

## Context for Implementer

`AsyncWorkerThread` 的 `run()` 已处理事件循环生命周期，子类只需实现 `async def main()`。在 `main()` 中启动 `subprocess.Popen` 完全安全——Python 事件循环与 OS 进程调度无冲突；`asyncio.create_subprocess_exec` 可选但不必须。

订阅 URL 含 auth token，与 FOFA Key 一样存 keyring（`keyring.set_password("ProxyPool", "subscription_urls", json.dumps([...]))`），不写入数据库，不打印到日志。

`proxies` 表的 unique index 是 `(host, port, type, username)`：VMess 节点 `type="vmess"` 与 SOCKS5 节点 `type="socks5"` 不会冲突，现有 `upsert_proxies()` 直接可用，无需改 schema。

## File Structure

- `app/core/mihomo_manager.py` (create) — 二进制下载 + MihomoProcess 生命周期管理
- `app/core/subscription.py` (create) — 订阅解析、延时测试、SubscriptionThread
- `app/ui/dialogs/subscription.py` (create) — 订阅管理对话框
- `app/ui/main_window.py` (modify) — 添加"订阅"按钮 + 回调
- `tests/test_subscription.py` (create) — 订阅解析单元测试
- `tests/test_mihomo_manager.py` (create) — 平台资源名检测单元测试

## Assumptions

- GitHub Releases 的资源文件命名遵循 `mihomo-{os}-{arch}-{tag}` 格式，gz 压缩（非 Windows）或 zip（Windows）— Task 1 依赖此假设

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| GitHub API 请求 429 / 下载超时 | 低 | 高 | 下载前先检查 BINARY_PATH，存在则跳过；下载失败 emit log + finished([])，不崩溃 |
| mihomo 启动端口冲突 | 低 | 中 | 用 `socket.bind(("",0))` 动态分配端口，不硬编码 |
| 订阅 YAML 解析失败 | 中 | 中 | `_parse_subscription` try/except，失败返回 `[]`，线程 emit log |
| mihomo 启动超时（5s 等待） | 低 | 中 | 超时后调用 `proc.stop()`，emit log + finished([]) |

## Progress Tracking

- [x] Task 1: MihomoManager — 二进制下载与进程管理
- [x] Task 2: 订阅解析 + SubscriptionThread
- [x] Task 3: SubscriptionDialog UI
- [x] Task 4: 主窗口集成（按钮 + 回调）
- [x] Task 5: 单元测试

## Implementation Tasks

---

### Task 1: MihomoManager — 二进制下载与进程管理

**Objective:** 创建 `app/core/mihomo_manager.py`，实现 mihomo 二进制的自动下载（`~/.proxy_pool/core/mihomo`）和进程生命周期管理。此模块是其余任务的基础，独立可测。

**Files:**

- Create: `app/core/mihomo_manager.py`
- Test: `tests/test_mihomo_manager.py`

**Key Decisions / Notes:**

- `BINARY_DIR = Path.home() / ".proxy_pool" / "core"`；Windows 在文件名加 `.exe`
- `ensure_binary(log_cb: Callable | None)` 为 async 函数；先检查 `BINARY_PATH.exists()`，存在直接返回
- GitHub API: `https://api.github.com/repos/MetaCubeX/mihomo/releases/latest`；解析 `tag_name` 和 `assets[].browser_download_url`
- 平台资源名规则：`mihomo-darwin-{arch}-{tag}.gz`（macOS）、`mihomo-linux-{arch}-{tag}.gz`、`mihomo-windows-{arch}-{tag}.zip`；arch 从 `platform.machine()` 映射（`x86_64`/`amd64` → `amd64`，`arm64`/`aarch64` → `arm64`）
- gz 解压：`gzip.decompress(content)`；zip 解压：取 zip 内含 "mihomo" 的第一个条目
- `MihomoProcess(config_path, api_port)` — `start(timeout=5.0)` 启动子进程，轮询 `GET /version` 直到 200 或超时；`stop()` 先 `terminate()`，3s 后 `kill()`
- `_find_free_port()` TOCTOU 处理：`start()` 内部捕获 mihomo 启动失败（通过 poll() 检测进程立即退出），换一个新端口重试一次，而非在分配时保持 socket 打开
- 所有 `log_cb` 调用格式：`"[订阅] ..."` 前缀

**Definition of Done:**

- [ ] `ensure_binary()` 在 `BINARY_PATH` 已存在时直接返回，不发出任何网络请求
- [ ] `_platform_asset_name()` 对 darwin/arm64、darwin/amd64、linux/amd64、windows/amd64 各返回正确名称
- [ ] `MihomoProcess.stop()` 在进程已不存在时不抛异常
- [ ] Verify: `uv run pytest tests/test_mihomo_manager.py -q`

---

### Task 2: 订阅解析 + SubscriptionThread

**Objective:** 创建 `app/core/subscription.py`，实现订阅内容解析和 mihomo 批量延时测试，最终封装为 `SubscriptionThread`（继承 `AsyncWorkerThread`）供主窗口调用。

**Files:**

- Create: `app/core/subscription.py`
- Modify: `requirements.txt` (add `pyyaml>=6.0`)
- Test: `tests/test_subscription.py`

**Key Decisions / Notes:**

- `_parse_subscription(text: str) -> list[dict]`：先尝试 base64 解码（`base64.b64decode(text + "==")`），若解码后含 `proxies:` 则替换为解码内容；再 `yaml.safe_load()`，取 `data["proxies"]` 列表（若无 `proxies` 键则返回 `[]`）
- 多订阅合并去重：汇总各 URL 的 configs 后，若节点名冲突则加前缀 `f"sub{i}_{name}"`（i 为 URL 序号），确保 mihomo config 内 `name` 唯一
- `async def test_proxies(configs, api_port, log_cb, concurrency=20)` → `list[SubscriptionResult]`：并发用 `asyncio.Semaphore`；延时测试 URL 固定为 `http://www.gstatic.com/generate_204`，请求：`GET http://127.0.0.1:{api_port}/proxies/{quote(name)}/delay?url=http://www.gstatic.com/generate_204&timeout=5000`；`urllib.parse.quote(name, safe="")` 处理中文名
- `SubscriptionResult` dataclass：`name, host, port, proxy_type, latency_ms(-1=fail), success`
- `SubscriptionThread` 信号：`progress = pyqtSignal(int, int)`, `log = pyqtSignal(str)`, `finished = pyqtSignal(list)`；`__init__` 接收 `urls: list[str]`
- `main()` 流程：遍历 urls → fetch_and_parse → 汇总 configs → ensure_binary → 写 temp config → MihomoProcess.start() → test_proxies → stop() → 构造 Proxy 列表 emit
- 构造 Proxy 时 username 字段映射（影响唯一索引 `(host, port, type, username)`）：VMess → `username=config.get("uuid", "")`, Trojan/SS → `username=config.get("password", "")`, SOCKS5 → `username=config.get("username", "")`；`password` 字段均置空（凭据语义已在 username 中，不入库明文密码）
- 构造 Proxy 时其余字段：`source="subscription"`, `status="valid"/"invalid"`, `latency=latency_ms`；`host=config["server"]`, `port=config["port"]`, `type=config["type"]`
- 安全：订阅 URL 不写入日志；`log.emit` 只输出节点数量、进度、错误类型，不含 URL 或节点 password
- mihomo temp config（写入 `tempfile.mkdtemp()`，在 try/finally 中 `shutil.rmtree(tmp_dir, ignore_errors=True)` 清理）：`mixed-port: 0`, `log-level: silent`, `external-controller: 127.0.0.1:{api_port}`, `proxies: [...]`, `proxy-groups: [{name: PROXY, type: select, proxies: [<所有节点名>]}]`, `rules: ["MATCH,PROXY"]`；若 `configs` 为空则跳过 mihomo，直接 emit finished([])
- `_find_free_port()`: `socket.socket(); s.bind(("127.0.0.1", 0)); return s.getsockname()[1]`

**Definition of Done:**

- [ ] `pyyaml>=6.0` 已添加到 `requirements.txt`，`uv pip install -r requirements.txt` 成功
- [ ] `_parse_subscription` 能正确解析标准 Clash YAML（含 vmess、trojan、ss 节点）
- [ ] `_parse_subscription` 能正确解析 base64 编码的 Clash YAML
- [ ] `_parse_subscription` 对空内容、纯 URI 列表、乱码均返回 `[]` 不抛异常
- [ ] `SubscriptionThread.__new__` 模式下 `main()` 可被单独测试（参考 `TestValidatorMain`）
- [ ] Verify: `uv run pytest tests/test_subscription.py -q`

---

### Task 3: SubscriptionDialog UI

**Objective:** 创建 `app/ui/dialogs/subscription.py`，提供订阅 URL 列表管理（增删）及导入触发，订阅 URL 通过 keyring 持久化。

**Files:**

- Create: `app/ui/dialogs/subscription.py`

**Key Decisions / Notes:**

- keyring key：`keyring.get_password("ProxyPool", "subscription_urls")` → JSON list；`keyring.set_password(...)` 保存
- 布局参考 `auto_crawl.py`：一个 `QGroupBox("订阅链接")` + `QListWidget` 显示 URL 列表（显示时截断 token 参数：`url[:60] + "..."` 若超长）；右侧 `[添加] [删除]` 按钮
- "添加"弹出 `QInputDialog.getText`，输入完整 URL；URL 不做合法性校验（用户自己负责）
- 并发数 SpinBox（1-100，默认 20）
- `get_config() -> dict`：返回 `{"urls": [...], "concurrency": int}`；URL 从 keyring 读

**Definition of Done:**

- [ ] 输入 URL 并点击"添加"后，URL 出现在列表中且重启 app 后仍保留（keyring 持久化）
- [ ] "删除"移除选中 URL，keyring 同步更新
- [ ] 对话框在没有 URL 时点击"导入"弹出提示（`QMessageBox`），不触发线程

---

### Task 4: 主窗口集成

**Objective:** 在 `app/ui/main_window.py` 中为"订阅"功能添加入口按钮、线程启动逻辑和完成回调，与"自动爬取"的集成模式保持一致。

**Files:**

- Modify: `app/ui/main_window.py`

**Key Decisions / Notes:**

- 在 `_build_action_bar()` 的 `btns` 列表中，`"批量管理"` 之后追加 `("订阅", self._on_subscription)`
- `self._subscription_thread: SubscriptionThread | None = None`（同 `_crawler_thread` 初始化位置）
- `closeEvent()` 中的线程清理元组（约 main_window.py:822）加入 `self._subscription_thread`，确保应用关闭时 mihomo 子进程被 terminate
- `_on_subscription()` 参考 `_on_auto_crawl()`：检查线程是否在运行 → 打开 dialog → 取 config → 创建 thread → 连接信号 → start
- `_on_subscription_finished(proxies: list[Proxy])`：`self._db.upsert_proxies(proxies)` → `valid_count = sum(1 for p in proxies if p.status == "valid")` → `self._log_event(f"[订阅] 完成，有效 {valid_count}/{len(proxies)} 个节点")` → `self._refresh_table()`
- 信号连接：`progress` → log ("已测试 {done}/{total}")；`log` → `_log_event`；`finished` → `_on_subscription_finished`；`error_occurred` → log

**Definition of Done:**

- [ ] Action Bar 出现"订阅"按钮，点击后弹出 SubscriptionDialog
- [ ] 取消对话框不启动线程
- [ ] 导入完成后，主表格刷新并显示新增的 subscription 来源代理
- [ ] 日志区显示进度（已测试 N/M）和完成消息，不含订阅 URL 或节点密码

---

### Task 5: 单元测试

**Objective:** 为纯函数编写单元测试（不涉及网络和子进程），确保核心解析逻辑有测试覆盖。

**Files:**

- Create: `tests/test_subscription.py`
- Create: `tests/test_mihomo_manager.py`

**Key Decisions / Notes:**

- 每个测试类最多 1 个，函数分组到同一类中
- `test_subscription.py`：以下场景合并到 `TestSubscriptionParser`
  - YAML 含 vmess + trojan → 返回正确 count 和字段
  - base64(yaml) → 等价结果
  - 空字符串 → `[]`
  - 非 YAML 文本 → `[]`
  - `proxies:` 为空列表 → `[]`
- `test_mihomo_manager.py`：`TestPlatformAssetName`
  - darwin/arm64 → `mihomo-darwin-arm64-v1.2.3.gz`
  - darwin/amd64 → `mihomo-darwin-amd64-v1.2.3.gz`
  - linux/amd64 → `mihomo-linux-amd64-v1.2.3.gz`
  - windows/amd64 → `mihomo-windows-amd64-v1.2.3.zip`
  - 用 `unittest.mock.patch("platform.system")` + `patch("platform.machine")`

**Definition of Done:**

- [ ] `TestSubscriptionParser` 5 个场景全部 pass
- [ ] `TestPlatformAssetName` 4 个平台组合全部 pass
- [ ] Verify: `uv run pytest tests/test_subscription.py tests/test_mihomo_manager.py -q`

---

## Open Questions

无。
