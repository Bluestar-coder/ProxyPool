import pytest
from unittest.mock import MagicMock
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from app.core.rest_api import RestApiThread
from app.db.models import Proxy


def _make_proxy(id_=1, host="1.2.3.4", port=1080, region="CN",
                latency=50.0, speed=200.0, use_count=10, fail_count=2):
    return Proxy(id=id_, host=host, port=port, type="socks5",
                 status="valid", region=region, latency=latency, speed=speed,
                 use_count=use_count, fail_count=fail_count)


@pytest.fixture
def mock_rotator():
    r = MagicMock()
    r.get_current.return_value = _make_proxy()
    return r


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.get_all_proxies.return_value = [_make_proxy()]
    db.count_proxies.side_effect = lambda status=None, region=None: (
        1 if status == "valid" else (0 if status in ("invalid", "unknown") else 1)
    )
    return db


@pytest.fixture
def api_app(mock_rotator, mock_db):
    thread = RestApiThread.__new__(RestApiThread)
    thread._rotator = mock_rotator
    thread._db = mock_db
    thread._port = 0

    app = web.Application()
    app.router.add_get("/proxy", thread._handle_proxy)
    app.router.add_get("/proxies", thread._handle_proxies)
    app.router.add_get("/status", thread._handle_status)
    app.router.add_post("/refresh", thread._handle_refresh)
    # stub emit so test doesn't need Qt event loop
    thread.refresh_requested = MagicMock()
    thread.refresh_requested.emit = MagicMock()
    return app


@pytest.mark.asyncio
async def test_get_proxy_returns_current(api_app):
    async with TestClient(TestServer(api_app)) as client:
        resp = await client.get("/proxy")
        assert resp.status == 200
        data = await resp.json()
        assert data["host"] == "1.2.3.4"
        assert data["port"] == 1080
        assert data["address"] == "1.2.3.4:1080"
        assert data["region"] == "CN"


@pytest.mark.asyncio
async def test_get_proxy_503_when_no_current(api_app, mock_rotator):
    mock_rotator.get_current.return_value = None
    async with TestClient(TestServer(api_app)) as client:
        resp = await client.get("/proxy")
        assert resp.status == 503
        data = await resp.json()
        assert "error" in data


@pytest.mark.asyncio
async def test_get_proxies_returns_list(api_app):
    async with TestClient(TestServer(api_app)) as client:
        resp = await client.get("/proxies")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["address"] == "1.2.3.4:1080"
        assert data[0]["success_rate"] == pytest.approx(10 / 12, rel=1e-3)


@pytest.mark.asyncio
async def test_get_status_returns_counts(api_app):
    async with TestClient(TestServer(api_app)) as client:
        resp = await client.get("/status")
        assert resp.status == 200
        data = await resp.json()
        assert data["total"] == 1
        assert data["valid"] == 1
        assert data["current_proxy"] == "1.2.3.4:1080"


@pytest.mark.asyncio
async def test_post_refresh_emits_signal():
    thread = RestApiThread.__new__(RestApiThread)
    thread._rotator = MagicMock()
    thread._db = MagicMock()
    thread.refresh_requested = MagicMock()
    thread.refresh_requested.emit = MagicMock()

    app = web.Application()
    app.router.add_post("/refresh", thread._handle_refresh)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/refresh")
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        thread.refresh_requested.emit.assert_called_once()
