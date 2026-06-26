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
    ids = [ep.proxy_id for ep in
           [await rotator.on_request_start() for _ in range(4)]]
    assert ids[:3] == [1, 2, 3]
    assert ids[3] == 1  # 循环


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
