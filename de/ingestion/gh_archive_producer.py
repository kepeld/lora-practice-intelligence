"""
GH Archive Kafka Producer

Fetches hourly event dumps from gharchive.org and publishes
ML-relevant events to Kafka topics for downstream processing.
"""

import gzip
import json
import logging
import time
from datetime import datetime, timedelta

import requests
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
KAFKA_TOPIC_RAW = "github.events.raw"
KAFKA_TOPIC_ML = "github.events.ml"

# Keywords used to identify ML-relevant repositories
ML_KEYWORDS = [
    "machine-learning", "deep-learning", "neural-network",
    "llm", "large-language-model", "transformer",
    "lora", "fine-tuning", "finetuning",
    "rag", "retrieval-augmented",
    "diffusion", "stable-diffusion",
    "reinforcement-learning", "rlhf",
    "computer-vision", "nlp", "natural-language-processing",
    "pytorch", "tensorflow", "huggingface",
    "langchain", "llamaindex", "openai",
    "agents", "ai-agent",
]

# Keywords that indicate a non-ML repository (crypto, web3, etc.)
# If any of these are found, the event is excluded regardless of ML keywords
CRYPTO_BLACKLIST = [
    "solidity", "uniswap", "defi", "ethereum", "web3",
    "arbitrage", "blockchain", "nft", "token", "evm",
    "smart-contract", "metamask", "binance", "coinbase",
    "crypto", "bitcoin", "hardhat", "truffle", "foundry",
    "airdrop", "staking", "yield-farming", "dex", "amm",
]

# Only these event types are forwarded to the raw topic
RELEVANT_EVENT_TYPES = [
    "WatchEvent",        # star
    "ForkEvent",         # fork
    "PushEvent",         # commit push
    "PullRequestEvent",  # pull request
    "IssuesEvent",       # issue opened/closed
    "ReleaseEvent",      # new release
    "CreateEvent",       # repository or branch created
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------

def create_producer(retries: int = 5) -> KafkaProducer:
    """Create a Kafka producer with retry logic."""
    for attempt in range(retries):
        try:
            producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",
                retries=3,
            )
            logger.info("Kafka producer connected")
            return producer
        except NoBrokersAvailable:
            logger.warning("Kafka unavailable, attempt %d/%d", attempt + 1, retries)
            time.sleep(5)
    raise RuntimeError("Failed to connect to Kafka after %d attempts" % retries)


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def is_ml_relevant(event: dict) -> bool:
    """
    Return True if the event is related to an ML/AI repository.

    Two-stage filter:
      1. Reject if any CRYPTO_BLACKLIST keyword is found (fast exclusion)
      2. Accept if any ML_KEYWORDS keyword is found
    """
    repo_name = event.get("repo", {}).get("name", "").lower()
    text = repo_name

    if event.get("type") == "PushEvent":
        commits = event.get("payload", {}).get("commits", [])
        text += " " + " ".join(c.get("message", "") for c in commits).lower()

    topics = event.get("repo", {}).get("topics", [])
    text += " " + " ".join(topics).lower()

    # Stage 1: exclude crypto/web3 repos
    if any(keyword in text for keyword in CRYPTO_BLACKLIST):
        return False

    # Stage 2: must match at least one ML keyword
    return any(keyword in text for keyword in ML_KEYWORDS)


def enrich_event(event: dict) -> dict:
    """Attach ingestion metadata to an event."""
    return {
        **event,
        "ingested_at": datetime.utcnow().isoformat(),
        "source": "gharchive",
    }


# ---------------------------------------------------------------------------
# GH Archive
# ---------------------------------------------------------------------------

def get_gharchive_url(dt: datetime) -> str:
    """Build the GH Archive download URL for a given hour."""
    return f"https://data.gharchive.org/{dt.strftime('%Y-%m-%d-%-H')}.json.gz"


def fetch_and_produce(producer: KafkaProducer, dt: datetime) -> dict:
    """
    Download one hour of GH Archive data and publish events to Kafka.
    Returns a stats dict with counts for total, relevant, skipped, errors.
    """
    url = get_gharchive_url(dt)
    logger.info("Fetching: %s", url)

    stats = {
        "hour": dt.strftime("%Y-%m-%d-%H"),
        "total": 0,
        "relevant": 0,
        "skipped": 0,
        "errors": 0,
    }

    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error("Download failed for %s: %s", url, e)
        stats["errors"] += 1
        return stats

    try:
        with gzip.GzipFile(fileobj=response.raw) as f:
            for line in f:
                try:
                    event = json.loads(line.decode("utf-8"))
                    stats["total"] += 1

                    # All relevant event types go to the raw topic
                    if event.get("type") in RELEVANT_EVENT_TYPES:
                        producer.send(
                            KAFKA_TOPIC_RAW,
                            key=event.get("id"),
                            value=enrich_event(event),
                        )

                    # ML-filtered events go to the ml topic
                    if is_ml_relevant(event):
                        producer.send(
                            KAFKA_TOPIC_ML,
                            key=event.get("id"),
                            value=enrich_event(event),
                        )
                        stats["relevant"] += 1
                    else:
                        stats["skipped"] += 1

                except json.JSONDecodeError as e:
                    logger.warning("JSON decode error: %s", e)
                    stats["errors"] += 1

    except Exception as e:
        logger.error("Error processing archive: %s", e)
        stats["errors"] += 1

    producer.flush()

    logger.info(
        "Processed %d events | ML relevant: %d | Skipped: %d",
        stats["total"],
        stats["relevant"],
        stats["skipped"],
    )
    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    producer = create_producer()

    # Start 2 hours behind current time (GH Archive has ~1h delay)
    start_dt = datetime.utcnow() - timedelta(hours=2)
    start_dt = start_dt.replace(minute=0, second=0, microsecond=0)

    logger.info("Starting from %s", start_dt)

    current_dt = start_dt

    while True:
        fetch_and_produce(producer, current_dt)
        current_dt += timedelta(hours=1)

        # Caught up to current time — wait for next hour
        if current_dt >= datetime.utcnow() - timedelta(hours=1):
            logger.info("Caught up to current time. Waiting 60 minutes.")
            time.sleep(60 * 60)
        else:
            time.sleep(2)


if __name__ == "__main__":
    main()