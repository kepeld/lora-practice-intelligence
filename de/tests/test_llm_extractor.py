"""Unit tests for the LLM-extraction fallback (de/ingestion/llm_extractor.py).

No network: extract_from_llm is exercised with a fake Anthropic client, and the
prompt/tool/parse helpers are pure.
"""

import json
import types

from llm_extractor import (
    LLM_CONFIDENCE,
    TOOL_NAME,
    build_messages,
    build_tool,
    extract_from_llm,
    parse_tool_response,
)


def _find(rows, name):
    return next((r for r in rows if r["param_name"] == name), None)


# --- fake Anthropic client -------------------------------------------------

class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)


def _tool_use(input_dict):
    return types.SimpleNamespace(type="tool_use", name=TOOL_NAME, input=input_dict)


def _text(text="ok"):
    return types.SimpleNamespace(type="text", text=text)


def _response(blocks):
    return types.SimpleNamespace(content=blocks)


# --- build_tool ------------------------------------------------------------

def test_build_tool_shape():
    tool = build_tool()
    assert tool["name"] == TOOL_NAME
    props = tool["input_schema"]["properties"]
    for name in ("rank_value", "lora_alpha", "target_modules", "optimizer", "bf16"):
        assert name in props
    assert tool["input_schema"]["additionalProperties"] is False
    assert props["target_modules"]["type"] == "array"
    assert props["rank_value"]["type"] == "integer"


# --- build_messages --------------------------------------------------------

def test_build_messages_includes_path_and_content():
    files = [{"file_path": "train.py", "file_category": "training_script",
              "content": "LoraConfig(r=16)"}]
    msgs = build_messages(files)
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    body = msgs[0]["content"]
    assert "train.py" in body and "LoraConfig(r=16)" in body


def test_build_messages_skips_empty_content():
    files = [{"file_path": "empty.py", "file_category": "training_script", "content": "   "}]
    assert build_messages(files)[0]["content"] == ""


def test_build_messages_respects_total_budget():
    files = [{"file_path": f"f{i}.py", "file_category": "config",
              "content": "x" * 1000} for i in range(50)]
    body = build_messages(files, max_total_chars=2000, max_file_chars=1000)[0]["content"]
    assert len(body) <= 2000


# --- parse_tool_response ---------------------------------------------------

def test_parse_maps_canonical_values():
    rows = parse_tool_response({
        "rank_value": 16, "lora_alpha": 32,
        "target_modules": ["q_proj", "v_proj"], "bf16": True,
    })
    assert all(r["source"] == "llm" and r["confidence"] == LLM_CONFIDENCE for r in rows)
    assert _find(rows, "rank_value")["param_value"] == "16"
    assert _find(rows, "lora_alpha")["param_value"] == "32"
    assert "q_proj" in _find(rows, "target_modules")["param_value"]
    assert _find(rows, "bf16")["param_value"] == "true"


def test_parse_normalizes_aliases():
    rows = parse_tool_response({"r": 8, "lr": 0.0002})
    assert _find(rows, "rank_value")["param_value"] == "8"
    assert _find(rows, "learning_rate")["param_value"] == "0.0002"


def test_parse_drops_none_and_unknown():
    rows = parse_tool_response({"rank_value": None, "foo": "bar", "lora_alpha": 16})
    assert {r["param_name"] for r in rows} == {"lora_alpha"}


def test_parse_optimizer_is_truncated_and_lowercased():
    rows = parse_tool_response({"optimizer": "AdamW (betas=0.9,0.999)"})
    assert _find(rows, "optimizer")["param_value"] == "adamw"


def test_parse_handles_empty_and_non_dict():
    assert parse_tool_response({}) == []
    assert parse_tool_response(None) == []


# --- extract_from_llm (fake client) ----------------------------------------

_FILES = [{"file_path": "train.py", "file_category": "training_script",
           "content": "LoraConfig(r=16)"}]


def test_extract_returns_parsed_rows():
    client = _FakeClient(_response([_tool_use({"rank_value": 16, "optimizer": "adamw"})]))
    rows = extract_from_llm(_FILES, client=client, model="claude-haiku-4-5")
    assert _find(rows, "rank_value")["param_value"] == "16"
    assert all(r["source"] == "llm" for r in rows)


def test_extract_no_tool_use_returns_empty():
    client = _FakeClient(_response([_text("I could not find any parameters.")]))
    assert extract_from_llm(_FILES, client=client) == []


def test_extract_empty_files_makes_no_call():
    client = _FakeClient(_response([_tool_use({"rank_value": 16})]))
    assert extract_from_llm([], client=client) == []
    assert client.messages.calls == []


def test_extract_forces_tool_and_caches_system():
    client = _FakeClient(_response([_tool_use({"rank_value": 16})]))
    extract_from_llm(_FILES, client=client, model="claude-haiku-4-5")
    kwargs = client.messages.calls[0]
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kwargs["tools"][0]["name"] == TOOL_NAME
