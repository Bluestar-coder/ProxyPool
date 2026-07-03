from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
from pathlib import Path

_logger = logging.getLogger(__name__)

from app.core.crawlers.base import BaseCrawler, CrawlPage, RateLimited, QuotaExhausted
from app.core.crawlers.fofa import FofaCrawler
from app.core.crawlers.quake import QuakeCrawler
from app.core.crawlers.hunter import HunterCrawler
from app.core.crawlers.free_sites import FreeSitesCrawler

_PACKAGE_DIR = Path(__file__).parent


def _all_subclasses(cls: type) -> list[type]:
    result = []
    for sub in cls.__subclasses__():
        result.append(sub)
        result.extend(_all_subclasses(sub))
    return result


def discover_crawlers(plugin_dir: Path | None = None) -> list[type[BaseCrawler]]:
    """Return all BaseCrawler subclasses, importing built-ins and any plugins."""
    for _, name, _ in pkgutil.iter_modules([str(_PACKAGE_DIR)]):
        if name != "base":
            _ = importlib.import_module(f"app.core.crawlers.{name}")

    if plugin_dir is not None:
        for path in sorted(Path(plugin_dir).glob("*.py")):
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                try:
                    spec.loader.exec_module(mod)  # type: ignore[arg-type]
                except Exception:
                    _logger.warning("Skipping plugin %s", path, exc_info=True)

    return _all_subclasses(BaseCrawler)  # type: ignore[return-value]


__all__ = [
    "BaseCrawler", "CrawlPage", "RateLimited", "QuotaExhausted",
    "FofaCrawler", "QuakeCrawler", "HunterCrawler", "FreeSitesCrawler",
    "discover_crawlers",
]
