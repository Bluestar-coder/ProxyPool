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
