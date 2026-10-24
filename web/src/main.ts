import "./style.css";

const state = { catalog: [], nicheCatalog: [], selected: [], modelInfo: null, pending: false };
const $ = (selector) => document.querySelector(selector);

const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));

async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || body.reason || `Request failed (${response.status})`);
  return body;
}

function showStatus(message, kind = "info") {
  const node = $("#request-status");
  node.textContent = message;
  node.dataset.kind = kind;
}

function renderSeeds() {
  $("#seed-count").textContent = `${state.selected.length} / 20`;
  const host = $("#selected-seeds");
  if (!state.selected.length) {
    host.innerHTML = '<span class="empty-state">Your picks will appear here.</span>';
    return;
  }
  host.innerHTML = state.selected.map((item) => `<span class="seed-chip"><span>${escapeHtml(item.title)}</span><button type="button" aria-label="Remove ${escapeHtml(item.title)}" data-remove="${escapeHtml(item.item_id)}">×</button></span>`).join("");
  host.querySelectorAll("[data-remove]").forEach((button) => button.addEventListener("click", () => {
    state.selected = state.selected.filter((item) => item.item_id !== button.dataset.remove);
    renderSeeds();
  }));
}

function renderSearch(items) {
  const host = $("#search-results");
  if (!items.length) {
    host.innerHTML = '<div class="empty-state">No matching games in this historical catalog.</div>';
    return;
  }
  host.innerHTML = items.map((item) => {
    const picked = state.selected.some((seed) => seed.item_id === item.item_id);
    return `<button class="search-result" role="option" aria-selected="${picked}" type="button" data-add="${escapeHtml(item.item_id)}" ${picked || state.selected.length >= 20 ? "disabled" : ""}><span>${escapeHtml(item.title)}<small>${escapeHtml(item.genres.slice(0, 3).join(" · ") || "Historical catalog entry")} · ID ${escapeHtml(item.item_id)}</small></span><span class="add-icon">${picked ? "✓" : "+"}</span></button>`;
  }).join("");
  host.querySelectorAll("[data-add]").forEach((button) => button.addEventListener("click", () => {
    const item = items.find((candidate) => candidate.item_id === button.dataset.add);
    if (item && !state.selected.some((seed) => seed.item_id === item.item_id) && state.selected.length < 20) {
      state.selected.push(item);
      renderSeeds();
      renderSearch(items);
    }
  }));
}

async function searchCatalog() {
  const query = $("#game-search").value.trim();
  const result = await api(`/v1/catalog?q=${encodeURIComponent(query)}&limit=20`);
  renderSearch(result.items);
}

function explanation(item) {
  const evidence = item.explanation_evidence || {};
  const shared = [...(evidence.shared_genres || []), ...(evidence.shared_tags || [])].slice(0, 3);
  return shared.length ? `${item.explanation} (${shared.map(escapeHtml).join(", ")})` : escapeHtml(item.explanation || "Ranked from historical signals.");
}

function recommendationCard(item, index, previousRanks, feedbackToken = null) {
  const earlierRank = previousRanks.get(item.item_id);
  let movement = "";
  if (earlierRank !== undefined && earlierRank !== index + 1) {
    const direction = earlierRank > index + 1 ? "up" : "down";
    movement = `<span class="rank-change ${direction}" aria-label="Moved from rank ${earlierRank}">${direction === "up" ? "↑" : "↓"} #${earlierRank}</span>`;
  }
  const tags = (item.genres || []).slice(0, 3).map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
  const feedback = feedbackToken ? `<div class="feedback-actions" aria-label="Anonymous feedback for ${escapeHtml(item.title)}"><button type="button" data-feedback="click" data-item="${escapeHtml(item.item_id)}" data-token="${escapeHtml(feedbackToken)}">Interesting</button><button type="button" data-feedback="save" data-item="${escapeHtml(item.item_id)}" data-token="${escapeHtml(feedbackToken)}">Save</button><button type="button" data-feedback="dismiss" data-item="${escapeHtml(item.item_id)}" data-token="${escapeHtml(feedbackToken)}">Dismiss</button></div>` : "";
  return `<article class="recommendation-card"><div class="recommendation-top"><span class="rank-number">${index + 1}</span><div class="recommendation-title">${escapeHtml(item.title)}<span class="recommendation-id">ID ${escapeHtml(item.item_id)}${item.release_date ? ` · ${escapeHtml(item.release_date)}` : ""}</span></div>${movement}</div><div class="tag-row">${tags}</div><div class="reason">${explanation(item)}</div><div class="score">Ranking score ${Number(item.ranking_score).toFixed(4)} · not a probability</div>${feedback}</article>`;
}

function renderColumn(label, note, result, previousRanks, champion = false) {
  const feedbackToken = champion && result.feedback_enabled ? result.impression_token : null;
  const cards = result.recommendations.map((item, index) => recommendationCard(item, index, previousRanks, feedbackToken)).join("");
  const fallback = result.fallback_reason ? `<div class="fallback-banner">Fallback: ${escapeHtml(result.fallback_reason.replaceAll("_", " "))}</div>` : "";
  return `<section class="model-column ${champion ? "champion" : ""}"><header class="model-head"><div class="model-label">${champion ? "Selected model" : "Comparison"}</div><h3>${escapeHtml(label)}</h3><p>${escapeHtml(note)}</p><div class="model-version">${escapeHtml(result.mode)} · ${Number(result.server_processing_ms).toFixed(1)} ms</div></header>${fallback}${cards || '<div class="empty-results">No eligible games matched this request.</div>'}</section>`;
}

async function getRecommendations() {
  if (state.pending) return;
  state.pending = true;
  const button = $("#get-recommendations");
  button.disabled = true;
  showStatus("Loading three rankings for the same profile…");
  const genres = $("#genre-filter").value.split(",").map((value) => value.trim()).filter(Boolean);
  const payload = {
    seed_item_ids: state.selected.map((item) => item.item_id),
    exclude_item_ids: [],
    genres,
    k: Number($("#result-count").value),
  };
  try {
    const models = ["recent_popularity", ...(state.modelInfo?.als_comparison_available ? ["als"] : []), "champion"];
    const results = await Promise.all(models.map((model) => api("/v1/recommendations", {
      method: "POST", body: JSON.stringify({ ...payload, model }),
    })));
    const byModel = Object.fromEntries(results.map((result) => [result.mode, result]));
    const champion = byModel.recent30_content_rank_fusion || byModel.recent30_popularity_fallback || byModel.recent30_popularity;
    const championRanks = new Map((champion?.recommendations || []).map((item, index) => [item.item_id, index + 1]));
    const baseline = byModel.recent30_popularity;
    const columns = [renderColumn("Recent popularity", "Ranks games by activity in the last 30 days of training data.", baseline, new Map(), false)];
    const als = byModel.implicit_als_validation_reference;
    if (als) columns.push(renderColumn("ALS reference", "Collaborative item factors; trained at the earlier validation cutoff.", als, championRanks, false));
    columns.push(renderColumn("Game Discovery", "Frozen content and recent-activity rank fusion.", champion, new Map(), true));
    $("#comparison-grid").innerHTML = columns.join("");
    document.querySelectorAll<HTMLButtonElement>("#comparison-grid [data-feedback]").forEach((button) => button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const response = await api("/v1/events", { method: "POST", body: JSON.stringify({
          event_id: crypto.randomUUID(), event_type: button.dataset.feedback, item_id: button.dataset.item,
          impression_token: button.dataset.token,
        }) });
        showStatus(response.duplicate ? "This feedback event was already saved." : `Anonymous feedback saved. It is retained for up to ${response.retention_days} days.`, "success");
      } catch (error) {
        showStatus(`Feedback was not saved: ${error.message}`, "error");
        button.disabled = false;
      }
    }));
    $("#result-model-version").textContent = champion.model_version;
    $("#recommendation-section").hidden = false;
    $("#recommendation-section").scrollIntoView({ behavior: "smooth", block: "start" });
    showStatus(`Loaded ${results.length} model outputs. Request IDs are available in the browser network panel.`);
  } catch (error) {
    showStatus(`Could not load recommendations: ${error.message}`, "error");
  } finally {
    state.pending = false;
    button.disabled = false;
  }
}

function metricRow(name, candidate, baseline, percent = false) {
  const max = Math.max(candidate, baseline, 0.000001);
  const formatter = (value) => percent ? `${(value * 100).toFixed(2)}%` : value.toFixed(4);
  return `<div class="metric-row"><span>${escapeHtml(name)}</span><div class="bar-track" role="img" aria-label="Game Discovery ${formatter(candidate)}, recent popularity ${formatter(baseline)}"><span class="bar-fill baseline" style="width:${baseline / max * 100}%"></span><span class="bar-fill" style="width:${candidate / max * 100}%"></span></div><span class="metric-value">${formatter(candidate)} / ${formatter(baseline)}</span></div>`;
}

function renderEvaluation(info) {
  const host = $("#evaluation-content");
  const evaluation = info.evaluation;
  if (!evaluation?.candidate || !evaluation?.recent_30d_popularity_baseline) {
    host.innerHTML = '<h2>Saved aggregate results are unavailable</h2><p class="muted">The app did not find the generated final-test aggregate JSON. No metrics are hard-coded into this interface.</p>';
    return;
  }
  const candidate = evaluation.candidate;
  const baseline = evaluation.recent_30d_popularity_baseline;
  const ranking = candidate.warm_catalog_ranking || {};
  const baselineRanking = baseline.warm_catalog_ranking || {};
  const difference = evaluation.paired_ndcg_at_10_candidate_minus_recent30 || {};
  const interval = difference.ci95_low !== undefined && difference.ci95_high !== undefined
    ? `[${Number(difference.ci95_low).toFixed(4)}, ${Number(difference.ci95_high).toFixed(4)}]` : "not reported";
  const metric = (key) => Number(ranking[key] ?? 0);
  const baseMetric = (key) => Number(baselineRanking[key] ?? 0);
  const allRecall = candidate.mean_all_target_recall_by_user || {};
  const baseAllRecall = baseline.mean_all_target_recall_by_user || {};
  host.innerHTML = `<div class="eyebrow">${escapeHtml(evaluation.evaluation_split || "Saved evaluation")} · ${escapeHtml(evaluation.split_manifest_sha256 || "")}</div><h2>Selected model vs recent popularity</h2><div class="eval-summary"><div class="metric-tile"><span>Warm NDCG@10 · Game Discovery</span><strong>${metric("mean_ndcg@10").toFixed(4)}</strong></div><div class="metric-tile"><span>Warm NDCG@10 · Recent popularity</span><strong>${baseMetric("mean_ndcg@10").toFixed(4)}</strong></div><div class="metric-tile"><span>Paired difference · 95% interval</span><strong>${Number(difference.mean_difference ?? 0).toFixed(4)}</strong><span>${escapeHtml(interval)}</span></div></div><h3 class="chart-title">Ranking and exposure tradeoffs · candidate / baseline</h3>${metricRow("Recall@10", metric("mean_recall@10"), baseMetric("mean_recall@10"))}${metricRow("Hit rate@10", metric("mean_hit_rate@10"), baseMetric("mean_hit_rate@10"))}${metricRow("All-target recall@10", Number(allRecall["recall@10"] || 0), Number(baseAllRecall["recall@10"] || 0))}${metricRow("Catalog coverage@10", Number(candidate.catalog_coverage_at_10 || 0), Number(baseline.catalog_coverage_at_10 || 0), true)}${metricRow("Tail exposure@10", Number(candidate.tail_exposure_share_at_10 || 0), Number(baseline.tail_exposure_share_at_10 || 0), true)}<p class="eval-footnote">${Number(evaluation.warm_catalog_users || 0).toLocaleString()} warm catalog users; ${Number(evaluation.future_target_users || 0).toLocaleString()} future-target users. Bars show relative magnitude within each metric. This is one historical time window; the confidence interval is paired across users and does not establish performance on present-day Steam.</p>`;
}

function setView(view) {
  document.querySelectorAll<HTMLElement>(".view").forEach((section) => { section.hidden = section.id !== `${view}-view`; });
  document.querySelectorAll<HTMLButtonElement>(".nav-button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  if (view === "evaluation" && state.modelInfo) renderEvaluation(state.modelInfo);
}

function renderFeedbackNotice(feedback) {
  const note = $("#feedback-note");
  if (!feedback?.enabled) {
    note.innerHTML = "<strong>Feedback is off.</strong> This demo does not save clicks or preferences.";
  } else if (feedback.mode === "local_test_only") {
    note.innerHTML = "<strong>Local test feedback is on.</strong> Actions are stored only in the local test directory and expire after 30 days; do not use this mode for a public demo.";
  } else {
    note.innerHTML = `<strong>Anonymous feedback is on.</strong> Actions on the selected model may be stored without an account for up to ${Number(feedback.retention_days || 30)} days. Small demo feedback is self-reported and is not proof of preference.`;
  }
}

function setExample(name) {
  if (name === "failure") {
    state.selected = [];
    renderSeeds();
    getRecommendationsWithSeeds(["unknown-demo-id"]);
    return;
  }
  if (name === "cold") {
    state.selected = [];
  } else if (name === "popular") {
    state.selected = state.catalog.slice(0, 3);
  } else if (name === "niche") {
    state.selected = state.nicheCatalog.slice(0, 2);
  } else if (name === "sparse") {
    state.selected = state.catalog.slice(0, 1);
  }
  renderSeeds();
  getRecommendations();
}

async function getRecommendationsWithSeeds(seedIds) {
  const known = state.selected;
  state.selected = seedIds.map((item_id) => ({ item_id, title: "Unknown demonstration ID", genres: [] }));
  await getRecommendations();
  state.selected = known;
  renderSeeds();
}

async function initialize() {
  try {
    const [catalog, nicheCatalog, modelInfo] = await Promise.all([
      api("/v1/catalog?limit=50"),
      api("/v1/catalog?limit=50&sort=tail"),
      api("/v1/model-info"),
    ]);
    state.catalog = catalog.items;
    state.nicheCatalog = nicheCatalog.items;
    state.modelInfo = modelInfo;
    renderFeedbackNotice(modelInfo.feedback);
    $("#footer-version").textContent = `Model ${modelInfo.model_version} · catalog ${modelInfo.catalog_version}`;
    const genres = [...new Set(state.catalog.flatMap((item) => item.genres))].sort((a, b) => a.localeCompare(b));
    $("#genre-options").innerHTML = genres.map((genre) => `<option value="${escapeHtml(genre)}"></option>`).join("");
    renderSearch(state.catalog.slice(0, 20));
    renderEvaluation(modelInfo);
    showStatus("Catalog and verified model bundle are ready.");
  } catch (error) {
    showStatus(`App setup failed: ${error.message}. Check that the local release bundle is installed.`, "error");
    $("#search-results").innerHTML = '<div class="empty-state">Catalog unavailable. The app may need its model artifact.</div>';
  }
}

$("#search-button").addEventListener("click", () => searchCatalog().catch((error) => showStatus(error.message, "error")));
$("#game-search").addEventListener("keydown", (event) => { if (event.key === "Enter") searchCatalog().catch((error) => showStatus(error.message, "error")); });
$("#clear-seeds").addEventListener("click", () => { state.selected = []; renderSeeds(); });
$("#get-recommendations").addEventListener("click", getRecommendations);
document.querySelectorAll<HTMLButtonElement>(".nav-button").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.querySelectorAll<HTMLButtonElement>("[data-example]").forEach((button) => button.addEventListener("click", () => setExample(button.dataset.example)));
initialize();
