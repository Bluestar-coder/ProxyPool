# ProxyPool

[English](README.en.md)

桌面代理池管理工具，基于 PyQt6 构建。从多个数据源抓取代理，自动验证连通性与测速，并通过本地 SOCKS5 / HTTP 代理和 REST API 对外提供服务。

![build](https://github.com/Bluestar-coder/ProxyPool/actions/workflows/build.yml/badge.svg)

---

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [配置](#配置)
- [服务说明](#服务说明)
- [REST API](#rest-api)
- [爬虫配置](#爬虫配置)
- [订阅代理](#订阅代理)
- [导出格式](#导出格式)
- [打包构建](#打包构建)
- [数据存储与安全](#数据存储与安全)
- [License](#license)

---

## 功能特性

### 代理抓取
- 内置四个爬虫数据源：**FOFA**、**Hunter**、**Quake**（需 API Key）及多个免费公开代理站点（无需 Key）
- 支持自定义每次抓取数量与并发限制
- 自动去重，避免重复入库

### 代理验证
- 并发连通性检测，可配置并发数（默认 50）与超时（默认 15s）
- 支持随时**暂停 / 继续 / 停止**，无需等待全部完成
- 验证后自动记录延迟、地区、匿名性等信息
- 支持自定义验证端点

### 代理测速
- 并发带宽测试，与验证独立运行
- 同样支持**暂停 / 继续 / 停止**
- 结果写入数据库，可按速度排序筛选

### 订阅代理
- 从订阅 URL 导入代理列表（支持常见格式）
- 右键上下文菜单：测试连通性、编辑、删除
- 有效的订阅代理自动加入代理池参与轮转

### 本地服务
| 服务 | 默认端口 | 说明 |
|------|----------|------|
| SOCKS5 | 51024 | 对外提供的 SOCKS5 代理，支持轮询/随机轮转 |
| HTTP 代理 | 51026 | HTTP CONNECT 代理，使用同一代理池 |
| REST API | 51025 | JSON 接口，供程序化查询与控制 |

### 其他
- **多主题**：内置多套 UI 配色方案
- **导出**：支持 Clash YAML、Surge conf、纯文本；可选密码脱敏
- **自动维护**：可开启定期清理失效代理

---

## 快速开始

### 环境要求
- Python 3.12+
- macOS 11+ 或 Windows 10+
- [uv](https://docs.astral.sh/uv/)（推荐的包管理工具）

### 安装并运行

```bash
git clone https://github.com/Bluestar-coder/ProxyPool.git
cd ProxyPool

# 安装依赖（自动创建虚拟环境）
uv sync

# 启动应用
uv run python main.py
```

### 运行测试

```bash
uv run pytest -q
```

---

## 配置

应用支持通过 `.env` 文件进行本地配置覆盖，优先级高于 UI 中保存的数据库值。

### 初始化

```bash
cp .env.example .env
# 按需编辑 .env
```

`.env` 已加入 `.gitignore`，不会被提交到仓库。

### 可用变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PROXYPOOL_DATA_DIR` | 系统数据目录 | 数据库存储目录 |
| `PROXYPOOL_DB_PATH` | `$DATA_DIR/proxies.db` | 数据库文件完整路径，优先于 `DATA_DIR` |
| `PROXYPOOL_LOG_LEVEL` | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `PROXYPOOL_SOCKS_PORT` | `51024` | SOCKS5 服务端口 |
| `PROXYPOOL_REST_PORT` | `51025` | REST API 端口 |
| `PROXYPOOL_HTTP_PORT` | `51026` | HTTP 代理端口 |
| `PROXYPOOL_VALIDATOR_CONCURRENCY` | `50` | 验证并发数 |
| `PROXYPOOL_VALIDATOR_TIMEOUT` | `15` | 验证超时（秒） |
| `PROXYPOOL_VALIDATOR_ENDPOINT` | `http://ip-api.com/json` | 验证端点 URL |

**优先级：** `.env` / 系统环境变量 > 数据库（UI 设置）> 内置默认值

---

## 服务说明

启动应用后，在主界面点击 **启动服务** 即可开启三项本地服务。

### SOCKS5

```bash
# 使用 curl 通过代理池发请求
curl --socks5 127.0.0.1:51024 https://ip-api.com/json
```

### HTTP 代理

```bash
curl -x http://127.0.0.1:51026 https://ip-api.com/json
```

### 轮转模式

在 **设置 → 轮转** 中可切换：
- `round_robin`：顺序轮询，均匀分配
- `random`：随机选取

---

## REST API

基础 URL：`http://127.0.0.1:51025`

### 获取单个代理（轮转）

```http
GET /proxy
```

```json
{
  "host": "1.2.3.4",
  "port": 1080,
  "type": "socks5",
  "region": "US",
  "latency": 312
}
```

### 列出所有有效代理

```http
GET /proxies
```

```json
[
  { "host": "1.2.3.4", "port": 1080, "type": "socks5", "region": "US", "latency": 312 },
  { "host": "5.6.7.8", "port": 8080, "type": "http",   "region": "DE", "latency": 450 }
]
```

### 查看服务状态

```http
GET /status
```

```json
{
  "pool_size": 42,
  "socks_port": 51024,
  "http_port": 51026
}
```

### 触发重新验证

```http
POST /refresh
```

```json
{ "status": "ok" }
```

---

## 爬虫配置

各数据源的 API Key 存储在**系统 Keychain**（macOS Keychain / Windows 凭据管理器）中，不写入源码或数据库，不会随代码提交泄露。

在 **设置 → 爬虫** 中填写后保存即可，无需重启。

| 数据源 | 所需凭据 | 获取地址 |
|--------|---------|----------|
| FOFA | 邮箱 + API Key | [fofa.info](https://fofa.info) |
| Hunter | API Key | [hunter.qianxin.com](https://hunter.qianxin.com) |
| Quake | API Key | [quake.360.cn](https://quake.360.cn) |
| 免费站点 | 无需 Key | 自动抓取 |

---

## 订阅代理

1. 进入 **订阅** 标签页
2. 点击 **添加订阅**，填写订阅 URL 和名称
3. 点击 **刷新** 拉取最新代理列表
4. 右键代理行可执行：测试连通性 / 编辑 / 删除

有效的订阅代理会自动加入代理池，参与 SOCKS5 / HTTP / REST 的轮转服务。

---

## 导出格式

在 **导出** 对话框中可选择格式与选项：

| 格式 | 文件后缀 | 适用场景 |
|------|----------|----------|
| Clash YAML | `.yaml` | Clash / Clash Meta 客户端 |
| Surge conf | `.conf` | Surge for Mac / iOS |
| 纯文本 | `.txt` | 通用，每行 `host:port` |

**密码脱敏**（默认开启）：导出时自动移除认证信息，防止凭据外泄。

---

## 打包构建

### macOS（本地）

需要已安装 Xcode Command Line Tools（提供 `iconutil` 和 `hdiutil`）。

```bash
bash scripts/build.sh
```

输出：
- `dist/ProxyPool.app` — 可直接运行的应用包
- `dist/ProxyPool-mac.dmg` — 分发用磁盘镜像

### Windows

在 Windows 机器上执行：

```bat
uv sync --dev
uv run python scripts/make_icons.py
uv run pyinstaller ProxyPool.spec --noconfirm
```

输出在 `dist\ProxyPool\` 目录下。

### CI/CD（GitHub Actions）

每次推送到 `main` 分支自动触发双平台构建，产物上传为 Artifact。

推送版本 Tag 后自动创建 **GitHub Release** 并附上安装包：

```bash
git tag v1.0.0
git push origin v1.0.0
```

| 产物 | 平台 | 构建环境 |
|------|------|----------|
| `ProxyPool-mac.dmg` | macOS (Apple Silicon) | `macos-14` |
| `ProxyPool-windows.zip` | Windows | `windows-latest` |

---

## 数据存储与安全

| 数据类型 | 存储位置 |
|---------|---------|
| 数据库（代理列表、配置） | macOS: `~/Library/Application Support/ProxyPool/` |
| | Windows: `%APPDATA%\ProxyPool\` |
| 可通过 `PROXYPOOL_DATA_DIR` 覆盖 | |
| API Key / 代理认证密码 | 系统 Keychain（macOS Keychain / Windows 凭据管理器） |
| 订阅 URL | 数据库（同上） |

**所有敏感数据均存储在项目目录之外**，不会被 git 追踪或意外提交。

---

## License

MIT
