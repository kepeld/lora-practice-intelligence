# ML Underground — documentation

LoRA Practice Intelligence: a data platform that mines rare LoRA training
practices from GitHub and validates them against HuggingFace model outcomes
(downloads, likes, fine-tune fan-out).

Live demo: **https://ml-underground.xyz**

| Doc | What it covers |
| --- | --- |
| [Overview](overview.md) | High-level: what the project is and what's on the site |
| [Architecture](architecture.md) | Components, data flow, the three Airflow DAGs, the medallion layers, key design decisions |
| [Data model](data-model.md) | Bronze / Silver / Gold tables and the analytics logic (success score, four-quadrant practice stats, Variant D) |
| [API contract](api-contract.md) | The FastAPI surface (endpoints + field shapes) served by `app/` |
| [Test scenarios](test-scenarios.md) | Basic E2E/API/degraded-mode scenarios mapped to the automated suite |

For local setup and service URLs, see the root [README](../README.md).
