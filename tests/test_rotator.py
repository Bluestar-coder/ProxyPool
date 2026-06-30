import asyncio
import pytest
from app.core.rotator import ProxyRotator, RotationMode
from app.db.models import Proxy


def make_proxy(id_, latency=100.0, status="valid"):
    return Proxy(id=id_, host=f"1.2.3.{id_}", port=1080, type="socks5",
                 status=status, latency=latency)


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
