# ML Underground — overview

**ML Underground** (LoRA Practice Intelligence) is a data platform that mines
rare LoRA fine-tuning practices from GitHub and validates them against
HuggingFace outcome signals (downloads, likes, fine-tune fan-out). It surfaces
**rare-but-works** recipes and flags **cargo cult** — popular but ineffective
settings.

Live demo: **https://ml-underground.xyz**

## The idea — four quadrants

Each hyperparameter value is placed on two axes, prevalence × success:

| | works | fails |
| --- | --- | --- |
| **common** | table stakes | cargo cult (avoid) |
| **rare** | **hidden gem** (the goal) | dead end |

The works/fails axis is base-model-stratified and gated by a minimum sample
size, so a "hidden gem" reflects a real effect rather than one lucky model.

## How it works (high level)

1. **Collect** — LoRA repos via targeted GitHub Search + API enrichment, and
   LoRA models from the HuggingFace Hub.
2. **Process** — Airflow orchestrates MySQL bronze → a DuckDB medallion (dbt);
   repo READMEs and model cards are embedded into Qdrant.
3. **Analyse** — extract hyperparameters (AST → JSON → YAML → regex → LLM
   fallback), compute a composite success score, and classify the quadrants.
4. **Serve** — a FastAPI service exposes the marts and serves the dashboard.

## What's on the site

- **Insights** — the four-quadrant practice cards, filterable by quadrant /
  parameter, each with evidence: the real HuggingFace models that use a value.
- **Models** — LoRA models with outcome signals and the composite success
  score; expand a row for its extracted training recipe.
- **Repos** — GitHub repos with their extracted LoRA configs and linked models.
- **Search & Ask** — semantic search over the corpus and a grounded "Ask"
  assistant that answers from retrieved sources plus warehouse facts. These need
  the full vector + LLM backend, so they are limited on the lightweight public
  demo and fully available in the complete deployment.

## Sample search queries

Try these in **Search the corpus** on the dashboard:

1. 8-bit adamw optimizer for qlora
2. qlora 4-bit quantization low vram
3. fine-tune llama 3 on medical data
4. lora rank and alpha selection
5. unsloth fast fine-tuning
6. axolotl training config
7. instruction tuning with dpo alignment
8. code generation model fine-tuning
9. merge lora adapter into base model
10. multilingual adapter for ukrainian

## More

Architecture, data model, the API contract, and test scenarios live alongside
this file; the presentation deck is in [presentation/](presentation/).
