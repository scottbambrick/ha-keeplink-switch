"""Load the integration's plain-Python modules without Home Assistant.

The package's __init__.py imports Home Assistant, so the package is
registered here by path instead; aiohttp is stubbed when not installed (the
tests replace the HTTP layer).
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "custom_components.keeplink_switch"

sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
_pkg = types.ModuleType(PACKAGE)
_pkg.__path__ = [str(ROOT / "custom_components" / "keeplink_switch")]
sys.modules[PACKAGE] = _pkg

try:
    import aiohttp  # noqa: F401
except ImportError:
    _aiohttp = types.ModuleType("aiohttp")
    _aiohttp.ClientError = type("ClientError", (Exception,), {})
    _aiohttp.ClientSession = object
    sys.modules["aiohttp"] = _aiohttp
