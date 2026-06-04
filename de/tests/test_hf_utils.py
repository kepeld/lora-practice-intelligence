"""Unit tests for the HuggingFace resilience helper.

Regression cover for the hourly `hf_ingestion` task crashing on a transient
`huggingface.co` DNS / connection blip ("Name or service not known"). The task
paginates `HfApi.list_models()` lazily, so the failure surfaces mid-iteration;
`list_models_with_retry` must absorb brief blips and only fail loudly on a
genuine, sustained outage.
"""

from types import SimpleNamespace

import pytest

from hf_utils import fetch_adapter_config, list_models_with_retry


class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def _models(*ids):
    return [SimpleNamespace(id=i) for i in ids]


class _IterRaises:
    """Mimics HfApi.list_models(): returns a lazy generator that raises only
    once iterated (the real failure mode — pagination is lazy)."""

    def __init__(self, exc):
        self._exc = exc

    def __iter__(self):
        raise self._exc


def test_returns_models_after_transient_failures():
    calls = {"n": 0}

    class Api:
        def list_models(self, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                return _IterRaises(ConnectionError("Name or service not known"))
            return iter(_models("a/b", "c/d"))

    out = list_models_with_retry(Api(), max_attempts=4, sleep=lambda _s: None)

    assert [m.id for m in out] == ["a/b", "c/d"]
    assert calls["n"] == 3  # failed twice, succeeded on the third


def test_reraises_after_exhausting_attempts():
    calls = {"n": 0}

    class Api:
        def list_models(self, **kwargs):
            calls["n"] += 1
            return _IterRaises(ConnectionError("sustained outage"))

    with pytest.raises(ConnectionError):
        list_models_with_retry(Api(), max_attempts=3, sleep=lambda _s: None)

    assert calls["n"] == 3  # exactly max_attempts, then give up


def test_passes_kwargs_through_and_no_backoff_on_first_success():
    received = {}
    sleeps = []

    class Api:
        def list_models(self, **kwargs):
            received.update(kwargs)
            return iter(_models("x/y"))

    out = list_models_with_retry(
        Api(), max_attempts=4, sleep=sleeps.append,
        sort="created_at", direction=-1, limit=100, full=True, filter="peft",
    )

    assert [m.id for m in out] == ["x/y"]
    assert received == {
        "sort": "created_at", "direction": -1,
        "limit": 100, "full": True, "filter": "peft",
    }
    assert sleeps == []  # success on first attempt => never sleeps


def test_non_transient_error_is_not_retried():
    calls = {"n": 0}

    class Api:
        def list_models(self, **kwargs):
            calls["n"] += 1
            raise ValueError("programming bug, not a network blip")

    with pytest.raises(ValueError):
        list_models_with_retry(Api(), max_attempts=4, sleep=lambda _s: None)

    assert calls["n"] == 1  # a real bug surfaces immediately, no retry storm


def test_uses_exponential_backoff_between_attempts():
    sleeps = []

    class Api:
        def list_models(self, **kwargs):
            return _IterRaises(ConnectionError("down"))

    with pytest.raises(ConnectionError):
        list_models_with_retry(
            Api(), max_attempts=4, base_delay=2.0, sleep=sleeps.append,
        )

    # 3 backoffs between 4 attempts: 2, 4, 8 (last attempt does not sleep)
    assert sleeps == [2.0, 4.0, 8.0]


def test_fetch_adapter_config_returns_text_on_200():
    cfg = '{"r": 16, "lora_alpha": 32, "target_modules": ["q_proj", "v_proj"]}'
    out = fetch_adapter_config("org/model", get=lambda url, timeout=10: _Resp(200, cfg))
    assert out == cfg


def test_fetch_adapter_config_none_on_404_without_retry():
    calls = {"n": 0}

    def get(url, timeout=10):
        calls["n"] += 1
        return _Resp(404)

    assert fetch_adapter_config("org/model", get=get) is None
    assert calls["n"] == 1  # 404 = model has no adapter_config; never retry


def test_fetch_adapter_config_none_on_other_status():
    assert fetch_adapter_config("org/model", get=lambda url, timeout=10: _Resp(401)) is None


def test_fetch_adapter_config_retries_transient_then_gives_up_quietly():
    calls = {"n": 0}

    def get(url, timeout=10):
        calls["n"] += 1
        raise ConnectionError("transient")

    # best-effort enrichment: never raises, returns None after exhausting retries
    out = fetch_adapter_config("org/model", get=get, max_attempts=3, sleep=lambda _s: None)
    assert out is None
    assert calls["n"] == 3


def test_fetch_adapter_config_builds_resolve_url():
    seen = {}

    def get(url, timeout=10):
        seen["url"] = url
        return _Resp(200, "{}")

    fetch_adapter_config("meta/llama-lora", get=get)
    assert seen["url"] == "https://huggingface.co/meta/llama-lora/resolve/main/adapter_config.json"
