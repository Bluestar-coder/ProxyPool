from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Proxy:
    id: int = 0
    host: str = ""
    port: int = 0
    type: str = "socks5"
    username: str = ""
    password: str = ""
    region: str = ""
    latency: float = -1
    speed: float = -1  # KB/s, -1 = untested
    status: str = "unknown"
    anonymity: str = ""
    supports_rdns: bool = True
    auth_required: bool = False
    use_count: int = 0
    fail_count: int = 0
    consecutive_failures: int = 0
    source: str = "manual"

    @property
    def url(self) -> str:
        if self.username:
            return f"{self.type}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{self.type}://{self.host}:{self.port}"

    @property
    def redacted_url(self) -> str:
        if self.username:
            return f"{self.type}://{self.username}:***@{self.host}:{self.port}"
        return f"{self.type}://{self.host}:{self.port}"


@dataclass(frozen=True)
class ProxyEndpoint:
    proxy_id: int
    url: str
    supports_rdns: bool


@dataclass
class ValidationResult:
    proxy_id: int
    success: bool
    latency: float
    anonymity: str
    region: str
    speed: float = -1.0  # KB/s, -1 = untested
    error: str = ""
    endpoint: str = ""


@dataclass
class ProxyCandidate:
    host: str
    port: int
    type: str
    source: str
    username: str = ""
    password: str = ""


@dataclass
class CrawlerResult:
    source: str
    candidates: list[ProxyCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    quota_exhausted: bool = False
