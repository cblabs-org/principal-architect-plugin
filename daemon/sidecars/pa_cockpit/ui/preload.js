/**
 * @fileoverview Frontend bridge for Antigravity sidecars.
 *
 * Injected into the sidecar's Web UI (iframe/webview).
 * It establishes the `window.sidecar` global object, synchronizes host theme
 * CSS variables and themeType in real time, and exposes the Antigravity Agent API.
 */

(function() {
  // Extract configuration from query parameters.
  const config = (function() {
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    const conversationId = params.get('conversationId');
    return { token, conversationId };
  })();

  const { token, conversationId } = config;

  // Active workspace folders pushed by the host via `workspace-change`
  let currentWorkspaceUris = [];
  let hasInitialWorkspace = false;
  const workspaceListeners = new Set();
  let resolveInitialWorkspace;
  const initialWorkspacePromise = new Promise((resolve) => {
    resolveInitialWorkspace = resolve;
  });

  function areUriArraysEqual(a, b) {
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return false;
    }
    return true;
  }

  function notifyWorkspaceListener(listener) {
    try {
      listener([...currentWorkspaceUris]);
    } catch (err) {
      console.error('workspace-change listener failed:', err);
    }
  }

  // Listen for events sent by the parent Antigravity / Jetski window.
  // - `theme-change`: host theme changed; apply root design tokens & themeType
  // - `workspace-change`: active workspace changed; notify subscribers
  window.addEventListener('message', (event) => {
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
      if (hasChanged) {
        for (const listener of workspaceListeners) {
          notifyWorkspaceListener(listener);
        }
      }
    }
  });

  // Apply theme-aware styles to the body element on initialization.
  const applyBodyStyles = () => {
    if (document.body) {
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

  // secureFetch helper automatically injects the security token
  // for requests to the sidecar backend.
  function secureFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set('Content-Type', 'application/json');
    if (token) {
      headers.set('X-Sidecar-Token', token);
    }
    return fetch(url, { ...options, headers });
  }

  const projectIdPromise = (async () => {
    if (conversationId) {
      try {
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

  async function getWorkspaceUris() {
    if (window.parent === window) {
      return [];
    }
    await initialWorkspacePromise;
    return [...currentWorkspaceUris];
  }

  // Expose the sidecar API to the frontend window.
  window.sidecar = {
    conversationId,
    fetch: secureFetch,
    getWorkspaceUris,
    onWorkspaceChange(listener) {
      if (typeof listener !== 'function') {
        return () => {};
      }
      workspaceListeners.add(listener);
      if (hasInitialWorkspace) {
        queueMicrotask(() => {
          if (workspaceListeners.has(listener)) {
            notifyWorkspaceListener(listener);
          }
        });
      }
      return () => {
        workspaceListeners.delete(listener);
      };
    },
    agent: {
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
      async startConversation(message, title) {
        const resolvedProjectId = await projectIdPromise;
        const res = await secureFetch('/_sidecar/new-conversation', {
          method: 'POST',
          body: JSON.stringify({ message, title, projectId: resolvedProjectId })
        });
        if (!res.ok) throw new Error(await res.text());
        return res.json();
      },
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
      toggleAuxPane(request) {
        window.parent.postMessage({
          type: 'toggle-aux-pane',
          payload: request
        }, '*');
      },
      toggleConversation(conversationId) {
        window.parent.postMessage({
          type: 'toggle-conversation',
          payload: { conversationId }
        }, '*');
      }
    }
  };
})();
