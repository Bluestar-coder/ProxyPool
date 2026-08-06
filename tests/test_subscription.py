import base64
import unittest

SAMPLE_YAML = """\
proxies:
  - name: node1
    type: vmess
    server: 1.2.3.4
    port: 443
    uuid: aaaabbbb-cccc-dddd-eeee-ffff00001111
    alterId: 0
    cipher: auto
  - name: node2
    type: trojan
    server: 5.6.7.8
    port: 8443
    password: secret123
"""


class TestCredentialExtraction(unittest.TestCase):
    def _username(self, cfg: dict):
        from app.core.subscription import _username_for
        return _username_for(cfg)

    def _password(self, cfg: dict):
        from app.core.subscription import _password_for
        return _password_for(cfg)

    def test_vmess_uses_uuid_as_username_no_password(self):
        cfg = {"type": "vmess", "uuid": "test-uuid"}
        assert self._username(cfg) == "test-uuid"
        assert self._password(cfg) == ""

    def test_trojan_uses_password_as_username_no_separate_password(self):
        cfg = {"type": "trojan", "password": "secret"}
        assert self._username(cfg) == "secret"
        assert self._password(cfg) == ""

    def test_ss_uses_password_as_username_no_separate_password(self):
        cfg = {"type": "ss", "password": "key123"}
        assert self._username(cfg) == "key123"
        assert self._password(cfg) == ""

    def test_socks5_preserves_username_and_password(self):
        cfg = {"type": "socks5", "username": "user", "password": "pass"}
        assert self._username(cfg) == "user"
        assert self._password(cfg) == "pass"

    def test_http_preserves_username_and_password(self):
        cfg = {"type": "http", "username": "admin", "password": "s3cr3t"}
        assert self._username(cfg) == "admin"
        assert self._password(cfg) == "s3cr3t"


class TestSubscriptionParser(unittest.TestCase):
    def _parse(self, text: str):
        from app.core.subscription import _parse_subscription
        return _parse_subscription(text)

    def test_yaml_with_vmess_and_trojan(self):
        result = self._parse(SAMPLE_YAML)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "vmess")
        self.assertEqual(result[0]["server"], "1.2.3.4")
        self.assertEqual(result[1]["type"], "trojan")
        self.assertEqual(result[1]["server"], "5.6.7.8")

    def test_base64_encoded_yaml(self):
        encoded = base64.b64encode(SAMPLE_YAML.encode()).decode()
        result = self._parse(encoded)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["type"], "vmess")

    def test_empty_string_returns_empty_list(self):
        self.assertEqual(self._parse(""), [])

    def test_non_yaml_text_returns_empty_list(self):
        self.assertEqual(self._parse("vmess://AAABBBCCC\ntrojan://XYZ"), [])

    def test_empty_proxies_list_returns_empty_list(self):
        yaml_empty = "proxies: []\n"
        self.assertEqual(self._parse(yaml_empty), [])


if __name__ == "__main__":
    unittest.main()
