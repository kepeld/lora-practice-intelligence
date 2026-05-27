"""Unit tests for the LoRA-config extractor (de/ingestion/lora_config_extractor.py)."""

from lora_config_extractor import (
    extract_from_adapter_config,
    extract_from_file,
    extract_from_python,
    extract_from_readme,
    extract_from_yaml,
    merge_params,
)


def _find(rows, name):
    return next((r for r in rows if r["param_name"] == name), None)


# ---------------------------------------------------------------------------
# AST layer
# ---------------------------------------------------------------------------

def test_ast_extracts_loraconfig_kwargs():
    code = (
        "from peft import LoraConfig\n"
        "config = LoraConfig(r=16, lora_alpha=32, "
        "target_modules=['q_proj','v_proj'], lora_dropout=0.05)\n"
    )
    rows = extract_from_python(code)
    rank = _find(rows, "rank_value")
    alpha = _find(rows, "lora_alpha")
    target = _find(rows, "target_modules")
    dropout = _find(rows, "lora_dropout")
    assert rank and rank["param_value"] == "16" and rank["confidence"] == 1.0
    assert alpha and alpha["param_value"] == "32"
    assert target and "q_proj" in target["param_value"]
    assert dropout and dropout["param_value"] == "0.05"
    assert all(r["source"] == "ast" for r in rows)


def test_ast_extracts_training_arguments():
    code = (
        "from transformers import TrainingArguments\n"
        "args = TrainingArguments(\n"
        "    learning_rate=2e-4, per_device_train_batch_size=4,\n"
        "    num_train_epochs=3, optim='adamw_torch', bf16=True,\n"
        "    gradient_accumulation_steps=8, warmup_steps=100)\n"
    )
    rows = extract_from_python(code)
    assert _find(rows, "learning_rate")["param_value"] == "0.0002"
    assert _find(rows, "batch_size")["param_value"] == "4"
    assert _find(rows, "num_train_epochs")["param_value"] == "3"
    assert _find(rows, "optimizer")["param_value"] == "adamw_torch"
    assert _find(rows, "bf16")["param_value"] == "true"
    assert _find(rows, "gradient_accumulation_steps")["param_value"] == "8"
    assert _find(rows, "warmup_steps")["param_value"] == "100"


def test_ast_ignores_unrelated_calls():
    # `print(r=16)` is syntactically valid as a kwarg; the AST layer must NOT
    # mine it because `print` is not in the target-call allowlist.
    code = "x = LoraConfig(r=16)\nprint(r=99)\n"  # print's kwarg ignored
    rows = extract_from_python(code)
    ranks = [r for r in rows if r["param_name"] == "rank_value"]
    assert len(ranks) == 1
    assert ranks[0]["param_value"] == "16"


def test_ast_handles_syntax_errors_gracefully():
    rows = extract_from_python("def f(:\n    pass")  # broken syntax
    assert rows == []


# ---------------------------------------------------------------------------
# adapter_config.json layer
# ---------------------------------------------------------------------------

def test_adapter_config_high_confidence():
    blob = '{"r": 8, "lora_alpha": 16, "target_modules": ["q_proj","v_proj"], "lora_dropout": 0.0}'
    rows = extract_from_adapter_config(blob)
    assert all(r["source"] == "json" and r["confidence"] == 1.0 for r in rows)
    assert _find(rows, "rank_value")["param_value"] == "8"
    assert "q_proj" in _find(rows, "target_modules")["param_value"]


def test_adapter_config_skips_nulls_and_unknowns():
    blob = '{"r": 16, "lora_alpha": null, "foo": "bar"}'
    rows = extract_from_adapter_config(blob)
    names = {r["param_name"] for r in rows}
    assert names == {"rank_value"}


def test_adapter_config_invalid_json_returns_empty():
    assert extract_from_adapter_config("not-json") == []
    assert extract_from_adapter_config("") == []


# ---------------------------------------------------------------------------
# YAML layer
# ---------------------------------------------------------------------------

def test_yaml_extracts_axolotl_flat():
    blob = (
        "base_model: meta-llama/Llama-2-7b-hf\n"
        "adapter: lora\n"
        "lora_r: 32\n"
        "lora_alpha: 64\n"
        "lora_dropout: 0.05\n"
        "learning_rate: 0.0002\n"
        "optimizer: adamw_bnb_8bit\n"
        "lr_scheduler: cosine\n"
        "micro_batch_size: 2\n"
        "bf16: true\n"
    )
    rows = extract_from_yaml(blob)
    assert _find(rows, "rank_value")["param_value"] == "32"
    assert _find(rows, "lora_alpha")["param_value"] == "64"
    assert _find(rows, "lora_dropout")["param_value"] == "0.05"
    assert _find(rows, "optimizer")["param_value"] == "adamw_bnb_8bit"
    assert _find(rows, "scheduler")["param_value"] == "cosine"
    assert _find(rows, "batch_size")["param_value"] == "2"
    assert _find(rows, "bf16")["param_value"] == "true"
    assert all(r["source"] == "yaml" and r["confidence"] == 0.9 for r in rows)


def test_yaml_extracts_nested_llama_factory():
    blob = (
        "finetuning_type: lora\n"
        "lora:\n"
        "  rank: 16\n"
        "  alpha: 32\n"
        "  target_modules: ['q_proj', 'v_proj']\n"
    )
    rows = extract_from_yaml(blob)
    assert _find(rows, "rank_value")["param_value"] == "16"
    assert _find(rows, "lora_alpha")["param_value"] == "32"
    assert "q_proj" in _find(rows, "target_modules")["param_value"]


def test_yaml_ignores_unrelated_keys():
    blob = "name: my-experiment\nproject: lora-tuning\nseed: 42\n"
    rows = extract_from_yaml(blob)
    assert rows == []


def test_yaml_invalid_returns_empty():
    # Tabs-in-yaml + weird structure → safe failure.
    rows = extract_from_yaml(":\n:\n:::invalid:::")
    assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# Regex layer
# ---------------------------------------------------------------------------

def test_regex_extracts_from_readme_text():
    # Regex layer is intentionally conservative: needs an `=` or `:` separator
    # so prose like "for 5 epochs" doesn't get mined as a hyperparameter.
    text = (
        "We trained with rank=64, lora_alpha=128, lr=3e-4, "
        "num_train_epochs=5 and batch_size=8."
    )
    rows = extract_from_readme(text)
    assert _find(rows, "rank_value")["param_value"] == "64"
    assert _find(rows, "lora_alpha")["param_value"] == "128"
    assert _find(rows, "learning_rate")["param_value"] == "3e-4"
    assert _find(rows, "num_train_epochs")["param_value"] == "5"
    assert _find(rows, "batch_size")["param_value"] == "8"
    assert all(r["source"] == "regex" and r["confidence"] == 0.5 for r in rows)


def test_regex_ignores_unrelated_numbers():
    # "PageRank=16" must not trigger rank_value — the regex requires either
    # `rank` standalone or one of the LoRA-prefixed forms with a word boundary.
    text = "Our PageRank=16 algorithm runs in O(n)."
    rows = extract_from_readme(text)
    assert _find(rows, "rank_value") is None


# ---------------------------------------------------------------------------
# File dispatcher
# ---------------------------------------------------------------------------

def test_dispatch_adapter_config_uses_json_layer():
    rows = extract_from_file(
        "adapter_config.json", "adapter_config",
        '{"r": 4, "lora_alpha": 8}',
    )
    assert all(r["source"] == "json" for r in rows)


def test_dispatch_training_script_uses_ast_layer():
    rows = extract_from_file(
        "train.py", "training_script",
        "config = LoraConfig(r=16, lora_alpha=32)\n",
    )
    assert all(r["source"] == "ast" for r in rows)


def test_dispatch_yaml_uses_yaml_layer():
    rows = extract_from_file(
        "configs/lora.yaml", "config",
        "lora_r: 8\nlora_alpha: 16\n",
    )
    assert all(r["source"] == "yaml" for r in rows)


def test_dispatch_dependencies_returns_empty():
    rows = extract_from_file(
        "requirements.txt", "dependencies",
        "peft==0.10.0\ntransformers>=4.40.0\n",
    )
    assert rows == []


# ---------------------------------------------------------------------------
# merge_params — priority + provenance
# ---------------------------------------------------------------------------

def test_merge_picks_higher_priority_source():
    rows = [
        {"source": "ast",   "param_name": "rank_value", "param_value": "16", "confidence": 1.0},
        {"source": "regex", "param_name": "rank_value", "param_value": "8",  "confidence": 0.5},
    ]
    merged = merge_params(rows)
    assert merged["rank_value"] == "16"
    assert merged["param_sources"]["rank_value"] == "ast"


def test_merge_aggregates_multiple_params():
    rows = [
        {"source": "ast",  "param_name": "rank_value", "param_value": "16",     "confidence": 1.0},
        {"source": "yaml", "param_name": "optimizer",  "param_value": "adamw",  "confidence": 0.9},
        {"source": "json", "param_name": "lora_alpha", "param_value": "32",     "confidence": 1.0},
    ]
    merged = merge_params(rows)
    assert merged["rank_value"] == "16"
    assert merged["optimizer"] == "adamw"
    assert merged["lora_alpha"] == "32"
    assert merged["total_params_extracted"] == 3
    assert merged["param_sources"] == {"rank_value": "ast", "optimizer": "yaml", "lora_alpha": "json"}
    assert 0 < merged["extraction_confidence"] <= 1.0


def test_merge_empty_returns_empty():
    assert merge_params([]) == {}


def test_yaml_drops_placeholder_values():
    # Template configs sometimes ship with the parameter name as the value
    # (`target_modules: target_modules`). The extractor must not emit those.
    blob = (
        "lora_r: lora_r\n"
        "target_modules: target_modules\n"
        "optimizer: optim\n"
        "scheduler: lr_scheduler_type\n"
    )
    rows = extract_from_yaml(blob)
    assert rows == []


def test_yaml_drops_single_element_placeholder_list():
    blob = "target_modules:\n  - target_modules\n"
    rows = extract_from_yaml(blob)
    assert rows == []


def test_yaml_unwraps_deepspeed_optimizer_block():
    # DeepSpeed configs wrap optimizer/scheduler as nested objects with `type`.
    blob = (
        "optimizer:\n"
        "  type: AdamW\n"
        "  params:\n"
        "    lr: 0.0002\n"
        "scheduler:\n"
        "  type: WarmupDecayLR\n"
        "  params:\n"
        "    warmup_max_lr: 0.0002\n"
    )
    rows = extract_from_yaml(blob)
    opt = _find(rows, "optimizer")
    sch = _find(rows, "scheduler")
    assert opt and opt["param_value"] == "AdamW"
    assert sch and sch["param_value"] == "WarmupDecayLR"


def test_adapter_config_drops_placeholder_target_modules():
    blob = '{"r": 16, "target_modules": ["target_modules"]}'
    rows = extract_from_adapter_config(blob)
    names = {r["param_name"] for r in rows}
    assert names == {"rank_value"}
    assert _find(rows, "target_modules") is None


def test_merge_confidence_is_mean_of_picked_rows():
    rows = [
        {"source": "ast",   "param_name": "rank_value", "param_value": "16", "confidence": 1.0},
        {"source": "regex", "param_name": "rank_value", "param_value": "8",  "confidence": 0.5},
        {"source": "yaml",  "param_name": "optimizer",  "param_value": "x",  "confidence": 0.9},
    ]
    merged = merge_params(rows)
    # picked: rank_value (1.0 from AST) + optimizer (0.9 from YAML) -> mean 0.95
    assert merged["extraction_confidence"] == 0.95
