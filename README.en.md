# ProxyPool

[中文](README.md)

A desktop proxy pool manager built with PyQt6. Crawl proxies from multiple sources, validate connectivity, run speed tests, and serve the pool via local SOCKS5 / HTTP proxy and REST API.

![CI](https://github.com/Bluestar-coder/ProxyPool/actions/workflows/ci.yml/badge.svg) ![Release](https://github.com/Bluestar-coder/ProxyPool/actions/workflows/release.yml/badge.svg)

---

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Services](#services)
- [REST API](#rest-api)
- [Crawler Setup](#crawler-setup)
- [Subscription Proxies](#subscription-proxies)
- [Export Formats](#export-formats)
- [Building](#building)
- [Data Storage & Security](#data-storage--security)
- [License](#license)

---

## Features

### Proxy Crawling
- Four built-in sources: **FOFA**, **Hunter**, **Quake** (API key required) and free public proxy sites (no key needed)
- Configurable fetch limits and concurrency
- Automatic deduplication before insertion

### Validation
- Concurrent connectivity checks with configurable concurrency (default 50) and timeout (default 15 s)
- **Pause / Resume / Stop** at any time — no need to wait for the full batch
- Records latency, region, and anonymity level after each check
- Custom validation endpoint support

### Speed Testing
- Concurrent bandwidth tests, independent from validation
- Also supports **Pause / Resume / Stop**
- Results stored in the database; sortable by speed

### Subscription Proxies
- Import proxy lists from subscription URLs
- Right-click context menu: test connectivity, edit, delete
- Valid subscription proxies are automatically included in the rotation pool

### Local Services
| Service | Default Port | Description |
|---------|-------------|-------------|
| SOCKS5 | 51024 | Local SOCKS5 proxy with round-robin / random rotation |
| HTTP proxy | 51026 | HTTP CONNECT proxy using the same pool |
| REST API | 51025 | JSON API for programmatic access and control |

### Other
- **Themes**: multiple built-in UI colour schemes
- **Export**: Clash YAML, Surge conf, plain text; optional password redaction
- **Auto-maintenance**: optional periodic cleanup of dead proxies

---

## Quick Start

### Requirements
- Python 3.12+
- macOS 11+ or Windows 10+
- [uv](https://docs.astral.sh/uv/)

### Install and Run

```bash
git clone https://github.com/Bluestar-coder/ProxyPool.git
cd ProxyPool

# Install dependencies (creates virtualenv automatically)
uv sync

# Launch the app
uv run python main.py
```

### Run Tests

```bash
uv run pytest -q
```

---

## Configuration

ProxyPool supports a `.env` file for local overrides. Values set here take priority over anything saved in the database via the Settings UI.

### Setup

```bash
cp .env.example .env
# Edit .env as needed
```

`.env` is gitignored and will never be committed.

### Available Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXYPOOL_DATA_DIR` | System data dir | Directory where `proxies.db` is stored |
| `PROXYPOOL_DB_PATH` | `$DATA_DIR/proxies.db` | Full path to the database file; overrides `DATA_DIR` |
| `PROXYPOOL_LOG_LEVEL` | `INFO` | Log verbosity: `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `PROXYPOOL_SOCKS_PORT` | `51024` | SOCKS5 service port |
| `PROXYPOOL_REST_PORT` | `51025` | REST API port |
| `PROXYPOOL_HTTP_PORT` | `51026` | HTTP proxy port |
| `PROXYPOOL_VALIDATOR_CONCURRENCY` | `50` | Validation concurrency |
| `PROXYPOOL_VALIDATOR_TIMEOUT` | `15` | Validation timeout in seconds |
| `PROXYPOOL_VALIDATOR_ENDPOINT` | `http://ip-api.com/json` | Validation endpoint URL |

**Priority:** `.env` / system env > database (UI settings) > built-in defaults

---

## Services

Click **Start Services** in the main window to activate all three local services.

### SOCKS5

```bash
curl --socks5 127.0.0.1:51024 https://ip-api.com/json
```

### HTTP Proxy

```bash
curl -x http://127.0.0.1:51026 https://ip-api.com/json
```

### Rotation Modes

Change in **Settings → Rotation**:
- `round_robin`: sequential, evenly distributed
- `random`: random selection per request

---

## REST API

Base URL: `http://127.0.0.1:51025`

### Get One Proxy (rotated)

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

### List All Valid Proxies

```http
GET /proxies
```

```json
[
  { "host": "1.2.3.4", "port": 1080, "type": "socks5", "region": "US", "latency": 312 },
  { "host": "5.6.7.8", "port": 8080, "type": "http",   "region": "DE", "latency": 450 }
]
```

### Service Status

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

### Trigger Re-validation

```http
POST /refresh
```

```json
{ "status": "ok" }
```

---

## Crawler Setup

API keys are stored in the **system keychain** (macOS Keychain / Windows Credential Manager). They are never written to source files or the database, and cannot be accidentally committed to git.

Enter keys once in **Settings → Crawlers**; no restart required.

| Source | Credential | Where to get it |
|--------|-----------|-----------------|
| FOFA | Email + API key | [fofa.info](https://fofa.info) |
| Hunter | API key | [hunter.qianxin.com](https://hunter.qianxin.com) |
| Quake | API key | [quake.360.cn](https://quake.360.cn) |
| Free sites | None | Auto-crawled |

---

## Subscription Proxies

1. Open the **Subscriptions** tab
2. Click **Add Subscription**, enter a URL and a name
3. Click **Refresh** to pull the latest list
4. Right-click any row to: test connectivity / edit / delete

Valid subscription proxies are automatically included in the rotation pool used by SOCKS5, HTTP proxy, and REST API.

---

## Export Formats

Open the **Export** dialog to choose format and options:

| Format | Extension | Use case |
|--------|-----------|----------|
| Clash YAML | `.yaml` | Clash / Clash Meta clients |
| Surge conf | `.conf` | Surge for Mac / iOS |
| Plain text | `.txt` | Generic, one `host:port` per line |

**Password redaction** (on by default): strips credentials from the export to prevent leaks.

---

## Building

### macOS (local)

Requires Xcode Command Line Tools (`iconutil` and `hdiutil`).

```bash
bash scripts/build.sh
```

Output:
- `dist/ProxyPool.app` — runnable app bundle
- `dist/ProxyPool-mac.dmg` — distributable disk image

### Windows

Run on a Windows machine:

```bat
uv sync --dev
uv run python scripts/make_icons.py
uv run pyinstaller ProxyPool.spec --noconfirm
```

Output is in `dist\ProxyPool\`.

### CI/CD (GitHub Actions)

- **Every push to `main` / PR** — runs the test suite (`ci.yml`, ubuntu-latest, free Linux runner)
- **Pushing a version tag** — triggers dual-platform builds; once both are ready, a unified **GitHub Release** is created (`release.yml`)

Push a version tag to trigger a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

| Artifact | Platform | Runner |
|----------|----------|--------|
| `ProxyPool-mac.dmg` | macOS (Apple Silicon) | `macos-14` |
| `ProxyPool-windows.zip` | Windows | `windows-latest` |

---

## Data Storage & Security

| Data | Location |
|------|----------|
| Database (proxies, config) | macOS: `~/Library/Application Support/ProxyPool/` |
| | Windows: `%APPDATA%\ProxyPool\` |
| Override via `PROXYPOOL_DATA_DIR` | |
| API keys / proxy passwords | System keychain |
| Subscription URLs | Database (above) |

**All sensitive data lives outside the project directory** and is never tracked by git.

---

## License

MIT
