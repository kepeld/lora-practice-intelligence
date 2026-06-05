"""LLM-extraction fallback (US-3.3, Issue #7).

For repos where the AST/JSON/YAML/regex layers in `lora_config_extractor`
yielded nothing, hand the training files to Claude and recover the LoRA
hyperparameters. Output rows are shaped like every other layer
({source, param_name, param_value, confidence}) with source="llm", so the
existing priority merge (AST > JSON > YAML > regex > LLM) consumes them
unchanged — LLM only fills gaps it can't overwrite a structured value.

Pure prompt-building and response-parsing live here and are unit-tested without
network. `extract_from_llm` makes the one API call (lazy `anthropic` import).
"""

from __future__ import annotations

import os
from typing import Any

# Reuse the canonical vocabulary + coercion from the structured extractor so the
# LLM rows normalise identically. Dual import: `ingestion.*` under Airflow,
# bare module under pytest (conftest puts de/ingestion on sys.path).
try:
    from ingestion.lora_config_extractor import (
        CANONICAL_PARAMS, normalize_name, _to_text, _is_placeholder,
        _coerce_optimizer, _coerce_scheduler,
    )
except ImportError:
    from lora_config_extractor import (
        CANONICAL_PARAMS, normalize_name, _to_text, _is_placeholder,
        _coerce_optimizer, _coerce_scheduler,
    )

DEFAULT_MODEL = "claude-haiku-4-5"   # cheap, fast — right tier for batch extraction
LLM_CONFIDENCE = 0.70                # above regex (0.5), below yaml (0.9)
TOOL_NAME = "record_lora_params"

# Per-call input bounds — keep cost predictable and well inside the context window.
MAX_TOTAL_CHARS = 24000
MAX_FILE_CHARS = 8000

SYSTEM_PROMPT = """\
You extract LoRA / PEFT fine-tuning hyperparameters from a repository's training \
files and report them by calling the record_lora_params tool.

Rules:
- Report ONLY values you can determine from the files. Omit anything not present \
— never guess or fill in framework defaults.
- Report the values used for THIS repo's actual training run. Ignore values that \
appear only in comments, example snippets, or unrelated configs.
- optimizer and scheduler: report the bare name, lowercased (e.g. "adamw_torch", \
"cosine"), not a full call expression.
- target_modules: a list of module-name strings (e.g. ["q_proj", "v_proj"]).
- If the files contain no LoRA hyperparameters at all, call the tool with no \
arguments.

Parameters:
- rank_value: LoRA rank (the `r` argument)
- lora_alpha: LoRA alpha scaling
- target_modules: modules LoRA is applied to
- learning_rate: training learning rate
- optimizer: optimizer name
- lora_dropout: LoRA dropout probability
- lora_bias: LoRA bias mode (e.g. "none", "all", "lora_only")
- scheduler: LR scheduler name
- batch_size: per-device train batch size
- gradient_accumulation_steps: gradient accumulation steps
- num_train_epochs: number of training epochs
- warmup_steps: warmup steps
- bf16 / fp16: mixed-precision flags
- gradient_checkpointing: gradient checkpointing flag
- merge_and_unload: whether the adapter is merged back into the base model
"""

# input_schema for the forced tool. Every field optional — the model fills only
# what it finds. Mirrors gold.repo_lora_params columns.
_TOOL_PROPERTIES: dict[str, dict] = {
    "rank_value": {"type": "integer", "description": "LoRA rank (r)"},
    "lora_alpha": {"type": "integer", "description": "LoRA alpha scaling"},
    "target_modules": {
        "type": "array", "items": {"type": "string"},
        "description": "Modules LoRA is applied to",
    },
    "learning_rate": {"type": "number", "description": "Training learning rate"},
    "optimizer": {"type": "string", "description": "Optimizer name, lowercased"},
    "lora_dropout": {"type": "number", "description": "LoRA dropout probability"},
    "lora_bias": {"type": "string", "description": "LoRA bias mode"},
    "scheduler": {"type": "string", "description": "LR scheduler name, lowercased"},
    "batch_size": {"type": "integer", "description": "Per-device train batch size"},
    "gradient_accumulation_steps": {"type": "integer"},
    "num_train_epochs": {"type": "integer"},
    "warmup_steps": {"type": "integer"},
    "bf16": {"type": "boolean"},
    "fp16": {"type": "boolean"},
    "gradient_checkpointing": {"type": "boolean"},
    "merge_and_unload": {"type": "boolean"},
}


def build_tool() -> dict:
    """The single forced tool Claude calls to report extracted params."""
    return {
        "name": TOOL_NAME,
        "description": "Record the LoRA hyperparameters found in the repo files.",
        "input_schema": {
            "type": "object",
            "properties": _TOOL_PROPERTIES,
            "additionalProperties": False,
        },
    }


def build_messages(files: list[dict],
                   max_total_chars: int = MAX_TOTAL_CHARS,
                   max_file_chars: int = MAX_FILE_CHARS) -> list[dict]:
    """Render repo files into a single user message, size-capped.

    Each file is dict-like with `file_path`, `file_category`, `content`.
    """
    parts: list[str] = []
    budget = max_total_chars
    for f in files:
        content = f.get("content") or ""
        if not content.strip():
            continue
        header = f"File: {f.get('file_path', '?')} ({f.get('file_category', '?')})"
        chunk = f"{header}\n```\n{content[:max_file_chars]}\n```\n"
        if len(chunk) > budget:
            parts.append(chunk[:budget])
            break
        parts.append(chunk)
        budget -= len(chunk)
    return [{"role": "user", "content": "".join(parts)}]


def parse_tool_response(tool_input: dict | None) -> list[dict]:
    """Map a record_lora_params tool input into canonical extractor rows."""
    if not isinstance(tool_input, dict):
        return []
    rows: list[dict] = []
    seen: set[str] = set()
    for key, value in tool_input.items():
        # The tool schema emits canonical names; accept those directly and still
        # normalise any alias the model might use instead.
        canonical = key if key in CANONICAL_PARAMS else normalize_name(key)
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
        text = _to_text(value)
        if text is None or text == "":
            continue
        seen.add(canonical)
        rows.append({
            "source": "llm",
            "param_name": canonical,
            "param_value": text,
            "confidence": LLM_CONFIDENCE,
        })
    return rows


def extract_from_llm(files: list[dict], client: Any = None,
                     model: str | None = None) -> list[dict]:
    """Run one forced-tool extraction over a repo's files. Returns extractor rows.

    `client` is an Anthropic client (injected in tests). When omitted, one is
    created lazily — requires ANTHROPIC_API_KEY in the environment.
    """
    if not files:
        return []
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    model = model or os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL)

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        # Static prefix (tool + system) is cached; the per-repo files are the
        # volatile suffix after the breakpoint.
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        tools=[build_tool()],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=build_messages(files),
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
            return parse_tool_response(block.input)
    return []
