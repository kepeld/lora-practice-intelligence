"""Resilience helpers for HuggingFace Hub calls (retry + adapter_config fetch)."""

from __future__ import annotations

import time

# requests ConnectionError/Timeout, huggingface_hub HfHubHTTPError and socket.gaierror
# are all OSError subclasses: OSError retries the transient network failures without a
# requests/hf import, and keeps programming errors (ValueError, ...) out of the retry.
TRANSIENT_NETWORK_ERRORS = (OSError,)


def list_models_with_retry(
    api,
    *,
    max_attempts: int = 4,
    base_delay: float = 2.0,
    transient_errors: tuple = TRANSIENT_NETWORK_ERRORS,
    sleep=time.sleep,
    **list_models_kwargs,
):
    """Materialise api.list_models(**kwargs) with bounded exponential backoff.

    list_models paginates lazily, so a transient blip surfaces mid-iteration;
    materialising inside the retry restarts cleanly. Re-raises after max_attempts.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return list(api.list_models(**list_models_kwargs))
        except transient_errors as exc:
            last_exc = exc
            if attempt >= max_attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            print(
                f"list_models_with_retry: attempt {attempt}/{max_attempts} failed "
                f"({type(exc).__name__}: {exc}); retrying in {delay:.0f}s"
            )
            sleep(delay)
    raise last_exc


def fetch_adapter_config(
    model_id: str,
    *,
    get=None,
    revision: str = "main",
    max_attempts: int = 3,
    base_delay: float = 2.0,
    transient_errors: tuple = TRANSIENT_NETWORK_ERRORS,
    sleep=time.sleep,
):
    """Fetch a HF model's adapter_config.json (PEFT canonical LoRA config) text, or None.

    Best-effort enrichment: never raises — returns None when the model has no
    adapter (404), is unreachable, or the network stays down after max_attempts.
    """
    if get is None:
        import requests
        get = requests.get
    url = f"https://huggingface.co/{model_id}/resolve/{revision}/adapter_config.json"
    for attempt in range(1, max_attempts + 1):
        try:
            resp = get(url, timeout=10)
        except transient_errors:
            if attempt >= max_attempts:
                return None
            sleep(base_delay * (2 ** (attempt - 1)))
            continue
        # 200 -> the config; anything else (404 no-adapter, 401, 5xx body) is a
        # definitive "nothing usable here" — do not retry a real HTTP response.
        return resp.text if getattr(resp, "status_code", None) == 200 else None
    return None
