from __future__ import annotations

import logging

import aiohttp
from bs4 import BeautifulSoup

from app.core.crawlers.base import BaseCrawler, CrawlPage, RateLimited
from app.db.models import ProxyCandidate

logger = logging.getLogger(__name__)

_PROXYSCRAPE_URL = (
    "https://api.proxyscrape.com/v3/free-proxy-list/get"
    "?request=displayproxies&protocol={proto}&timeout=10000&country=all"
)
_SOCKS_PROXY_NET_URL = "https://www.socks-proxy.net/"
_PROTOCOLS = ("socks5", "socks4", "http")


class FreeSitesCrawler(BaseCrawler):
    name = "free_sites"
    rate_limit = 0.0

    async def fetch_page(
        self,
        session: aiohttp.ClientSession,
        query: str,
        cursor: object,
    ) -> CrawlPage:
        items: list[ProxyCandidate] = []

        # --- proxyscrape.com ---
        for proto in _PROTOCOLS:
            url = _PROXYSCRAPE_URL.format(proto=proto)
            try:
                async with session.get(url) as resp:
                    if resp.status == 429:
                        raise RateLimited()
                    if resp.status != 200:
                        logger.warning("proxyscrape %s HTTP %s", proto, resp.status)
                        continue
                    text = await resp.text()
                for line in text.splitlines():
                    line = line.strip()
                    if ":" not in line:
                        continue
                    host, _, port_str = line.partition(":")
                    try:
                        items.append(
                            ProxyCandidate(
                                host=host,
                                port=int(port_str),
                                type=proto,
                                source=self.name,
                            )
                        )
                    except ValueError:
                        continue
            except RateLimited:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("proxyscrape %s error: %s", proto, exc)

        # --- socks-proxy.net ---
        try:
            async with session.get(_SOCKS_PROXY_NET_URL) as resp:
                if resp.status == 429:
                    raise RateLimited()
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "lxml")
                    for row in soup.select("table tbody tr"):
                        cols = row.find_all("td")
                        if len(cols) < 2:
                            continue
                        host = cols[0].get_text(strip=True)
                        port_text = cols[1].get_text(strip=True)
                        try:
                            items.append(
                                ProxyCandidate(
                                    host=host,
                                    port=int(port_text),
                                    type="socks5",
                                    source=self.name,
                                )
                            )
                        except ValueError:
                            continue
        except RateLimited:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("socks-proxy.net error: %s", exc)

        return CrawlPage(items=items, next_cursor=None)
