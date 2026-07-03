import pytest
from app.core.rotator import ProxyRotator, RotationMode
from app.db.models import Proxy


def make_proxy(id_, latency=100.0, speed=-1.0, status="valid",
               use_count=0, fail_count=0):
    return Proxy(id=id_, host=f"1.2.3.{id_}", port=1080, type="socks5",
                 status=status, latency=latency, speed=speed,
                 use_count=use_count, fail_count=fail_count)


@pytest.fixture
def rotator():
    r = ProxyRotator()
    r.load_proxies([make_proxy(1), make_proxy(2), make_proxy(3)])
    return r


@pytest.mark.asyncio
async def test_round_robin_cycles(rotator):
    rotator.set_mode(RotationMode.ROUND_ROBIN)
    # Round-robin advances on every request_start, regardless of when
    # (or whether) request_done is called for the prior request.
    ids = []
    for _ in range(4):
        ep = await rotator.on_request_start()
        ids.append(ep.proxy_id)
        await rotator.on_request_done(ep.proxy_id, success=True)
    assert ids[:3] == [1, 2, 3]
    assert ids[3] == 1  # Cycles back


@pytest.mark.asyncio
async def test_round_robin_fans_out_concurrent_requests(rotator):
    """Concurrent connections that start before any prior one finishes must
    still land on different proxies, not all collapse onto the same one."""
    rotator.set_mode(RotationMode.ROUND_ROBIN)
    ep1 = await rotator.on_request_start()
    ep2 = await rotator.on_request_start()
    ep3 = await rotator.on_request_start()
    assert [ep1.proxy_id, ep2.proxy_id, ep3.proxy_id] == [1, 2, 3]
    # Completing them later (in any order) must not re-advance the index.
    await rotator.on_request_done(ep2.proxy_id, success=True)
    await rotator.on_request_done(ep1.proxy_id, success=True)
    ep4 = await rotator.on_request_start()
    assert ep4.proxy_id == 1  # cycled back, not skipped ahead


@pytest.mark.asyncio
async def test_fixed_selects_lowest_latency(rotator):
    rotator.load_proxies([
        make_proxy(1, latency=200),
        make_proxy(2, latency=50),
        make_proxy(3, latency=150),
    ])
    rotator.set_mode(RotationMode.FIXED)
    ep = await rotator.on_request_start()
    assert ep.proxy_id == 2


@pytest.mark.asyncio
async def test_returns_none_when_no_valid_proxies(rotator):
    rotator.load_proxies([make_proxy(1, status="invalid")])
    ep = await rotator.on_request_start()
    assert ep is None


@pytest.mark.asyncio
async def test_by_count_switches_after_threshold(rotator):
    rotator.set_mode(RotationMode.BY_COUNT, threshold=2)
    ep1 = await rotator.on_request_start()
    await rotator.on_request_done(ep1.proxy_id, success=True)
    ep2 = await rotator.on_request_start()
    await rotator.on_request_done(ep2.proxy_id, success=True)
    ep3 = await rotator.on_request_start()  # 达到阈值，切换
    assert ep3.proxy_id != ep1.proxy_id


@pytest.mark.asyncio
async def test_failover_switches_on_failure(rotator):
    rotator.set_mode(RotationMode.FAILOVER)
    ep1 = await rotator.on_request_start()
    await rotator.on_request_done(ep1.proxy_id, success=False)
    ep2 = await rotator.on_request_start()
    assert ep2.proxy_id != ep1.proxy_id


@pytest.mark.asyncio
async def test_on_request_done_returns_new_current_proxy_atomically(rotator):
    """on_request_done must hand back the proxy it switched to directly,
    rather than callers re-acquiring the lock via a separate get_current()
    call that a concurrent load_proxies() could race with."""
    rotator.set_mode(RotationMode.FAILOVER)
    ep1 = await rotator.on_request_start()
    new_current = await rotator.on_request_done(ep1.proxy_id, success=False)
    assert new_current is not None
    assert new_current.id != ep1.proxy_id
    assert new_current.id == rotator.get_current().id


@pytest.mark.asyncio
async def test_on_request_done_returns_none_when_no_switch(rotator):
    rotator.set_mode(RotationMode.FAILOVER)
    ep1 = await rotator.on_request_start()
    result = await rotator.on_request_done(ep1.proxy_id, success=True)
    assert result is None


@pytest.mark.asyncio
async def test_load_proxies_orders_by_latency_then_speed(rotator):
    """All modes start from the front of _valid, so load order should rank
    low-latency proxies first and use speed as the tiebreaker."""
    rotator.load_proxies([
        make_proxy(1, latency=200, speed=10),
        make_proxy(2, latency=50, speed=5),
        make_proxy(3, latency=50, speed=80),   # same latency as #2, faster
        make_proxy(4, latency=150, speed=999),  # higher latency wins nothing
    ])
    rotator.set_mode(RotationMode.ROUND_ROBIN)
    ep = await rotator.on_request_start()
    assert ep.proxy_id == 3  # lowest latency tier, fastest within it


@pytest.mark.asyncio
async def test_load_proxies_sinks_untested_proxies_last(rotator):
    rotator.load_proxies([
        make_proxy(1, latency=-1, speed=-1),    # never tested
        make_proxy(2, latency=300, speed=1),    # tested, slow
    ])
    rotator.set_mode(RotationMode.ROUND_ROBIN)
    ep = await rotator.on_request_start()
    assert ep.proxy_id == 2  # any tested proxy outranks an untested one


@pytest.mark.asyncio
async def test_fixed_mode_uses_speed_as_tiebreak(rotator):
    rotator.load_proxies([
        make_proxy(1, latency=50, speed=2),     # tied latency, slow speed
        make_proxy(2, latency=50, speed=500),   # tied latency, much faster
    ])
    rotator.set_mode(RotationMode.FIXED)
    ep = await rotator.on_request_start()
    assert ep.proxy_id == 2


@pytest.mark.asyncio
async def test_success_rate_outranks_low_latency():
    """A proxy with proven high success rate beats a faster-but-flaky one."""
    rotator = ProxyRotator()
    rotator.load_proxies([
        make_proxy(1, latency=50, use_count=2, fail_count=8),   # 20% - fast but flaky
        make_proxy(2, latency=200, use_count=95, fail_count=5), # 95% - slow but reliable
        make_proxy(3, latency=100),                              # untested - neutral
    ])
    rotator.set_mode(RotationMode.ROUND_ROBIN)
    ep1 = await rotator.on_request_start()
    ep2 = await rotator.on_request_start()
    ep3 = await rotator.on_request_start()
    ids = [ep1.proxy_id, ep2.proxy_id, ep3.proxy_id]
    assert ids[0] == 2   # proven reliable first
    assert ids[1] == 3   # untested neutral second (better than known-bad)
    assert ids[2] == 1   # flaky last
