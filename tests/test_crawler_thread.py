import pytest
from app.db.models import ProxyCandidate
from app.core.crawlers.base import CrawlerResult


def _make_result(candidates, quota_exhausted=False, source="test"):
    return CrawlerResult(
        source=source,
        candidates=candidates,
        quota_exhausted=quota_exhausted,
    )


def _make_candidate(host, port="1080", proxy_type="socks5", source="test"):
    return ProxyCandidate(host=host, port=int(port), type=proxy_type, source=source)


class _FakeCrawlerThread:
    """Replicates CrawlerThread.main() logic without Qt dependency."""

    def __init__(self, config):
        self._config = config
        self._log_calls: list[str] = []
        self._found_calls: list[int] = []
        self._finished_result: list = []

    def _emit_log(self, msg):
        self._log_calls.append(msg)

    def _emit_found(self, n):
        self._found_calls.append(n)

    def _emit_finished(self, candidates):
        self._finished_result = candidates

    async def main(self, gather_results):
        """Core logic extracted from CrawlerThread.main() for isolated testing."""
        all_candidates: list[ProxyCandidate] = []
        seen: set[tuple] = set()

        for result in gather_results:
            if isinstance(result, Exception):
                self._emit_log(f"[爬虫] 错误: {result}")
                continue
            for c in result.candidates:
                key = (c.host, c.port, c.type, c.username)
                if key not in seen:
                    seen.add(key)
                    all_candidates.append(c)
            if result.quota_exhausted:
                self._emit_log(f"[爬虫] {result.source} 额度已耗尽")
            self._emit_found(len(all_candidates))

        self._emit_finished(all_candidates)


@pytest.mark.asyncio
async def test_deduplication_across_crawlers():
    t = _FakeCrawlerThread({})
    c1 = _make_candidate("1.2.3.4")
    c2 = _make_candidate("1.2.3.4")   # duplicate
    c3 = _make_candidate("5.6.7.8")

    results = [
        _make_result([c1, c3], source="fofa"),
        _make_result([c2], source="quake"),
    ]
    await t.main(results)

    assert len(t._finished_result) == 2
    hosts = {c.host for c in t._finished_result}
    assert hosts == {"1.2.3.4", "5.6.7.8"}


@pytest.mark.asyncio
async def test_exception_results_logged_and_skipped():
    t = _FakeCrawlerThread({})
    results = [
        RuntimeError("network error"),
        _make_result([_make_candidate("9.9.9.9")]),
    ]
    await t.main(results)

    assert any("network error" in m for m in t._log_calls)
    assert len(t._finished_result) == 1


@pytest.mark.asyncio
async def test_quota_exhausted_logged():
    t = _FakeCrawlerThread({})
    results = [_make_result([], quota_exhausted=True, source="fofa")]
    await t.main(results)

    assert any("fofa" in m and "额度" in m for m in t._log_calls)


@pytest.mark.asyncio
async def test_found_signal_increments():
    t = _FakeCrawlerThread({})
    results = [
        _make_result([_make_candidate("1.1.1.1"), _make_candidate("2.2.2.2")], source="a"),
        _make_result([_make_candidate("3.3.3.3")], source="b"),
    ]
    await t.main(results)

    assert t._found_calls == [2, 3]
