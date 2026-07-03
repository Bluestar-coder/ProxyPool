# ProxyPool

A desktop proxy pool manager with a PyQt6 GUI. Crawl, validate, speed-test, and serve proxies — all from one app.

![build](https://github.com/Bluestar-coder/ProxyPool/actions/workflows/build.yml/badge.svg)

---

## Features

- **Multi-source crawling** — FOFA, Hunter, Quake, and free public sites
- **Subscription proxies** — import and auto-refresh from subscription URLs
- **Validation** — concurrent connectivity checks with pause / resume / stop
- **Speed test** — concurrent bandwidth tests with pause / resume / stop
- **SOCKS5 server** — serves the valid proxy pool on a local port with round-robin / random rotation
- **HTTP proxy server** — same pool exposed as an HTTP CONNECT proxy
- **REST API** — lightweight JSON API to query and refresh the pool
- **Export** — Clash YAML, Surge conf, or plain text; password redaction toggle
- **Themes** — multiple built-in UI themes

---

## Ports (default)

| Service | Port |
|---------|------|
| SOCKS5 server | 51024 |
| REST API | 51025 |
| HTTP proxy | 51026 |

All ports are configurable in **Settings**.

---

## REST API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/proxy` | Get one proxy (rotated) |
| `GET` | `/proxies` | List all valid proxies |
| `GET` | `/status` | Pool size and service info |
| `POST` | `/refresh` | Trigger re-validation |

---

## Requirements

- Python 3.12+
- macOS 11+ or Windows 10+

---

## Installation (development)

```bash
git clone https://github.com/Bluestar-coder/ProxyPool.git
cd ProxyPool
uv venv && uv pip install -r requirements.txt
uv run python main.py
```

---

## Crawler API Keys

Keys are stored in the **system keyring** (macOS Keychain / Windows Credential Manager) — never in source files or the database. Enter them once in **Settings → Crawlers**.

| Source | Credential |
|--------|-----------|
| FOFA | email + API key |
| Hunter | API key |
| Quake | API key |

---

## Build

### macOS (local)

```bash
bash scripts/build.sh
# Output: dist/ProxyPool.app  and  dist/ProxyPool-mac.dmg
```

### Windows

Run on a Windows machine:

```bat
pip install -r requirements.txt pyinstaller
python scripts/make_icons.py
pyinstaller ProxyPool.spec --noconfirm
```

### CI/CD (GitHub Actions)

Every push to `main` triggers a build. Pushing a version tag creates a GitHub Release with downloadable artifacts:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Artifacts:
- `ProxyPool-mac.dmg` — macOS (Apple Silicon, built on `macos-14`)
- `ProxyPool-windows.zip` — Windows (built on `windows-latest`)

---

## Data storage

| Data | Location |
|------|----------|
| Database (proxies, config) | `~/Library/Application Support/ProxyPool/` (macOS) / `%APPDATA%\ProxyPool\` (Windows) |
| API keys / proxy passwords | System keyring |
| Subscription URLs | Database (above) |

No sensitive data is stored in the project directory or committed to source control.

---

## License

MIT
