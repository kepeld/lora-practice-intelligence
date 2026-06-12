"""Seed a small demo warehouse so the app (and its tests) run without the
pipeline. The real .duckdb file is derived — never committed — so local dev and
CI need a stand-in with the same schemas/columns the API queries.

    python -m app.demo_seed            # writes the local default path
    python -m app.demo_seed out.duckdb # custom path

Refuses to overwrite an existing file unless --force is passed: the real
warehouse must never be clobbered by demo data.
"""

from __future__ import annotations

import json
import sys

PARAMS_AXOLOTL = dict(rank_value=64, lora_alpha=16,
                      target_modules='["q_proj","v_proj","k_proj","o_proj"]',
                      learning_rate=2e-4, optimizer="adamw_8bit", lora_dropout=0.05,
                      lora_bias="none", scheduler="cosine", batch_size=4,
                      gradient_accumulation_steps=2, num_train_epochs=3,
                      warmup_steps=100, bf16=True, fp16=False,
                      gradient_checkpointing=True, merge_and_unload=False,
                      param_sources='{"rank_value":"json","optimizer":"yaml"}',
                      total_params_extracted=14, extraction_confidence=1.0)
PARAMS_UNSLOTH = dict(rank_value=128, lora_alpha=256,
                      target_modules='["q_proj","v_proj","gate_proj","up_proj"]',
                      learning_rate=5e-5, optimizer="adamw_torch_fused", lora_dropout=0.0,
                      lora_bias="none", scheduler="linear", batch_size=2,
                      gradient_accumulation_steps=4, num_train_epochs=2,
                      warmup_steps=50, bf16=True, fp16=False,
                      gradient_checkpointing=True, merge_and_unload=True,
                      param_sources='{"rank_value":"ast"}',
                      total_params_extracted=12, extraction_confidence=0.92)
PARAMS_CARGO = dict(rank_value=8, lora_alpha=16, target_modules='["q_proj","v_proj"]',
                    learning_rate=1e-4, optimizer="adamw_torch", lora_dropout=0.1,
                    lora_bias="none", scheduler="constant", batch_size=1,
                    gradient_accumulation_steps=1, num_train_epochs=1,
                    warmup_steps=0, bf16=False, fp16=True,
                    gradient_checkpointing=False, merge_and_unload=False,
                    param_sources='{"rank_value":"regex"}',
                    total_params_extracted=9, extraction_confidence=0.65)
PARAMS_PAGED = dict(rank_value=32, lora_alpha=64, target_modules='["q_proj","v_proj"]',
                    learning_rate=3e-4, optimizer="paged_adamw_8bit", lora_dropout=0.05,
                    lora_bias="all", scheduler="cosine_with_restarts", batch_size=8,
                    gradient_accumulation_steps=8, num_train_epochs=5,
                    warmup_steps=200, bf16=True, fp16=False,
                    gradient_checkpointing=True, merge_and_unload=True,
                    param_sources='{"optimizer":"ast","rank_value":"llm"}',
                    total_params_extracted=15, extraction_confidence=0.88)

PARAM_COLS = ("rank_value", "lora_alpha", "target_modules", "learning_rate",
              "optimizer", "lora_dropout", "lora_bias", "scheduler", "batch_size",
              "gradient_accumulation_steps", "num_train_epochs", "warmup_steps",
              "bf16", "fp16", "gradient_checkpointing", "merge_and_unload",
              "param_sources", "total_params_extracted", "extraction_confidence")

MODELS = [
    # model_id, author, base, pipeline, library, downloads, likes, fan_out, score parts
    ("alice/llama3-finance-lora", "alice", "meta-llama/Llama-3.1-8B",
     "text-generation", "peft", 48213, 312, 7, 0.98, 0.95, 0.99, PARAMS_AXOLOTL),
    ("med-ai/phi3-clinical-reasoning", "med-ai", "microsoft/Phi-3-mini-4k-instruct",
     "text-generation", "peft", 19450, 244, 12, 0.93, 0.93, 1.0, PARAMS_PAGED),
    ("bob/unsloth-mistral-medical", "bob", "mistralai/Mistral-7B-v0.3",
     "text-generation", "unsloth", 12500, 98, 2, 0.88, 0.84, 0.92, PARAMS_UNSLOTH),
    ("code-masters/qwen2-coder-1.5b-pro", "code-masters", "Qwen/Qwen2-1.5B-Instruct",
     "text-generation", "unsloth", 8920, 76, 1, 0.81, 0.79, 0.85, PARAMS_UNSLOTH),
    ("hf-exp/sgd-is-dead", "hf-exp", "mistralai/Mistral-7B-v0.3",
     "text-generation", "peft", 110, 2, 0, 0.31, 0.22, 0.0, PARAMS_CARGO),
    ("fail-whale/overfitted-garbage", "fail-whale", "meta-llama/Llama-3.1-8B",
     "text-generation", "peft", 42, 0, 0, 0.12, 0.05, 0.0, PARAMS_CARGO),
]

REPOS = [
    # repo_id, name, description, lang, topics, stars, forks, tests, ci, params
    (1, "axolotl/llama-3-configs", "Production-ready configs for fine-tuning Llama 3.1 with PEFT.",
     "Python", '["llama3","lora","axolotl"]', 1420, 310, True, True, PARAMS_AXOLOTL),
    (2, "unsloth/unsloth-examples", "Notebooks and training scripts for 2x faster LoRA fine-tuning.",
     "Jupyter Notebook", '["unsloth","fine-tuning"]', 5100, 940, True, False, PARAMS_UNSLOTH),
    (3, "random-user/cargo-cult-lora", "Generic scripts copy-pasted from old tutorials.",
     "Python", '["tutorial"]', 4, 1, False, False, PARAMS_CARGO),
    (4, "intel-analytics/phi3-medical-expert", "Paged optimizers to inject medical domain knowledge into Phi-3.",
     "Python", '["phi3","medical","qlora"]', 389, 42, True, True, PARAMS_PAGED),
    (5, "quant-trading-group/qwen2-finance-math", "Tuning Qwen2-7B on alternative data.",
     "Python", '["qwen2","finance"]', 122, 19, False, False, None),
]

# param_name, param_value, prevalence, avg_score, vs_base, lift, sample_ok, quadrant
PRACTICE_STATS = [
    ("optimizer", "paged_adamw_8bit", 4, 0.93, 0.24, 0.21, True, "rare+works"),
    ("optimizer", "adamw_8bit", 12, 0.74, 0.21, 0.18, True, "rare+works"),
    ("optimizer", "adamw_torch_fused", 145, 0.69, 0.05, 0.06, True, "common+works"),
    ("optimizer", "adamw_torch", 88, 0.41, -0.11, -0.13, True, "common+fails"),
    ("optimizer", "sgd", 2, 0.28, -0.19, -0.25, False, "rare+fails"),
    ("rank_value", "128", 9, 0.7, 0.16, 0.12, True, "rare+works"),
    ("rank_value", "64", 84, 0.66, 0.07, 0.08, True, "common+works"),
    ("rank_value", "8", 210, 0.45, -0.06, -0.08, True, "common+fails"),
    ("rank_value", "2", 3, 0.21, -0.22, -0.3, True, "rare+fails"),
    ("scheduler", "cosine", 198, 0.68, 0.06, 0.07, True, "common+works"),
    ("scheduler", "constant", 54, 0.33, -0.14, -0.21, True, "common+fails"),
    ("scheduler", "cosine_with_restarts", 5, 0.79, 0.18, 0.17, True, "rare+works"),
    ("lora_alpha", "16", 89, 0.43, -0.09, -0.1, True, "common+fails"),
    ("lora_alpha", "256", 7, 0.72, 0.15, 0.14, True, "rare+works"),
    ("lora_dropout", "0.05", 120, 0.64, 0.04, 0.05, True, "common+works"),
    ("bf16", "true", 240, 0.62, 0.03, 0.04, True, "common+works"),
    ("learning_rate", "0.0002", 96, 0.61, 0.02, 0.03, True, "common+works"),
    ("batch_size", "1", 6, 0.3, -0.16, -0.2, True, "rare+fails"),
]

LINKS = [
    ("axolotl/llama-3-configs", "alice/llama3-finance-lora", 0.92),
    ("intel-analytics/phi3-medical-expert", "med-ai/phi3-clinical-reasoning", 0.88),
    ("unsloth/unsloth-examples", "bob/unsloth-mistral-medical", 0.74),
]

_TS = "2026-06-01 12:00:00"


def seed(path: str, force: bool = False) -> str:
    """Create the demo warehouse at `path`. Returns the path."""
    import os

    import duckdb

    if os.path.exists(path) and not force:
        raise FileExistsError(f"{path} already exists; pass force=True to overwrite")
    if os.path.exists(path):
        os.remove(path)

    con = duckdb.connect(path)
    try:
        for schema in ("BRONZE", "SILVER", "GOLD"):
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

        param_ddl = """
            rank_value INTEGER, lora_alpha INTEGER, target_modules VARCHAR,
            learning_rate DOUBLE, optimizer VARCHAR, lora_dropout DOUBLE,
            lora_bias VARCHAR, scheduler VARCHAR, batch_size INTEGER,
            gradient_accumulation_steps INTEGER, num_train_epochs INTEGER,
            warmup_steps INTEGER, bf16 BOOLEAN, fp16 BOOLEAN,
            gradient_checkpointing BOOLEAN, merge_and_unload BOOLEAN,
            param_sources VARCHAR, total_params_extracted INTEGER,
            extraction_confidence DOUBLE"""

        con.execute(f"""CREATE TABLE SILVER.HF_MODELS_LORA_PARAMS (
            model_id VARCHAR, {param_ddl}, extracted_at TIMESTAMP)""")
        con.execute(f"""CREATE TABLE GOLD.REPO_LORA_PARAMS (
            repo_full_name VARCHAR, {param_ddl}, extracted_at TIMESTAMP,
            primary_language VARCHAR, star_count INTEGER,
            contributors_count INTEGER, has_tests BOOLEAN, has_ci BOOLEAN)""")
        con.execute("""CREATE TABLE GOLD.REPO_LORA_OUTCOMES (
            model_id VARCHAR, author VARCHAR, base_model VARCHAR,
            pipeline_tag VARCHAR, library_name VARCHAR, downloads INTEGER,
            likes INTEGER, fine_tune_fan_out INTEGER, is_fine_tune BOOLEAN,
            downloads_pct DOUBLE, likes_pct DOUBLE, fan_out_pct DOUBLE,
            composite_success_score DOUBLE)""")
        con.execute("""CREATE TABLE SILVER.HF_MODELS (
            model_id VARCHAR, author VARCHAR, base_model VARCHAR,
            pipeline_tag VARCHAR, library_name VARCHAR, downloads INTEGER,
            likes INTEGER, tags VARCHAR, tag_count INTEGER, is_fine_tune BOOLEAN,
            created_at TIMESTAMP, last_modified TIMESTAMP)""")
        con.execute("""CREATE TABLE SILVER.REPOS (
            repo_id BIGINT, repo_name VARCHAR, star_count INTEGER,
            fork_count INTEGER, event_count INTEGER, description VARCHAR,
            primary_language VARCHAR, topics VARCHAR, license VARCHAR,
            open_issues_count INTEGER, readme_length INTEGER,
            repo_created_at TIMESTAMP, pushed_at TIMESTAMP, repo_size_kb INTEGER,
            has_tests BOOLEAN, has_ci BOOLEAN, contributors_count INTEGER,
            commit_count_30d INTEGER, is_fork BOOLEAN, is_archived BOOLEAN,
            forks_count INTEGER, subscribers_count INTEGER, homepage VARCHAR,
            enriched_at TIMESTAMP, enrichment_status VARCHAR, is_enriched BOOLEAN)""")
        con.execute("""CREATE TABLE SILVER.GITHUB_HF_LINKS (
            repo_full_name VARCHAR, model_id VARCHAR, best_confidence DOUBLE)""")
        con.execute("""CREATE TABLE GOLD.HF_MODEL_TREE (
            base_model VARCHAR, fine_tune_count INTEGER, total_downloads BIGINT,
            total_likes BIGINT, fine_tune_models VARCHAR[])""")
        con.execute("""CREATE TABLE GOLD.LORA_PRACTICE_STATS (
            param_name VARCHAR, param_value VARCHAR, prevalence INTEGER,
            avg_success_score DOUBLE, avg_score_vs_base DOUBLE,
            score_lift DOUBLE, sample_ok BOOLEAN, quadrant VARCHAR)""")
        con.execute("""CREATE TABLE BRONZE.GITHUB_FILES (
            file_id BIGINT, repo_full_name VARCHAR, file_path VARCHAR,
            file_category VARCHAR, content VARCHAR)""")

        def params_values(p):
            return [p[c] if c != "extraction_confidence" else float(p[c])
                    for c in PARAM_COLS]

        for (mid, author, base, pipe, lib, dl, likes, fan,
             dpct, lpct, fpct, params) in MODELS:
            score = round(0.55 * dpct + 0.35 * lpct + 0.10 * fpct, 4)
            con.execute(
                "INSERT INTO GOLD.REPO_LORA_OUTCOMES VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [mid, author, base, pipe, lib, dl, likes, fan, True,
                 dpct, lpct, fpct, score])
            con.execute(
                "INSERT INTO SILVER.HF_MODELS VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [mid, author, base, pipe, lib, dl, likes,
                 json.dumps(["lora", pipe]), 2, True, _TS, _TS])
            con.execute(
                f"INSERT INTO SILVER.HF_MODELS_LORA_PARAMS VALUES "
                f"(?{',?' * len(PARAM_COLS)},?)",
                [mid] + params_values(params) + [_TS])

        for (rid, name, desc, lang, topics, stars, forks,
             tests, ci, params) in REPOS:
            con.execute(
                "INSERT INTO SILVER.REPOS VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [rid, name, stars, forks, 0, desc, lang, topics, "MIT", 3,
                 4200, _TS, _TS, 900, tests, ci, 4, 12, False, False,
                 forks, 10, None, _TS, "ok", True])
            if params:
                con.execute(
                    f"INSERT INTO GOLD.REPO_LORA_PARAMS VALUES "
                    f"(?{',?' * len(PARAM_COLS)},?,?,?,?,?,?)",
                    [name] + params_values(params)
                    + [_TS, lang, stars, 4, tests, ci])
            con.execute(
                "INSERT INTO BRONZE.GITHUB_FILES VALUES (?,?,?,?,?)",
                [rid, name, "train.py", "training_script", "LoraConfig(r=16)"])

        for repo, mid, conf in LINKS:
            con.execute("INSERT INTO SILVER.GITHUB_HF_LINKS VALUES (?,?,?)",
                        [repo, mid, conf])

        con.execute("""
            INSERT INTO GOLD.HF_MODEL_TREE
            SELECT base_model, count(*), sum(downloads), sum(likes),
                   array_agg(model_id)
            FROM GOLD.REPO_LORA_OUTCOMES
            WHERE base_model IS NOT NULL
            GROUP BY base_model""")

        con.executemany(
            "INSERT INTO GOLD.LORA_PRACTICE_STATS VALUES (?,?,?,?,?,?,?,?)",
            [list(r) for r in PRACTICE_STATS])
    finally:
        con.close()
    return path


if __name__ == "__main__":
    from .db import LOCAL_DEFAULT
    args = [a for a in sys.argv[1:] if a != "--force"]
    out = args[0] if args else LOCAL_DEFAULT
    seed(out, force="--force" in sys.argv)
    print(f"demo warehouse written to {out}")
