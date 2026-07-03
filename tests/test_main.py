"""Tests for main._resolve_log_level."""
from __future__ import annotations

import logging

import pytest

from main import _resolve_log_level


class TestResolveLogLevel:
    def test_default_is_info(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("PROXYPOOL_LOG_LEVEL", raising=False)
        assert _resolve_log_level() == logging.INFO

    def test_debug_level(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_LOG_LEVEL", "DEBUG")
        assert _resolve_log_level() == logging.DEBUG

    def test_warning_level(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_LOG_LEVEL", "WARNING")
        assert _resolve_log_level() == logging.WARNING

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_LOG_LEVEL", "debug")
        assert _resolve_log_level() == logging.DEBUG

    def test_invalid_value_falls_back_to_info(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("PROXYPOOL_LOG_LEVEL", "NONSENSE")
        assert _resolve_log_level() == logging.INFO
