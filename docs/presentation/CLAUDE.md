# Presentation: ML Underground

## What to edit

**Edit `slides.md`** — single source of truth. Speaker notes live in `<!-- ... -->`
HTML comments with a `UK:` prefix (Ukrainian) and a `[Name]` presenter tag.
All other output files are auto-generated.

**Do NOT edit directly:** `presentation.html`, `presentation.pdf`, `presentation.pptx`

## Building

```bash
./build.sh
```

Requires the `marp` CLI (run via `npx @marp-team/marp-cli`, no global install needed;
Node 18+). PDF/PPTX export needs Chrome/Puppeteer; HTML always builds.

## Theme

`theme.css` — custom Marp theme matching the product dashboard:
- `--bg: #F3EFE6` (warm paper)
- `--ink: #26201A` (dark warm)
- `--accent: #BC5430` (terracotta)
- Fonts: Source Serif 4 (headings/body), IBM Plex Sans (labels), IBM Plex Mono (numerals)

## Slides

12 content slides (+ title + end):

| # | Slide | Presenter |
|---|---|---|
| 1 | Проблема та ідея | Дарина |
| 2 | Чотири квадранти (HTML grid) | Дарина |
| 3 | Збір і обробка даних (data_flow.svg) | Андрій |
| 4 | Витяг параметрів (+ stat tiles) | Андрій |
| 5 | Success score та квадранти (+ app_insights.png) | Дмитро |
| 6 | Семантичний пошук і Ask (rag_flow.svg) | Дмитро |
| 7 | Розгортання на AWS (aws.svg) | Максим |
| 8 | Деплой і дані | Максим |
| 9 | Демонстрація (`_class: demo`) | Дмитро |
| 10–12 | Запасні скріни (`_class: shot`) | Дмитро |

## Assets

- `assets/*.svg` — hand-written diagrams (data flow, RAG, AWS), palette-matched.
- `assets/app_*.png` — real dashboard screenshots.
- `capture.js` — one-off screenshot grabber (system Edge via puppeteer-core).
  Regenerate: app on `127.0.0.1:8099` (+ Qdrant + key for Ask), then
  `npm i puppeteer-core` and `EDGE_PATH="...msedge.exe" node capture.js`.
  `node_modules` is intentionally not kept.

## Text rules

- Ukrainian only in slide body and speaker notes.
- Do NOT use the `·` (middle dot) symbol.
- Keep code-like identifiers in backticks (`base_model`, `terraform apply`);
  product terms and acronyms stay plain (LoRA, RAG, AWS, DuckDB, Qdrant).
- The 2×2 quadrant matrix is a `.quadrants` grid (see theme.css), not an image.

## Adding a logo

Drop a PNG in `assets/` and add to the title slide:
`<div class="kicker">…</div>` already styles the top label; for an image use
`![w:110](assets/<file>.png)`.
