/**
 * Principal Architect Plugin (c) 2026 Matt McNeill
 * https://github.com/matthewmcneill/principal-architect-plugin
 * SPDX-License-Identifier: Apache-2.0
 *
 * Module: daemon/sidecars/pa_cockpit/ui/app.js
 *
 * Responsibility:
 *   Single-page AuxPane & Sidebar frontend controller for the Principal Architect
 *   Cockpit (`SPEC.md` §10.3, PR-04 Charter G2/R5). Synchronizes active repository
 *   workspaces with the Antigravity host bridge (`window.sidecar`), subscribes to
 *   live Server-Sent Events (`/api/events`) with `/api/state` HTTP fallback, and
 *   renders the three-zone operational cockpit interface.
 *
 * Component / Function Summary:
 *   DOM & Transport Utilities:
 *     - escapeHtml(raw): Escape HTML special characters for safe DOM interpolation.
 *     - showToast(message, isError): Render a transient status or error toast in Zone 1.
 *     - jumpToConversation(conversationId): Focus an agent thread in the host IDE sidebar.
 *     - postJson(endpoint, payload): Execute a JSON POST request against the Cockpit API.
 *   Mutation Actions:
 *     - triggerSync(): Reconcile VCS trailers, audits, and receipts via POST /api/sync.
 *     - updateModeOrModel(options): Switch execution mode or architect model via POST /api/mode.
 *     - approvePrPlan(prId): Record human plan approval via POST /api/pr/approve-plan.
 *     - resolveEscalation(escalationId, decision, requestedFiles): Approve or deny an escalation via POST /api/escalation/resolve.
 *     - startPr(prId): Launch or focus the Principal Architect session for a PR via POST /api/pr/start.
 *     - debugWorkOrder(woId): Spawn an interactive Tier 3b Debugger session via POST /api/wo/debug.
 *     - graduatePr(prId): Graduate an audit-approved PR via POST /api/pr/graduate.
 *   Zone 1 Header:
 *     - renderZone1Header(state): Update VCS/Memory badges, mode toggle, and architect model selector.
 *   Zone 2 Attention Banner:
 *     - classifyAttentionKind(item): Categorize an attention queue item into an actionable workflow kind.
 *     - priorityAccentClass(priority): Map numeric priority to a P0/P1/P2 border accent CSS class.
 *     - renderZone2Attention(state): Render the priority-ordered "🔔 Human Attention Needed" inbox.
 *   Zone 3 Active/Historical DAG:
 *     - statusClass(rawStatus): Normalize a PR or Work Order status into a CSS pill class.
 *     - formatPrStatusBadge(pr): Format the human-readable lifecycle and audit badge for a PR card.
 *     - buildWorkOrderRow(wo): Construct a DOM row for a single Work Order with receipt and skill pills.
 *     - buildProgrammeCard(prog, options): Construct a collapsible Programme summary card.
 *     - buildPrCard(pr, options): Construct a collapsible Stacked PR card with Charter lock and WO list.
 *     - renderZone3Dag(state): Partition and render Zone 3.1 Active Development and Zone 3.2 Historical & Merged DAGs.
 *     - renderFullState(state): Orchestrate a full re-render across Zones 1, 2, and 3.
 *   SSE Lifecycle & Workspace Initialization:
 *     - fetchWorkspaceState(): Fetch a point-in-time snapshot from GET /api/state.
 *     - connectEventStream(): Open and manage the EventSource connection to GET /api/events.
 *     - setActiveWorkspace(uriOrPath): Switch the active workspace and rebind state/SSE streams.
 *     - initWorkspaces(): Load enrolled workspaces from GET /api/workspaces on startup.
 *     - bindUiControls(): Attach DOM event listeners to Zone 1 controls and window.sidecar hooks.
 */

(function () {
  "use strict";

  /** In-memory reactive state store for the Cockpit AuxPane session. */
  const stateStore = {
    workspaces: [], // Enrolled repository metadata records from GET /api/workspaces.
    activeWorkspace: "", // Repository root path or file:// URI currently displayed.
    latestState: null, // Most recent workspace state payload from /api/state or SSE.
    eventSource: null, // Active EventSource instance subscribed to /api/events.
  };

  /**
   * Escape HTML special characters for safe DOM insertion.
   * @param {unknown} raw - Untrusted value to convert and escape.
   * @returns {string} HTML-escaped string safe for innerHTML interpolation.
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
   * @param {string} message - Notification text to display.
   * @param {boolean} [isError=false] - Whether to style the toast as an error alert.
   * @returns {void}
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
   * @param {string | null | undefined} conversationId - Target agent conversation UUID.
   * @returns {void}
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
   * @param {string} endpoint - Relative API path (e.g. "/api/mode").
   * @param {Record<string, unknown>} payload - Request body fields merged with active workspace.
   * @returns {Promise<Record<string, unknown>>} Parsed JSON response object on success.
   */
  async function postJson(endpoint, payload) {
    // --- Step 1: Merge active workspace context into request body ---
    const bodyObj = {
      workspace: stateStore.activeWorkspace || undefined,
      ...payload,
    };

    // --- Step 2: Dispatch HTTP POST request and parse JSON response ---
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bodyObj),
    });
    const data = await response.json().catch(() => ({ ok: false, error: "Invalid server response" }));

    // --- Step 3: Surface server error messages on non-2xx or ok=false responses ---
    if (!response.ok || data.ok === false) {
      throw new Error(data.error || `Request to ${endpoint} failed (${response.status})`);
    }
    return data;
  }

  // --- API Mutation Helpers (all 7 POST routes) ---

  /**
   * Trigger a VCS and state database reconciliation via POST /api/sync.
   * @returns {Promise<void>}
   */
  async function triggerSync() {
    try {
      const res = await postJson("/api/sync", {});
      showToast(`Synced state (audits: ${res.synced_audits ?? 0})`);
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  /**
   * Update execution mode ("monitored" | "autonomous") or architect model via POST /api/mode.
   * @param {Record<string, unknown>} options - Mode or model mutation payload.
   * @returns {Promise<void>}
   */
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

  /**
   * Approve a Planned PR's Part II Implementation Plan via POST /api/pr/approve-plan.
   * @param {string} prId - Target PR identifier (e.g. "PR-01").
   * @returns {Promise<void>}
   */
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

  /**
   * Resolve an open boundary or charter escalation via POST /api/escalation/resolve.
   * @param {string} escalationId - Escalation identifier (`esc_*`).
   * @param {"approve" | "deny"} decision - Resolution action to apply.
   * @param {string[]} [requestedFiles] - Subset of requested files approved for boundary expansion.
   * @returns {Promise<void>}
   */
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

  /**
   * Start or resume the Principal Architect session for a PR via POST /api/pr/start.
   * @param {string} prId - Target PR identifier (e.g. "PR-01").
   * @returns {Promise<void>}
   */
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

  /**
   * Launch an interactive Tier 3b Debugger session for a Work Order via POST /api/wo/debug.
   * @param {string} woId - Target Work Order identifier (e.g. "WO-01.1").
   * @returns {Promise<void>}
   */
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

  /**
   * Graduate an audit-approved PR into repository memory via POST /api/pr/graduate.
   * @param {string} prId - Target PR identifier (e.g. "PR-01").
   * @returns {Promise<void>}
   */
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

  /**
   * Map a raw status string to its corresponding CSS modifier class.
   * @param {string | null | undefined} rawStatus - Lifecycle status token.
   * @returns {string} CSS status modifier class name.
   */
  function statusClass(rawStatus) {
    const norm = String(rawStatus || "PENDING")
      .toLowerCase()
      .replace(/_/g, "-");
    if (norm === "merged") {
      return "status-graduated";
    }
    return `status-${norm}`;
  }

  /**
   * Format a concise status badge label for a Stacked PR card.
   * @param {Record<string, any>} pr - Serialized PR state record.
   * @returns {string} Formatted badge string with geometric status prefix.
   */
  function formatPrStatusBadge(pr) {
    // --- Step 1: Normalize status and optional GitHub PR number ---
    const st = String(pr.status || "PLANNED").toUpperCase();
    const ghNum = pr.github_pr ? ` #${pr.github_pr}` : "";
    const latestAudit = pr.latest_audit;

    // --- Step 2: Check terminal graduation and merge states ---
    if (st === "GRADUATED") {
      return `● Graduated${ghNum}`;
    }
    if (pr.is_merged) {
      return `● Merged${ghNum}`;
    }

    // --- Step 3: Check Cold-Firewall audit verdicts and staging states ---
    if (st === "AUDIT_APPROVED" || (latestAudit && latestAudit.verdict === "APPROVED")) {
      return `✓ Audit Approved${ghNum}`;
    }
    if (latestAudit && latestAudit.verdict === "CHANGES_REQUESTED") {
      return `! Changes Requested (R${latestAudit.audit_round || 1}/5)`;
    }
    if (st === "STAGED_FOR_AUDIT") {
      return `↑ Staged for Audit${ghNum}`;
    }
    if (pr.github_pr) {
      return `◌ Draft PR #${pr.github_pr} ↗`;
    }
    return `○ ${st}`;
  }

  /**
   * Render Zone 1 Header badges, execution mode toggle, and architect model dropdown.
   * @param {Record<string, any>} state - Workspace state payload from /api/state.
   * @returns {void}
   */
  function renderZone1Header(state) {
    // --- Step 1: Update VCS and Memory mode badges ---
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

    // --- Step 2: Synchronize segmented Monitored vs Autonomous mode buttons ---
    const execMode = env.execution_mode || "monitored";
    const btnMonitored = document.getElementById("btn-mode-monitored");
    const btnAutonomous = document.getElementById("btn-mode-autonomous");
    if (btnMonitored && btnAutonomous) {
      btnMonitored.classList.toggle("active", execMode === "monitored");
      btnAutonomous.classList.toggle("active", execMode === "autonomous");
    }

    // --- Step 3: Populate and select the active Architect model option ---
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

  /**
   * Classify an attention queue item into a UI action template category.
   * @param {Record<string, any>} item - Attention queue item with optional linked escalation.
   * @returns {"PLAN_APPROVAL" | "ESCALATION_RESOLVE" | "GRADUATE_PR" | "DEBUG_WORKER" | "GENERIC"} Action category.
   */
  function classifyAttentionKind(item) {
    // --- Step 1: Extract normalized kind and escalation trigger codes ---
    const kind = String(item.kind || "").toUpperCase();
    const esc = item.escalation || {};
    const trigger = String(esc.trigger_code || esc.reason_code || "").toUpperCase();

    // --- Step 2: Match plan approval, boundary/charter, graduation, and debug patterns ---
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

  /**
   * Map a numeric attention priority into a CSS border-accent class.
   * @param {number | null | undefined} priority - Numeric priority (lower is more urgent).
   * @returns {string} Priority CSS class ("priority-p0", "priority-p1", or "priority-p2").
   */
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

  /**
   * Render Zone 2 ("🔔 Human Attention Needed" inbox) sorted by priority and timestamp.
   * @param {Record<string, any>} state - Workspace state payload from /api/state.
   * @returns {void}
   */
  function renderZone2Attention(state) {
    // --- Step 1: Locate Zone 2 DOM containers and sort attention items by priority ---
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

    // --- Step 2: Update counter badge and handle empty queue state ---
    countEl.textContent = String(queue.length);
    countEl.classList.toggle("zero", queue.length === 0);

    if (queue.length === 0) {
      listEl.innerHTML =
        '<div class="empty-state">No open escalations or approvals pending.</div>';
      return;
    }

    // --- Step 3: Index PR objects by ID for quick conversation lookup ---
    const prsById = {};
    for (const pr of (state && state.prs) || []) {
      prsById[String(pr.pr_id).toUpperCase()] = pr;
    }

    // --- Step 4: Build an interactive card for each queued attention item ---
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

      // --- Step 5: Render file selection checkboxes for boundary/charter escalations ---
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

      // --- Step 6: Wire category-specific HITL action buttons ---
      const actionsDiv = document.createElement("div");
      actionsDiv.className = "attention-actions";

      if (category === "PLAN_APPROVAL") {
        const btnApprove = document.createElement("button");
        btnApprove.type = "button";
        btnApprove.className = "btn btn-primary btn-compact";
        btnApprove.textContent = "Approve Plan";
        btnApprove.addEventListener("click", () => approvePrPlan(prId));
        actionsDiv.appendChild(btnApprove);

        const btnOpenPa = document.createElement("button");
        btnOpenPa.type = "button";
        btnOpenPa.className = "btn btn-compact";
        btnOpenPa.textContent = "Open PA Thread";
        btnOpenPa.addEventListener("click", () => jumpToConversation(paConvId));
        actionsDiv.appendChild(btnOpenPa);
      } else if (category === "ESCALATION_RESOLVE") {
        const escId = item.escalation_id || esc.escalation_id || "";
        const btnApproveResume = document.createElement("button");
        btnApproveResume.type = "button";
        btnApproveResume.className = "btn btn-primary btn-compact";
        btnApproveResume.textContent = "Approve & Resume";
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
        btnDeny.textContent = "Deny";
        btnDeny.addEventListener("click", () => resolveEscalation(escId, "deny"));
        actionsDiv.appendChild(btnDeny);
      } else if (category === "DEBUG_WORKER") {
        const btnDebug = document.createElement("button");
        btnDebug.type = "button";
        btnDebug.className = "btn btn-primary btn-compact";
        btnDebug.textContent = "Launch Interactive Debug";
        btnDebug.addEventListener("click", () => debugWorkOrder(woId));
        actionsDiv.appendChild(btnDebug);
      } else if (category === "GRADUATE_PR") {
        const btnGrad = document.createElement("button");
        btnGrad.type = "button";
        btnGrad.className = "btn btn-primary btn-compact";
        btnGrad.textContent = "Graduate PR";
        btnGrad.addEventListener("click", () => graduatePr(prId));
        actionsDiv.appendChild(btnGrad);
      } else {
        if (woId) {
          const btnDebug = document.createElement("button");
          btnDebug.type = "button";
          btnDebug.className = "btn btn-compact";
          btnDebug.textContent = "Launch Interactive Debug";
          btnDebug.addEventListener("click", () => debugWorkOrder(woId));
          actionsDiv.appendChild(btnDebug);
        }
        if (prId) {
          const btnOpenPa = document.createElement("button");
          btnOpenPa.type = "button";
          btnOpenPa.className = "btn btn-compact";
          btnOpenPa.textContent = "Open PA Thread";
          btnOpenPa.addEventListener("click", () => jumpToConversation(paConvId));
          actionsDiv.appendChild(btnOpenPa);
        }
      }

      card.appendChild(actionsDiv);
      listEl.appendChild(card);
    }
  }

  /**
   * Build a DOM element representing a single Work Order row inside a PR card.
   * @param {Record<string, any>} wo - Serialized Work Order state record.
   * @returns {HTMLDivElement} Constructed `.wo-row` DOM element.
   */
  function buildWorkOrderRow(wo) {
    // --- Step 1: Render Work Order ID, title, and lifecycle status pill ---
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

    // --- Step 2: Render complexity, attempt counter, verification receipt, and required skill pills ---
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
      skillPill.textContent = skill;
      metaRow.appendChild(skillPill);
    }

    row.appendChild(metaRow);

    // --- Step 3: Wire Peek Worker and Interactive Debug action buttons ---
    const actionsRow = document.createElement("div");
    actionsRow.className = "wo-actions";

    const btnPeek = document.createElement("button");
    btnPeek.type = "button";
    btnPeek.className = "btn btn-compact";
    btnPeek.textContent = "Peek Worker";
    btnPeek.disabled = !wo.subagent_id;
    btnPeek.addEventListener("click", () => jumpToConversation(wo.subagent_id));
    actionsRow.appendChild(btnPeek);

    const btnDebug = document.createElement("button");
    btnDebug.type = "button";
    btnDebug.className = "btn btn-compact";
    btnDebug.textContent = "Debug";
    btnDebug.addEventListener("click", () => debugWorkOrder(wo.wo_id));
    actionsRow.appendChild(btnDebug);

    row.appendChild(actionsRow);
    return row;
  }

  /**
   * Build a collapsible Programme overview card for Zone 3.
   * @param {Record<string, any>} prog - Serialized Programme state record.
   * @param {{ collapsed?: boolean, historical?: boolean }} [options={}] - Display configuration.
   * @returns {HTMLDivElement} Constructed `.programme-card` DOM element.
   */
  function buildProgrammeCard(prog, options = {}) {
    // --- Step 1: Initialize collapsible card container and header elements ---
    const isCollapsed = Boolean(options.collapsed);
    const card = document.createElement("div");
    card.className =
      "programme-card collapsible" +
      (isCollapsed ? " collapsed" : "") +
      (options.historical ? " historical" : " active");

    const header = document.createElement("div");
    header.className = "programme-header";

    const titleGroup = document.createElement("div");
    titleGroup.className = "programme-title-group";

    const toggleIcon = document.createElement("span");
    toggleIcon.className = "pr-collapse-toggle";
    toggleIcon.innerHTML = isCollapsed ? "&#9654;" : "&#9660;";
    toggleIcon.setAttribute("aria-hidden", "true");
    titleGroup.appendChild(toggleIcon);

    const titleText = document.createElement("div");
    titleText.className = "programme-title";
    titleText.textContent = `${prog.title} (${prog.programme_id})`;
    titleGroup.appendChild(titleText);

    header.appendChild(titleGroup);

    const statusPill = document.createElement("span");
    statusPill.className = `status-pill ${statusClass(prog.status)}`;
    statusPill.textContent = prog.status;
    header.appendChild(statusPill);

    // --- Step 2: Bind click handler to toggle card collapse state ---
    header.addEventListener("click", (evt) => {
      if (evt.target.closest("button, a, select, input")) {
        return;
      }
      card.classList.toggle("collapsed");
      const nowCollapsed = card.classList.contains("collapsed");
      toggleIcon.innerHTML = nowCollapsed ? "&#9654;" : "&#9660;";
    });

    card.appendChild(header);

    // --- Step 3: Populate Programme metadata badges in the collapsible body ---
    const body = document.createElement("div");
    body.className = "programme-body";
    body.innerHTML = `
      <div class="programme-meta">
        <span class="badge badge-muted">VCS: ${escapeHtml(prog.vcs_mode)}</span>
        <span class="badge badge-muted">Memory: ${escapeHtml(prog.memory_mode)}</span>
        <span class="badge badge-muted">Mode: ${escapeHtml(prog.execution_mode)}</span>
        <span class="badge badge-muted">Model: ${escapeHtml(prog.architect_model)}</span>
      </div>
    `;
    card.appendChild(body);
    return card;
  }

  /**
   * Build a collapsible Stacked PR card containing Charter badges, actions, and Work Order rows.
   * @param {Record<string, any>} pr - Serialized Stacked PR state record.
   * @param {{ collapsed?: boolean }} [options={}] - Initial collapse configuration.
   * @returns {HTMLDivElement} Constructed `.pr-card` DOM element.
   */
  function buildPrCard(pr, options = {}) {
    // --- Step 1: Determine active vs historical styling and build collapsible header ---
    const isCollapsed = Boolean(options.collapsed);
    const isHistorical =
      Boolean(pr.is_merged) ||
      String(pr.status).toUpperCase() === "GRADUATED" ||
      String(pr.status).toUpperCase() === "CLOSED";

    const card = document.createElement("div");
    card.className =
      "pr-card collapsible" +
      (isCollapsed ? " collapsed" : "") +
      (isHistorical ? " historical" : " active");

    const headerTop = document.createElement("div");
    headerTop.className = "pr-header-top";

    const titleGroup = document.createElement("div");
    titleGroup.className = "pr-title-group";

    const toggleIcon = document.createElement("span");
    toggleIcon.className = "pr-collapse-toggle";
    toggleIcon.innerHTML = isCollapsed ? "&#9654;" : "&#9660;";
    toggleIcon.setAttribute("aria-hidden", "true");
    titleGroup.appendChild(toggleIcon);

    const prIdCode = document.createElement("span");
    prIdCode.className = "pr-id-code";
    prIdCode.textContent = pr.pr_id;
    titleGroup.appendChild(prIdCode);

    const prTitleText = document.createElement("span");
    prTitleText.className = "pr-title-text";
    prTitleText.textContent = pr.title;
    titleGroup.appendChild(prTitleText);

    headerTop.appendChild(titleGroup);

    // --- Step 2: Populate right-hand summary badges (GitHub PR #, WO count, status pill) ---
    const rightBadges = document.createElement("div");
    rightBadges.className = "pr-header-right-badges";

    if (pr.github_pr) {
      const ghBadge = document.createElement("span");
      ghBadge.className = "badge badge-muted";
      ghBadge.textContent = `#${pr.github_pr}`;
      rightBadges.appendChild(ghBadge);
    }

    const workOrders = Array.isArray(pr.work_orders) ? pr.work_orders : [];
    if (workOrders.length > 0) {
      const woCountBadge = document.createElement("span");
      woCountBadge.className = "badge badge-muted";
      woCountBadge.textContent = `${workOrders.length} WO${workOrders.length === 1 ? "" : "s"}`;
      rightBadges.appendChild(woCountBadge);
    }

    const statusBadge = document.createElement("span");
    statusBadge.className = `status-pill ${statusClass(pr.is_merged ? "merged" : pr.status)}`;
    statusBadge.textContent = formatPrStatusBadge(pr);
    rightBadges.appendChild(statusBadge);

    headerTop.appendChild(rightBadges);

    headerTop.addEventListener("click", (evt) => {
      if (evt.target.closest("button, a, select, input")) {
        return;
      }
      card.classList.toggle("collapsed");
      const nowCollapsed = card.classList.contains("collapsed");
      toggleIcon.innerHTML = nowCollapsed ? "&#9654;" : "&#9660;";
    });

    card.appendChild(headerTop);

    // --- Step 3: Build card body with branch topology, Charter lock badge, and audit verdict ---
    const cardBody = document.createElement("div");
    cardBody.className = "pr-card-body";

    const branchLine = document.createElement("div");
    branchLine.className = "pr-branch-line";
    branchLine.textContent = `${pr.branch} → ${pr.base_branch}`;
    cardBody.appendChild(branchLine);

    const badgesRow = document.createElement("div");
    badgesRow.className = "pr-badges-row";

    const charterBadge = document.createElement("span");
    const hashPrefix = pr.charter_hash ? String(pr.charter_hash).slice(0, 8) : "unlocked";
    charterBadge.className = `charter-badge ${pr.charter_locked ? "" : "unlocked"}`;
    charterBadge.textContent = pr.charter_locked
      ? `Charter Locked (${hashPrefix})`
      : `Charter Unlocked`;
    charterBadge.title = pr.charter_locked
      ? `🔒 Charter by Chief (${pr.charter_hash})`
      : "Part I PR Charter is unlocked";
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

    cardBody.appendChild(badgesRow);

    // --- Step 4: Wire PR-level lifecycle action buttons (Jump to PA, Start, Approve Plan, Graduate) ---
    const prActions = document.createElement("div");
    prActions.className = "pr-actions";

    const btnJumpPa = document.createElement("button");
    btnJumpPa.type = "button";
    btnJumpPa.className = "btn btn-compact";
    btnJumpPa.textContent = "Jump to PA";
    btnJumpPa.disabled = !pr.pa_conversation_id;
    btnJumpPa.addEventListener("click", () => jumpToConversation(pr.pa_conversation_id));
    prActions.appendChild(btnJumpPa);

    const btnStartPr = document.createElement("button");
    btnStartPr.type = "button";
    btnStartPr.className = "btn btn-compact";
    btnStartPr.textContent = "Start PR";
    btnStartPr.addEventListener("click", () => startPr(pr.pr_id));
    prActions.appendChild(btnStartPr);

    if (String(pr.status).toUpperCase() === "PLANNED") {
      const btnApprovePlan = document.createElement("button");
      btnApprovePlan.type = "button";
      btnApprovePlan.className = "btn btn-primary btn-compact";
      btnApprovePlan.textContent = "Approve Plan";
      btnApprovePlan.addEventListener("click", () => approvePrPlan(pr.pr_id));
      prActions.appendChild(btnApprovePlan);
    }

    const isAuditApproved =
      String(pr.status).toUpperCase() === "AUDIT_APPROVED" ||
      Boolean(pr.latest_audit && pr.latest_audit.verdict === "APPROVED");
    const btnGradPr = document.createElement("button");
    btnGradPr.type = "button";
    btnGradPr.className = "btn btn-primary btn-compact";
    btnGradPr.textContent = "Graduate PR";
    btnGradPr.disabled = !isAuditApproved || String(pr.status).toUpperCase() === "GRADUATED";
    btnGradPr.addEventListener("click", () => graduatePr(pr.pr_id));
    prActions.appendChild(btnGradPr);

    cardBody.appendChild(prActions);

    // --- Step 5: Append child Work Order rows ---
    if (workOrders.length > 0) {
      const woList = document.createElement("div");
      woList.className = "wo-list";
      for (const wo of workOrders) {
        woList.appendChild(buildWorkOrderRow(wo));
      }
      cardBody.appendChild(woList);
    }

    card.appendChild(cardBody);
    return card;
  }

  /**
   * Render Zone 3 (Programme -> Stacked PR -> Work Order DAG) partitioned into Active and Historical sections.
   * @param {Record<string, any>} state - Workspace state payload from /api/state.
   * @returns {void}
   */
  function renderZone3Dag(state) {
    // --- Step 1: Validate DOM container and handle empty workspace state ---
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

    // --- Step 2: Partition PRs into Active Development vs Historical & Merged ---
    const activePrs = [];
    const historicalPrs = [];

    for (const pr of prs) {
      const isHistorical =
        Boolean(pr.is_merged) ||
        String(pr.status).toUpperCase() === "GRADUATED" ||
        String(pr.status).toUpperCase() === "CLOSED";
      if (isHistorical) {
        historicalPrs.push(pr);
      } else {
        activePrs.push(pr);
      }
    }

    // Active PRs: maintain forward stack/dependency order (PR-01 -> PR-02 -> PR-03...)
    // Historical PRs: sorted in REVERSE CHRONOLOGICAL ORDER (most recent first: PR-05 -> PR-04 -> ...)
    historicalPrs.sort((a, b) => {
      if (b.github_pr && a.github_pr && b.github_pr !== a.github_pr) {
        return b.github_pr - a.github_pr;
      }
      if (b.approved_at && a.approved_at && b.approved_at !== a.approved_at) {
        return b.approved_at.localeCompare(a.approved_at);
      }
      return b.pr_id.localeCompare(a.pr_id, undefined, { numeric: true });
    });

    // --- Step 3: Render Zone 3.1 Active Development section (expanded by default) ---
    const activeSection = document.createElement("div");
    activeSection.className = "dag-section active-dev-section";

    const activeHeader = document.createElement("div");
    activeHeader.className = "dag-section-header";
    activeHeader.innerHTML = `
      <div class="dag-section-title">
        <span>Active Development</span>
        <span class="badge ${activePrs.length > 0 ? "badge-live" : "badge-muted"}">${activePrs.length} Active</span>
      </div>
    `;
    activeSection.appendChild(activeHeader);

    // Active Programmes
    for (const prog of programmes) {
      const isProgActive =
        String(prog.status).toUpperCase() !== "COMPLETED" &&
        String(prog.status).toUpperCase() !== "ARCHIVED";
      if (isProgActive) {
        activeSection.appendChild(buildProgrammeCard(prog, { collapsed: false }));
      }
    }

    if (activePrs.length === 0) {
      const emptyActive = document.createElement("div");
      emptyActive.className = "empty-state";
      emptyActive.textContent = "No active PRs in progress. All changes are graduated or merged.";
      activeSection.appendChild(emptyActive);
    } else {
      for (const pr of activePrs) {
        // Active PRs are EXPANDED by default
        activeSection.appendChild(buildPrCard(pr, { collapsed: false }));
      }
    }
    dagContainer.appendChild(activeSection);

    // --- Step 4: Render Zone 3.2 Historical & Merged section (collapsed by default) ---
    const completedProgs = programmes.filter(
      (p) =>
        String(p.status).toUpperCase() === "COMPLETED" ||
        String(p.status).toUpperCase() === "ARCHIVED"
    );

    if (historicalPrs.length > 0 || completedProgs.length > 0) {
      const histSection = document.createElement("div");
      histSection.className = "dag-section historical-section";

      const histHeader = document.createElement("div");
      histHeader.className = "dag-section-header clickable";
      histHeader.innerHTML = `
        <div class="dag-section-title">
          <span class="section-collapse-icon" aria-hidden="true">&#9660;</span>
          <span>Historical &amp; Merged</span>
          <span class="badge badge-muted">${historicalPrs.length} PR${historicalPrs.length === 1 ? "" : "s"}</span>
        </div>
      `;

      const histList = document.createElement("div");
      histList.className = "historical-list";

      // Completed programmes in history (collapsed by default)
      for (const prog of completedProgs) {
        histList.appendChild(buildProgrammeCard(prog, { collapsed: true, historical: true }));
      }

      // Historical PRs (collapsed by default in reverse chronological order)
      for (const pr of historicalPrs) {
        histList.appendChild(buildPrCard(pr, { collapsed: true }));
      }

      histHeader.addEventListener("click", () => {
        histList.classList.toggle("collapsed");
        const isCollapsed = histList.classList.contains("collapsed");
        const icon = histHeader.querySelector(".section-collapse-icon");
        if (icon) {
          icon.innerHTML = isCollapsed ? "&#9654;" : "&#9660;";
        }
      });

      histSection.appendChild(histHeader);
      histSection.appendChild(histList);
      dagContainer.appendChild(histSection);
    }
  }

  /**
   * Coordinate a complete re-render across Zones 1, 2, and 3 when a new state snapshot arrives.
   * @param {Record<string, any>} state - Workspace state payload.
   * @returns {void}
   */
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

  /**
   * Fetch the current workspace state snapshot from GET /api/state and render it.
   * @returns {Promise<void>}
   */
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

  /**
   * Subscribe to the live Server-Sent Events stream at GET /api/events for the active workspace.
   * @returns {void}
   */
  function connectEventStream() {
    // --- Step 1: Close any prior EventSource connection ---
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

    // --- Step 2: Open new EventSource and bind state frame & error listeners ---
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

  /**
   * Switch the active workspace URI or path, sync the selector dropdown, and refresh state/SSE.
   * @param {string | string[]} uriOrPath - Workspace URI array from host bridge or path string.
   * @returns {void}
   */
  function setActiveWorkspace(uriOrPath) {
    // --- Step 1: Normalize workspace candidate from string or array ---
    let candidate = "";
    if (Array.isArray(uriOrPath)) {
      candidate = String(uriOrPath[0] || "").trim();
    } else if (typeof uriOrPath === "string") {
      candidate = uriOrPath.trim();
    }
    if (!candidate) {
      return;
    }

    // --- Step 2: Update stateStore and ensure option exists in workspace dropdown ---
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

    // --- Step 3: Trigger immediate state fetch and reconnect SSE stream ---
    fetchWorkspaceState();
    connectEventStream();
  }

  /**
   * Load enrolled repositories from GET /api/workspaces and initialize the active workspace view.
   * @returns {Promise<void>}
   */
  async function initWorkspaces() {
    // --- Step 1: Fetch enrolled workspaces list from Cockpit backend ---
    const selectEl = document.getElementById("workspace-select");
    try {
      const resp = await fetch("/api/workspaces");
      const data = await resp.json();
      const workspaces = Array.isArray(data.workspaces) ? data.workspaces : [];
      stateStore.workspaces = workspaces;

      // --- Step 2: Populate the workspace selector dropdown ---
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

      // --- Step 3: Activate initial workspace and start SSE stream ---
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

  /**
   * Bind DOM event listeners for Zone 1 controls and subscribe to host workspace changes.
   * @returns {void}
   */
  function bindUiControls() {
    // --- Step 1: Bind Sync button and Monitored/Autonomous mode toggle buttons ---
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

    // --- Step 2: Bind Architect model and Workspace selector dropdowns ---
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

    // --- Step 3: Subscribe to Antigravity host workspace changes via window.sidecar ---
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
