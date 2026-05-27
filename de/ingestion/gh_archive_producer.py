"""
GH Archive Kafka Producer

Fetches hourly event dumps from gharchive.org and publishes
ML-relevant events to Kafka topics for downstream processing.
"""

import gzip
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

from filters import is_ml_relevant

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"
KAFKA_TOPIC_ML = "github.events.ml"

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

def enrich_event(event: dict) -> dict:
    """Attach ingestion metadata to an event."""
    return {
        **event,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
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
    start_dt = datetime.now(timezone.utc) - timedelta(hours=2)
    start_dt = start_dt.replace(minute=0, second=0, microsecond=0)

    logger.info("Starting from %s", start_dt)

    current_dt = start_dt

    while True:
        fetch_and_produce(producer, current_dt)
        current_dt += timedelta(hours=1)

        # Caught up to current time — wait for next hour
        if current_dt >= datetime.now(timezone.utc) - timedelta(hours=1):
            logger.info("Caught up to current time. Waiting 60 minutes.")
            time.sleep(60 * 60)
        else:
            time.sleep(2)


if __name__ == "__main__":
    main()