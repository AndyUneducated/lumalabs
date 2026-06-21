"""MCP tool module state: notify callback, caches, fidelity profile."""

from __future__ import annotations

from browser import CaptureResult
from compare import DEFAULT_PROFILE, resolve_profile

SERVER_NAME = "builder"

_notify_fn = None

_target_cache: dict[str, CaptureResult] = {}
_asset_manifest_cache: dict[str, dict] = {}
_session_profile: str = DEFAULT_PROFILE


def set_notify_fn(fn):
    global _notify_fn
    _notify_fn = fn


def _notify(event="update"):
    if _notify_fn:
        _notify_fn(event)


def set_fidelity_profile(profile: str | None) -> str:
    global _session_profile
    _session_profile = resolve_profile(profile)
    return _session_profile


def get_fidelity_profile() -> str:
    return _session_profile


def _normalize_url(url: str) -> str:
    u = url.strip()
    if not u.startswith(("http://", "https://")):
        u = "https://" + u.lstrip("/")
    return u


def get_target_cache():
    return _target_cache


def get_asset_manifest_cache():
    return _asset_manifest_cache
