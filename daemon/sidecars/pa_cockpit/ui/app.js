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
 *   renders the three-zone operational cockpit interface using native Antigravity
 *   Google Symbols wght300 SVG iconography and keyframe animations.
 *
 * Exported API Summary (Component / Function Summary):
 *   DOM, Icon & Transport Utilities:
 *     - escapeHtml(raw): Escape HTML special characters for safe DOM interpolation.
 *     - iconSvg(name, size, extraClass): Render an inline Antigravity Google Symbol wght300 SVG icon.
 *     - statusDotHtml(ping): Render an Antigravity AttentionDot / live status dot with optional ping animation.
 *     - statusIconFor(rawStatus): Map a lifecycle status token to its corresponding Antigravity SVG icon.
 *     - showToast(message, isError): Render a transient status or error toast in Zone 1.
 *     - isOpenableConversationId(conversationId): Check whether a conversation ID is a real IDE thread vs synthetic fallback.
 *     - jumpToConversation(conversationId): Focus an agent thread in the host IDE sidebar.
 *     - buildSpecLinks(links): Build an inline row of clickable spec-file preview anchors.
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
 *     - formatPrStatusBadge(pr): Format the SVG-badged lifecycle and audit pill HTML for a PR card.
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
    lastRenderedStateJson: "", // Serialized JSON of last rendered state to skip no-op DOM rebuilds.
    eventSource: null, // Active EventSource instance subscribed to /api/events.
    prCollapsedOverrides: new Map(), // User-toggled collapse state keyed by pr_id.
    programmeCollapsedOverrides: new Map(), // User-toggled collapse state keyed by programme_id.
    historicalSectionCollapsed: false, // User-toggled collapse state for the Historical & Merged section.
  };

  /**
   * Canonical Antigravity Google Symbols wght300 24px SVG path data (`viewBox="0 -960 960 960"`).
   * Matches `agent_ui_toolkit/src/icons/generated/*.tsx` and `LoadingSpinner.tsx`.
   */
  const GOOGLE_SYMBOL_PATHS = {
    progress_activity:
      "M332.55-129.9q-69.29-29.9-121.02-81.63T129.9-332.55T100-480.35t29.96-147.5t81.58-120.61t121.04-81.58T480-860q12.75,0 21.37,8.63T510-829.99t-8.62,21.37T480-800q-133,0-226.5,93.5T160-480t93.5,226.5T480-160t226.5-93.5T800-480q0-12.77 8.63-21.38T830.01-510t21.37,8.62T860-480q0,77.99-29.96,147.42T748.46-211.54T627.85-129.96T480.35-100t-147.8-29.9Z",
    check_circle:
      "M423.23-309.85L692.15-578.77L650-620.92L423.23-394.15l-114-114L267.08-466L423.23-309.85ZM480.07-100q-78.84,0-148.2-29.92T211.18-211.13T129.93-331.76T100-479.93t29.92-148.2t81.21-120.68t120.63-81.25T479.93-860t148.2,29.92t120.68,81.21t81.25,120.63T860-480.07t-29.92,148.2T748.87-211.18T628.24-129.93T480.07-100ZM480-160q134,0 227-93t93-227T707-707T480-800T253-707T160-480t93,227t227,93Z",
    verified:
      "M352.46-85.39L281.08-205.69L145.54-235.39l13.23-139.54L66.93-480l91.85-105.08L145.54-724.61l135.54-29.69l71.38-120.31L480-820.46l127.54-54.15l71.38,120.31l135.54,29.69L801.23-585.08L893.07-480L801.23-374.92l13.23,139.54L678.92-205.69L607.54-85.39L480-139.54L352.46-85.39ZM378-162l102-43.23L583.23-162L640-258l110-25.23L740-396l74-84l-74-85.23L750-678L640-702l-58-96L480-754.77L376.77-798L320-702L210-678l10,112.77L146-480l74,84L210-282l110,24l58,96ZM438-351.85L650.15-564L608-607.38l-170,170l-86-84.77L309.85-480L438-351.85Z",
    chevron_right:
      "M517.85-480l-184-184L376-706.15L602.15-480L376-253.85L333.85-296l184-184Z",
    refresh:
      "M481.54-180q-125.62,0-212.81-87.17T181.54-479.94t87.19-212.83T481.54-780q70.15,0 132.77,31.19t104.15,88.04V-780h60v244.61H533.85v-60h158q-31.62-57.92-87.69-91.27T481.54-720q-100,0-170,70t-70,170t70,170t170,70q77,0 139-44t87-116h63.23Q743.54-302.08 663.5-241.04T481.54-180Z",
    lock:
      "M252.31-100q-29.92,0-51.11-21.19T180-172.31V-547.69q0-29.92 21.19-51.11T252.31-620H300v-80q0-74.92 52.54-127.46T480-880t127.46,52.54T660-700v80h47.69q29.92,0 51.11,21.19T780-547.69v375.38q0,29.92-21.19,51.11T707.69-100H252.31Zm0-60H707.69q5.39,0 8.85-3.46t3.46-8.85V-547.69q0-5.39-3.46-8.85T707.69-560H252.31q-5.39,0-8.85,3.46T240-547.69v375.38q0,5.39 3.46,8.85t8.85,3.46ZM529.58-310.42Q550-330.85 550-360t-20.42-49.58T480-430t-49.58,20.42T410-360t20.42,49.58T480-290t49.58-20.42ZM360-620H600v-80q0-50-35-85t-85-35t-85,35t-35,85v80Z",
    lock_open:
      "M252.31-620H600v-80q0-50-35-85t-85-35t-85,35t-35,85H300q0-74.92 52.54-127.46T480-880t127.46,52.54T660-700v80h47.69q29.92,0 51.11,21.19T780-547.69v375.38q0,29.92-21.19,51.11T707.69-100H252.31q-29.92,0-51.11-21.19T180-172.31V-547.69q0-29.92 21.19-51.11T252.31-620Zm0,460H707.69q5.39,0 8.85-3.46t3.46-8.85V-547.69q0-5.39-3.46-8.85T707.69-560H252.31q-5.39,0-8.85,3.46T240-547.69v375.38q0,5.39 3.46,8.85t8.85,3.46ZM529.58-310.42Q550-330.85 550-360t-20.42-49.58T480-430t-49.58,20.42T410-360t20.42,49.58T480-290t49.58-20.42Z",
    error:
      "M502.92-300.15q9.38-9.38 9.38-22.92T502.92-346T480-355.38T457.08-346t-9.38,22.92t9.38,22.92T480-290.77t22.92-9.38ZM450-436.92h60v-240H450v240ZM480.07-100q-78.84,0-148.2-29.92T211.18-211.13T129.93-331.76T100-479.93t29.92-148.2t81.21-120.68t120.63-81.25T479.93-860t148.2,29.92t120.68,81.21t81.25,120.63T860-480.07t-29.92,148.2T748.87-211.18T628.24-129.93T480.07-100ZM480-160q134,0 227-93t93-227T707-707T480-800T253-707T160-480t93,227t227,93Z",
    warning:
      "M74.62-140L480-840L885.38-140H74.62ZM178-200H782L480-720L178-200Zm324.92-57.08q9.38-9.38 9.38-22.92t-9.38-22.92T480-312.31t-22.92,9.38T447.69-280t9.38,22.92T480-247.69t22.92-9.38ZM450-352.31h60v-200H450v200Z",
    cancel:
      "M336-293.85l144-144l144,144L666.15-336l-144-144l144-144L624-666.15l-144,144l-144-144L293.85-624l144,144l-144,144L336-293.85ZM480.07-100q-78.84,0-148.2-29.92T211.18-211.13T129.93-331.76T100-479.93t29.92-148.2t81.21-120.68t120.63-81.25T479.93-860t148.2,29.92t120.68,81.21t81.25,120.63T860-480.07t-29.92,148.2T748.87-211.18T628.24-129.93T480.07-100ZM480-160q134,0 227-93t93-227T707-707T480-800T253-707T160-480t93,227t227,93Z",
    pending:
      "M315.38-444.57Q330-459.14 330-479.95t-14.57-35.43T280.05-530t-35.43,14.57T230-480.05t14.57,35.43T279.95-430t35.43-14.57Zm200,0Q530-459.14 530-479.95t-14.57-35.43T480.05-530t-35.43,14.57T430-480.05t14.57,35.43T479.95-430t35.43-14.57Zm200,0Q730-459.14 730-479.95t-14.57-35.43T680.05-530t-35.43,14.57T630-480.05t14.57,35.43T679.95-430t35.43-14.57ZM480.07-100q-78.84,0-148.2-29.92T211.18-211.13T129.93-331.76T100-479.93t29.92-148.2t81.21-120.68t120.63-81.25T479.93-860t148.2,29.92t120.68,81.21t81.25,120.63T860-480.07t-29.92,148.2T748.87-211.18T628.24-129.93T480.07-100ZM480-160q134,0 227-93t93-227T707-707T480-800T253-707T160-480t93,227t227,93Z",
    play_arrow:
      "M340-236.16V-723.84L723.07-480L340-236.16ZM400-346L610.77-480L400-614v268Z",
    rocket_launch:
      "M216.77-535.15l88,37.23q16.31-32.62 34.77-63.04t40.69-59.89l-58.69-11.38q-3.08-0.77-5.96,0.19t-5.19,3.27l-93.62,93.62Zm135.85,74.92l113.62,113q44.69-18.69 92.69-51.69t91.15-76.15q67.31-67.31 104.11-146.65T790.61-785q-83.92-0.38-163.39,36.42T480.46-644.46q-43.15,43.15-76.15,91.35t-51.69,92.88ZM524.92-589.61q0-29.08 20.31-49.38t49.88-20.31T645-639t20.31,49.38T645-540.23t-49.88,20.31t-49.88-20.31t-20.31-49.38Zm15.84,378.85l93.62-93.62q2.31-2.31 3.27-5.19t0.19-5.96l-11.38-58.69Q597-352 566.58-333.85t-63.04,34.46l37.23,88.62ZM845.31-839.92q12.85,115.61-27.35,219.15T685.69-425.15q-1.92,1.92-3.46,3.46t-3.46,3.46l18.08,90.54q3.62,18.08-1.62,35.15t-18.08,29.92L520.31-106.16L445.15-282.77L288.39-439.54L111.77-515.08L267.62-671.54q12.85-12.85 30.23-18.27t35.46-1.81l91.31,18.46q1.92-1.92 3.27-3.46t3.27-3.46q92.08-92.08 195.31-132.38t218.84-27.46Z",
    bug_report:
      "M480-200q66,0 113-47t47-113V-520q0-66-47-113T480-680T367-633T320-520v160q0,66 47,113t113,47ZM406.15-330H553.85v-60H406.15v60Zm0-160H553.85v-60H406.15v60ZM480-140q-59.61,0-110.11-29.31T289.69-250H180v-60h87.08q-6.08-24.62-6.58-49.81T260-410H180v-60h80q0-25.39 0.12-50.58T267.08-570H180v-60H289.69q14.38-24.54 34-44.73t44.92-34.04l-67.85-69.08l41.38-41.38L427.39-734q25.69-7.85 52-7.85t52,7.85l87.23-85.23L660-777.85l-69.08,69.08q25.31,13.85 45.15,33.73T670.31-630H780v60H692.92q6.85,24.23 6.96,49.42T700-470h80v60H700q0,25-0.5,50.19T692.92-310H780v60H670.31q-29.69,51.38-80.19,80.69T480-140Z",
    chat:
      "M250-410H550v-60H250v60Zm0-120H710v-60H250v60Zm0-120H710v-60H250v60ZM100-118.46V-787.69Q100-818 121-839t51.31-21H787.69Q818-860 839-839t21,51.31v455.38Q860-302 839-281t-51.31,21H241.54L100-118.46ZM216-320H787.69q4.62,0 8.46-3.85t3.85-8.46V-787.69q0-4.62-3.85-8.46T787.69-800H172.31q-4.62,0-8.46,3.85T160-787.69v523.08L216-320Z",
    visibility:
      "M595.58-384.51q47.5-47.59 47.5-115.58T595.49-615.58t-115.58-47.5T364.42-615.49t-47.5,115.58t47.59,115.49t115.58,47.5t115.49-47.59ZM403.5-423.5Q372-455 372-500t31.5-76.5T480-608t76.5,31.5T588-500t-31.5,76.5T480-392t-76.5-31.5ZM228.62-296.12Q115.16-372.23 61.54-500q53.62-127.77 167.02-203.88T479.95-780t251.44,76.11T898.46-500Q844.84-372.23 731.44-296.12T480.05-220T228.62-296.12ZM687.5-339.5Q782-399 832-500Q782-601 687.5-660.5T480-720T272.5-660.5T128-500q50,101 144.5,160.5T480-280t207.5-59.5Z",
    commit:
      "M356.54-335.5q-52-45.5-64.46-114.5H100v-60H292.08q12.46-69 64.46-114.5T480-670t123.65,45.5T667.92-510H860v60H667.92q-12.08,69-64.27,114.5T480-290T356.54-335.5ZM480-350q53.85,0 91.92-38.08T610-480t-38.08-91.92T480-610t-91.92,38.08T350-480t38.08,91.92T480-350Z",
    call_split:
      "M450-180V-467.85l-210-210V-560H180V-780H400v60H282.15L510-492.15V-180H450ZM580.15-536.77l-43.38-43.38L677.85-720H560v-60H780v220H720V-677.85L580.15-536.77Z",
    description:
      "M320-240h320v-60H320v60Zm0-160h320v-60H320v60ZM220-80q-24.75,0-42.37-17.63T160-140v-680q0-24.75,17.63-42.38T220-880h340l240,240v500q0,24.75-17.63,42.37T740-80H220Zm310-530v-210H220v680h520v-470H530ZM220-820v210V-820v680V-820Z",
  };

  /**
   * Render an inline Google Symbol SVG matching Antigravity's `GoogleSymbol.tsx` / `LoadingSpinner.tsx`.
   * @param {keyof typeof GOOGLE_SYMBOL_PATHS} name - Google Symbol identifier.
   * @param {number} [size=12] - Icon width and height in pixels.
   * @param {string} [extraClass=""] - Optional CSS class names (e.g. "animate-spin").
   * @returns {string} SVG element markup string.
   */
  function iconSvg(name, size = 12, extraClass = "") {
    const pathData = GOOGLE_SYMBOL_PATHS[name] || GOOGLE_SYMBOL_PATHS.pending;
    const cls = extraClass ? `ag-icon ${extraClass}` : "ag-icon";
    return `<svg class="${cls}" width="${size}" height="${size}" viewBox="0 -960 960 960" aria-hidden="true"><path d="${pathData}"/></svg>`;
  }

  /**
   * Render an Antigravity `AttentionDot` / live status indicator dot.
   * @param {boolean} [ping=false] - Whether to include the `animate-unread-ping` pulse ring.
   * @returns {string} HTML markup for the status dot.
   */
  function statusDotHtml(ping = false) {
    const pingSpan = ping
      ? '<span class="ag-status-dot-ping animate-unread-ping"></span>'
      : "";
    return `<span class="ag-status-dot" aria-hidden="true"><span class="ag-status-dot-core"></span>${pingSpan}</span>`;
  }

  /**
   * Select the canonical Antigravity status SVG icon for a lifecycle status string.
   * @param {string | null | undefined} rawStatus - Lifecycle status token.
   * @returns {string} Inline SVG markup (`check_circle`, spinning `progress_activity`, `verified`, `error`, or `pending`).
   */
  function statusIconFor(rawStatus) {
    const norm = String(rawStatus || "PENDING").toUpperCase();
    if (norm === "APPROVED" || norm === "COMPLETED" || norm === "AUDIT_APPROVED") {
      return iconSvg("check_circle", 12);
    }
    if (norm === "GRADUATED" || norm === "MERGED") {
      return iconSvg("verified", 12);
    }
    if (norm === "IN_PROGRESS" || norm === "RUNNING" || norm === "STAGED_FOR_AUDIT") {
      return iconSvg("progress_activity", 12, "animate-spin");
    }
    if (norm === "BLOCKED" || norm === "ESCALATED" || norm === "CHANGES_REQUESTED") {
      return iconSvg("error", 12);
    }
    return iconSvg("pending", 12);
  }

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
   * Determine whether a conversation ID represents a real, openable IDE conversation
   * rather than an empty string or a synthetic headless/offline fallback ID (`headless-*`, `ls-*`).
   * @param {string | null | undefined} conversationId - Candidate conversation ID.
   * @returns {boolean} True when the ID can be opened via `window.sidecar.ui.toggleConversation`.
   */
  function isOpenableConversationId(conversationId) {
    const raw = String(conversationId || "").trim();
    if (!raw) {
      return false;
    }
    return !raw.startsWith("headless-") && !raw.startsWith("ls-");
  }

  /**
   * Focus/open an agent conversation in the Antigravity IDE sidebar when available.
   * @param {string | null | undefined} conversationId - Target agent conversation UUID.
   * @returns {void}
   */
  function jumpToConversation(conversationId) {
    if (!isOpenableConversationId(conversationId)) {
      showToast("No active IDE conversation is bound to this target.", true);
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
   * Build an inline spec-file links row for Programme, PR, or Work Order cards.
   * Each non-null entry in `links` produces a small clickable anchor with a document icon.
   * @param {Array<{ label: string, filePath: string | null | undefined }>} links - File link specs.
   * @returns {HTMLDivElement} DOM element containing the spec link anchors.
   */
  function buildSpecLinks(links) {
    const row = document.createElement("div");
    row.className = "spec-links";
    for (const { label, filePath } of links) {
      if (!filePath) {
        continue;
      }
      const a = document.createElement("a");
      a.className = "btn btn-spec-link";
      a.href = `/api/preview?file=${encodeURIComponent(filePath)}`;
      a.target = "_blank";
      a.rel = "noopener";
      a.innerHTML = `${iconSvg("description", 11)}<span>${escapeHtml(label)}</span>`;
      a.title = filePath;
      a.addEventListener("click", (evt) => evt.stopPropagation());
      row.appendChild(a);
    }
    return row;
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
    const btnSync = document.getElementById("btn-sync");
    if (btnSync) {
      btnSync.innerHTML = `${iconSvg("progress_activity", 13, "animate-spin")}<span>Syncing</span>`;
      btnSync.disabled = true;
    }
    try {
      const res = await postJson("/api/sync", {});
      showToast(`Synced state (audits: ${res.synced_audits ?? 0})`);
      await fetchWorkspaceState();
    } catch (err) {
      showToast(err.message, true);
    } finally {
      if (btnSync) {
        btnSync.innerHTML = `${iconSvg("refresh", 13)}<span>Sync</span>`;
        btnSync.disabled = false;
      }
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
      if (isOpenableConversationId(res.conversation_id)) {
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
      if (isOpenableConversationId(res.conversation_id)) {
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
   * Format a concise SVG-badged status pill HTML string for a Stacked PR card.
   * @param {Record<string, any>} pr - Serialized PR state record.
   * @returns {string} HTML string with inline Google Symbol SVG icon and status label.
   */
  function formatPrStatusBadge(pr) {
    // --- Step 1: Normalize status and optional GitHub PR number ---
    const st = String(pr.status || "PLANNED").toUpperCase();
    const ghNum = pr.github_pr ? ` #${escapeHtml(pr.github_pr)}` : "";
    const latestAudit = pr.latest_audit;

    // --- Step 2: Check terminal graduation and merge states ---
    if (st === "GRADUATED") {
      return `${iconSvg("verified", 12)}<span>Graduated${ghNum}</span>`;
    }
    if (pr.is_merged) {
      return `${iconSvg("verified", 12)}<span>Merged${ghNum}</span>`;
    }

    // --- Step 3: Check Cold-Firewall audit verdicts and staging states ---
    if (st === "AUDIT_APPROVED" || (latestAudit && latestAudit.verdict === "APPROVED")) {
      return `${iconSvg("check_circle", 12)}<span>Audit Approved${ghNum}</span>`;
    }
    if (latestAudit && latestAudit.verdict === "CHANGES_REQUESTED") {
      return `${iconSvg("error", 12)}<span>Changes Requested (R${escapeHtml(latestAudit.audit_round || 1)}/5)</span>`;
    }
    if (st === "STAGED_FOR_AUDIT") {
      return `${iconSvg("progress_activity", 12, "animate-spin")}<span class="animate-shimmer-text">Staged for Audit${ghNum}</span>`;
    }
    if (st === "IN_PROGRESS" || st === "RUNNING") {
      return `${iconSvg("progress_activity", 12, "animate-spin")}<span class="animate-shimmer-text">In Progress${ghNum}</span>`;
    }
    if (pr.github_pr) {
      return `${iconSvg("pending", 12)}<span>Draft PR #${escapeHtml(pr.github_pr)}</span>`;
    }
    return `${statusIconFor(st)}<span>${escapeHtml(st)}</span>`;
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
      vcsBadge.innerHTML = `${iconSvg("commit", 12)}<span>Git: ${escapeHtml(vcsLabel)}</span>`;
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
    if (queue.length > 0) {
      countEl.innerHTML = `${statusDotHtml(true)}<span>${queue.length}</span>`;
    } else {
      countEl.textContent = "0";
    }
    countEl.classList.toggle("zero", queue.length === 0);

    if (queue.length === 0) {
      listEl.innerHTML =
        '<div class="empty-state">No open escalations or approvals pending.</div>';
      return;
    }

    // --- Step 3: Index PR and Work Order objects by ID for state-machine gating ---
    const prsById = {};
    const wosById = {};
    for (const pr of (state && state.prs) || []) {
      prsById[String(pr.pr_id).toUpperCase()] = pr;
      for (const wo of pr.work_orders || []) {
        wosById[String(wo.wo_id).toUpperCase()] = wo;
      }
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
      const woObj = wosById[String(woId).toUpperCase()] || null;
      const paConvId = prObj ? prObj.pa_conversation_id : "";
      const prStatus = prObj ? String(prObj.status || "PLANNED").toUpperCase() : "";
      const isPrHistorical = Boolean(
        prObj &&
          (prObj.is_merged ||
            prStatus === "GRADUATED" ||
            prStatus === "CLOSED" ||
            prStatus === "CANCELLED")
      );
      const woStatus = woObj ? String(woObj.status || "PENDING").toUpperCase() : "";
      const isWoCompleted = woStatus === "COMPLETED";

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

      // --- Step 6: Wire category-specific HITL action buttons with SVG icons ---
      const actionsDiv = document.createElement("div");
      actionsDiv.className = "attention-actions";

      if (category === "PLAN_APPROVAL") {
        const btnApprove = document.createElement("button");
        btnApprove.type = "button";
        btnApprove.className = "btn btn-primary btn-compact";
        btnApprove.innerHTML = `${iconSvg("check_circle", 12)}<span>Approve Plan</span>`;
        btnApprove.disabled = !prId || isPrHistorical || (prStatus !== "" && prStatus !== "PLANNED");
        btnApprove.title = btnApprove.disabled
          ? "Plan approval is only available while the PR is in PLANNED state."
          : `Approve Part II Implementation Plan for ${prId}`;
        btnApprove.addEventListener("click", () => approvePrPlan(prId));
        actionsDiv.appendChild(btnApprove);

        const btnOpenPa = document.createElement("button");
        btnOpenPa.type = "button";
        btnOpenPa.className = "btn btn-compact";
        btnOpenPa.innerHTML = `${iconSvg("chat", 12)}<span>Open PA Thread</span>`;
        btnOpenPa.disabled = !isOpenableConversationId(paConvId);
        btnOpenPa.title = btnOpenPa.disabled
          ? "No active Principal Architect IDE conversation bound."
          : `Open Principal Architect conversation (${paConvId})`;
        btnOpenPa.addEventListener("click", () => jumpToConversation(paConvId));
        actionsDiv.appendChild(btnOpenPa);
      } else if (category === "ESCALATION_RESOLVE") {
        const escId = item.escalation_id || esc.escalation_id || "";
        const btnApproveResume = document.createElement("button");
        btnApproveResume.type = "button";
        btnApproveResume.className = "btn btn-primary btn-compact";
        btnApproveResume.innerHTML = `${iconSvg("check_circle", 12)}<span>Approve & Resume</span>`;
        btnApproveResume.disabled = !escId || isPrHistorical;
        if (checkboxesContainer) {
          checkboxesContainer.addEventListener("change", () => {
            const checkedCount = checkboxesContainer.querySelectorAll(
              'input[type="checkbox"]:checked'
            ).length;
            btnApproveResume.disabled = !escId || isPrHistorical || checkedCount === 0;
          });
        }
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
        btnDeny.innerHTML = `${iconSvg("cancel", 12)}<span>Deny</span>`;
        btnDeny.disabled = !escId;
        btnDeny.addEventListener("click", () => resolveEscalation(escId, "deny"));
        actionsDiv.appendChild(btnDeny);
      } else if (category === "DEBUG_WORKER") {
        const btnDebug = document.createElement("button");
        btnDebug.type = "button";
        btnDebug.className = "btn btn-primary btn-compact";
        btnDebug.innerHTML = `${iconSvg("bug_report", 12)}<span>Launch Interactive Debug</span>`;
        btnDebug.disabled = !woId || isPrHistorical || isWoCompleted;
        btnDebug.title = btnDebug.disabled
          ? "Cannot debug a completed or historical Work Order."
          : `Spawn an interactive Tier 3b Debugger session for ${woId}`;
        btnDebug.addEventListener("click", () => debugWorkOrder(woId));
        actionsDiv.appendChild(btnDebug);
      } else if (category === "GRADUATE_PR") {
        const btnGrad = document.createElement("button");
        btnGrad.type = "button";
        btnGrad.className = "btn btn-primary btn-compact";
        btnGrad.innerHTML = `${iconSvg("rocket_launch", 12)}<span>Graduate PR</span>`;
        btnGrad.disabled = !prId || isPrHistorical;
        btnGrad.title = btnGrad.disabled
          ? "PR is already graduated or merged."
          : `Graduate ${prId} into repository memory`;
        btnGrad.addEventListener("click", () => graduatePr(prId));
        actionsDiv.appendChild(btnGrad);
      } else {
        if (woId) {
          const btnDebug = document.createElement("button");
          btnDebug.type = "button";
          btnDebug.className = "btn btn-compact";
          btnDebug.innerHTML = `${iconSvg("bug_report", 12)}<span>Launch Interactive Debug</span>`;
          btnDebug.disabled = isPrHistorical || isWoCompleted;
          btnDebug.addEventListener("click", () => debugWorkOrder(woId));
          actionsDiv.appendChild(btnDebug);
        }
        if (prId) {
          const btnOpenPa = document.createElement("button");
          btnOpenPa.type = "button";
          btnOpenPa.className = "btn btn-compact";
          btnOpenPa.innerHTML = `${iconSvg("chat", 12)}<span>Open PA Thread</span>`;
          btnOpenPa.disabled = !isOpenableConversationId(paConvId);
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
   * @param {{ historical?: boolean }} [options={}] - Parent PR context flags.
   * @returns {HTMLDivElement} Constructed `.wo-row` DOM element.
   */
  function buildWorkOrderRow(wo, options = {}) {
    // --- Step 1: Render Work Order ID, title, and SVG-badged lifecycle status pill ---
    const row = document.createElement("div");
    row.className = "wo-row";

    const woSt = String(wo.status || "PENDING").toUpperCase();
    const isHistorical = Boolean(options.historical);
    const isCompleted = woSt === "COMPLETED";
    const isRunning = woSt === "IN_PROGRESS" || woSt === "RUNNING";
    const labelClass = isRunning ? ' class="animate-shimmer-text"' : "";

    const topRow = document.createElement("div");
    topRow.className = "wo-row-top";
    topRow.innerHTML = `
      <div class="wo-id-title">
        <span class="wo-id-code">${escapeHtml(wo.wo_id)}</span>
        <span class="wo-title-text">${escapeHtml(wo.title)}</span>
      </div>
      <span class="status-pill ${statusClass(wo.status)}">${statusIconFor(wo.status)}<span${labelClass}>${escapeHtml(wo.status)}</span></span>
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
      rcptBadge.innerHTML = `${iconSvg("check_circle", 11)}<span>${escapeHtml(wo.receipt_id || shortHash)}</span>`;
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

    // --- Step 2b: Render clickable WORKORDER.md spec-file link ---
    if (wo.spec_file) {
      const woSpecLinks = buildSpecLinks([
        { label: "WORKORDER.md", filePath: wo.spec_file },
      ]);
      row.appendChild(woSpecLinks);
    }

    // --- Step 3: Wire Peek Worker and Interactive Debug action buttons with state-machine gating ---
    const canPeekWorker = isOpenableConversationId(wo.subagent_id);
    if (isHistorical || isCompleted) {
      // Historical or completed Work Orders are immutable; only offer Peek Worker if a real thread exists.
      if (canPeekWorker) {
        const actionsRow = document.createElement("div");
        actionsRow.className = "wo-actions";
        const btnPeek = document.createElement("button");
        btnPeek.type = "button";
        btnPeek.className = "btn btn-compact";
        btnPeek.innerHTML = `${iconSvg("visibility", 12)}<span>Peek Worker</span>`;
        btnPeek.title = `Open Worker conversation (${wo.subagent_id})`;
        btnPeek.addEventListener("click", () => jumpToConversation(wo.subagent_id));
        actionsRow.appendChild(btnPeek);
        row.appendChild(actionsRow);
      }
      return row;
    }

    const actionsRow = document.createElement("div");
    actionsRow.className = "wo-actions";

    const btnPeek = document.createElement("button");
    btnPeek.type = "button";
    btnPeek.className = "btn btn-compact";
    btnPeek.innerHTML = `${iconSvg("visibility", 12)}<span>Peek Worker</span>`;
    btnPeek.disabled = !canPeekWorker;
    btnPeek.title = canPeekWorker
      ? `Open Worker conversation (${wo.subagent_id})`
      : "No active Worker IDE conversation bound yet.";
    btnPeek.addEventListener("click", () => jumpToConversation(wo.subagent_id));
    actionsRow.appendChild(btnPeek);

    const isInteractiveComplexity = String(wo.complexity || "").toLowerCase() === "interactive";
    const hasAttempts = Number(wo.attempts || 0) > 0;
    const canDebugWo =
      woSt === "BLOCKED" ||
      woSt === "ESCALATED_TO_PA" ||
      woSt === "ESCALATED" ||
      woSt === "FAILED" ||
      woSt === "IN_PROGRESS" ||
      woSt === "RUNNING" ||
      (woSt === "PENDING" && (isInteractiveComplexity || hasAttempts));

    const btnDebug = document.createElement("button");
    btnDebug.type = "button";
    btnDebug.className = "btn btn-compact";
    btnDebug.innerHTML = `${iconSvg("bug_report", 12)}<span>Debug</span>`;
    btnDebug.disabled = !canDebugWo;
    btnDebug.title = canDebugWo
      ? `Launch interactive Tier 3b Debugger session for ${wo.wo_id}`
      : "Work Order has not started or encountered a blocker yet.";
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
    const progKey = String(prog.programme_id || prog.slug || "");
    const isCollapsed = stateStore.programmeCollapsedOverrides.has(progKey)
      ? Boolean(stateStore.programmeCollapsedOverrides.get(progKey))
      : Boolean(options.collapsed);
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
    toggleIcon.innerHTML = iconSvg("chevron_right", 14);
    toggleIcon.setAttribute("aria-hidden", "true");
    titleGroup.appendChild(toggleIcon);

    const titleText = document.createElement("div");
    titleText.className = "programme-title";
    titleText.textContent = `${prog.title} (${prog.programme_id})`;
    titleGroup.appendChild(titleText);

    header.appendChild(titleGroup);

    const statusPill = document.createElement("span");
    statusPill.className = `status-pill ${statusClass(prog.status)}`;
    statusPill.innerHTML = `${statusIconFor(prog.status)}<span>${escapeHtml(prog.status)}</span>`;
    header.appendChild(statusPill);

    // --- Step 2: Bind click handler to toggle and persist card collapse state ---
    header.addEventListener("click", (evt) => {
      if (evt.target.closest("button, a, select, input")) {
        return;
      }
      card.classList.toggle("collapsed");
      if (progKey) {
        stateStore.programmeCollapsedOverrides.set(
          progKey,
          card.classList.contains("collapsed")
        );
      }
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

    // --- Step 3b: Render clickable spec-file links (PROGRAM.md, PROGRAM-PLAN.md) ---
    const progSpecLinks = buildSpecLinks([
      { label: "PROGRAM.md", filePath: prog.spec_file },
      { label: "PROGRAM-PLAN.md", filePath: prog.plan_file },
    ]);
    if (progSpecLinks.children.length > 0) {
      body.appendChild(progSpecLinks);
    }

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
    const prKey = String(pr.pr_id || pr.slug || "");
    const isCollapsed = stateStore.prCollapsedOverrides.has(prKey)
      ? Boolean(stateStore.prCollapsedOverrides.get(prKey))
      : Boolean(options.collapsed);
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
    toggleIcon.innerHTML = iconSvg("chevron_right", 14);
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
    statusBadge.innerHTML = formatPrStatusBadge(pr);
    rightBadges.appendChild(statusBadge);

    headerTop.appendChild(rightBadges);

    headerTop.addEventListener("click", (evt) => {
      if (evt.target.closest("button, a, select, input")) {
        return;
      }
      card.classList.toggle("collapsed");
      if (prKey) {
        stateStore.prCollapsedOverrides.set(
          prKey,
          card.classList.contains("collapsed")
        );
      }
    });

    card.appendChild(headerTop);

    // --- Step 3: Build card body with branch topology, Charter lock badge, and audit verdict ---
    const cardBody = document.createElement("div");
    cardBody.className = "pr-card-body";

    const branchLine = document.createElement("div");
    branchLine.className = "pr-branch-line";
    branchLine.innerHTML = `${iconSvg("call_split", 11)}<span>${escapeHtml(pr.branch)} → ${escapeHtml(pr.base_branch)}</span>`;
    cardBody.appendChild(branchLine);

    const badgesRow = document.createElement("div");
    badgesRow.className = "pr-badges-row";

    const charterBadge = document.createElement("span");
    const hashPrefix = pr.charter_hash ? String(pr.charter_hash).slice(0, 8) : "unlocked";
    charterBadge.className = `charter-badge ${pr.charter_locked ? "" : "unlocked"}`;
    charterBadge.innerHTML = pr.charter_locked
      ? `${iconSvg("lock", 11)}<span>Charter Locked (${escapeHtml(hashPrefix)})</span>`
      : `${iconSvg("lock_open", 11)}<span>Charter Unlocked</span>`;
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
      auditBadge.innerHTML = `${statusIconFor(verdict)}<span>Audit R${escapeHtml(pr.latest_audit.audit_round || 1)}: ${escapeHtml(verdict)}</span>`;
      badgesRow.appendChild(auditBadge);
    }

    cardBody.appendChild(badgesRow);

    // --- Step 3b: Render clickable PROJECT.md spec-file link ---
    const prSpecLinks = buildSpecLinks([
      { label: "PROJECT.md", filePath: pr.spec_file },
    ]);
    if (prSpecLinks.children.length > 0) {
      cardBody.appendChild(prSpecLinks);
    }

    // --- Step 4: Wire PR-level lifecycle action buttons with state-machine gating ---
    const prStatus = String(pr.status || "PLANNED").toUpperCase();
    const canJumpPa = isOpenableConversationId(pr.pa_conversation_id);
    if (isHistorical) {
      // Historical & Merged PRs are read-only; only offer Jump to PA when a real IDE conversation exists.
      if (canJumpPa) {
        const prActions = document.createElement("div");
        prActions.className = "pr-actions";
        const btnJumpPa = document.createElement("button");
        btnJumpPa.type = "button";
        btnJumpPa.className = "btn btn-compact";
        btnJumpPa.innerHTML = `${iconSvg("chat", 12)}<span>Jump to PA</span>`;
        btnJumpPa.title = `Open Principal Architect conversation (${pr.pa_conversation_id})`;
        btnJumpPa.addEventListener("click", () => jumpToConversation(pr.pa_conversation_id));
        prActions.appendChild(btnJumpPa);
        cardBody.appendChild(prActions);
      }
    } else {
      const prActions = document.createElement("div");
      prActions.className = "pr-actions";

      const btnJumpPa = document.createElement("button");
      btnJumpPa.type = "button";
      btnJumpPa.className = "btn btn-compact";
      btnJumpPa.innerHTML = `${iconSvg("chat", 12)}<span>Jump to PA</span>`;
      btnJumpPa.disabled = !canJumpPa;
      btnJumpPa.title = canJumpPa
        ? `Open Principal Architect conversation (${pr.pa_conversation_id})`
        : "No active Principal Architect IDE conversation bound yet.";
      btnJumpPa.addEventListener("click", () => jumpToConversation(pr.pa_conversation_id));
      prActions.appendChild(btnJumpPa);

      const charterReady = Boolean(pr.charter_locked) && pr.charter_valid !== false;
      const canStartPr =
        charterReady &&
        (prStatus === "PLANNED" ||
          prStatus === "APPROVED" ||
          prStatus === "CHANGES_REQUESTED" ||
          (prStatus === "IN_PROGRESS" && !canJumpPa));
      const btnStartPr = document.createElement("button");
      btnStartPr.type = "button";
      btnStartPr.className = "btn btn-compact";
      btnStartPr.innerHTML = `${iconSvg("play_arrow", 12)}<span>Start PR</span>`;
      btnStartPr.disabled = !canStartPr;
      if (!charterReady) {
        btnStartPr.title = "Lock and validate the Part I PR Charter before starting.";
      } else if (prStatus === "IN_PROGRESS" && canJumpPa) {
        btnStartPr.title = "PR is already in progress; use Jump to PA to open the thread.";
      } else if (!canStartPr) {
        btnStartPr.title = `Cannot start PR while in ${prStatus} state.`;
      } else {
        btnStartPr.title = `Launch or resume Principal Architect session for ${pr.pr_id}`;
      }
      btnStartPr.addEventListener("click", () => startPr(pr.pr_id));
      prActions.appendChild(btnStartPr);

      if (prStatus === "PLANNED") {
        const canApprovePlan = charterReady && workOrders.length > 0;
        const btnApprovePlan = document.createElement("button");
        btnApprovePlan.type = "button";
        btnApprovePlan.className = "btn btn-primary btn-compact";
        btnApprovePlan.innerHTML = `${iconSvg("check_circle", 12)}<span>Approve Plan</span>`;
        btnApprovePlan.disabled = !canApprovePlan;
        btnApprovePlan.title = canApprovePlan
          ? `Approve Part II Implementation Plan (${workOrders.length} Work Order${workOrders.length === 1 ? "" : "s"})`
          : "Requires a locked Part I Charter and at least 1 decomposed Work Order.";
        btnApprovePlan.addEventListener("click", () => approvePrPlan(pr.pr_id));
        prActions.appendChild(btnApprovePlan);
      }

      const isAuditApproved =
        prStatus === "AUDIT_APPROVED" ||
        Boolean(pr.latest_audit && pr.latest_audit.verdict === "APPROVED");
      const allWosCompleted =
        workOrders.length > 0 &&
        workOrders.every((w) => String(w.status || "").toUpperCase() === "COMPLETED");
      const canGraduatePr = isAuditApproved && allWosCompleted && prStatus !== "GRADUATED";
      const btnGradPr = document.createElement("button");
      btnGradPr.type = "button";
      btnGradPr.className = "btn btn-primary btn-compact";
      btnGradPr.innerHTML = `${iconSvg("rocket_launch", 12)}<span>Graduate PR</span>`;
      btnGradPr.disabled = !canGraduatePr;
      btnGradPr.title = canGraduatePr
        ? `Graduate ${pr.pr_id} and distill architectural memory`
        : "Requires all Work Orders COMPLETED and Cold-Firewall Audit APPROVED.";
      btnGradPr.addEventListener("click", () => graduatePr(pr.pr_id));
      prActions.appendChild(btnGradPr);

      cardBody.appendChild(prActions);
    }

    // --- Step 5: Append child Work Order rows ---
    if (workOrders.length > 0) {
      const woList = document.createElement("div");
      woList.className = "wo-list";
      for (const wo of workOrders) {
        woList.appendChild(buildWorkOrderRow(wo, { historical: isHistorical }));
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
    const activeIcon =
      activePrs.length > 0
        ? iconSvg("progress_activity", 12, "animate-spin")
        : iconSvg("check_circle", 12);
    activeHeader.innerHTML = `
      <div class="dag-section-title">
        <span>Active Development</span>
        <span class="badge ${activePrs.length > 0 ? "badge-live" : "badge-muted"}">${activeIcon}<span>${activePrs.length} Active</span></span>
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
      emptyActive.innerHTML = `${iconSvg("check_circle", 13)} <span>No active PRs in progress. All changes are graduated or merged.</span>`;
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

      const isHistSectionCollapsed = Boolean(stateStore.historicalSectionCollapsed);
      const histHeader = document.createElement("div");
      histHeader.className = "dag-section-header clickable";
      histHeader.innerHTML = `
        <div class="dag-section-title">
          <span class="section-collapse-icon${isHistSectionCollapsed ? " is-collapsed" : ""}" aria-hidden="true">${iconSvg("chevron_right", 14)}</span>
          <span>Historical &amp; Merged</span>
          <span class="badge badge-muted">${historicalPrs.length} PR${historicalPrs.length === 1 ? "" : "s"}</span>
        </div>
      `;

      const histList = document.createElement("div");
      histList.className =
        "historical-list" + (isHistSectionCollapsed ? " collapsed" : "");

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
        stateStore.historicalSectionCollapsed = isCollapsed;
        const icon = histHeader.querySelector(".section-collapse-icon");
        if (icon) {
          icon.classList.toggle("is-collapsed", isCollapsed);
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
    const serialized = JSON.stringify(state);
    if (serialized === stateStore.lastRenderedStateJson) {
      return;
    }
    stateStore.lastRenderedStateJson = serialized;
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
        sseBadge.innerHTML = `${statusDotHtml(true)}<span>Live SSE</span>`;
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
        sseBadge.innerHTML = `${iconSvg("progress_activity", 11, "animate-spin")}<span>Reconnecting…</span>`;
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

    const normCandidate = candidate.replace(/^file:\/\//, "");
    const normCurrent = String(stateStore.activeWorkspace || "").replace(/^file:\/\//, "");
    if (normCandidate === normCurrent && stateStore.eventSource) {
      return;
    }

    // --- Step 2: Update stateStore and ensure option exists in workspace dropdown ---
    stateStore.activeWorkspace = candidate;
    stateStore.lastRenderedStateJson = "";
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
        selectEl.disabled = workspaces.length === 0;
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
      btnMonitored.addEventListener("click", () => {
        if (btnMonitored.classList.contains("active")) {
          return;
        }
        updateModeOrModel({ mode: "monitored" });
      });
    }

    const btnAutonomous = document.getElementById("btn-mode-autonomous");
    if (btnAutonomous) {
      btnAutonomous.addEventListener("click", () => {
        if (btnAutonomous.classList.contains("active")) {
          return;
        }
        updateModeOrModel({ mode: "autonomous" });
      });
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
