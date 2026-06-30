import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.speed_test import measure_speed


def _make_mock_session(chunks):
    mock_resp = MagicMock()
    mock_resp.status = 200

    async def _iter_chunked(size):
        for c in chunks:
            yield c

    mock_resp.content.iter_chunked = _iter_chunked
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    return mock_session


@pytest.mark.asyncio
async def test_measure_speed_reuses_provided_session():
    """A pre-connected session must be reused instead of opening a second
    TCP/SOCKS connection to the same proxy."""
    chunks = [b"x" * 8192 for _ in range(13)]  # ~104KB, over the 100KB target
    mock_session = _make_mock_session(chunks)

    with patch("app.core.speed_test.ProxyConnector") as mock_connector, \
         patch("app.core.speed_test.aiohttp.ClientSession") as mock_session_cls:
        speed = await measure_speed("socks5://1.2.3.4:1080", session=mock_session)

    mock_connector.from_url.assert_not_called()
    mock_session_cls.assert_not_called()
    assert speed > 0


@pytest.mark.asyncio
async def test_measure_speed_creates_own_session_when_none_provided():
    chunks = [b"x" * 8192 for _ in range(13)]
    mock_session = _make_mock_session(chunks)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.core.speed_test.ProxyConnector"), \
         patch("app.core.speed_test.aiohttp.ClientSession", return_value=mock_session):
        speed = await measure_speed("socks5://1.2.3.4:1080")

    assert speed > 0
