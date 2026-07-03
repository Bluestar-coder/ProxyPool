import textwrap
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.core.crawlers.fofa import FofaCrawler
from app.core.crawlers.base import QuotaExhausted
from app.core.crawlers import discover_crawlers


@pytest.fixture
def fofa():
    return FofaCrawler(api_key="test_key", page_size=10)


@pytest.mark.asyncio
async def test_fofa_fetch_page_success(fofa):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "error": False,
        "results": [["1.2.3.4", "1080", "socks5", "China"]],
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp)

    page = await fofa.fetch_page(session, "test query", None)
    assert len(page.items) == 1
    assert page.items[0].host == "1.2.3.4"
    assert page.items[0].port == 1080


@pytest.mark.asyncio
async def test_fofa_quota_exhausted(fofa):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "error": True, "errmsg": "Quota exceeded"
    })
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.get = MagicMock(return_value=mock_resp)

    with pytest.raises(QuotaExhausted):
        await fofa.fetch_page(session, "test", None)


@pytest.mark.asyncio
async def test_fofa_crawl_completes():
    crawler = FofaCrawler(api_key="key", page_size=2)
    from app.db.models import ProxyCandidate
    from app.core.crawlers.base import CrawlPage

    call_count = 0

    async def fake_fetch(session, query, cursor):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return CrawlPage(
                items=[ProxyCandidate("1.2.3.4", 1080, "socks5", "fofa"),
                       ProxyCandidate("1.2.3.5", 1080, "socks5", "fofa")],
                next_cursor=2,
            )
        return CrawlPage(items=[], next_cursor=None)

    crawler.fetch_page = fake_fetch
    result = await crawler.crawl(MagicMock(), {"query": "test"}, limit=10)
    assert len(result.candidates) == 2
    assert result.quota_exhausted is False


def test_discover_crawlers_finds_builtins():
    classes = discover_crawlers()
    names = {c.__name__ for c in classes}
    assert "FofaCrawler" in names
    assert "QuakeCrawler" in names
    assert "HunterCrawler" in names
    assert "FreeSitesCrawler" in names


def test_discover_crawlers_loads_plugin(tmp_path):
    plugin_src = textwrap.dedent("""\
        from app.core.crawlers.base import BaseCrawler, CrawlPage
        class TestPluginCrawler(BaseCrawler):
            source = "test_plugin"
            async def fetch_page(self, session, query, cursor):
                return CrawlPage(items=[], next_cursor=None)
    """)
    (tmp_path / "my_plugin.py").write_text(plugin_src)
    classes = discover_crawlers(plugin_dir=tmp_path)
    names = {c.__name__ for c in classes}
    assert "TestPluginCrawler" in names
