# Presentation plan — ML Underground

~12–14 min, 4 presenters. Body and speaker notes in Ukrainian.

Team: Саваріна Дарина, Козін Андрій, Авдєєнко Дмитро, Мигаль Максим.
Закінчуємо демо (Дмитро відкриває застосунок наживо) + запасні скріни.

## Flow and handoffs

1. **Дарина — продукт (slides 1–2).** The cargo-cult problem, the rare-but-works
   idea, and the four-quadrant framing the dashboard delivers.
   *Handoff:* "А як ми взагалі збираємо ці дані — розкаже Андрій."

2. **Андрій — data engineering (slides 3–4).** Targeted GitHub + HuggingFace
   collection; Airflow → MySQL bronze → DuckDB medallion; layered extraction
   (AST → … → LLM) and Variant D; corpus numbers.
   *Handoff:* "Що ми рахуємо з цих даних — далі Дмитро."

3. **Дмитро — ML (slides 5–6).** The composite success score (percentile blend,
   fan-out de-weighted), base-model-stratified quadrants, and the RAG layer:
   semantic search + Ask grounded in warehouse facts.
   *Handoff:* "Як усе це живе в проді — Максим."

4. **Максим — deployment (slides 7–8).** AWS via Terraform (EC2, RDS, S3,
   Secrets Manager), the component→service mapping, data migration (mysqldump,
   Qdrant snapshots, derived DuckDB), images in ECR, acceptance criteria.

## Key numbers (kept honest, from the real warehouse, 2026-06-12)

- 6 986 repos enriched, 13 996 HF models (9 096 LoRA-scored), 7 159 with params
- 220 GitHub↔HF links, 37% extraction coverage
- Qdrant: 5 596 repo + 8 933 model vectors
- Success score: 0.55 downloads + 0.35 likes + 0.10 fan-out
- Example Ask: adamw 0.73 vs paged_adamw_8bit 0.38

## Notes

- The full deploy lands via a separate PR shortly; slide 8 frames it as
  near-complete.
- Demo option: the live dashboard at `localhost:8000` (insights, evidence
  drawer, search, Ask) can replace or supplement slides 2 and 6.
