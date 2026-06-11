"""Composite LoRA success score (US-4.1, Issue #6) — pandas mirror of the
gold.repo_lora_outcomes dbt model, for offline weight experimentation.

dbt is canonical; this mirrors its logic so the ML side can re-score and tune
weights on a DataFrame (e.g. ml.data.outcomes(), or a join of hf_models +
hf_model_tree) without re-running the warehouse.

    from ml.data import load
    import ml.scoring as scoring
    scored = scoring.add_success_score(load("outcomes"))

Each signal is mapped to its percentile (PERCENT_RANK: (rank-1)/(n-1) in [0,1])
then blended with WEIGHTS. See the dbt model header for the selection-bias
caveat (Risk 3). Column lookup is case-insensitive (DuckDB is case-insensitive
for unquoted identifiers).
"""

from __future__ import annotations

# Tunable weights — should sum to 1.0. fine_tune_fan_out is the hardest signal
# to game (other people built on the model), so it carries the most weight.
WEIGHTS = {"fine_tune_fan_out": 0.5, "downloads": 0.3, "likes": 0.2}

_SIGNALS = ("downloads", "likes", "fine_tune_fan_out")


def _percent_rank(series):
    """PERCENT_RANK equivalent: (rank-1)/(n-1) in [0,1]; 0.0 when n <= 1."""
    n = len(series)
    if n <= 1:
        return series.rank(method="min") * 0.0
    return (series.rank(method="min") - 1.0) / (n - 1)


def add_success_score(df, weights=None):
    """Return a copy of `df` with <signal>_pct columns and composite_success_score.

    `df` must contain (case-insensitively) downloads, likes, fine_tune_fan_out.
    """
    weights = weights or WEIGHTS
    cols = {c.lower(): c for c in df.columns}
    missing = [s for s in _SIGNALS if s not in cols]
    if missing:
        raise KeyError(f"missing required columns: {missing}")

    out = df.copy()
    out["downloads_pct"] = _percent_rank(out[cols["downloads"]].fillna(0)).round(4)
    out["likes_pct"] = _percent_rank(out[cols["likes"]].fillna(0)).round(4)
    out["fan_out_pct"] = _percent_rank(out[cols["fine_tune_fan_out"]].fillna(0)).round(4)
    out["composite_success_score"] = (
        weights["downloads"] * out["downloads_pct"]
        + weights["likes"] * out["likes_pct"]
        + weights["fine_tune_fan_out"] * out["fan_out_pct"]
    ).round(4)
    return out
