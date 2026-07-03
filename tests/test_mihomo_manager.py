import unittest
from unittest.mock import patch


class TestPlatformAssetName(unittest.TestCase):
    def _call(self, system, machine, tag):
        from app.core.mihomo_manager import _platform_asset_name
        with patch("platform.system", return_value=system), \
             patch("platform.machine", return_value=machine):
            return _platform_asset_name(tag)

    def test_darwin_arm64(self):
        self.assertEqual(self._call("Darwin", "arm64", "v1.2.3"), "mihomo-darwin-arm64-v1.2.3.gz")

    def test_darwin_amd64(self):
        self.assertEqual(self._call("Darwin", "x86_64", "v1.2.3"), "mihomo-darwin-amd64-v1.2.3.gz")

    def test_linux_amd64(self):
        self.assertEqual(self._call("Linux", "amd64", "v1.2.3"), "mihomo-linux-amd64-v1.2.3.gz")

    def test_windows_amd64(self):
        self.assertEqual(self._call("Windows", "x86_64", "v1.2.3"), "mihomo-windows-amd64-v1.2.3.zip")


class TestMihomoProcessStop(unittest.TestCase):
    def test_stop_when_process_not_running(self):
        """stop() 在进程已不存在时不应抛异常"""
        from app.core.mihomo_manager import MihomoProcess
        proc = MihomoProcess.__new__(MihomoProcess)
        proc._proc = None
        proc.stop()  # must not raise


if __name__ == "__main__":
    unittest.main()
