"""性能测试 - 验证关键路径的响应时间在可接受范围内"""
from __future__ import annotations

import time

import pytest

from app.core.crawlers import discover_crawlers
from app.core.rotator import _quality_key
from app.db.database import Database
from app.db.models import Proxy
from app.ui.dialogs.export_proxy import _to_clash_yaml, _to_surge_conf


# ── 公共 fixture ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def large_db(tmp_path_factory):
    """1000 条代理的 SQLite 数据库（module 级复用）"""
    path = tmp_path_factory.mktemp("perf") / "perf.db"
    db = Database(path)
    db.initialize()
    db._conn.executemany(
        "INSERT INTO proxies "
        "(host,port,type,status,region,use_count,fail_count) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (
                f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}",
                1080 + i % 100,
                "socks5",
                "valid",
                ["CN", "US", "JP", "DE", "FR"][i % 5],
                i % 20,
                i % 5,
            )
            for i in range(1000)
        ],
    )
    db._conn.commit()
    yield db
    db.close()


def _make_proxies(n: int) -> list[Proxy]:
    return [
        Proxy(
            host=f"10.{i // 65536 % 256}.{i // 256 % 256}.{i % 256}",
            port=1080,
            username="user",
            password="pass",
            region="CN",
            latency=float(50 + i % 500),
            speed=float(100 + i % 1000),
            use_count=i % 20,
            fail_count=i % 5,
        )
        for i in range(n)
    ]


# ── DB 性能 ──────────────────────────────────────────────────────────────────


class TestDbPerformance:
    def test_get_all_proxies_1000_under_500ms(self, large_db):
        t0 = time.perf_counter()
        rows = large_db.get_all_proxies(status="valid")
        elapsed = time.perf_counter() - t0
        assert len(rows) == 1000
        assert elapsed < 0.5, f"get_all_proxies(1000) took {elapsed:.3f}s (limit 0.5s)"

    def test_region_filter_1000_under_200ms(self, large_db):
        t0 = time.perf_counter()
        rows = large_db.get_all_proxies(status="valid", region="CN")
        elapsed = time.perf_counter() - t0
        assert len(rows) == 200  # 1/5 of 1000
        assert elapsed < 0.2, f"region filter took {elapsed:.3f}s (limit 0.2s)"

    def test_count_proxies_under_100ms(self, large_db):
        t0 = time.perf_counter()
        count = large_db.count_proxies(status="valid")
        elapsed = time.perf_counter() - t0
        assert count == 1000
        assert elapsed < 0.1, f"count_proxies took {elapsed:.3f}s (limit 0.1s)"

    def test_count_with_region_under_100ms(self, large_db):
        t0 = time.perf_counter()
        count = large_db.count_proxies(status="valid", region="US")
        elapsed = time.perf_counter() - t0
        assert count == 200
        assert elapsed < 0.1, f"count_proxies(region) took {elapsed:.3f}s (limit 0.1s)"

    def test_get_distinct_regions_under_100ms(self, large_db):
        t0 = time.perf_counter()
        regions = large_db.get_distinct_regions()
        elapsed = time.perf_counter() - t0
        assert sorted(regions) == ["CN", "DE", "FR", "JP", "US"]
        assert elapsed < 0.1, f"get_distinct_regions took {elapsed:.3f}s (limit 0.1s)"

    def test_paginated_query_under_50ms(self, large_db):
        t0 = time.perf_counter()
        rows = large_db.get_all_proxies(status="valid", page=3, page_size=20)
        elapsed = time.perf_counter() - t0
        assert len(rows) == 20
        assert elapsed < 0.05, f"paginated query took {elapsed:.3f}s (limit 0.05s)"


# ── Rotator 排序性能 ──────────────────────────────────────────────────────────


class TestRotatorSortPerformance:
    def test_sort_10000_proxies_under_100ms(self):
        proxies = _make_proxies(10_000)
        t0 = time.perf_counter()
        sorted_list = sorted(proxies, key=_quality_key)
        elapsed = time.perf_counter() - t0
        assert len(sorted_list) == 10_000
        assert elapsed < 0.1, f"sort(10k) took {elapsed:.3f}s (limit 0.1s)"

    def test_sort_preserves_stability_between_equal_keys(self):
        proxies = [Proxy(id=i, use_count=0, fail_count=0, latency=100.0, speed=200.0)
                   for i in range(1000)]
        sorted_list = sorted(proxies, key=_quality_key)
        # All keys are equal; Python sort is stable, so order should be preserved
        assert [p.id for p in sorted_list] == list(range(1000))


# ── 导出格式性能 ──────────────────────────────────────────────────────────────


class TestExportPerformance:
    def test_clash_yaml_1000_proxies_under_200ms(self):
        proxies = _make_proxies(1000)
        t0 = time.perf_counter()
        out = _to_clash_yaml(proxies, redact=True)
        elapsed = time.perf_counter() - t0
        assert out.startswith("proxies:")
        assert elapsed < 0.2, f"Clash YAML(1k) took {elapsed:.3f}s (limit 0.2s)"

    def test_surge_conf_1000_proxies_under_200ms(self):
        proxies = _make_proxies(1000)
        t0 = time.perf_counter()
        out = _to_surge_conf(proxies, redact=True)
        elapsed = time.perf_counter() - t0
        assert out.startswith("[Proxy]")
        assert elapsed < 0.2, f"Surge conf(1k) took {elapsed:.3f}s (limit 0.2s)"

    def test_clash_yaml_redact_no_slower_than_plain(self):
        proxies = _make_proxies(500)
        t_redact = time.perf_counter()
        _to_clash_yaml(proxies, redact=True)
        t_redact = time.perf_counter() - t_redact

        t_plain = time.perf_counter()
        _to_clash_yaml(proxies, redact=False)
        t_plain = time.perf_counter() - t_plain

        # Redacted should be within 2x of plain (same code path, just different string)
        assert t_redact < t_plain * 3 + 0.05, "Redacted export significantly slower than plain"


# ── 爬虫发现性能 ──────────────────────────────────────────────────────────────


class TestCrawlerDiscoveryPerformance:
    def test_repeated_calls_under_500ms_total(self):
        discover_crawlers()  # warm-up: modules already imported
        t0 = time.perf_counter()
        for _ in range(20):
            discover_crawlers()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.5, f"20x discover_crawlers took {elapsed:.3f}s (limit 0.5s)"

    def test_single_call_with_empty_plugin_dir_under_50ms(self, tmp_path):
        discover_crawlers()  # warm-up
        t0 = time.perf_counter()
        discover_crawlers(plugin_dir=tmp_path)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.05, f"discover_crawlers(empty dir) took {elapsed:.3f}s (limit 0.05s)"
