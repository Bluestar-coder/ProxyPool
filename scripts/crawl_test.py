"""CLI crawl tester - diagnoses crawler without Qt."""
from __future__ import annotations
import asyncio
import sys
import time
import aiohttp

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=8)


async def run_free_sites():
    from app.core.crawlers.free_sites import FreeSitesCrawler

    print("[free_sites] starting...")
    t0 = time.monotonic()
    async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
        try:
            result = await asyncio.wait_for(
                FreeSitesCrawler().crawl(session, {}, limit=50),
                timeout=90.0,
            )
            elapsed = time.monotonic() - t0
            print(f"[free_sites] done in {elapsed:.1f}s - {len(result.candidates)} proxies")
            if result.errors:
                for e in result.errors:
                    print(f"  ERROR: {e}")
            for c in result.candidates[:5]:
                print(f"  {c.type}://{c.host}:{c.port}")
            if len(result.candidates) > 5:
                print(f"  ... and {len(result.candidates) - 5} more")
        except asyncio.TimeoutError:
            print(f"[free_sites] TIMEOUT after {time.monotonic() - t0:.1f}s")


async def run_fofa(api_key: str):
    from app.core.crawlers.fofa import FofaCrawler

    print(f"[fofa] starting (key=***{api_key[-4:] if len(api_key) >= 4 else '?'})")
    t0 = time.monotonic()
    async with aiohttp.ClientSession(timeout=_REQUEST_TIMEOUT) as session:
        try:
            result = await asyncio.wait_for(
                FofaCrawler(api_key, page_size=100).crawl(session, {}, limit=100),
                timeout=90.0,
            )
            elapsed = time.monotonic() - t0
            print(f"[fofa] done in {elapsed:.1f}s - {len(result.candidates)} proxies")
            if result.errors:
                for e in result.errors:
                    print(f"  ERROR: {e}")
            if result.quota_exhausted:
                print("  quota exhausted")
            for c in result.candidates[:5]:
                print(f"  {c.type}://{c.host}:{c.port}")
        except asyncio.TimeoutError:
            print(f"[fofa] TIMEOUT after {time.monotonic() - t0:.1f}s")


async def main(args: list[str]):
    if not args or args[0] == "free":
        await run_free_sites()
    elif args[0] == "fofa" and len(args) >= 2:
        await run_fofa(args[1])
    else:
        print("Usage:")
        print("  uv run python crawl_test.py free")
        print("  uv run python crawl_test.py fofa <api_key>")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
