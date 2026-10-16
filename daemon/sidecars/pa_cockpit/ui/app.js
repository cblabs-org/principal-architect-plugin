/**
 * Principal Architect Cockpit AuxPane Frontend (`app.js`)
 * Implements SPEC.md §10.3 and PR-04 Charter G2/R5:
 * - Safe `window.sidecar` bindings (`onWorkspaceChange`, `ui.toggleConversation`)
 * - Live SSE subscription on `/api/events?workspace=<encoded>` + `/api/state` fallback
 * - Interactive mutation actions for `/api/sync`, `/api/mode`, `/api/pr/approve-plan`,
 *   `/api/escalation/resolve`, `/api/pr/start`, `/api/wo/debug`, and `/api/pr/graduate`
 * - Renders Zone 1 (Header/Mode/Model), Zone 2 (🔔 Human Attention Needed inbox),
 *   and Zone 3 (Programme -> Stacked PR -> Work Order DAG).
 */

(function () {
  "use strict";

  const stateStore = {
    workspaces: [],
    activeWorkspace: "",
    latestState: null,
    eventSource: null,
  };

  /**
   * Escape HTML special characters for safe DOM insertion.
   * @param {unknown} raw
   * @returns {string}
   */
  function escapeHtml(raw) {
    return String(raw ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /**
   * Show a brief status or error toast in Zone 1.
   * @param {string} message
   * @param {boolean} [isError=false]
   */
  function showToast(message, isError = false) {
    const toastEl = document.getElementById("action-toast");
    if (!toastEl) {
      return;
    }
    toastEl.textContent = message;
    toastEl.classList.toggle("error", Boolean(isError));
    toastEl.classList.remove("hidden");
    window.clearTimeout(toastEl._hideTimer);
    toastEl._hideTimer = window.setTimeout(() => {
      toastEl.classList.add("hidden");
    }, 4000);
  }

  /**
   * Focus/open an agent conversation in the Antigravity IDE sidebar when available.
   * @param {string | null | undefined} conversationId
   */
  function jumpToConversation(conversationId) {
    if (!conversationId) {
      showToast("No bound conversation ID for this target yet.", true);
      return;
    }
    if (
      window.sidecar &&
      window.sidecar.ui &&
      typeof window.sidecar.ui.toggleConversation === "function"
    ) {
      window.sidecar.ui.toggleConversation(conversationId);
    }
  }

  /**
   * Perform a JSON POST request to a Cockpit API endpoint.
   * @param {string} endpoint
   * @param {Record<string, unknown>} payload
   * @returns {Promise<Record<string, unknown>>}
   */
  async function postJson(endpoint, payload) {
    const bodyObj = {
      workspace: stateStore.activeWorkspace || undefined,
      ...payload,
    };
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyObj),
    });
    const data = await response.json().catch(() => ({ ok: false, error: "Invalid server response" }));
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `Request to ${endpoint} failed (${response.status})`);
    }
    return data;
  }

  // --- API Mutation Helpers (all 7 POST routes) ---

  async function triggerSync() {
    try {
      const res = await postJson("/api/sync", {});
      showToast(`Synced state (audits: ${res.synced_audits ?? 0})`);
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function updateModeOrModel(options) {
    try {
      const res = await postJson("/api/mode", options);
      showToast(
        `Mode: ${res.execution_mode} · Model: ${res.architect_model}`
      );
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function approvePrPlan(prId) {
    try {
      const res = await postJson("/api/pr/approve-plan", {
        pr_id: prId,
        approved_by: "human",
      });
      showToast(`Approved plan for ${res.pr_id}`);
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function resolveEscalation(escalationId, decision, requestedFiles) {
    try {
      const payload = {
        escalation_id: escalationId,
        decision: decision,
      };
      if (Array.isArray(requestedFiles)) {
        payload.requested_files = requestedFiles;
      }
      const res = await postJson("/api/escalation/resolve", payload);
      showToast(`Escalation ${res.escalation_id}: ${res.status}`);
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function startPr(prId) {
    try {
      const res = await postJson("/api/pr/start", { pr_id: prId });
      showToast(`Started ${res.pr_id}`);
      if (res.conversation_id) {
        jumpToConversation(res.conversation_id);
      }
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function debugWorkOrder(woId) {
    try {
      const res = await postJson("/api/wo/debug", { wo_id: woId });
      showToast(`Launched debugger for ${res.wo_id}`);
      if (res.conversation_id) {
        jumpToConversation(res.conversation_id);
      }
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function graduatePr(prId) {
    try {
      const res = await postJson("/api/pr/graduate", { pr_id: prId });
      showToast(`Graduated ${res.pr_id} (${res.status})`);
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  // --- Rendering Helpers ---

  function statusClass(rawStatus) {
    const norm = String(rawStatus || "PENDING")
      .toLowerCase()
      .replace(/_/g, "-");
    return `status-${norm}`;
  }

  function formatPrStatusBadge(pr) {
    const st = String(pr.status || "PLANNED").toUpperCase();
    const ghNum = pr.github_pr ? ` #${pr.github_pr}` : "";
    const latestAudit = pr.latest_audit;
    if (st === "GRADUATED") {
      return `🟣 Graduated${ghNum}`;
    }
    if (st === "AUDIT_APPROVED" || (latestAudit && latestAudit.verdict === "APPROVED")) {
      return `✅ Audit Approved${ghNum}`;
    }
    if (latestAudit && latestAudit.verdict === "CHANGES_REQUESTED") {
      return `🔍 Changes Requested (Round ${latestAudit.audit_round || 1}/5)`;
    }
    if (st === "STAGED_FOR_AUDIT") {
      return `📤 Staged for Audit${ghNum}`;
    }
    if (pr.github_pr) {
      return `🚧 Draft PR #${pr.github_pr} ↗`;
    }
    return `📝 ${st}`;
  }

  function renderZone1Header(state) {
    const env = (state && state.env) || {};
    const vcsBadge = document.getElementById("badge-vcs-mode");
    if (vcsBadge) {
      const vcsLabel = env.vcs_mode === "github" ? "GitHub" : "Local";
      vcsBadge.textContent = `Git: ${vcsLabel}`;
    }

    const memBadge = document.getElementById("badge-memory-mode");
    if (memBadge) {
      const memLabel = env.memory_mode === "external" ? "repo-memory" : "Built-in";
      memBadge.textContent = `Memory: ${memLabel}`;
    }

    const execMode = env.execution_mode || "monitored";
    const btnMonitored = document.getElementById("btn-mode-monitored");
    const btnAutonomous = document.getElementById("btn-mode-autonomous");
    if (btnMonitored && btnAutonomous) {
      btnMonitored.classList.toggle("active", execMode === "monitored");
      btnAutonomous.classList.toggle("active", execMode === "autonomous");
    }

    const modelSelect = document.getElementById("architect-model-select");
    if (modelSelect && env.architect_model) {
      const options = Array.isArray(env.architect_model_options)
        ? env.architect_model_options
        : [];
      for (const optVal of options) {
        if (!Array.from(modelSelect.options).some((o) => o.value === optVal)) {
          const optEl = document.createElement("option");
          optEl.value = optVal;
          optEl.textContent = optVal;
          modelSelect.appendChild(optEl);
        }
      }
      modelSelect.value = env.architect_model;
    }
  }

  function classifyAttentionKind(item) {
    const kind = String(item.kind || "").toUpperCase();
    const esc = item.escalation || {};
    const trigger = String(esc.trigger_code || esc.reason_code || "").toUpperCase();
    if (
      kind.includes("PLAN") ||
      kind === "APPROVE_PLAN" ||
      kind === "R1_MON_PLAN_APPROVAL" ||
      trigger.includes("PLAN_APPROVAL")
    ) {
      return "PLAN_APPROVAL";
    }
    if (
      kind.includes("BOUNDARY") ||
      kind.includes("CHARTER") ||
      kind === "EXPAND_ALLOWED_FILES" ||
      kind === "RESOLVE_ESCALATION" ||
      trigger.includes("BOUNDARY") ||
      trigger.includes("CHARTER")
    ) {
      return "ESCALATION_RESOLVE";
    }
    if (
      kind.includes("GRADUATE") ||
      kind === "GRADUATE_PR" ||
      kind === "R6" ||
      trigger.includes("GRADUATE")
    ) {
      return "GRADUATE_PR";
    }
    if (
      kind.includes("DEBUG") ||
      kind === "DEBUG_WORKER" ||
      kind === "R3_REPEAT_FAILURE_CIRCUIT_BREAKER" ||
      kind === "R4_STRUCTURAL_BLOCKER" ||
      trigger.includes("MAX_ATTEMPTS") ||
      trigger.includes("STRUCTURAL")
    ) {
      return "DEBUG_WORKER";
    }
    return "GENERIC";
  }

  function priorityAccentClass(priority) {
    const p = Number(priority ?? 10);
    if (p <= 5) {
      return "priority-p0";
    }
    if (p <= 15) {
      return "priority-p1";
    }
    return "priority-p2";
  }

  function renderZone2Attention(state) {
    const listEl = document.getElementById("attention-list");
    const countEl = document.getElementById("attention-count");
    if (!listEl || !countEl) {
      return;
    }

    const queue = Array.isArray(state && state.attention_queue)
      ? [...state.attention_queue]
      : [];
    queue.sort((a, b) => {
      const pa = Number(a.priority ?? 50);
      const pb = Number(b.priority ?? 50);
      if (pa !== pb) {
        return pa - pb;
      }
      return String(a.created_at || "").localeCompare(String(b.created_at || ""));
    });

    countEl.textContent = String(queue.length);
    countEl.classList.toggle("zero", queue.length === 0);

    if (queue.length === 0) {
      listEl.innerHTML =
        '<div class="empty-state">No items in 🔔 Human Attention Needed queue.</div>';
      return;
    }

    const prsById = {};
    for (const pr of (state && state.prs) || []) {
      prsById[String(pr.pr_id).toUpperCase()] = pr;
    }

    listEl.innerHTML = "";
    for (const item of queue) {
      const category = classifyAttentionKind(item);
      const card = document.createElement("div");
      card.className = `attention-card ${priorityAccentClass(item.priority)}`;

      const esc = item.escalation || {};
      const prId = item.pr_id || esc.pr_id || "";
      const woId = item.wo_id || esc.wo_id || "";
      const prObj = prsById[String(prId).toUpperCase()] || null;
      const paConvId = prObj ? prObj.pa_conversation_id : "";

      const headerDiv = document.createElement("div");
      headerDiv.className = "attention-card-header";
      headerDiv.innerHTML = `
        <div class="attention-card-title">${escapeHtml(item.title || item.kind)}</div>
        <span class="badge badge-muted">P${escapeHtml(item.priority ?? 10)}</span>
      `;
      card.appendChild(headerDiv);

      const metaParts = [];
      if (prId) metaParts.push(`PR: ${prId}`);
      if (woId) metaParts.push(`WO: ${woId}`);
      if (esc.reason_code || esc.trigger_code) {
        metaParts.push(esc.reason_code || esc.trigger_code);
      }
      if (esc.summary || esc.reason) {
        metaParts.push(esc.summary || esc.reason);
      }
      if (metaParts.length > 0) {
        const metaDiv = document.createElement("div");
        metaDiv.className = "attention-card-meta";
        metaDiv.textContent = metaParts.join(" · ");
        card.appendChild(metaDiv);
      }

      let checkboxesContainer = null;
      const requestedFiles = Array.isArray(esc.requested_files)
        ? esc.requested_files
        : [];
      if (category === "ESCALATION_RESOLVE" && requestedFiles.length > 0) {
        checkboxesContainer = document.createElement("div");
        checkboxesContainer.className = "requested-files-list";
        for (const filePath of requestedFiles) {
          const label = document.createElement("label");
          label.className = "file-checkbox-label";
          const cb = document.createElement("input");
          cb.type = "checkbox";
          cb.checked = true;
          cb.value = filePath;
          label.appendChild(cb);
          const span = document.createElement("span");
          span.textContent = filePath;
          label.appendChild(span);
          checkboxesContainer.appendChild(label);
        }
        card.appendChild(checkboxesContainer);
      }

      const actionsDiv = document.createElement("div");
      actionsDiv.className = "attention-actions";

      if (category === "PLAN_APPROVAL") {
        const btnApprove = document.createElement("button");
        btnApprove.type = "button";
        btnApprove.className = "btn btn-primary btn-compact";
        btnApprove.textContent = "✅ Approve Plan";
        btnApprove.addEventListener("click", () => approvePrPlan(prId));
        actionsDiv.appendChild(btnApprove);

        const btnOpenPa = document.createElement("button");
        btnOpenPa.type = "button";
        btnOpenPa.className = "btn btn-compact";
        btnOpenPa.textContent = "💬 Open PA Thread";
        btnOpenPa.addEventListener("click", () => jumpToConversation(paConvId));
        actionsDiv.appendChild(btnOpenPa);
      } else if (category === "ESCALATION_RESOLVE") {
        const escId = item.escalation_id || esc.escalation_id || "";
        const btnApproveResume = document.createElement("button");
        btnApproveResume.type = "button";
        btnApproveResume.className = "btn btn-primary btn-compact";
        btnApproveResume.textContent = "✅ Approve & Resume";
        btnApproveResume.addEventListener("click", () => {
          const selected = checkboxesContainer
            ? Array.from(
                checkboxesContainer.querySelectorAll('input[type="checkbox"]:checked')
              ).map((el) => el.value)
            : requestedFiles;
          resolveEscalation(escId, "approve", selected);
        });
        actionsDiv.appendChild(btnApproveResume);

        const btnDeny = document.createElement("button");
        btnDeny.type = "button";
        btnDeny.className = "btn btn-danger btn-compact";
        btnDeny.textContent = "❌ Deny";
        btnDeny.addEventListener("click", () => resolveEscalation(escId, "deny"));
        actionsDiv.appendChild(btnDeny);
      } else if (category === "DEBUG_WORKER") {
        const btnDebug = document.createElement("button");
        btnDebug.type = "button";
        btnDebug.className = "btn btn-primary btn-compact";
        btnDebug.textContent = "🔬 Launch Interactive Debug";
        btnDebug.addEventListener("click", () => debugWorkOrder(woId));
        actionsDiv.appendChild(btnDebug);
      } else if (category === "GRADUATE_PR") {
        const btnGrad = document.createElement("button");
        btnGrad.type = "button";
        btnGrad.className = "btn btn-primary btn-compact";
        btnGrad.textContent = "🚀 Graduate PR";
        btnGrad.addEventListener("click", () => graduatePr(prId));
        actionsDiv.appendChild(btnGrad);
      } else {
        if (woId) {
          const btnDebug = document.createElement("button");
          btnDebug.type = "button";
          btnDebug.className = "btn btn-compact";
          btnDebug.textContent = "🔬 Launch Interactive Debug";
          btnDebug.addEventListener("click", () => debugWorkOrder(woId));
          actionsDiv.appendChild(btnDebug);
        }
        if (prId) {
          const btnOpenPa = document.createElement("button");
          btnOpenPa.type = "button";
          btnOpenPa.className = "btn btn-compact";
          btnOpenPa.textContent = "💬 Open PA Thread";
          btnOpenPa.addEventListener("click", () => jumpToConversation(paConvId));
          actionsDiv.appendChild(btnOpenPa);
        }
      }

      card.appendChild(actionsDiv);
      listEl.appendChild(card);
    }
  }

  function buildWorkOrderRow(wo) {
    const row = document.createElement("div");
    row.className = "wo-row";

    const topRow = document.createElement("div");
    topRow.className = "wo-row-top";
    topRow.innerHTML = `
      <div class="wo-id-title">
        <span class="wo-id-code">${escapeHtml(wo.wo_id)}</span>
        <span class="wo-title-text">${escapeHtml(wo.title)}</span>
      </div>
      <span class="status-pill ${statusClass(wo.status)}">${escapeHtml(wo.status)}</span>
    `;
    row.appendChild(topRow);

    const metaRow = document.createElement("div");
    metaRow.className = "wo-meta-row";

    const compBadge = document.createElement("span");
    compBadge.className = "badge badge-muted";
    compBadge.textContent = `${wo.complexity || "standard"} (${wo.model_tier || "inherit"})`;
    metaRow.appendChild(compBadge);

    const attemptsBadge = document.createElement("span");
    attemptsBadge.className = "badge badge-muted";
    attemptsBadge.textContent = `Attempt ${wo.attempts ?? 0}/${wo.max_attempts ?? 5}`;
    metaRow.appendChild(attemptsBadge);

    if (wo.receipt_id || wo.tree_hash) {
      const rcptBadge = document.createElement("span");
      rcptBadge.className = "receipt-badge";
      const shortHash = wo.tree_hash ? String(wo.tree_hash).slice(0, 8) : "";
      rcptBadge.textContent = `✓ ${wo.receipt_id || shortHash}`;
      rcptBadge.title = wo.tree_hash ? `Tree SHA-256: ${wo.tree_hash}` : "";
      metaRow.appendChild(rcptBadge);
    }

    for (const skill of wo.required_skills || []) {
      const skillPill = document.createElement("span");
      skillPill.className = "skill-pill";
      skillPill.textContent = `⚡ ${skill}`;
      metaRow.appendChild(skillPill);
    }

    row.appendChild(metaRow);

    const actionsRow = document.createElement("div");
    actionsRow.className = "wo-actions";

    const btnPeek = document.createElement("button");
    btnPeek.type = "button";
    btnPeek.className = "btn btn-compact";
    btnPeek.textContent = "👁️ Peek Worker";
    btnPeek.disabled = !wo.subagent_id;
    btnPeek.addEventListener("click", () => jumpToConversation(wo.subagent_id));
    actionsRow.appendChild(btnPeek);

    const btnDebug = document.createElement("button");
    btnDebug.type = "button";
    btnDebug.className = "btn btn-compact";
    btnDebug.textContent = "🔬 Debug";
    btnDebug.addEventListener("click", () => debugWorkOrder(wo.wo_id));
    actionsRow.appendChild(btnDebug);

    row.appendChild(actionsRow);
    return row;
  }

  function buildPrCard(pr) {
    const card = document.createElement("div");
    card.className = "pr-card";

    const headerTop = document.createElement("div");
    headerTop.className = "pr-header-top";
    headerTop.innerHTML = `
      <div class="pr-title-group">
        <span class="pr-id-code">${escapeHtml(pr.pr_id)}</span>
        <span class="pr-title-text">${escapeHtml(pr.title)}</span>
      </div>
      <span class="status-pill ${statusClass(pr.status)}">${escapeHtml(formatPrStatusBadge(pr))}</span>
    `;
    card.appendChild(headerTop);

    const branchLine = document.createElement("div");
    branchLine.className = "pr-branch-line";
    branchLine.textContent = `${pr.branch} → ${pr.base_branch}`;
    card.appendChild(branchLine);

    const badgesRow = document.createElement("div");
    badgesRow.className = "pr-badges-row";

    const charterBadge = document.createElement("span");
    const hashPrefix = pr.charter_hash ? String(pr.charter_hash).slice(0, 8) : "unlocked";
    charterBadge.className = `charter-badge ${pr.charter_locked ? "" : "unlocked"}`;
    charterBadge.textContent = pr.charter_locked
      ? `🔒 Charter by Chief (${hashPrefix})`
      : `🔓 Charter Unlocked`;
    badgesRow.appendChild(charterBadge);

    if (pr.latest_audit) {
      const auditBadge = document.createElement("span");
      const verdict = pr.latest_audit.verdict || "PENDING";
      auditBadge.className = `status-pill ${
        verdict === "APPROVED" ? "status-approved" : "status-changes-requested"
      }`;
      auditBadge.textContent = `Audit R${pr.latest_audit.audit_round || 1}: ${verdict}`;
      badgesRow.appendChild(auditBadge);
    }

    card.appendChild(badgesRow);

    const prActions = document.createElement("div");
    prActions.className = "pr-actions";

    const btnJumpPa = document.createElement("button");
    btnJumpPa.type = "button";
    btnJumpPa.className = "btn btn-compact";
    btnJumpPa.textContent = "💬 Jump to PA";
    btnJumpPa.disabled = !pr.pa_conversation_id;
    btnJumpPa.addEventListener("click", () => jumpToConversation(pr.pa_conversation_id));
    prActions.appendChild(btnJumpPa);

    const btnStartPr = document.createElement("button");
    btnStartPr.type = "button";
    btnStartPr.className = "btn btn-compact";
    btnStartPr.textContent = "▶️ Start PR";
    btnStartPr.addEventListener("click", () => startPr(pr.pr_id));
    prActions.appendChild(btnStartPr);

    if (String(pr.status).toUpperCase() === "PLANNED") {
      const btnApprovePlan = document.createElement("button");
      btnApprovePlan.type = "button";
      btnApprovePlan.className = "btn btn-primary btn-compact";
      btnApprovePlan.textContent = "✅ Approve Plan";
      btnApprovePlan.addEventListener("click", () => approvePrPlan(pr.pr_id));
      prActions.appendChild(btnApprovePlan);
    }

    const isAuditApproved =
      String(pr.status).toUpperCase() === "AUDIT_APPROVED" ||
      Boolean(pr.latest_audit && pr.latest_audit.verdict === "APPROVED");
    const btnGradPr = document.createElement("button");
    btnGradPr.type = "button";
    btnGradPr.className = "btn btn-primary btn-compact";
    btnGradPr.textContent = "🚀 Graduate PR";
    btnGradPr.disabled = !isAuditApproved || String(pr.status).toUpperCase() === "GRADUATED";
    btnGradPr.addEventListener("click", () => graduatePr(pr.pr_id));
    prActions.appendChild(btnGradPr);

    card.appendChild(prActions);

    const workOrders = Array.isArray(pr.work_orders) ? pr.work_orders : [];
    if (workOrders.length > 0) {
      const woList = document.createElement("div");
      woList.className = "wo-list";
      for (const wo of workOrders) {
        woList.appendChild(buildWorkOrderRow(wo));
      }
      card.appendChild(woList);
    }

    return card;
  }

  function renderZone3Dag(state) {
    const dagContainer = document.getElementById("dag-container");
    const prCountEl = document.getElementById("dag-pr-count");
    if (!dagContainer) {
      return;
    }

    const programmes = Array.isArray(state && state.programmes) ? state.programmes : [];
    const prs = Array.isArray(state && state.prs) ? state.prs : [];
    if (prCountEl) {
      prCountEl.textContent = `${prs.length} PR${prs.length === 1 ? "" : "s"}`;
    }

    if (programmes.length === 0 && prs.length === 0) {
      dagContainer.innerHTML =
        '<div class="empty-state">No Programme or Stacked PR specs found in this workspace.</div>';
      return;
    }

    dagContainer.innerHTML = "";

    for (const prog of programmes) {
      const progCard = document.createElement("div");
      progCard.className = "programme-card";
      progCard.innerHTML = `
        <div class="programme-header">
          <div class="programme-title">🏛️ ${escapeHtml(prog.title)} (${escapeHtml(prog.programme_id)})</div>
          <span class="status-pill ${statusClass(prog.status)}">${escapeHtml(prog.status)}</span>
        </div>
        <div class="programme-meta">
          <span class="badge badge-muted">VCS: ${escapeHtml(prog.vcs_mode)}</span>
          <span class="badge badge-muted">Memory: ${escapeHtml(prog.memory_mode)}</span>
          <span class="badge badge-muted">Mode: ${escapeHtml(prog.execution_mode)}</span>
        </div>
      `;
      dagContainer.appendChild(progCard);
    }

    for (const pr of prs) {
      dagContainer.appendChild(buildPrCard(pr));
    }
  }

  function renderFullState(state) {
    if (!state || state.ok === false) {
      return;
    }
    stateStore.latestState = state;
    renderZone1Header(state);
    renderZone2Attention(state);
    renderZone3Dag(state);
  }

  // --- Workspace & SSE Connection Management ---

  async function fetchWorkspaceState() {
    const qs = stateStore.activeWorkspace
      ? `?workspace=${encodeURIComponent(stateStore.activeWorkspace)}`
      : "";
    try {
      const resp = await fetch(`/api/state${qs}`);
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      renderFullState(data);
    } catch (_err) {
      // Ignore transient network errors; SSE stream will reconnect
    }
  }

  function connectEventStream() {
    if (stateStore.eventSource) {
      stateStore.eventSource.close();
      stateStore.eventSource = null;
    }
    const sseBadge = document.getElementById("badge-sse-status");
    const qs = stateStore.activeWorkspace
      ? `?workspace=${encodeURIComponent(stateStore.activeWorkspace)}`
      : "";
    if (typeof window.EventSource !== "function") {
      return;
    }
    const es = new EventSource(`/api/events${qs}`);
    stateStore.eventSource = es;

    es.addEventListener("state", (event) => {
      if (sseBadge) {
        sseBadge.textContent = "● Live SSE";
        sseBadge.classList.remove("disconnected");
      }
      try {
        const parsed = JSON.parse(event.data);
        renderFullState(parsed);
      } catch (_err) {
        // Ignore malformed frame
      }
    });

    es.onerror = () => {
      if (sseBadge) {
        sseBadge.textContent = "○ Reconnecting…";
        sseBadge.classList.add("disconnected");
      }
    };
  }

  function setActiveWorkspace(uriOrPath) {
    let candidate = "";
    if (Array.isArray(uriOrPath)) {
      candidate = String(uriOrPath[0] || "").trim();
    } else if (typeof uriOrPath === "string") {
      candidate = uriOrPath.trim();
    }
    if (!candidate) {
      return;
    }
    stateStore.activeWorkspace = candidate;
    const selectEl = document.getElementById("workspace-select");
    if (selectEl) {
      const hasOption = Array.from(selectEl.options).some((o) => o.value === candidate);
      if (!hasOption) {
        const opt = document.createElement("option");
        opt.value = candidate;
        opt.textContent = candidate.replace(/^file:\/\//, "");
        selectEl.appendChild(opt);
      }
      selectEl.value = candidate;
    }
    fetchWorkspaceState();
    connectEventStream();
  }

  async function initWorkspaces() {
    const selectEl = document.getElementById("workspace-select");
    try {
      const resp = await fetch("/api/workspaces");
      const data = await resp.json();
      const workspaces = Array.isArray(data.workspaces) ? data.workspaces : [];
      stateStore.workspaces = workspaces;

      if (selectEl) {
        selectEl.innerHTML = "";
        if (workspaces.length === 0) {
          const emptyOpt = document.createElement("option");
          emptyOpt.value = "";
          emptyOpt.textContent = "No enrolled repositories";
          selectEl.appendChild(emptyOpt);
        } else {
          for (const ws of workspaces) {
            const opt = document.createElement("option");
            opt.value = ws.repo_root || ws.uri;
            opt.textContent = `${ws.slug} (${ws.repo_root})`;
            selectEl.appendChild(opt);
          }
        }
      }

      const initialWs =
        data.active_workspace || (workspaces[0] && workspaces[0].repo_root) || "";
      if (initialWs) {
        setActiveWorkspace(initialWs);
      } else {
        await fetchWorkspaceState();
        connectEventStream();
      }
    } catch (_err) {
      await fetchWorkspaceState();
      connectEventStream();
    }
  }

  function bindUiControls() {
    const btnSync = document.getElementById("btn-sync");
    if (btnSync) {
      btnSync.addEventListener("click", () => triggerSync());
    }

    const btnMonitored = document.getElementById("btn-mode-monitored");
    if (btnMonitored) {
      btnMonitored.addEventListener("click", () =>
        updateModeOrModel({ mode: "monitored" })
      );
    }

    const btnAutonomous = document.getElementById("btn-mode-autonomous");
    if (btnAutonomous) {
      btnAutonomous.addEventListener("click", () =>
        updateModeOrModel({ mode: "autonomous" })
      );
    }

    const modelSelect = document.getElementById("architect-model-select");
    if (modelSelect) {
      modelSelect.addEventListener("change", (ev) => {
        if (ev.target && ev.target.value) {
          updateModeOrModel({ architect_model: ev.target.value });
        }
      });
    }

    const wsSelect = document.getElementById("workspace-select");
    if (wsSelect) {
      wsSelect.addEventListener("change", (ev) => {
        if (ev.target && ev.target.value) {
          setActiveWorkspace(ev.target.value);
        }
      });
    }

    if (
      window.sidecar &&
      typeof window.sidecar.onWorkspaceChange === "function"
    ) {
      window.sidecar.onWorkspaceChange((uri) => setActiveWorkspace(uri));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    bindUiControls();
    initWorkspaces();
  });
})();
