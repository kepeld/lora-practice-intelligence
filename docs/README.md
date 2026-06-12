# ML Underground — documentation

LoRA Practice Intelligence: a data platform that mines rare LoRA training
practices from GitHub and validates them against HuggingFace model outcomes
(downloads, likes, fine-tune fan-out).

| Doc | What it covers |
| --- | --- |
| [Architecture](architecture.md) | Components, data flow, the three Airflow DAGs, the medallion layers, key design decisions |
| [Data model](data-model.md) | Bronze / Silver / Gold tables and the analytics logic (success score, four-quadrant practice stats, Variant D) |
| [API contract](api-contract.md) | Proposed FastAPI surface for the frontend (endpoints + field shapes) |
| [Test scenarios](test-scenarios.md) | Basic E2E/API/degraded-mode scenarios mapped to the automated suite |

For local setup and service URLs, see the root [README](../README.md).
