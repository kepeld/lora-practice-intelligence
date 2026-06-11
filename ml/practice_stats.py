"""LoRA practice-stats quadrants (US-4.2, Issue #10) — pandas mirror of the
gold.lora_practice_stats dbt model, for offline exploration.

dbt is canonical; this mirrors its logic so the ML side can explore quadrants on
a DataFrame (e.g. ml.data outputs) without re-running the warehouse.

For each (parameter, value) bucket it computes prevalence, mean success score,
the base_model-stratified score (avg_score_vs_base), an effect size (score_lift),
a min-sample flag (sample_ok), and a quadrant. The works/fails axis uses the
base-stratified score to control for base-model popularity (Risk 3); see the dbt
model header for the rationale.
"""

from __future__ import annotations

# Same parameters the dbt long-form unions.
DEFAULT_PARAMS = (
    "rank_value", "lora_alpha", "optimizer", "scheduler", "batch_size",
    "num_train_epochs", "gradient_accumulation_steps", "lora_dropout", "bf16",
    "learning_rate", "lora_bias", "warmup_steps", "gradient_checkpointing",
    "fp16",
)
MIN_SAMPLE = 3


def _score_vs_base(models, reference_models=None):
    """Per-model outperformance vs same-base peers (global mean when base unknown).

    Peer/global means come from `reference_models` when given; by default they
    are computed from `models` itself. NOTE: the dbt model derives them from the
    FULL repo_lora_outcomes mart — passing a subset (e.g. only models with
    extracted params) without `reference_models` yields a different reference
    population, and possibly different quadrants, than the warehouse (#53).
    Pass the full outcomes frame as `reference_models` for warehouse parity.
    """
    reference = models if reference_models is None else reference_models
    global_mean = reference["composite_success_score"].mean()
    base_means = (
        reference.dropna(subset=["base_model"])
        .groupby("base_model")["composite_success_score"]
        .mean()
    )
    # bases absent from the reference (and NULL bases) fall back to the global
    # mean, matching the dbt coalesce(base_avg, global).
    peer = models["base_model"].map(base_means).fillna(global_mean)
    return models["composite_success_score"] - peer


def practice_stats(models, param_cols=DEFAULT_PARAMS, min_sample=MIN_SAMPLE,
                   reference_models=None):
    """Compute the quadrant table from a model-level DataFrame.

    `models` needs columns: model_id, base_model, composite_success_score, and
    the parameter columns. `reference_models` (optional) is the population used
    for the base-peer means — pass the full outcomes mart to match dbt (#53).
    Returns one row per (param_name, param_value).
    """
    df = models.copy()
    df["score_vs_base"] = _score_vs_base(df, reference_models)

    present = [c for c in param_cols if c in df.columns]
    long = df.melt(
        id_vars=["model_id", "composite_success_score", "score_vs_base"],
        value_vars=present,
        var_name="param_name",
        value_name="param_value",
    ).dropna(subset=["param_value"])
    long["param_value"] = long["param_value"].astype(str)

    buckets = (
        long.groupby(["param_name", "param_value"])
        .agg(
            prevalence=("model_id", "nunique"),
            avg_success_score=("composite_success_score", "mean"),
            avg_score_vs_base=("score_vs_base", "mean"),
        )
        .reset_index()
    )

    param_pooled = long.groupby("param_name")["composite_success_score"].mean()
    medians = buckets.groupby("param_name").agg(
        prevalence_median=("prevalence", "median"),
        vsbase_median=("avg_score_vs_base", "median"),
    )

    # Quadrant axes use unrounded values; rounding is cosmetic and applied last.
    buckets["score_lift"] = buckets["avg_success_score"] - buckets["param_name"].map(param_pooled)
    buckets["sample_ok"] = buckets["prevalence"] >= min_sample

    common = buckets["prevalence"] >= buckets["param_name"].map(medians["prevalence_median"])
    works = buckets["avg_score_vs_base"] >= buckets["param_name"].map(medians["vsbase_median"])
    buckets["quadrant"] = [
        f"{'common' if c else 'rare'}+{'works' if w else 'fails'}"
        for c, w in zip(common, works)
    ]

    for col in ("avg_success_score", "avg_score_vs_base", "score_lift"):
        buckets[col] = buckets[col].round(3)

    return buckets.sort_values(
        ["param_name", "prevalence"], ascending=[True, False]
    ).reset_index(drop=True)
