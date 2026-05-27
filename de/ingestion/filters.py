"""
LoRA-relevance filtering for GitHub events.

Single source of truth for the keyword heuristic — imported by both the
Airflow DAG (de/airflow/dags/ml_underground_dag.py) and the standalone
ingestion scripts. Narrowed to LoRA/adapter-tuning territory only — this is
LoRA Practice Intelligence, not a broad ML monitor.
"""

import re

# Keywords used to identify LoRA-relevant repositories. Two layers:
# (1) core LoRA family; (2) adjacent fine-tuning vocabulary that LoRA repos
# routinely use (so we don't miss e.g. "qwen-finetune" repos that train via
# PEFT but don't mention "lora" in the repo name); (3) training frameworks
# that wrap LoRA (axolotl, unsloth, LLaMA-Factory).
ML_KEYWORDS = [
    # core LoRA family
    "lora", "qlora", "dora", "peft",
    "lora-finetuning", "lora-training",
    # adjacent fine-tuning techniques routinely used in LoRA contexts
    "fine-tuning", "finetuning", "fine-tune",
    "adapter", "adapters",
    # LoRA-training frameworks
    "axolotl", "unsloth", "llama-factory", "llamafactory",
]

# Keywords indicating a non-ML repo (crypto/web3). If any is found the event
# is excluded regardless of ML keywords.
CRYPTO_BLACKLIST = [
    "solidity", "uniswap", "defi", "ethereum", "web3",
    "arbitrage", "blockchain", "nft", "token", "evm",
    "smart-contract", "metamask", "binance", "coinbase",
    "crypto", "bitcoin", "hardhat", "truffle", "foundry",
    "airdrop", "staking", "yield-farming", "dex", "amm",
]


def _compile(keywords):
    # Whole-word match, optionally plural, so "rag" does not match "storage"
    # and "token" does not drop NLP repos via "tokenizer".
    return re.compile(r"\b(?:" + "|".join(re.escape(k) for k in keywords) + r")s?\b")


_ML_PATTERN = _compile(ML_KEYWORDS)
_CRYPTO_PATTERN = _compile(CRYPTO_BLACKLIST)


def event_text(event):
    """Concatenate the searchable text fields of a GitHub event, lowercased."""
    text = event.get("repo", {}).get("name", "").lower()
    if event.get("type") == "PushEvent":
        commits = event.get("payload", {}).get("commits", [])
        text += " " + " ".join(c.get("message", "") for c in commits).lower()
    topics = event.get("repo", {}).get("topics", [])
    text += " " + " ".join(topics).lower()
    return text


def is_ml_relevant(event):
    """
    Return True if the event relates to an ML/AI repository.

    Two-stage filter: reject on any crypto/web3 keyword, then accept on any
    ML keyword. Keywords match as whole words, not raw substrings.
    """
    text = event_text(event)
    if _CRYPTO_PATTERN.search(text):
        return False
    return bool(_ML_PATTERN.search(text))
