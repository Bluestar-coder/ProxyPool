import csv
import json
import pytest
from pathlib import Path

from app.db.models import Proxy
from app.ui.dialogs.export_proxy import _write


@pytest.fixture
def proxies():
    return [
        Proxy(host="1.2.3.4", port=1080, type="socks5",
              username="u", password="secret", status="valid",
              region="US", latency=0.5, anonymity="elite"),
        Proxy(host="5.6.7.8", port=8080, type="http",
              status="valid", region="CN", latency=1.2, anonymity="transparent"),
    ]


class TestWrite:
    def test_txt_host_port(self, proxies, tmp_path):
        p = tmp_path / "out.txt"
        _write(p, proxies, "txt (host:port)", redact=True)
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines == ["1.2.3.4:1080", "5.6.7.8:8080"]

    def test_txt_url_redacted(self, proxies, tmp_path):
        p = tmp_path / "out.txt"
        _write(p, proxies, "txt (url)", redact=True)
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "socks5://u:***@1.2.3.4:1080"
        assert "secret" not in lines[0]
        assert lines[1] == "http://5.6.7.8:8080"

    def test_txt_url_unredacted(self, proxies, tmp_path):
        p = tmp_path / "out.txt"
        _write(p, proxies, "txt (url)", redact=False)
        lines = p.read_text(encoding="utf-8").splitlines()
        assert "secret" in lines[0]

    def test_csv_redacted(self, proxies, tmp_path):
        p = tmp_path / "out.csv"
        _write(p, proxies, "csv", redact=True)
        with p.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert rows[0][4] == "password"          # header
        assert rows[1][4] == "***"               # redacted
        assert "secret" not in str(rows)

    def test_csv_unredacted(self, proxies, tmp_path):
        p = tmp_path / "out.csv"
        _write(p, proxies, "csv", redact=False)
        with p.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        assert rows[1][4] == "secret"

    def test_json_redacted(self, proxies, tmp_path):
        p = tmp_path / "out.json"
        _write(p, proxies, "json", redact=True)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert "password" not in data[0]
        assert "secret" not in str(data)

    def test_json_unredacted(self, proxies, tmp_path):
        p = tmp_path / "out.json"
        _write(p, proxies, "json", redact=False)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data[0]["password"] == "secret"
