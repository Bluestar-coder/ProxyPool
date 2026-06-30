from PyQt6.QtCore import Qt
from app.ui.proxy_table import ProxyTableModel
from app.db.models import Proxy


def _make_proxy(id_, latency: float = -1, speed: float = -1):
    return Proxy(id=id_, host=f"1.2.3.{id_}", port=1080, type="socks5",
                 status="valid", latency=latency, speed=speed)


def _model_with(proxies):
    m = ProxyTableModel()
    m.load(proxies, total=len(proxies), page=1, page_size=len(proxies))
    return m


def test_sort_speed_ascending_keeps_untested_last():
    proxies = [
        _make_proxy(1, speed=50.0),
        _make_proxy(2, speed=-1),    # untested
        _make_proxy(3, speed=10.0),
    ]
    m = _model_with(proxies)
    m.sort(6, Qt.SortOrder.AscendingOrder)
    ids = [p.id for p in m._proxies]
    assert ids == [3, 1, 2]  # slowest real value first, untested last


def test_sort_speed_descending_keeps_untested_last():
    proxies = [
        _make_proxy(1, speed=50.0),
        _make_proxy(2, speed=-1),    # untested
        _make_proxy(3, speed=10.0),
    ]
    m = _model_with(proxies)
    m.sort(6, Qt.SortOrder.DescendingOrder)
    ids = [p.id for p in m._proxies]
    assert ids == [1, 3, 2]  # fastest real value first, untested still last


def test_sort_latency_ascending_keeps_untested_last():
    proxies = [
        _make_proxy(1, latency=50.0),
        _make_proxy(2, latency=-1),  # untested
        _make_proxy(3, latency=10.0),
    ]
    m = _model_with(proxies)
    m.sort(5, Qt.SortOrder.AscendingOrder)
    ids = [p.id for p in m._proxies]
    assert ids == [3, 1, 2]  # lowest latency first, untested last
