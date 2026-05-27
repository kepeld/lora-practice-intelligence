"""Unit tests for the LoRA-relevance filter (de/ingestion/filters.py)."""

from filters import CRYPTO_BLACKLIST, ML_KEYWORDS, is_ml_relevant


def _event(repo_name, event_type="WatchEvent", commits=None, topics=None):
    event = {"type": event_type, "repo": {"name": repo_name}}
    if topics is not None:
        event["repo"]["topics"] = topics
    if commits is not None:
        event["payload"] = {"commits": [{"message": m} for m in commits]}
    return event


def test_lora_repos_accepted():
    assert is_ml_relevant(_event("user/qwen-lora-trainer"))
    assert is_ml_relevant(_event("user/awesome-qlora-recipes"))
    assert is_ml_relevant(_event("user/llama-peft-finetune"))
    assert is_ml_relevant(_event("user/axolotl-configs"))


def test_plural_keywords_accepted():
    # adapters (plural of adapter) should match
    assert is_ml_relevant(_event("user/peft-adapters-collection"))
    # loras (plural of lora)
    assert is_ml_relevant(_event("user/diffusion-loras"))


def test_substring_false_positives_rejected():
    # "lora" must not match inside "Colorado" or "flora"; "peft" must not
    # match inside random text — the whole-word filter exists for this.
    assert not is_ml_relevant(_event("user/colorado-weather"))
    assert not is_ml_relevant(_event("acme/flora-encyclopedia"))


def test_unrelated_repo_rejected():
    # Broad ML topics that we explicitly removed from the LoRA-targeted filter
    # (transformers, NLP, computer-vision, RAG, LLM agents) must NOT be accepted
    # on their own — they were part of the old broad-ML scope, not LoRA.
    assert not is_ml_relevant(_event("user/transformer-architecture-101"))
    assert not is_ml_relevant(_event("user/awesome-llm-prompts"))
    assert not is_ml_relevant(_event("user/my-rag-app"))
    assert not is_ml_relevant(_event("user/todo-list-app"))


def test_crypto_repos_rejected():
    # a crypto keyword wins even when a LoRA keyword is also present
    assert not is_ml_relevant(_event("user/defi-lora-trading-bot"))
    assert not is_ml_relevant(_event("user/web3-peft-adapter"))


def test_crypto_blacklist_not_over_matching():
    # "token" in the blacklist must not drop a LoRA-adjacent repo whose
    # description happens to include a tokenizer reference.
    assert is_ml_relevant(_event("user/qlora-tokenizer-finetune"))


def test_keyword_in_commit_messages():
    event = _event("user/plain-repo", event_type="PushEvent",
                   commits=["add lora adapter to training loop"])
    assert is_ml_relevant(event)


def test_keyword_in_topics():
    assert is_ml_relevant(_event("user/plain-repo", topics=["lora-finetuning"]))
    assert is_ml_relevant(_event("user/plain-repo", topics=["peft"]))


def test_framework_keywords():
    # Training frameworks that wrap LoRA — repo name with axolotl/unsloth
    # alone should be enough signal.
    assert is_ml_relevant(_event("user/axolotl-recipes"))
    assert is_ml_relevant(_event("user/unsloth-finetune"))
    assert is_ml_relevant(_event("user/llama-factory-configs"))


def test_keyword_lists_populated():
    assert len(ML_KEYWORDS) > 5
    assert len(CRYPTO_BLACKLIST) > 10
