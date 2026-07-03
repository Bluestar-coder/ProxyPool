# ProxyPool

[English](README.en.md)

桌面代理池管理工具，基于 PyQt6 构建。支持从多数据源抓取代理、验证连通性、测速，并通过本地服务对外提供代理服务。

![build](https://github.com/Bluestar-coder/ProxyPool/actions/workflows/build.yml/badge.svg)

---

## 功能特性

- **多源抓取** — 支持 FOFA、Hunter、Quake 及多个免费代理站点
- **订阅代理** — 从订阅 URL 导入并自动刷新代理列表
- **代理验证** — 并发连通性检测，支持暂停 / 继续 / 停止
- **代理测速** — 并发带宽测试，支持暂停 / 继续 / 停止
- **SOCKS5 服务** — 将有效代理池以本地 SOCKS5 代理形式对外提供，支持轮询 / 随机轮转
- **HTTP 代理服务** — 同一代理池的 HTTP CONNECT 代理端口
- **REST API** — 轻量 JSON 接口，支持查询和刷新代理池
- **导出** — 支持 Clash YAML、Surge conf 及纯文本格式，可选密码脱敏
- **多主题** — 内置多套 UI 主题

---

## 默认端口

| 服务 | 端口 |
|------|------|
| SOCKS5 服务 | 51024 |
| REST API | 51025 |
| HTTP 代理 | 51026 |

所有端口均可在 **设置** 中修改。

---

## REST API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/proxy` | 获取一个代理（轮转） |
| `GET` | `/proxies` | 列出所有有效代理 |
| `GET` | `/status` | 代理池大小与服务信息 |
| `POST` | `/refresh` | 触发重新验证 |

---

## 环境要求

- Python 3.12+
- macOS 11+ 或 Windows 10+

---

## 开发环境安装

```bash
git clone https://github.com/Bluestar-coder/ProxyPool.git
cd ProxyPool
uv sync
uv run python main.py
```

---

## 爬虫 API Key 配置

所有 Key 存储在**系统 Keychain**（macOS Keychain / Windows 凭据管理器）中，不写入源码或数据库。首次使用在 **设置 → 爬虫** 中填写即可。

| 数据源 | 所需凭据 |
|--------|---------|
| FOFA | 邮箱 + API Key |
| Hunter | API Key |
| Quake | API Key |

---

## 打包构建

### macOS（本地）

```bash
bash scripts/build.sh
# 输出: dist/ProxyPool.app  和  dist/ProxyPool-mac.dmg
```

### Windows

在 Windows 机器上执行：

```bat
uv sync --dev
uv run python scripts/make_icons.py
uv run pyinstaller ProxyPool.spec --noconfirm
```

### CI/CD（GitHub Actions）

每次推送到 `main` 分支自动构建。推送版本 tag 后自动创建 GitHub Release 并附上安装包：

```bash
git tag v1.0.0
git push origin v1.0.0
```

产物：
- `ProxyPool-mac.dmg` — macOS（Apple Silicon，基于 `macos-14` 构建）
- `ProxyPool-windows.zip` — Windows（基于 `windows-latest` 构建）

---

## 数据存储

| 数据类型 | 存储位置 |
|---------|---------|
| 数据库（代理、配置） | macOS: `~/Library/Application Support/ProxyPool/` / Windows: `%APPDATA%\ProxyPool\` |
| API Key / 代理密码 | 系统 Keychain |
| 订阅 URL | 数据库（同上） |

所有敏感数据均存储在项目目录之外，不会被提交到源码仓库。

---

## License

MIT
