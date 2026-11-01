"""fcrawl - web search, scraping, Reddit, X, YouTube and Dcard for AI coding agents"""

from importlib.metadata import PackageNotFoundError, version

# single source of truth: [project] version in pyproject.toml
try:
    __version__ = version("fcrawl")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"

from .cli import cli

__all__ = ["__version__", "cli"]
