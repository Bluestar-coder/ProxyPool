from app.db.models import Proxy, ProxyEndpoint, ValidationResult, ProxyCandidate, CrawlerResult


def test_proxy_url_no_auth():
    p = Proxy(host="1.2.3.4", port=1080, type="socks5")
    assert p.url == "socks5://1.2.3.4:1080"


def test_proxy_url_with_auth():
    p = Proxy(host="1.2.3.4", port=1080, type="socks5", username="u", password="p")
    assert p.url == "socks5://u:p@1.2.3.4:1080"


def test_proxy_redacted_url():
    p = Proxy(host="1.2.3.4", port=1080, type="socks5", username="u", password="secret")
    assert p.redacted_url == "socks5://u:***@1.2.3.4:1080"
    assert "secret" not in p.redacted_url


def test_proxy_endpoint_immutable():
    ep = ProxyEndpoint(proxy_id=1, url="socks5://1.2.3.4:1080", supports_rdns=True)
    assert ep.proxy_id == 1


def test_validation_result_defaults():
    r = ValidationResult(proxy_id=1, success=False, latency=-1, anonymity="", region="")
    assert r.error == ""


def test_crawler_result_not_exhausted():
    r = CrawlerResult(source="fofa", candidates=[], errors=[])
    assert r.quota_exhausted is False
