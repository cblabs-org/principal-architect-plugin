/**
 * Principal Architect Plugin (c) 2026 Matt McNeill
 * https://github.com/matthewmcneill/principal-architect-plugin
 * SPDX-License-Identifier: Apache-2.0
 *
 * Module: daemon/sidecars/pa_cockpit/ui/preload.js
 *
 * Responsibility:
 *   Frontend host bridge injected into the Principal Architect Cockpit Web UI
 *   (iframe / webview). Establishes the global `window.sidecar` contract,
 *   synchronizes Antigravity host theme CSS variables (`--background`,
 *   `--foreground`, `--primary`, `--card`, `--border`, `--muted`) and
 *   `themeType` (`dark` | `light`) in real time via `postMessage`, tracks active
 *   workspace folder URIs pushed by the IDE host, and exposes authenticated
 *   proxy helpers for sidecar HTTP routes and Agent API conversation management.
 *
 * Exported API Summary (`window.sidecar` Host Bridge Contract):
 *   Core Properties & Transport:
 *     - window.sidecar.conversationId: Active host conversation UUID extracted from URL query parameters.
 *     - window.sidecar.fetch(url, options): Authenticated fetch wrapper injecting `X-Sidecar-Token`.
 *     - window.sidecar.getWorkspaceUris(): Resolve the list of active workspace folder URIs from the host.
 *     - window.sidecar.onWorkspaceChange(listener): Subscribe to real-time host `workspace-change` events; returns an unsubscribe callback.
 *   Agent API Bridge (`window.sidecar.agent`):
 *     - window.sidecar.agent.sendMessage(message, convId): Send a message to an existing agent conversation (`sendMessageToConversation` / `/_sidecar/send-message`).
 *     - window.sidecar.agent.startConversation(message, title): Start a new agent conversation in the current project (`/_sidecar/new-conversation`).
 *     - window.sidecar.agent.getConversationMetadata(conversationId): Retrieve conversation metadata (`getInfo` / `/_sidecar/get-conversation-metadata`).
 *   Host UI Controls (`window.sidecar.ui`):
 *     - window.sidecar.ui.toggleAuxPane(request): Request the parent host window to toggle an auxiliary sidecar pane.
 *     - window.sidecar.ui.toggleConversation(conversationId): Focus or open a target conversation in the host IDE sidebar (`openUrl` / `toggle-conversation` postMessage).
 *     - window.sidecar.ui.openFile(filePath): Request the parent host window to open a file in the editor (`open-file` postMessage).
 */

(function() {
  // Extract sidecar authentication secret and bound conversation ID from URL query parameters.
  const config = (function() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    const conversationId = params.get('conversationId');
    return { token, conversationId };
  })();

  const { token, conversationId } = config; // Shared `X-Sidecar-Token` secret (`secret`) and initial `conversationId` from host iframe URL.

  let currentWorkspaceUris = []; // Active workspace folder URIs pushed by the host via `workspace-change`.
  let hasInitialWorkspace = false; // Flag indicating whether the first `workspace-change` payload has been received.
  const workspaceListeners = new Set(); // Registered listener callbacks (`workspaceChangeListener` set) notified on workspace URI updates.
  let resolveInitialWorkspace; // Resolver function for `initialWorkspacePromise` (`initPromise`).
  const initialWorkspacePromise = new Promise((resolve) => { // Promise (`initPromise`) that settles once the host pushes initial workspace URIs.
    resolveInitialWorkspace = resolve;
  });

  /**
   * Compare two workspace URI string arrays for shallow element-by-element equality.
   * @param {string[]} a - Previous workspace URI list.
   * @param {string[]} b - Next workspace URI list.
   * @returns {boolean} True when both arrays have identical lengths and ordered elements.
   */
  function areUriArraysEqual(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return false;
    }
    return true;
  }

  /**
   * Safely invoke a workspace change listener with a shallow copy of `currentWorkspaceUris`.
   * @param {(uris: string[]) => void} listener - Subscriber callback to notify.
   * @returns {void}
   */
  function notifyWorkspaceListener(listener) {
    try {
      listener([...currentWorkspaceUris]);
    } catch (err) {
      console.error('workspace-change listener failed:', err);
    }
  }

  /**
   * Handle `message` events posted by the parent Antigravity IDE host window (`parentOrigin`).
   * Synchronizes host theme design tokens (`theme-change`) and workspace URIs (`workspace-change`).
   */
  window.addEventListener('message', (event) => {
    // --- Step 1: Apply host CSS custom properties and themeType on `theme-change` ---
    if (event.data?.type === 'theme-change') {
      const payload = event.data.payload || {};
      const vars = payload.cssVariables || {};
      for (const [key, value] of Object.entries(vars)) {
        document.documentElement.style.setProperty(key, value);
      }
      const themeType = payload.themeType;
      if (themeType) {
        document.documentElement.setAttribute('data-theme', themeType);
        document.documentElement.classList.toggle('dark', themeType === 'dark');
        document.documentElement.classList.toggle('light', themeType === 'light');
      }
      if (payload.theme) {
        document.documentElement.setAttribute('data-theme-name', payload.theme);
      }
    } else if (event.data?.type === 'workspace-change') {
      // --- Step 2: Diff incoming workspace URIs and settle initial workspace handshake ---
      const payload = event.data.payload ?? {};
      const nextWorkspaceUris = Array.isArray(payload.workspaceUris)
        ? [...payload.workspaceUris]
        : [];
      const isFirstPush = !hasInitialWorkspace;
      const hasChanged =
        isFirstPush ||
        !areUriArraysEqual(currentWorkspaceUris, nextWorkspaceUris);
      currentWorkspaceUris = nextWorkspaceUris;
      hasInitialWorkspace = true;
      resolveInitialWorkspace();

      // --- Step 3: Broadcast updated workspace URIs to all registered subscribers ---
      if (hasChanged) {
        for (const listener of workspaceListeners) {
          notifyWorkspaceListener(listener);
        }
      }
    }
  });

  /**
   * Apply baseline theme-aware CSS variables (`--background`, `--foreground`) and typography
   * to `document.body` once the DOM is available (`initialStylesApplied`).
   * @returns {void}
   */
  const applyBodyStyles = () => {
    // --- Step 1: Verify `document.body` is mounted before mutating inline styles ---
    if (document.body) {
      // --- Step 2: Reset box model margins and bind adaptive host theme colors ---
      document.body.style.margin = '0';
      document.body.style.padding = '0';
      document.body.style.background = 'var(--background, #ffffff)';
      document.body.style.color = 'var(--foreground, #1f2328)';
      document.body.style.fontFamily =
        '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    }
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', applyBodyStyles);
  } else {
    applyBodyStyles();
  }

  /**
   * Execute an HTTP request against the sidecar backend with `Content-Type: application/json`
   * and the `X-Sidecar-Token` authentication header automatically attached.
   * @param {string | URL} url - Target sidecar endpoint URL.
   * @param {RequestInit} [options={}] - Standard `fetch` request init options.
   * @returns {Promise<Response>} Fetch response promise.
   */
  function secureFetch(url, options = {}) {
    // --- Step 1: Clone caller headers and enforce JSON content type ---
    const headers = new Headers(options.headers || {});
    headers.set('Content-Type', 'application/json');

    // --- Step 2: Inject sidecar authentication token when present ---
    if (token) {
      headers.set('X-Sidecar-Token', token);
    }

    // --- Step 3: Dispatch underlying browser fetch request ---
    return fetch(url, { ...options, headers });
  }

  // Promise resolving the parent project ID associated with the initial `conversationId`.
  const projectIdPromise = (async () => {
    // --- Step 1: Short-circuit with empty project ID when no conversationId was provided ---
    if (conversationId) {
      try {
        // --- Step 2: Query sidecar metadata endpoint for conversation project metadata ---
        const res = await secureFetch('/_sidecar/get-conversation-metadata', {
          method: 'POST',
          body: JSON.stringify({ conversationId })
        });
        if (!res.ok) {
          console.error('Failed to resolve project ID for conversation ' + conversationId + ':', await res.text());
          return '';
        }
        const data = await res.json();
        if (data && data.error) {
          console.error('agentapi returned error resolving project ID:', data.error);
          return '';
        }

        // --- Step 3: Extract projectId from camelCase or snake_case response envelope ---
        const metaEvent = data?.response?.conversationMetadata || data?.response?.conversation_metadata;
        const meta = metaEvent?.metadata;
        const resolvedId = meta?.projectId || meta?.project_id || '';
        return resolvedId;
      } catch (err) {
        console.error('Failed to resolve project ID for conversation ' + conversationId + ':', err);
        return '';
      }
    }
    return '';
  })();

  /**
   * Return the current list of workspace folder URIs after awaiting the initial host handshake.
   * @returns {Promise<string[]>} Shallow copy of active workspace URIs (or `[]` when standalone).
   */
  async function getWorkspaceUris() {
    // --- Step 1: Return empty list immediately when running outside a host iframe ---
    if (window.parent === window) {
      return [];
    }

    // --- Step 2: Await initial `workspace-change` postMessage and return cloned URIs ---
    await initialWorkspacePromise;
    return [...currentWorkspaceUris];
  }

  // Expose the sidecar API to the frontend window.
  window.sidecar = {
    conversationId,
    fetch: secureFetch,
    getWorkspaceUris,
    /**
     * Register a callback invoked whenever the host IDE workspace folder list changes.
     * @param {(uris: string[]) => void} listener - Callback receiving updated workspace URIs.
     * @returns {() => void} Unsubscribe function removing the listener.
     */
    onWorkspaceChange(listener) {
      // --- Step 1: Guard against non-function listener arguments ---
      if (typeof listener !== 'function') {
        return () => {};
      }

      // --- Step 2: Register subscriber and replay current workspace URIs on next microtask ---
      workspaceListeners.add(listener);
      if (hasInitialWorkspace) {
        queueMicrotask(() => {
          if (workspaceListeners.has(listener)) {
            notifyWorkspaceListener(listener);
          }
        });
      }

      // --- Step 3: Return disposer callback to unregister subscriber ---
      return () => {
        workspaceListeners.delete(listener);
      };
    },
    agent: {
      /**
       * Send a message to an existing agent conversation via `/_sidecar/send-message`.
       * @param {string} message - Prompt or message content to deliver.
       * @param {string} [convId] - Target conversation ID (defaults to bound `conversationId`).
       * @returns {Promise<Record<string, any>>} Parsed JSON response from the sidecar proxy.
       */
      async sendMessage(message, convId) {
        const resolvedProjectId = await projectIdPromise;
        const res = await secureFetch('/_sidecar/send-message', {
          method: 'POST',
          body: JSON.stringify({
            conversationId: convId || conversationId,
            message,
            projectId: resolvedProjectId
          })
        });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
      },
      /**
       * Start a new agent conversation in the resolved project via `/_sidecar/new-conversation`.
       * @param {string} message - Initial prompt for the new conversation.
       * @param {string} [title] - Optional display title for the conversation.
       * @returns {Promise<Record<string, any>>} Parsed JSON response containing the new conversation ID.
       */
      async startConversation(message, title) {
        const resolvedProjectId = await projectIdPromise;
        const res = await secureFetch('/_sidecar/new-conversation', {
          method: 'POST',
          body: JSON.stringify({ message, title, projectId: resolvedProjectId })
        });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
      },
      /**
       * Fetch metadata for a specific agent conversation via `/_sidecar/get-conversation-metadata`.
       * @param {string} conversationId - Target conversation UUID.
       * @returns {Promise<Record<string, any>>} Parsed conversation metadata payload.
       */
      async getConversationMetadata(conversationId) {
        const res = await secureFetch('/_sidecar/get-conversation-metadata', {
          method: 'POST',
          body: JSON.stringify({ conversationId })
        });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
      }
    },
    ui: {
      /**
       * Request the parent Antigravity host window to toggle an auxiliary pane.
       * @param {Record<string, any>} request - AuxPane toggle request payload.
       * @returns {void}
       */
      toggleAuxPane(request) {
        window.parent.postMessage({
          type: 'toggle-aux-pane',
          payload: request
        }, '*');
      },
      /**
       * Request the parent Antigravity host window to focus or open a conversation in the sidebar.
       * @param {string} conversationId - Target conversation UUID to focus.
       * @returns {void}
       */
      toggleConversation(conversationId) {
        window.parent.postMessage({
          type: 'toggle-conversation',
          payload: { conversationId }
        }, '*');
      },
      /**
       * Request the parent Antigravity host window to open a file in the editor.
       * @param {string} filePath - Absolute filesystem path to open.
       * @returns {void}
       */
      openFile(filePath) {
        window.parent.postMessage({
          type: 'open-file',
          payload: { filePath }
        }, '*');
      }
    }
  };
})();
