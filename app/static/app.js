const state = { user: null, projects: [], project: null, view: "dashboard", toastTimer: null, sources: [], claims: [], handoverVersion: null, lastExtraction: null };
const $ = (selector, root = document) => root.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const roleLabel = (role) => ({
  owner: "Project owner", reviewer: "Reviewer", incoming_lead: "Incoming lead", member: "Member",
}[role] || role);
const badgeClass = (value) => {
  const normal = String(value).toLowerCase();
  if (normal === "verified" || normal === "accepted" || normal === "project") return "badge-verified";
  if (normal === "corroborated" || normal === "edited" || normal === "resolved") return "badge-corroborated";
  if (normal === "conflicting" || normal === "restricted" || normal === "rejected") return "badge-conflicting";
  if (normal === "missing" || normal === "unresolved" || normal === "open" || normal === "single-source" || normal === "proposed") return "badge-single";
  return "badge-project";
};
const badge = (value) => `<span class="badge ${badgeClass(value)}">${escapeHtml(value)}</span>`;
const empty = (title, text) => `<div class="empty-state"><strong>${escapeHtml(title)}</strong>${escapeHtml(text)}</div>`;
const canReview = () => ["owner", "reviewer"].includes(state.project?.role);
const THEME_STORAGE_KEY = "continuityos-theme";
const themes = new Set(["clean-light", "dark", "editorial"]);

function applyTheme(theme) {
  const selectedTheme = themes.has(theme) ? theme : "clean-light";
  $("#workspace").dataset.theme = selectedTheme;
  $("#theme-switch").value = selectedTheme;
  localStorage.setItem(THEME_STORAGE_KEY, selectedTheme);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: "same-origin" });
  if (response.status === 204) return null;
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(result?.detail?.code || `request_failed_${response.status}`);
    error.status = response.status;
    throw error;
  }
  return result;
}
const json = (method, body) => ({ method, body: JSON.stringify(body) });
function announce(message, isError = false) {
  const toast = $("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle("notice-error", isError);
  toast.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { toast.hidden = true; }, 4800);
}
function friendlyError(error) {
  return ({
    authentication_required: "Please sign in again.",
    invalid_credentials: "Email or password is incorrect.",
    account_already_exists: "An account with this email already exists.",
    project_not_found: "That project is not available to your account.",
    insufficient_project_role: "Your project role does not allow this action.",
    unsupported_file_type: "Choose a TXT, Markdown, CSV, PDF, or DOCX file.",
    file_too_large: "The file exceeds the 2 MB upload limit.",
    document_extraction_failed: "The file could not be safely extracted. Check it and try again.",
    no_extractable_text: "No readable text was found in that file.",
    invalid_source_citation: "Choose a source span you are allowed to access.",
    quote_not_in_source_span: "The quote must match text in the selected source span.",
    quote_does_not_directly_support_claim: "The citation must directly contain the claim wording.",
    claim_citation_not_verified: "Add and verify source evidence before accepting this claim.",
    edited_claim_not_supported_by_evidence: "Keep the edited claim within what its source evidence says.",
    unresolved_conflicts_block_approval: "Resolve or explicitly retain every conflict before approval.",
    no_reviewed_claims_to_approve: "Review and accept at least one claim before approval.",
    unverified_claim_blocks_approval: "Approval is blocked because a claim citation could not be verified.",
    demo_already_seeded: "The synthetic AURORA demo is already in this project.",
    handover_already_acknowledged: "You have already acknowledged this version.",
    claim_has_unresolved_conflict: "Resolve or explicitly retain the conflict before accepting this claim.",
    handover_already_acknowledged: "You have already acknowledged this version.",
    review_reason_required: "Add a reason before rejecting or marking a claim unresolved.",
    claim_extraction_provider_error: "OpenRouter claim extraction failed. No fallback claims were created; retry or remove the provider key to use deterministic reconstruction.",
    ai_source_text_limit_exceeded: "The visible source text exceeds the 60,000-character OpenRouter limit. Reduce the input and try again.",
  })[error.message] || (error.message.startsWith("request_failed_")
    ? `The request failed (${error.message.slice(-3)}). Please try again.`
    : "Something went wrong. Please try again.");
}

function showAuth() {
  $("#workspace").hidden = true;
  $("#auth-screen").hidden = false;
}
function showWorkspace() {
  $("#auth-screen").hidden = true;
  $("#workspace").hidden = false;
  $("#user-email").textContent = state.user.email;
}
function setAuthMode(mode) {
  const signup = mode === "signup";
  $("#auth-title").textContent = signup ? "Start with context" : "Welcome back";
  $("#auth-copy").textContent = signup ? "Create your account to join or start a project." : "Sign in to pick up where your team left off.";
  $("#auth-submit").innerHTML = signup ? "Create account <span aria-hidden=\"true\">→</span>" : "Sign in securely <span aria-hidden=\"true\">→</span>";
  $("#auth-password").autocomplete = signup ? "new-password" : "current-password";
  document.querySelectorAll("[data-auth-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.authMode === mode);
  });
  $("#auth-form").dataset.mode = mode;
  $("#auth-error").hidden = true;
}
async function enterWorkspace() {
  state.projects = await api("/projects");
  await loadProjectPicklist();
  showWorkspace();
  if (state.projects.length) {
    selectProject(state.projects[0].id);
  } else {
    state.project = null;
    $("#project-name").textContent = "New workspace";
    await render();
  }
}
async function selectProject(id) {
  state.project = state.projects.find((project) => project.id === id) || null;
  if (!state.project) return;
  $("#project-name").textContent = state.project.name;
  $("#project-picker").value = id;
  await render();
}
async function loadProjectPicklist() {
  const picker = $("#project-picker");
  picker.innerHTML = state.projects.map((project) =>
    `<option value="${escapeHtml(project.id)}">${escapeHtml(project.name)} · ${escapeHtml(project.role)}</option>`,
  ).join("");
}
async function loadWorkspaceView(view) {
  if (!state.project) {
    return `<section class="page-heading"><div><p class="eyebrow">GET YOUR TEAM STARTED</p><h1>Create a project</h1><p>Start a private workspace for your team. You will be its project owner.</p></div></section>
      <section class="card form-card"><form id="new-project-form"><label for="new-project-name">Project name</label><input id="new-project-name" name="name" maxlength="200" placeholder="e.g. AURORA" required><div class="form-actions"><button class="button button-primary" type="submit">Create project</button></div></form></section>`;
  }
  switch (view) {
    case "dashboard": return dashboardView();
    case "sources": return sourcesView();
    case "search": return searchView();
    case "claims": return claimsView();
    case "conflicts": return conflictsView();
    case "readiness": return readinessView();
    case "handover": return handoverView();
    case "team": return teamView();
    case "audit": return auditView();
    default: return dashboardView();
  }
}
async function render() {
  const root = $("#view-root");
  root.innerHTML = `<p class="loading">Loading project data…</p>`;
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("is-active", item.dataset.view === state.view));
  try {
    root.innerHTML = await loadWorkspaceView(state.view);
    bindViewEvents();
  } catch (error) {
    root.innerHTML = `<div class="notice notice-error" role="alert">${escapeHtml(friendlyError(error))}</div>`;
  }
}

async function dashboardView() {
  if (!state.project) return loadWorkspaceView("dashboard");
  const data = await api(`/projects/${state.project.id}/dashboard`);
  $("#source-badge").textContent = data.source_count || "";
  $("#claim-badge").textContent = data.claim_count || "";
  const extraction = state.lastExtraction?.projectId === state.project.id
    ? `<section class="card extraction-results"><h2 class="section-title">Latest extraction candidates <small>${state.lastExtraction.candidates.length} citation-checked</small></h2>${state.lastExtraction.candidates.length ? `<div class="list">${state.lastExtraction.candidates.map((candidate) => `<article class="list-row"><div class="list-main"><div class="claim-meta">${badge(candidate.category)}${candidate.has_conflict ? badge("conflict flagged") : ""}</div><strong>${escapeHtml(candidate.claim_title)}</strong><div class="evidence-box">${escapeHtml(candidate.exact_quote)}<cite>Lines ${candidate.source_line_start}-${candidate.source_line_end} · ${escapeHtml(candidate.confidence_reason)}</cite></div>${candidate.has_conflict ? '<p class="role-note">Review both source statements; this candidate was not automatically resolved.</p>' : ""}</div></article>`).join("")}</div>` : empty("No candidates returned", "The model did not return verifiable claim quotes for the new source lines.")}</section>`
    : "";
  const sources = data.recent_sources.length
    ? `<div class="list">${data.recent_sources.map((source) => `<div class="list-row"><div class="list-main"><strong>${escapeHtml(source.filename)}</strong><p>Added ${new Date(source.created_at).toLocaleString()}</p></div></div>`).join("")}</div>`
    : empty("No sources connected", "Upload authorized project documents to start building an evidence-backed picture.");
  return `  <section class="page-heading"><div><p class="eyebrow">PROJECT OVERVIEW</p><h1>${escapeHtml(data.name)}</h1><p>Your workspace keeps claims tied to source evidence and the next actions visible to the team.</p></div><div class="actions">${data.role === "owner" ? `<button type="button" class="button button-outline" id="seed-demo">Load synthetic AURORA demo</button>` : ""}${data.source_count ? `<button type="button" class="button button-outline" id="reconstruct">Reconstruct visible sources</button>` : ""}<button type="button" class="button button-primary" data-go="sources">Connect a source</button></div></section>
  ${extraction}
  <section class="welcome-card"><div><p class="eyebrow">YOUR ROLE · ${escapeHtml(roleLabel(data.role).toUpperCase())}</p><h2>Knowledge that carries forward.</h2><p>Review evidence, record decisions, and prepare a human-approved handover when your team is ready.</p></div><div class="actions"><button type="button" class="button button-outline" data-go="claims">Review claims <span aria-hidden="true">→</span></button></div></section>
  <section class="grid grid-cards">
    <article class="card"><span class="stat-label">Visible sources</span><strong class="stat-value">${data.source_count}</strong><span class="stat-sub">${data.source_span_count} traceable spans</span></article>
    <article class="card"><span class="stat-label">Visible claims</span><strong class="stat-value">${data.claim_count}</strong><span class="stat-sub">With evidence and review status</span></article>
    <article class="card"><span class="stat-label">Open conflicts</span><strong class="stat-value">${data.open_conflict_count}</strong><span class="stat-sub">Need a human decision</span></article>
    <article class="card"><span class="stat-label">Missing evidence</span><strong class="stat-value">${data.missing_evidence_count}</strong><span class="stat-sub">Questions that matter to handover</span></article>
  </section>
  <section class="grid grid-two"><article class="card"><h2 class="section-title">Recent source activity <small>${data.source_count} visible</small></h2>${sources}</article><article class="card"><h2 class="section-title">The workflow</h2><div class="list"><div class="list-row"><div class="list-main"><strong>01 · Connect</strong><p>Upload an authorized export or project document.</p></div></div><div class="list-row"><div class="list-main"><strong>02 · Verify</strong><p>Every important claim needs a source span that supports it.</p></div></div><div class="list-row"><div class="list-main"><strong>03 · Review &amp; hand over</strong><p>Resolve conflicts, approve a version, and check recipient redactions.</p></div></div></div></article></section>`;
}

async function sourcesView() {
  state.sources = await api(`/projects/${state.project.id}/sources`);
  return `<section class="page-heading"><div><p class="eyebrow">CONNECT · SOURCE LIBRARY</p><h1>Project sources</h1><p>Only material your team is authorized to share should be uploaded. Sources are split into line-addressable evidence spans.</p></div></section>
  <section class="card form-card"><h2 class="section-title">Add a document</h2><form id="source-form" class="form-grid">
    <div class="span-all"><label for="source-file">File · TXT, Markdown, CSV, PDF or DOCX · 2 MB max</label><input id="source-file" name="file" type="file" accept=".txt,.md,.csv,.pdf,.docx" required></div>
    <div><label for="source-sensitivity">Who may access it?</label><select id="source-sensitivity" name="sensitivity"><option value="project">Project members</option>${canReview() ? '<option value="restricted">Owner and reviewer only</option>' : ""}</select></div>
    <div class="form-actions span-all"><button type="submit" class="button button-primary">Upload and extract</button></div>
  </form></section>
  <section class="card"><h2 class="section-title">Connected sources <small>${state.sources.length} visible to your role</small></h2><div id="source-list">${state.sources.length ? `<div class="list">${state.sources.map((source) => `<div class="list-row"><div class="list-main"><strong>${escapeHtml(source.filename)}</strong><p>${source.span_count} evidence spans · ${new Date(source.created_at).toLocaleDateString()}</p></div><div class="list-actions">${badge(source.sensitivity)}<button class="button button-outline button-small" type="button" data-source="${escapeHtml(source.id)}">View spans</button></div></div>`).join("")}</div>` : empty("No documents yet", "Upload a source to create traceable spans.")}</div><div id="source-detail"></div></section>`;
}

async function searchView() {
  return `<section class="page-heading"><div><p class="eyebrow">ACCESS-CONTROLLED RETRIEVAL</p><h1>Search project evidence</h1><p>Search runs against source spans and claims the server has already filtered to your project role. This is keyword retrieval, not vector search.</p></div></section>
    <section class="card form-card"><form id="search-form"><label for="project-search">Search terms</label><div class="filter-row"><input id="project-search" type="search" minlength="2" maxlength="200" required placeholder="e.g. battery, calibration, line sensor"><button class="button button-primary" type="submit">Search authorized evidence</button></div></form><div id="search-results">${empty("Search your accessible sources", "Restricted source text and metadata are filtered before search.")}</div></section>`;
}

async function claimsView() {
  state.sources = await api(`/projects/${state.project.id}/sources`);
  state.claims = await api(`/projects/${state.project.id}/claims`);
  return `<section class="page-heading"><div><p class="eyebrow">RECONSTRUCT · VERIFY · REVIEW</p><h1>Claim ledger</h1><p>Claims are project facts only when backed by stored evidence. Inferences and gaps are not presented as verified knowledge.</p></div></section>
  <section class="card form-card"><h2 class="section-title">Propose a claim</h2><form id="claim-form" class="form-grid">
    <div><label for="claim-category">Category</label><select id="claim-category" required><option value="current_state">Current state</option><option value="owner">Owner</option><option value="decision">Decision</option><option value="task">Task</option><option value="risk">Risk</option><option value="dependency">Dependency</option><option value="open_question">Open question</option></select></div>
    <div><label for="claim-sensitivity">Sensitivity</label><select id="claim-sensitivity"><option value="project">Project</option>${canReview() ? '<option value="restricted">Restricted · owner and reviewer</option>' : ""}</select></div>
    <div class="span-all"><label for="claim-text">What does the source directly say?</label><textarea id="claim-text" maxlength="4000" placeholder="Use a faithful, evidence-backed statement. Do not infer missing details." required></textarea></div>
    <div><label for="evidence-source">Source (optional)</label><select id="evidence-source"><option value="">No citation yet</option>${state.sources.map((source) => `<option value="${escapeHtml(source.id)}">${escapeHtml(source.filename)}</option>`).join("")}</select></div>
    <div><label for="evidence-span">Source span</label><select id="evidence-span" disabled><option value="">Choose a source first</option></select></div>
    <div class="span-all"><label for="claim-owner">Owner, only when stated in the evidence</label><input id="claim-owner" maxlength="200" placeholder="Optional"></div>
    <div class="form-actions span-all"><button type="submit" class="button button-primary">Add proposed claim</button></div>
  </form></section>
  <section class="card"><div class="section-title"><span>Claims <small>${state.claims.length} visible</small></span><div class="filter-row"><input id="claim-search" type="search" placeholder="Search visible claims" aria-label="Search visible claims"><select id="claim-category-filter" aria-label="Filter by category"><option value="">All categories</option><option value="owner">Owner</option><option value="decision">Decision</option><option value="current_state">Current state</option><option value="task">Task</option><option value="risk">Risk</option><option value="dependency">Dependency</option><option value="open_question">Open question</option></select></div></div><div id="claim-list">${renderClaimList(state.claims)}</div></section>`;
}

function renderClaimList(claims) {
  if (!claims.length) return empty("No claims yet", "Connect a source and propose a claim backed by a verified span.");
  return claims.map((claim) => `<article class="claim-row" data-claim-row="${escapeHtml(claim.id)}">
    <div class="claim-heading"><strong>${escapeHtml(claim.claim_text)}</strong>${badge(claim.evidence_tier)}</div>
    <div class="claim-meta">${badge(claim.category.replaceAll("_", " "))}${badge(claim.status)}${badge(claim.sensitivity)}${claim.owner_text ? `<span class="role-note">Owner: ${escapeHtml(claim.owner_text)}</span>` : ""}</div>
    ${claim.evidence.map((item) => `<div class="evidence-box">“${escapeHtml(item.quote)}”<cite>${escapeHtml(item.filename)} · ${escapeHtml(item.location)} · ${item.citation_valid ? "Citation verified against the stored span" : "Citation needs review"}</cite></div>`).join("")}
    ${canReview() ? `    <div class="list-actions claim-actions"><button type="button" class="button button-outline button-small" data-review="accept" data-claim="${escapeHtml(claim.id)}" ${claim.status === "accepted" ? "disabled" : ""}>Accept</button><button type="button" class="button button-outline button-small" data-review="edit" data-claim="${escapeHtml(claim.id)}">Edit</button><button type="button" class="button button-danger button-small" data-review="reject" data-claim="${escapeHtml(claim.id)}">Reject</button><button type="button" class="button button-outline button-small" data-review="unresolved" data-claim="${escapeHtml(claim.id)}">Mark unresolved</button></div>` : ""}
  </article>`).join("");
}

async function conflictsView() {
  const conflicts = await api(`/projects/${state.project.id}/conflicts`);
  state.claims = await api(`/projects/${state.project.id}/claims`);
  const openCount = conflicts.filter((conflict) => conflict.status === "open").length;
  const createForm = canReview() ? `<section class="card form-card"><h2 class="section-title">Record a disagreement</h2><form id="conflict-form" class="form-grid"><div><label for="conflict-first">First claim</label><select id="conflict-first">${state.claims.map((claim) => `<option value="${escapeHtml(claim.id)}">${escapeHtml(claim.claim_text)}</option>`).join("")}</select></div><div><label for="conflict-second">Competing claim</label><select id="conflict-second">${state.claims.map((claim) => `<option value="${escapeHtml(claim.id)}">${escapeHtml(claim.claim_text)}</option>`).join("")}</select></div><div class="form-actions span-all"><button type="submit" class="button button-outline" ${state.claims.length < 2 ? "disabled" : ""}>Record conflict</button></div></form></section>` : "";
  const rows = conflicts.length ? `<div class="list">${conflicts.map((item) => `<article class="list-row"><div class="list-main"><div class="claim-meta">${badge(item.conflict_type.replaceAll("_", " "))}${badge(item.status)}</div><strong>${escapeHtml(item.claims[0].claim_text)}</strong><p>Conflicts with: ${escapeHtml(item.claims[1].claim_text)}</p>${item.rationale ? `<p>Reviewer rationale: ${escapeHtml(item.rationale)}</p>` : ""}${item.status === "open" && canReview() ? `<label for="rationale-${escapeHtml(item.id)}">Resolution or ambiguity rationale</label><input id="rationale-${escapeHtml(item.id)}" maxlength="2000" placeholder="Explain the reviewer decision"><div class="list-actions left-actions"><button type="button" class="button button-primary button-small" data-resolve="resolved" data-conflict="${escapeHtml(item.id)}">Resolve</button><button type="button" class="button button-outline button-small" data-resolve="accepted_as_ambiguity" data-conflict="${escapeHtml(item.id)}">Retain as ambiguity</button><button type="button" class="button button-quiet button-small" data-resolve="dismissed" data-conflict="${escapeHtml(item.id)}">Dismiss</button></div>` : ""}</div></article>`).join("")}</div>` : empty("No conflicts recorded", "When sources disagree, preserve both claims and record the reviewer’s resolution.");
  return `<section class="page-heading"><div><p class="eyebrow">HUMAN REVIEW · NO SILENT WINNER</p><h1>Conflicts &amp; decisions</h1><p>Competing claims remain visible until a reviewer records a decision. A newer source never wins automatically.</p></div><span class="badge ${openCount ? "badge-open" : "badge-resolved"}">${openCount} open</span></section>${createForm}<section class="card"><h2 class="section-title">Conflict register</h2>${rows}</section>`;
}

async function readinessView() {
  if (!canReview()) {
    return `<section class="page-heading"><div><p class="eyebrow">REVIEWER WORKSPACE</p><h1>Readiness breakdown</h1><p>The detailed readiness calculation is limited to project owners and reviewers.</p></div></section>${empty("Ask your project owner", "The readiness score includes review and conflict information reserved for the review team.")}`;
  }
  const [data, missing] = await Promise.all([
    api(`/projects/${state.project.id}/readiness`),
    api(`/projects/${state.project.id}/missing-evidence`),
  ]);
  const gaps = data.gaps.length ? `<ul class="gap-list">${data.gaps.map((gap) => `<li>${escapeHtml(gap)}</li>`).join("")}</ul>` : `<p class="role-note">No current gaps in this breakdown.</p>`;
  const evidenceItems = missing.length ? `<div class="list">${missing.map((item) => `<div class="list-row"><div class="list-main"><strong>${escapeHtml(item.description)}</strong><p>${escapeHtml(item.why_it_matters)}${item.suggested_question ? ` Suggested question: ${escapeHtml(item.suggested_question)}` : ""}</p></div><div class="list-actions">${item.resolved ? badge("resolved") : `<button class="button button-outline button-small" type="button" data-missing-resolve="${escapeHtml(item.id)}">Mark addressed</button>`}</div></div>`).join("")}</div>` : empty("No missing-evidence items", "Add a question when a gap could affect a safe handover.");
  return `<section class="page-heading"><div><p class="eyebrow">TRANSPARENT · DETERMINISTIC · DRAFT</p><h1>Handover readiness</h1><p>The score is a review aid, never an approval shortcut. Category coverage, verified citations, conflicts, missing evidence, and review status each show their contribution.</p></div><span class="badge badge-proposed">DRAFT — NOT APPROVED</span></section>
  <section class="grid grid-two"><article class="card"><h2 class="section-title">Readiness score</h2><div class="score-layout"><div><div class="score-number">${data.score}<small>/100</small></div><progress class="score-progress" max="100" value="${data.score}" aria-label="${data.score} out of 100">${data.score}%</progress><p class="role-note">This project has ${data.accepted_claims} accepted claims out of ${data.total_claims} visible claims. A project with no claims scores 0.</p></div><div>${Object.entries(data.breakdown).map(([name, value]) => `<div class="breakdown-row"><span>${escapeHtml(name.replaceAll("_", " "))}</span><strong>${value}</strong></div>`).join("")}</div></div></article><article class="card"><h2 class="section-title">Gaps that reduce readiness</h2>${gaps}<p class="role-note">${escapeHtml(data.formula)}</p></article></section>
  <section class="card form-card spacing-top-16"><h2 class="section-title">Missing evidence &amp; open questions</h2>${evidenceItems}${canReview() ? `<form id="missing-form" class="form-grid"><div class="span-all"><label for="missing-description">What is not known or evidenced?</label><input id="missing-description" maxlength="1000" required placeholder="e.g. The competition track calibration has not been validated"></div><div><label for="missing-why">Why does it matter?</label><input id="missing-why" maxlength="1000" required></div><div><label for="missing-question">Suggested question</label><input id="missing-question" maxlength="1000"></div><div class="form-actions span-all"><button class="button button-outline" type="submit">Add missing-evidence item</button></div></form>` : ""}</section>`;
}

async function handoverView() {
  const versions = await api(`/projects/${state.project.id}/handovers`);
  const activeVersion = versions.find((version) => version.version === state.handoverVersion) || versions[0];
  if (activeVersion) state.handoverVersion = activeVersion.version;
  const preview = activeVersion ? await api(`/projects/${state.project.id}/handovers/${activeVersion.version}/preview`) : null;
  const canApprove = canReview();
  const versionRows = versions.map((version) => `<div class="list-row"><div class="list-main"><strong>Version ${version.version}</strong><p>${version.claim_count} approved claims · ${new Date(version.approved_at).toLocaleString()}</p></div><button class="button button-outline button-small" type="button" data-preview-version="${version.version}">${version.version === activeVersion.version ? "Viewing" : "Preview"}</button></div>`).join("");
  const claimRows = preview?.claims.map((claim) => `<div class="list-row"><div class="list-main"><div class="claim-meta">${badge(claim.category.replaceAll("_", " "))}${badge(claim.evidence_tier)}</div><strong>${escapeHtml(claim.claim_text)}</strong>${claim.evidence.map((item) => `<div class="evidence-box">“${escapeHtml(item.quote)}”<cite>${escapeHtml(item.filename)} · ${escapeHtml(item.location)}</cite></div>`).join("")}</div></div>`).join("");
  const acknowledgementForm = state.project.role === "incoming_lead" ? `<form id="ack-form"><label for="ack-note">Optional receipt note</label><textarea id="ack-note" maxlength="2000" placeholder="I have received this version."></textarea><div class="form-actions"><button type="submit" class="button button-primary">Acknowledge receipt</button></div><p class="role-note">Acknowledgement confirms receipt; it does not mean you agree with every claim.</p></form>` : "";
  return `<section class="page-heading"><div><p class="eyebrow">HUMAN-APPROVED · VERSIONED · ROLE-SCOPED</p><h1>Project handover</h1><p>Approved snapshots are immutable. Each view is filtered again using your current clearance; withheld content is never included in the redaction details.</p></div>${canApprove ? `<button id="approve-handover" type="button" class="button button-primary" ${versions.length && versions[0].version ? "" : ""}>Approve a new version</button>` : ""}</section>
  ${versions.length ? `<section class="grid grid-two"><article class="card"><h2 class="section-title">Approved versions</h2><div class="list">${versionRows}</div></article><article class="card"><h2 class="section-title">Your recipient view · version ${preview.version}</h2><div class="redaction-box"><strong>${preview.redaction.withheld_claim_count} claim(s) and ${preview.redaction.withheld_evidence_count} evidence item(s) withheld</strong><br>Reason: recipient clearance. Protected contents and names are deliberately omitted.</div><div class="list compact-list">${claimRows || empty("No claims visible", "No claims from this snapshot are cleared for this project role.")}</div>${acknowledgementForm}</article></section>` : `<section class="card">${empty("No handover approved yet", "A reviewer must resolve or explicitly retain conflicts, then approve an evidence-checked snapshot.")}</section>`}
  ${versions.length ? `<div class="role-note spacing-top-13">Showing the selected approved snapshot. Version history is preserved even if the project ledger changes later.</div>` : ""}`;
}

async function teamView() {
  const members = await api(`/projects/${state.project.id}/members`);
  return `<section class="page-heading"><div><p class="eyebrow">PROJECT-SCOPED ACCESS</p><h1>Team &amp; roles</h1><p>Roles determine project actions and clearance. Protected data access is checked by the API on every request.</p></div></section>
  ${state.project.role === "owner" ? `<section class="card form-card"><h2 class="section-title">Invite or update a member</h2><form id="member-form" class="form-grid"><div><label for="member-email">Existing account email</label><input id="member-email" type="email" required placeholder="teammate@team.org"></div><div><label for="member-role">Project role</label><select id="member-role"><option value="member">Member</option><option value="reviewer">Reviewer / approver</option><option value="incoming_lead">Incoming lead</option><option value="owner">Project owner</option></select></div><div class="form-actions span-all"><button class="button button-primary" type="submit">Save project role</button></div></form><p class="role-note">Members must create an account before being added. Inviting an unregistered address does not silently create an account.</p></section>` : ""}
  <section class="card"><h2 class="section-title">Project members <small>${members.length} members</small></h2><div class="list">${members.map((member) => `<div class="list-row"><div class="list-main"><strong>${escapeHtml(member.email)}</strong><p>Joined ${new Date(member.joined_at).toLocaleDateString()}</p></div>${badge(roleLabel(member.role))}</div>`).join("")}</div></section>`;
}

async function auditView() {
  if (!canReview()) return `<section class="page-heading"><div><p class="eyebrow">OWNER &amp; REVIEWER</p><h1>Audit trail</h1><p>Access, reviews, approvals, redaction counts, and acknowledgements are recorded.</p></div></section>${empty("Audit access is restricted", "Project owners and reviewers can inspect the audit trail.")}`;
  const events = await api(`/projects/${state.project.id}/audit`);
  return `<section class="page-heading"><div><p class="eyebrow">HISTORY · ACCOUNTABILITY</p><h1>Audit trail</h1><p>Records who accessed, changed, reviewed, approved, rendered, and acknowledged project information.</p></div></section>
  <section class="card"><div class="list">${events.length ? events.map((event) => `<div class="list-row"><div class="list-main"><strong>${escapeHtml(event.event_type.replaceAll("_", " "))}</strong><p>${escapeHtml(event.actor_id)} · ${new Date(event.created_at).toLocaleString()}</p></div>${Object.keys(event.metadata || {}).length ? `<span class="role-note">${escapeHtml(Object.entries(event.metadata).map(([key, value]) => `${key}: ${value}`).join(" · "))}</span>` : ""}</div>`).join("") : empty("No audit events yet", "Actions taken in this project will appear here.")}</div></section>`;
}

async function bindViewEvents() {
  $("[data-go]")?.addEventListener("click", async (event) => { state.view = event.currentTarget.dataset.go; await render(); });
  $("#new-project-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const project = await api("/projects", json("POST", { name: $("#new-project-name").value }));
      state.projects.push(project);
      await loadProjectPicklist();
      state.project = project;
      $("#project-name").textContent = project.name;
      state.view = "dashboard";
      await render();
      announce("Private project workspace created.");
    } catch (error) { announce(friendlyError(error), true); }
  });
  $("#seed-demo")?.addEventListener("click", async () => {
    try {
      const result = await api(`/projects/${state.project.id}/demo/aurora`, { method: "POST" });
      announce(`Synthetic AURORA corpus loaded: ${result.source_count} sources, ${result.claim_count} cited claims, ${result.conflict_count} conflict, ${result.missing_evidence_count} evidence gap.`);
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  });
  $("#reconstruct")?.addEventListener("click", async () => {
    try {
      const result = await api(`/projects/${state.project.id}/reconstruction`, { method: "POST" });
      state.lastExtraction = {
        projectId: state.project.id,
        candidates: result.candidates || [],
      };
      const method = result.llm_used ? "OpenRouter" : "Deterministic";
      const conflictCount = state.lastExtraction.candidates.filter((candidate) => candidate.has_conflict).length;
      const conflictNotice = conflictCount
        ? ` ${conflictCount} candidate(s) flagged for conflict review.`
        : "";
      const omittedNotice = result.omitted_span_count
        ? ` ${result.omitted_span_count} source span(s) had no verified candidate.`
        : "";
      announce(`${method} reconstruction proposed ${result.created_claim_count} claim(s) from ${result.processed_span_count} visible source span(s). All claims need human review.${conflictNotice}${omittedNotice}`);
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  });
  $("#search-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const resultsRoot = $("#search-results");
    resultsRoot.innerHTML = `<p class="loading">Searching evidence your role can access…</p>`;
    try {
      const result = await api(`/projects/${state.project.id}/search?q=${encodeURIComponent($("#project-search").value)}`);
      resultsRoot.innerHTML = result.results.length
        ? `<p class="role-note">${result.results.length} visible result(s) · ACL-filtered keyword search</p><div class="list">${result.results.map((item) => item.type === "source_span"
          ? `<div class="list-row"><div class="list-main">${badge(item.sensitivity)}<strong>${escapeHtml(item.filename)} · ${escapeHtml(item.location)}</strong><div class="evidence-box">${escapeHtml(item.text)}</div></div></div>`
          : `<div class="list-row"><div class="list-main">${badge(item.claim.evidence_tier)}<strong>${escapeHtml(item.claim.claim_text)}</strong><p>Claim · ${escapeHtml(item.claim.category)}</p></div></div>`).join("")}</div>`
        : empty("No matching evidence", "Try other keywords from sources you are allowed to access.");
    } catch (error) { resultsRoot.innerHTML = `<div class="notice notice-error" role="alert">${escapeHtml(friendlyError(error))}</div>`; }
  });
  $("#source-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("#source-file").files[0];
    if (!file) return;
    const body = new FormData();
    body.append("file", file);
    body.append("sensitivity", $("#source-sensitivity").value);
    try {
      const source = await api(`/projects/${state.project.id}/sources`, { method: "POST", body });
      announce(`${source.filename} ingested into ${source.span_count} evidence span(s).`);
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  });
  document.querySelectorAll("[data-source]").forEach((button) => button.addEventListener("click", async () => {
    try {
      const source = await api(`/projects/${state.project.id}/sources/${button.dataset.source}`);
      $("#source-detail").innerHTML = `<div class="evidence-box">${source.spans.map((span) => `<p><strong>Line ${span.line_start}</strong> · ${escapeHtml(span.text)}</p>`).join("")}</div>`;
    } catch (error) { announce(friendlyError(error), true); }
  }));
  $("#evidence-source")?.addEventListener("change", async (event) => {
    const select = $("#evidence-span");
    select.disabled = true;
    select.innerHTML = `<option value="">Loading source spans…</option>`;
    if (!event.target.value) { select.innerHTML = `<option value="">Choose a source first</option>`; return; }
    try {
      const source = await api(`/projects/${state.project.id}/sources/${event.target.value}`);
      select.innerHTML = `<option value="">Select a source span</option>${source.spans.map((span) => `<option value="${escapeHtml(span.id)}" data-quote="${escapeHtml(span.text)}">Line ${span.line_start} · ${escapeHtml(span.text.slice(0, 85))}</option>`).join("")}`;
      select.disabled = false;
    } catch (error) { announce(friendlyError(error), true); }
  });
  $("#evidence-span")?.addEventListener("change", (event) => {
    const selected = event.target.selectedOptions[0];
    if (selected?.dataset.quote && !$("#claim-text").value) $("#claim-text").value = selected.dataset.quote;
  });
  $("#claim-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const spanId = $("#evidence-span").value;
    const quote = spanId ? $("#evidence-span").selectedOptions[0].dataset.quote : "";
    const body = {
      category: $("#claim-category").value,
      claim_text: $("#claim-text").value,
      sensitivity: $("#claim-sensitivity").value,
      owner_text: $("#claim-owner").value || null,
      evidence: spanId ? [{ source_span_id: spanId, quote }] : [],
    };
    try {
      await api(`/projects/${state.project.id}/claims`, json("POST", body));
      announce("Claim proposed and citation checked against the stored source span.");
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  });
  $("#claim-search")?.addEventListener("input", filterClaims);
  $("#claim-category-filter")?.addEventListener("change", filterClaims);
  document.querySelectorAll("[data-review]").forEach((button) => button.addEventListener("click", async () => {
    let body = { action: button.dataset.review };
    if (["reject", "unresolved"].includes(body.action)) {
      body.reason = window.prompt("Add a brief review reason:");
      if (!body.reason) return;
    } else if (body.action === "edit") {
      body.updated_text = window.prompt("Edit this claim. Its existing source must still directly support it:", "");
      if (!body.updated_text) return;
    }
    try {
      await api(`/projects/${state.project.id}/claims/${button.dataset.claim}/review`, json("POST", body));
      announce("Claim review recorded.");
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  }));
  $("#conflict-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api(`/projects/${state.project.id}/conflicts`, json("POST", {
        first_claim_id: $("#conflict-first").value,
        second_claim_id: $("#conflict-second").value,
        conflict_type: "reviewer_recorded",
      }));
      announce("Conflict recorded; both claims remain visible.");
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  });
  document.querySelectorAll("[data-resolve]").forEach((button) => button.addEventListener("click", async () => {
    const rationale = $(`#rationale-${button.dataset.conflict}`).value;
    if (!rationale.trim()) { announce("Add a rationale before resolving a conflict.", true); return; }
    try {
      await api(`/projects/${state.project.id}/conflicts/${button.dataset.conflict}/resolve`, json("POST", {
        status: button.dataset.resolve, rationale,
      }));
      announce("Conflict decision recorded in the audit trail.");
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  }));
  $("#missing-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api(`/projects/${state.project.id}/missing-evidence`, json("POST", {
        description: $("#missing-description").value,
        why_it_matters: $("#missing-why").value,
        suggested_question: $("#missing-question").value || null,
      }));
      announce("Missing-evidence item recorded.");
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  });
  document.querySelectorAll("[data-missing-resolve]").forEach((button) => button.addEventListener("click", async () => {
    try {
      await api(`/projects/${state.project.id}/missing-evidence/${button.dataset.missingResolve}/resolve`, { method: "POST" });
      announce("Evidence gap marked addressed.");
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  }));
  $("#approve-handover")?.addEventListener("click", async () => {
    if (!window.confirm("Approve an immutable snapshot of all accepted claims?")) return;
    try {
      const version = await api(`/projects/${state.project.id}/handovers/approve`, { method: "POST" });
      state.handoverVersion = version.version;
      announce(`Handover version ${version.version} approved and frozen.`);
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  });
  document.querySelectorAll("[data-preview-version]").forEach((button) => button.addEventListener("click", async () => {
    try {
      state.handoverVersion = Number(button.dataset.previewVersion);
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  }));
  $("#ack-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      if (!state.handoverVersion) return;
      await api(`/projects/${state.project.id}/handovers/${state.handoverVersion}/acknowledgement`, json("POST", { note: $("#ack-note").value || null }));
      announce("Receipt acknowledged. This does not imply agreement with every claim.");
      form.reset();
    } catch (error) { announce(friendlyError(error), true); }
  });
  $("#member-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await api(`/projects/${state.project.id}/members`, json("POST", {
        email: $("#member-email").value, role: $("#member-role").value,
      }));
      announce("Project membership updated.");
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  });
}

function filterClaims() {
  const query = $("#claim-search").value.trim().toLowerCase();
  const category = $("#claim-category-filter").value;
  const filtered = state.claims.filter((claim) =>
    (!category || claim.category === category) && (!query || claim.claim_text.toLowerCase().includes(query)),
  );
  $("#claim-list").innerHTML = renderClaimList(filtered);
  document.querySelectorAll("[data-review]").forEach((button) => button.addEventListener("click", async () => {
    const action = button.dataset.review;
    const body = { action };
    if (["reject", "unresolved"].includes(action)) { body.reason = window.prompt("Add a brief review reason:"); if (!body.reason) return; }
    if (action === "edit") { body.updated_text = window.prompt("Edit this claim; source evidence must still support it:"); if (!body.updated_text) return; }
    try {
      await api(`/projects/${state.project.id}/claims/${button.dataset.claim}/review`, json("POST", body));
      announce("Claim review recorded.");
      await render();
    } catch (error) { announce(friendlyError(error), true); }
  }));
}

document.querySelectorAll("[data-auth-mode]").forEach((button) => button.addEventListener("click", () => setAuthMode(button.dataset.authMode)));
$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const mode = event.currentTarget.dataset.mode || "login";
  const errorBox = $("#auth-error");
  errorBox.hidden = true;
  try {
    state.user = await api(`/auth/${mode === "signup" ? "signup" : "login"}`, json("POST", {
      email: $("#auth-email").value,
      password: $("#auth-password").value,
    }));
    await enterWorkspace();
  } catch (error) {
    errorBox.textContent = friendlyError(error);
    errorBox.hidden = false;
  }
});
document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", async () => {
  if (button.dataset.view) {
    state.view = button.dataset.view;
    await render();
  }
}));
$("#project-picker").addEventListener("change", async (event) => selectProject(event.target.value));
$("#theme-switch").addEventListener("change", (event) => applyTheme(event.target.value));
$("#logout").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch (error) {
    announce(friendlyError(error), true);
    return;
  }
  state.user = null;
  state.projects = [];
  state.project = null;
  showAuth();
});
applyTheme(localStorage.getItem(THEME_STORAGE_KEY) || "clean-light");
async function start() {
  try {
    state.user = await api("/auth/me");
    await enterWorkspace();
  } catch {
    showAuth();
  }
}
start();
