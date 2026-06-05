"""LoRA-config extractor (US-3.1, US-3.2).

Layered extractors over `bronze.github_files` content (AST/1.0, JSON/1.0,
YAML/0.9, regex/0.5). Each layer yields rows shaped
{source, param_name, param_value, confidence}; merge_params keeps the best
source per parameter via PRIORITY (AST > JSON > YAML > regex > LLM).

Pure parsing — no DB / no Airflow. The DAG `lora_extraction_dag` wires it up.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from collections import defaultdict
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# Canonical names we emit. Anything not in this set is dropped.
CANONICAL_PARAMS = {
    "rank_value", "lora_alpha", "target_modules", "learning_rate", "optimizer",
    "lora_dropout", "lora_bias", "scheduler", "batch_size",
    "gradient_accumulation_steps", "num_train_epochs", "warmup_steps",
    "bf16", "fp16", "gradient_checkpointing", "merge_and_unload",
}

# Map any framework-specific alias -> canonical name.
ALIASES = {
    "r":                              "rank_value",
    "lora_r":                         "rank_value",
    "lora_rank":                      "rank_value",
    "rank":                           "rank_value",
    "lora_alpha":                     "lora_alpha",
    "alpha":                          "lora_alpha",
    "target_modules":                 "target_modules",
    "target_module_list":             "target_modules",
    "lora_target_modules":            "target_modules",
    "modules_to_save":                "target_modules",   # close-enough alias
    "learning_rate":                  "learning_rate",
    "lr":                             "learning_rate",
    "optim":                          "optimizer",
    "optimizer":                      "optimizer",
    "optimizer_type":                 "optimizer",
    "lora_dropout":                   "lora_dropout",
    "dropout":                        "lora_dropout",
    "lora_bias":                      "lora_bias",
    "bias":                           "lora_bias",
    "lr_scheduler_type":              "scheduler",
    "scheduler":                      "scheduler",
    "lr_scheduler":                   "scheduler",
    "per_device_train_batch_size":    "batch_size",
    "batch_size":                     "batch_size",
    "train_batch_size":               "batch_size",
    "micro_batch_size":               "batch_size",
    "gradient_accumulation_steps":    "gradient_accumulation_steps",
    "gradient_accumulation":          "gradient_accumulation_steps",
    "gradient_accumulation_step":     "gradient_accumulation_steps",
    "num_train_epochs":               "num_train_epochs",
    "epochs":                         "num_train_epochs",
    "num_epochs":                     "num_train_epochs",
    "warmup_steps":                   "warmup_steps",
    "warmup":                         "warmup_steps",
    "bf16":                           "bf16",
    "bfloat16":                       "bf16",
    "fp16":                           "fp16",
    "float16":                        "fp16",
    "gradient_checkpointing":         "gradient_checkpointing",
    "use_gradient_checkpointing":     "gradient_checkpointing",
    "merge_and_unload":               "merge_and_unload",
}


def normalize_name(name: str | None) -> str | None:
    """Return the canonical param name, or None if not one we track."""
    if not name:
        return None
    key = name.strip().lower()
    canonical = ALIASES.get(key)
    if canonical in CANONICAL_PARAMS:
        return canonical
    return None


# Placeholder strings that show up as YAML *values* in template / commented
# configs (e.g. `target_modules: target_modules` in axolotl template files).
# A value that is just a parameter-name alias is meaningless and must be
# dropped — otherwise we end up with target_modules=["target_modules"] etc.
_PLACEHOLDER_STRINGS = set(ALIASES.keys()) | {
    "true", "false", "none", "null", "auto",
}


def _is_placeholder(value: Any) -> bool:
    """True if `value` just names a parameter — an unfilled template placeholder."""
    if isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], str):
            return False
        return value[0].strip().lower() in _PLACEHOLDER_STRINGS
    if isinstance(value, str):
        return value.strip().lower() in _PLACEHOLDER_STRINGS
    return False


def _truncate_name(value: Any) -> Any:
    """Reduce an optimizer/scheduler value to a single name token ('adamw', 'cosine')."""
    if isinstance(value, list):
        if not value or not isinstance(value[0], str):
            return None
        value = value[0]
    if not isinstance(value, str):
        return value
    head = re.split(r"[\s(,]", value.strip(), maxsplit=1)[0]
    if not head or len(head) > 50:
        return None
    # Lower-case so casing variants ('AdamW' == 'adamw') don't split one practice
    # into separate buckets downstream (false rare-quadrant singletons).
    return head.lower()


def _coerce_optimizer(value: Any) -> Any:
    # DeepSpeed wraps optimizer as {type: AdamW, params: {...}} — pull out the name.
    if isinstance(value, dict):
        t = value.get("type") or value.get("name")
        value = t if isinstance(t, str) else None
    return _truncate_name(value)


def _coerce_scheduler(value: Any) -> Any:
    # DeepSpeed wraps scheduler the same way as optimizer.
    if isinstance(value, dict):
        t = value.get("type") or value.get("name")
        value = t if isinstance(t, str) else None
    return _truncate_name(value)


def _to_text(value: Any) -> str | None:
    """Serialize a Python value for storage in lora_configs_raw.param_value (TEXT)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


# Calls whose keyword arguments we mine. Anything outside this set is ignored
# even if it shadows a canonical-named kwarg (e.g. a logging helper).
AST_TARGET_CALLS = {
    "LoraConfig", "PeftConfig", "LoftQConfig", "AdaLoraConfig",
    "TrainingArguments", "Seq2SeqTrainingArguments", "DPOConfig",
    "SFTConfig", "ORPOConfig",
}


def _call_name(node: ast.Call) -> str | None:
    """Return the bare function name of an ast.Call, ignoring module prefixes."""
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _literal(value: ast.AST) -> Any:
    """Best-effort literal extraction. Returns None for non-literals."""
    try:
        return ast.literal_eval(value)
    except Exception:
        # Constant strings without surrounding quotes (e.g. typed enums) —
        # just record the source text.
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Attribute):
            # e.g. `optim=Optimizers.ADAMW_TORCH` -> "ADAMW_TORCH"
            return value.attr
        return None


def extract_from_python(content: str) -> list[dict]:
    """Mine kwargs of LoraConfig/TrainingArguments/etc. calls. AST-safe."""
    if not content:
        return []
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        logger.debug("python AST parse failed: %s", exc)
        return []

    out: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in AST_TARGET_CALLS:
            continue
        for kw in node.keywords:
            canonical = normalize_name(kw.arg)
            if not canonical:
                continue
            value = _literal(kw.value)
            if value is None or _is_placeholder(value):
                continue
            if canonical == "optimizer":
                value = _coerce_optimizer(value)
            elif canonical == "scheduler":
                value = _coerce_scheduler(value)
            if value is None:
                continue
            out.append({
                "source": "ast",
                "param_name": canonical,
                "param_value": _to_text(value),
                "confidence": 1.00,
            })
    return out


def extract_from_adapter_config(content: str) -> list[dict]:
    """PEFT-generated adapter_config.json — keys are canonical, confidence 1.0."""
    if not content:
        return []
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []

    out: list[dict] = []
    for key, value in data.items():
        canonical = normalize_name(key)
        if canonical is None or value is None or _is_placeholder(value):
            continue
        if canonical == "optimizer":
            value = _coerce_optimizer(value)
        elif canonical == "scheduler":
            value = _coerce_scheduler(value)
        if value is None:
            continue
        out.append({
            "source": "json",
            "param_name": canonical,
            "param_value": _to_text(value),
            "confidence": 1.00,
        })
    return out


def _flatten(value: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    """Yield (dotted-key, leaf-value) pairs from a nested dict/list mix."""
    if isinstance(value, dict):
        for k, v in value.items():
            sub = f"{prefix}.{k}" if prefix else str(k)
            yield from _flatten(v, sub)
    elif isinstance(value, list):
        # Whole lists ARE leaves for our purposes (target_modules is a list).
        yield prefix, value
    else:
        yield prefix, value


def _yaml_load(content: str) -> Any:
    """Lazy yaml import. Returns None on failure (binary, anchors w/o defs, …)."""
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("PyYAML not installed; YAML layer disabled")
        return None
    try:
        return yaml.safe_load(content)
    except Exception as exc:
        logger.debug("yaml parse failed: %s", exc)
        return None


def extract_from_yaml(content: str) -> list[dict]:
    """Extract canonical-named params from a flat-or-nested YAML/JSON config."""
    if not content:
        return []
    data = _yaml_load(content)
    if data is None:
        # Maybe it's JSON parseable but not YAML.
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(data, (dict, list)):
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for dotted_key, value in _flatten(data):
        # Walk the dotted key from the leaf up — `peft.lora.r` should match
        # as `r` (canonical: rank_value). Pick the *deepest* segment that
        # normalises, so `peft_args.lora_dropout` resolves to `lora_dropout`,
        # not to `dropout` of some sibling.
        segments = dotted_key.split(".")
        canonical = None
        for seg in reversed(segments):
            canonical = normalize_name(seg)
            if canonical:
                break
        if not canonical or canonical in seen:
            continue
        if value is None or _is_placeholder(value):
            continue
        if canonical == "optimizer":
            value = _coerce_optimizer(value)
        elif canonical == "scheduler":
            value = _coerce_scheduler(value)
        if value is None:
            continue
        seen.add(canonical)
        out.append({
            "source": "yaml",
            "param_name": canonical,
            "param_value": _to_text(value),
            "confidence": 0.90,
        })
    return out


# Word-boundary precision so `rank=16` doesn't fire on "PageRank=16".
REGEX_PATTERNS: dict[str, re.Pattern[str]] = {
    "rank_value":      re.compile(r"\b(?:lora_)?r(?:ank)?\s*[=:]\s*(\d{1,4})\b"),
    "lora_alpha":      re.compile(r"\b(?:lora_)?alpha\s*[=:]\s*(\d{1,5})\b"),
    "lora_dropout":    re.compile(r"\b(?:lora_)?dropout\s*[=:]\s*([0-9]*\.?[0-9]+)\b"),
    "learning_rate":   re.compile(r"\b(?:learning_rate|lr)\s*[=:]\s*([0-9]*\.?[0-9]+(?:[eE][-+]?\d+)?)\b"),
    "batch_size":      re.compile(r"\b(?:per_device_train_)?batch_size\s*[=:]\s*(\d{1,4})\b"),
    "num_train_epochs":re.compile(r"\b(?:num_train_)?epochs?\s*[=:]\s*(\d{1,4})\b"),
    "warmup_steps":    re.compile(r"\bwarmup(?:_steps)?\s*[=:]\s*(\d{1,6})\b"),
}


def extract_from_readme(content: str) -> list[dict]:
    """Conservative regex sweep — confidence 0.50."""
    if not content:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for canonical, pattern in REGEX_PATTERNS.items():
        match = pattern.search(content)
        if not match or canonical in seen:
            continue
        value = next((g for g in match.groups() if g), None)
        if not value:
            continue
        seen.add(canonical)
        out.append({
            "source": "regex",
            "param_name": canonical,
            "param_value": value,
            "confidence": 0.50,
        })
    return out


# HuggingFace model-card extractor (US-4.2 Variant D): parse the *structured*
# parts (front-matter YAML, fenced python/json/yaml blocks) at high confidence
# and only fall back to regex on freeform prose. Accepts ``` and ~~~ fences.
_FENCED_BLOCK_RE = re.compile(
    r"(?:^|\n)(```|~~~)(\w*)\s*\n(.*?)\n\1",
    re.DOTALL,
)

# YAML front-matter on HF cards starts/ends with --- on its own line at the
# very top of the file.
_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _extract_fenced_blocks(content: str):
    """Yield (language, body) tuples for every fenced code block."""
    for m in _FENCED_BLOCK_RE.finditer(content):
        lang = (m.group(2) or "").lower()
        body = m.group(3)
        if body.strip():
            yield lang, body


def _extract_front_matter(content: str) -> str | None:
    m = _FRONT_MATTER_RE.match(content)
    return m.group(1) if m else None


def extract_from_hf_model_card(card_content: str,
                               tags: list | None = None) -> list[dict]:
    """Layered extraction over a HuggingFace model card (US-4.2 Variant D).

    `tags` is the JSON-parsed list from huggingface_models_bronze.tags
    (e.g. ["peft", "lora", "base_model:adapter:meta-llama/..."]); pass None
    if not available.
    """
    if not card_content:
        return []

    out: list[dict] = []

    fm = _extract_front_matter(card_content)
    if fm:
        out.extend(extract_from_yaml(fm))

    for lang, body in _extract_fenced_blocks(card_content):
        if lang in ("python", "py"):
            out.extend(extract_from_python(body))
        elif lang in ("json",):
            # adapter_config-style first, then yaml-style flatten fallback
            rows = extract_from_adapter_config(body)
            if not rows:
                rows = extract_from_yaml(body)
            out.extend(rows)
        elif lang in ("yaml", "yml"):
            out.extend(extract_from_yaml(body))
        # plain code blocks (no lang tag): try python AST; parse failure -> [].
        elif lang == "":
            out.extend(extract_from_python(body))

    # Structured tags carry no hyperparameter values and the canonical set has no
    # `is_peft` slot, so skip the tags pass for now (kept to document the intent).

    # Strip fenced blocks before the regex pass to avoid double-counting.
    prose = _FENCED_BLOCK_RE.sub("\n", card_content)
    if fm:
        prose = prose.replace("---\n" + fm + "\n---", "", 1)
    out.extend(extract_from_readme(prose))

    return out


def extract_from_file(file_path: str, file_category: str,
                      content: str | None) -> list[dict]:
    """Route a bronze.github_files row to the right extractor(s).

    `file_category` follows the migration-004 enum:
    training_script | config | dependencies | adapter_config.
    """
    if not content:
        return []
    lower = file_path.lower()

    if file_category == "adapter_config":
        return extract_from_adapter_config(content)

    if file_category == "training_script" and lower.endswith(".py"):
        return extract_from_python(content)

    if file_category == "config":
        if lower.endswith((".yaml", ".yml")):
            return extract_from_yaml(content)
        if lower.endswith(".json"):
            # canonical adapter_config first; flat yaml-style sweep for hand-rolled JSON
            rows = extract_from_adapter_config(content)
            return rows or extract_from_yaml(content)

    if file_category == "dependencies":
        return []  # nothing to extract from requirements.txt or pyproject

    # Unknown / mixed (e.g. notebook README files). Fall back to regex sweep.
    return extract_from_readme(content)


# Higher wins. The LLM tier exists for forward-compatibility (US-3.3).
SOURCE_PRIORITY = {"ast": 4, "json": 3, "yaml": 2, "regex": 1, "llm": 0}


def merge_params(raw_rows: list[dict]) -> dict:
    """Collapse one repo's raw rows into a single repo_lora_params dict.

    Returns {<canonical_param>: <value>, ..., "param_sources": {...},
    "total_params_extracted": N, "extraction_confidence": <0..1>}, or an empty
    dict if `raw_rows` is empty (caller should skip the insert).
    """
    if not raw_rows:
        return {}

    by_param: dict[str, list[dict]] = defaultdict(list)
    for row in raw_rows:
        by_param[row["param_name"]].append(row)

    final: dict[str, Any] = {}
    sources: dict[str, str] = {}
    confidences: list[float] = []

    for name, candidates in by_param.items():
        best = max(
            candidates,
            key=lambda r: (SOURCE_PRIORITY.get(r["source"], 0),
                           float(r["confidence"])),
        )
        final[name] = best["param_value"]
        sources[name] = best["source"]
        confidences.append(float(best["confidence"]))

    final["param_sources"] = sources
    final["total_params_extracted"] = len(sources)
    final["extraction_confidence"] = (
        round(sum(confidences) / len(confidences), 2) if confidences else 0.0
    )
    return final
