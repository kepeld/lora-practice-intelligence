/* ML Underground dashboard — vanilla JS over /api/v1 (no build step). */

const $ = (sel) => document.querySelector(sel);

const state = {
  insights: { quadrant: "", param_name: "", sample_ok: true,
              sort: "avg_success_score", offset: 0, limit: 24 },
  models: { base_model: "", sort: "composite_success_score", offset: 0, limit: 25 },
  repos: { q: "", language: "", has_tests: false, offset: 0, limit: 25 },
};

async function api(path, params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v !== null && v !== undefined && v !== false) qs.set(k, v);
  }
  const url = `/api/v1${path}${qs.toString() ? "?" + qs.toString() : ""}`;
  const res = await fetch(url);
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error body */ }
  return { ok: res.ok, status: res.status, data };
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const score = (v) => (v === null || v === undefined) ? "—" : Number(v).toFixed(2);
const lift = (v) => {
  if (v === null || v === undefined) return "—";
  const n = Number(v);
  const cls = n >= 0 ? "lift-pos" : "lift-neg";
  return `<span class="${cls}">${n >= 0 ? "+" : ""}${n.toFixed(2)}</span>`;
};
const compact = (n) => {
  if (n === null || n === undefined) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "m";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
};
const QUAD_PILL = {
  "rare+works": ["gem", "hidden gem"],
  "common+works": ["works", "common · works"],
  "common+fails": ["fails", "cargo cult"],
  "rare+fails": ["dead", "rare · fails"],
};

function notice(text, isError = false) {
  return `<div class="notice${isError ? " error" : ""}">${text}</div>`;
}

/* ---------- KPIs ---------- */

async function loadSummary() {
  const r = await api("/stats/summary");
  if (!r.ok) {
    $("#kpis").innerHTML = "";
    $("#global-notice").innerHTML = notice(
      `Warehouse is not reachable (${esc(r.data?.detail || r.status)}). ` +
      `Run the pipeline, or seed a demo: <code>python -m app.demo_seed</code>`, true);
    return;
  }
  const s = r.data;
  const tile = (v, l) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`;
  $("#kpis").innerHTML =
    tile(compact(s.repos_total), "repos collected") +
    tile(compact(s.repos_enriched), "repos enriched") +
    tile(compact(s.hf_models_total), "hf models") +
    tile(compact(s.repos_with_params), "repos with params") +
    tile(compact(s.links_total), "gh–hf links") +
    tile(Math.round((s.extraction_coverage || 0) * 100) + "%", "extraction coverage");
}

/* ---------- Insights ---------- */

async function loadInsights(append = false) {
  const st = state.insights;
  const r = await api("/insights", {
    quadrant: st.quadrant, param_name: st.param_name,
    sample_ok: st.sample_ok ? true : "", sort: st.sort,
    limit: st.limit, offset: st.offset,
  });
  const grid = $("#insight-cards");
  if (!r.ok) {
    grid.innerHTML = notice(esc(r.data?.detail || "insights unavailable"), true);
    return;
  }
  const html = r.data.items.map((i) => {
    const [cls, label] = QUAD_PILL[i.quadrant] || ["dead", i.quadrant];
    const low = i.sample_ok ? "" : ` <span class="pill low">low sample</span>`;
    return `
    <div class="card" data-param="${esc(i.param_name)}" data-value="${esc(i.param_value)}">
      <div class="param">${esc(i.param_name)}</div>
      <div class="value">${esc(i.param_value)}</div>
      <span class="pill ${cls}">${label}</span>${low}
      <div class="scorebar"><i style="width:${Math.round((i.avg_success_score || 0) * 100)}%"></i></div>
      <div class="stats">
        <div class="stat"><div class="n">${compact(i.prevalence)}</div><div class="t">models</div></div>
        <div class="stat"><div class="n">${score(i.avg_success_score)}</div><div class="t">avg score</div></div>
        <div class="stat"><div class="n">${lift(i.score_lift)}</div><div class="t">lift</div></div>
        <div class="stat"><div class="n">${lift(i.avg_score_vs_base)}</div><div class="t">vs base</div></div>
      </div>
    </div>`;
  }).join("");
  if (append) grid.insertAdjacentHTML("beforeend", html);
  else grid.innerHTML = html || notice("No practices match these filters.");
  const seen = st.offset + r.data.items.length;
  $("#insights-more").hidden = seen >= r.data.total;
  grid.querySelectorAll(".card").forEach((c) =>
    c.addEventListener("click", () => openEvidence(c.dataset.param, c.dataset.value)));
}

async function loadParamOptions() {
  const r = await api("/insights", { limit: 200, sort: "prevalence" });
  if (!r.ok) return;
  const names = [...new Set(r.data.items.map((i) => i.param_name))].sort();
  $("#param-filter").innerHTML =
    `<option value="">all parameters</option>` +
    names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
}

/* ---------- Evidence drawer ---------- */

function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#drawer-scrim").hidden = true;
}

async function openEvidence(param, value) {
  $("#drawer-title").innerHTML =
    `<div class="param">${esc(param)}</div><div class="value">${esc(value)}</div>`;
  $("#drawer-body").innerHTML = `<div class="muted">Loading evidence…</div>`;
  $("#drawer").classList.add("open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#drawer-scrim").hidden = false;
  const r = await api(`/insights/${encodeURIComponent(param)}/${encodeURIComponent(value)}/models`);
  if (!r.ok) {
    $("#drawer-body").innerHTML = notice(esc(r.data?.detail || "unavailable"), true);
    return;
  }
  if (!r.data.items.length) {
    $("#drawer-body").innerHTML = notice("No models with this exact value in the warehouse.");
    return;
  }
  $("#drawer-body").innerHTML =
    `<div class="detail-sub">models using this value</div>` +
    r.data.items.map((m) => `
      <div class="evidence">
        <div class="e-name"><a class="ext-link" target="_blank" rel="noopener"
          href="https://huggingface.co/${esc(m.model_id)}">${esc(m.model_id)}</a></div>
        <div class="e-meta">score ${score(m.composite_success_score)} ·
          ${compact(m.downloads)} downloads · ${compact(m.likes)} likes ·
          fan-out ${m.fine_tune_fan_out ?? 0}</div>
      </div>`).join("");
}

/* ---------- Search & Ask ---------- */

function renderHits(items) {
  if (!items.length) return notice("Nothing matched.");
  return `<div class="result-list">` + items.map((h) => {
    const o = h.object || {};
    const name = h.type === "repo" ? o.repo_name : o.model_id;
    const href = h.type === "repo"
      ? `https://github.com/${name}` : `https://huggingface.co/${name}`;
    const meta = h.type === "repo"
      ? `${o.primary_language || ""}`
      : `base ${o.base_model || "—"} · ${compact(o.downloads)} downloads`;
    return `
    <div class="result">
      <div>
        <span class="kind-tag">${h.type}</span>
        <a class="ext-link r-name" target="_blank" rel="noopener" href="${esc(href)}">${esc(name)}</a>
        <div class="r-meta">${esc(meta)}</div>
      </div>
      <div class="r-score">sim ${Number(h.score).toFixed(2)}</div>
    </div>`;
  }).join("") + `</div>`;
}

async function runSearch() {
  const q = $("#search-input").value.trim();
  if (!q) return;
  $("#search-out").innerHTML = `<div class="muted">Searching…</div>`;
  const r = await api("/search", { q, limit: 10 });
  $("#search-out").innerHTML = r.ok
    ? renderHits(r.data.items)
    : notice(esc(r.data?.detail || "search unavailable"), true);
}

/* Minimal markdown -> HTML for the RAG answer. esc() runs first on every text
   segment, so only our own safe tags (h*, strong, code, a[http], ul/ol/li, p)
   are ever introduced — no raw model output reaches innerHTML. */
function mdToHtml(raw) {
  const inline = (s) => esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
             '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const cells = (row) => row.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const isRow = (s) => /^\|.*\|$/.test(s);
  const isSep = (s) => /^\|[\s:|-]+\|$/.test(s);
  const lines = String(raw || "").replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let list = null, para = [];
  const flushPara = () => {
    if (para.length) { out.push("<p>" + para.map(inline).join("<br>") + "</p>"); para = []; }
  };
  const closeList = () => { if (list) { out.push("</" + list + ">"); list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    let m;
    if (!t) { flushPara(); closeList(); }
    else if (isRow(t) && i + 1 < lines.length && isSep(lines[i + 1].trim())) {
      flushPara(); closeList();
      out.push("<table><thead><tr>"
        + cells(t).map((c) => "<th>" + inline(c) + "</th>").join("")
        + "</tr></thead><tbody>");
      i += 2;
      while (i < lines.length && isRow(lines[i].trim())) {
        out.push("<tr>"
          + cells(lines[i].trim()).map((c) => "<td>" + inline(c) + "</td>").join("")
          + "</tr>");
        i++;
      }
      i--;
      out.push("</tbody></table>");
    } else if ((m = t.match(/^(#{1,6})\s+(.*)$/))) {
      flushPara(); closeList();
      const lvl = Math.min(m[1].length + 2, 6);
      out.push(`<h${lvl}>${inline(m[2])}</h${lvl}>`);
    } else if ((m = t.match(/^[-*]\s+(.*)$/))) {
      flushPara();
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      out.push("<li>" + inline(m[1]) + "</li>");
    } else if ((m = t.match(/^\d+\.\s+(.*)$/))) {
      flushPara();
      if (list !== "ol") { closeList(); out.push("<ol>"); list = "ol"; }
      out.push("<li>" + inline(m[1]) + "</li>");
    } else { closeList(); para.push(t); }
  }
  flushPara(); closeList();
  return out.join("");
}

async function runAsk() {
  const q = $("#search-input").value.trim();
  if (!q) return;
  $("#search-out").innerHTML = `<div class="muted">Retrieving sources and asking…</div>`;
  const r = await api("/ask", { q });
  if (!r.ok) {
    $("#search-out").innerHTML = notice(esc(r.data?.detail || "ask unavailable"), true);
    return;
  }
  $("#search-out").innerHTML =
    `<div class="answer"><div class="a-label">answer</div>` +
    `<div class="md">${mdToHtml(r.data.answer)}</div></div>` +
    `<div class="detail-sub">sources</div>` + renderHits(r.data.sources);
}

/* ---------- Models ---------- */

function paramChips(p) {
  if (!p) return `<span class="muted">no extracted params</span>`;
  const skip = new Set(["param_sources", "extracted_at"]);
  const chips = Object.entries(p)
    .filter(([k, v]) => !skip.has(k) && v !== null && v !== undefined)
    .map(([k, v]) => {
      const val = Array.isArray(v) ? v.join(", ") : v;
      return `<span class="param-chip">${esc(k)} = ${esc(val)}</span>`;
    });
  return `<div class="chips-line">${chips.join("")}</div>`;
}

async function loadModels(append = false) {
  const st = state.models;
  const r = await api("/models", { base_model: st.base_model, sort: st.sort,
                                   limit: st.limit, offset: st.offset });
  const tbody = $("#models-table tbody");
  if (!r.ok) {
    tbody.innerHTML = `<tr><td colspan="6">${notice(esc(r.data?.detail || "unavailable"), true)}</td></tr>`;
    return;
  }
  const rows = r.data.items.map((m, idx) => `
    <tr data-idx="${st.offset + idx}">
      <td class="name">${esc(m.model_id)}</td>
      <td class="muted">${esc(m.base_model || "—")}</td>
      <td class="num">${compact(m.downloads)}</td>
      <td class="num">${compact(m.likes)}</td>
      <td class="num">${m.fine_tune_fan_out ?? 0}</td>
      <td><div class="num">${score(m.composite_success_score)}</div>
        <div class="scorebar"><i style="width:${Math.round((m.composite_success_score || 0) * 100)}%"></i></div></td>
    </tr>`).join("");
  if (append) tbody.insertAdjacentHTML("beforeend", rows);
  else { tbody.innerHTML = rows || `<tr><td colspan="6" class="muted">No models yet.</td></tr>`; modelCache = {}; }
  r.data.items.forEach((m, idx) => { modelCache[st.offset + idx] = m; });
  $("#models-more").hidden = st.offset + r.data.items.length >= r.data.total;
  bindRowToggle(tbody, (tr) => {
    const m = modelCache[tr.dataset.idx];
    return `<div class="detail-sub">extracted recipe</div>${paramChips(m.lora_params)}
      <div class="detail-sub">links</div>
      <a class="ext-link" target="_blank" rel="noopener"
         href="https://huggingface.co/${esc(m.model_id)}">open on HuggingFace</a>`;
  }, 6);
}
let modelCache = {};

async function loadBaseModelOptions() {
  const r = await api("/models", { limit: 200, sort: "downloads" });
  if (!r.ok) return;
  const bases = [...new Set(r.data.items.map((m) => m.base_model).filter(Boolean))].sort();
  $("#model-base").innerHTML = `<option value="">all base models</option>` +
    bases.map((b) => `<option value="${esc(b)}">${esc(b)}</option>`).join("");
}

/* ---------- Repos ---------- */

async function loadRepos(append = false) {
  const st = state.repos;
  const r = await api("/repos", { q: st.q, language: st.language,
                                  has_tests: st.has_tests ? true : "",
                                  limit: st.limit, offset: st.offset });
  const tbody = $("#repos-table tbody");
  if (!r.ok) {
    tbody.innerHTML = `<tr><td colspan="5">${notice(esc(r.data?.detail || "unavailable"), true)}</td></tr>`;
    return;
  }
  const rows = r.data.items.map((rep, idx) => `
    <tr data-idx="${st.offset + idx}">
      <td class="name">${esc(rep.repo_name)}</td>
      <td class="muted">${esc(rep.primary_language || "—")}</td>
      <td class="num">${compact(rep.star_count)}</td>
      <td class="num">${rep.lora_params ? (rep.lora_params.total_params_extracted ?? "—") : "—"}</td>
      <td class="num">${rep.lora_params ? score(rep.lora_params.extraction_confidence) : "—"}</td>
    </tr>`).join("");
  if (append) tbody.insertAdjacentHTML("beforeend", rows);
  else { tbody.innerHTML = rows || `<tr><td colspan="5" class="muted">No repos yet.</td></tr>`; repoCache = {}; }
  r.data.items.forEach((rep, idx) => { repoCache[st.offset + idx] = rep; });
  $("#repos-more").hidden = st.offset + r.data.items.length >= r.data.total;
  bindRowToggle(tbody, null, 5, async (tr) => {
    const rep = repoCache[tr.dataset.idx];
    const d = await api(`/repos/${rep.repo_name}`);
    const linked = d.ok && d.data.linked_models.length
      ? d.data.linked_models.map((l) =>
          `<span class="param-chip">${esc(l.model_id)} · ${score(l.best_confidence)}</span>`).join(" ")
      : `<span class="muted">no linked models</span>`;
    return `<div class="detail-sub">extracted recipe</div>${paramChips(rep.lora_params)}
      <div class="detail-sub">linked hf models</div><div class="chips-line">${linked}</div>
      <div class="detail-sub">links</div>
      <a class="ext-link" target="_blank" rel="noopener"
         href="https://github.com/${esc(rep.repo_name)}">open on GitHub</a>`;
  });
}
let repoCache = {};

/* Row click → expandable detail row. `render` is sync, `renderAsync` wins if given. */
function bindRowToggle(tbody, render, colspan, renderAsync) {
  tbody.querySelectorAll("tr[data-idx]").forEach((tr) => {
    if (tr.dataset.bound) return;
    tr.dataset.bound = "1";
    tr.addEventListener("click", async () => {
      const next = tr.nextElementSibling;
      if (next && next.classList.contains("detail-row")) { next.remove(); return; }
      tbody.querySelectorAll(".detail-row").forEach((d) => d.remove());
      const detail = document.createElement("tr");
      detail.className = "detail-row";
      detail.innerHTML = `<td colspan="${colspan}"><div class="muted">Loading…</div></td>`;
      tr.after(detail);
      const html = renderAsync ? await renderAsync(tr) : render(tr);
      detail.innerHTML = `<td colspan="${colspan}">${html}</td>`;
    });
  });
}

/* ---------- wiring ---------- */

function bind() {
  document.querySelectorAll("#quadrant-chips .chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll("#quadrant-chips .chip").forEach((c) => c.classList.remove("is-active"));
      chip.classList.add("is-active");
      state.insights.quadrant = chip.dataset.quadrant;
      state.insights.offset = 0;
      loadInsights();
    });
  });
  $("#param-filter").addEventListener("change", (e) => {
    state.insights.param_name = e.target.value; state.insights.offset = 0; loadInsights();
  });
  $("#insight-sort").addEventListener("change", (e) => {
    state.insights.sort = e.target.value; state.insights.offset = 0; loadInsights();
  });
  $("#sample-ok").addEventListener("change", (e) => {
    state.insights.sample_ok = e.target.checked; state.insights.offset = 0; loadInsights();
  });
  $("#insights-more").addEventListener("click", () => {
    state.insights.offset += state.insights.limit; loadInsights(true);
  });

  $("#search-btn").addEventListener("click", runSearch);
  $("#ask-btn").addEventListener("click", runAsk);
  $("#search-input").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

  $("#model-base").addEventListener("change", (e) => {
    state.models.base_model = e.target.value; state.models.offset = 0; loadModels();
  });
  $("#model-sort").addEventListener("change", (e) => {
    state.models.sort = e.target.value; state.models.offset = 0; loadModels();
  });
  $("#models-more").addEventListener("click", () => {
    state.models.offset += state.models.limit; loadModels(true);
  });

  let repoTimer = null;
  $("#repo-q").addEventListener("input", (e) => {
    clearTimeout(repoTimer);
    repoTimer = setTimeout(() => {
      state.repos.q = e.target.value.trim(); state.repos.offset = 0; loadRepos();
    }, 250);
  });
  $("#repo-lang").addEventListener("change", (e) => {
    state.repos.language = e.target.value; state.repos.offset = 0; loadRepos();
  });
  $("#repo-tests").addEventListener("change", (e) => {
    state.repos.has_tests = e.target.checked; state.repos.offset = 0; loadRepos();
  });
  $("#repos-more").addEventListener("click", () => {
    state.repos.offset += state.repos.limit; loadRepos(true);
  });

  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#drawer-scrim").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
}

async function loadRepoLangOptions() {
  const r = await api("/repos", { limit: 200 });
  if (!r.ok) return;
  const langs = [...new Set(r.data.items.map((x) => x.primary_language).filter(Boolean))].sort();
  $("#repo-lang").innerHTML = `<option value="">all languages</option>` +
    langs.map((l) => `<option value="${esc(l)}">${esc(l)}</option>`).join("");
}

bind();
loadSummary();
loadParamOptions();
loadInsights();
loadBaseModelOptions();
loadModels();
loadRepoLangOptions();
loadRepos();
