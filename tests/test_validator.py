import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.validator import validate_single, _extract_ip, ValidatorThread
from app.db.models import Proxy, ValidationResult


def test_extract_ip_handles_ipify_format():
    assert _extract_ip({"ip": "9.8.7.6"}) == "9.8.7.6"


def test_extract_ip_handles_httpbin_format():
    assert _extract_ip({"origin": "9.8.7.6"}) == "9.8.7.6"


def test_extract_ip_handles_ip_api_format():
    assert _extract_ip({"query": "9.8.7.6"}) == "9.8.7.6"


def make_proxy():
    return Proxy(id=1, host="1.2.3.4", port=1080, type="socks5")


@pytest.mark.asyncio
async def test_validate_success():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value='{"origin": "9.8.7.6"}')
    mock_response.json = AsyncMock(return_value={"origin": "9.8.7.6"})
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.validator.aiohttp.ClientSession", return_value=mock_session), \
         patch("app.core.validator.ProxyConnector"), \
         patch("app.core.validator.measure_speed", AsyncMock(return_value=42.0)):
        result = await validate_single(make_proxy(), ["https://httpbin.org/ip"], 10, "1.1.1.1")

    assert result.success is True
    assert result.latency >= 0
    assert result.anonymity == "high"
    assert result.speed == 42.0


@pytest.mark.asyncio
async def test_validate_connection_error():
    with patch("app.core.validator.aiohttp.ClientSession") as mock_cls, \
         patch("app.core.validator.ProxyConnector"):
        mock_cls.return_value.__aenter__ = AsyncMock(side_effect=Exception("refused"))
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await validate_single(make_proxy(), ["https://httpbin.org/ip"], 10, "")

    assert result.success is False
    assert result.error != ""


@pytest.mark.asyncio
async def test_one_proxy_crashing_does_not_abort_the_batch():
    """asyncio.gather without return_exceptions=True would propagate the
    first failure and silently skip Phase 2 / the finished signal for
    every other proxy still in flight."""
    proxies = [Proxy(id=1, host="1.1.1.1", port=1080), Proxy(id=2, host="2.2.2.2", port=1080)]
    thread = ValidatorThread(proxies, timeout=5)
    finished_calls = []
    results = []
    thread.finished.connect(lambda: finished_calls.append(True))
    thread.result_ready.connect(lambda r: results.append(r))

    async def fake_validate_single(proxy, endpoints, timeout, local_ip, test_speed=True):
        if proxy.id == 1:
            raise RuntimeError("boom")
        return ValidationResult(
            proxy_id=proxy.id, success=True, latency=10.0, anonymity="high", region="", speed=5.0
        )

    with patch("app.core.validator.validate_single", fake_validate_single), \
         patch("app.core.validator._get_local_ip", AsyncMock(return_value="1.1.1.1")):
        await thread.main()

    assert finished_calls == [True]
    assert len(results) == 1
    assert results[0].proxy_id == 2
