const HOST_NAME = "feedly.ai.overlay";
const RECONNECT_DELAY_MS = 1500;
const CACHE_TTL_MS = 30 * 1000;

let port = null;
let connecting = false;
let pending = [];
const cache = new Map();

function connectNative() {
  if (connecting || port) return;
  connecting = true;
  try {
    port = chrome.runtime.connectNative(HOST_NAME);
    port.onMessage.addListener(handleNativeMessage);
    port.onDisconnect.addListener(() => {
      port = null;
      connecting = false;
      setTimeout(connectNative, RECONNECT_DELAY_MS);
    });
  } catch (err) {
    port = null;
  } finally {
    connecting = false;
  }
}

function handleNativeMessage(message) {
  const callbacks = pending;
  pending = [];
  for (const cb of callbacks) {
    cb.resolve(message || {});
  }
}

function sendNativeMessage(payload) {
  return new Promise((resolve) => {
    if (!port) {
      resolve({ error: "not_connected" });
      return;
    }
    pending.push({ resolve });
    port.postMessage(payload);
  });
}

function getCached(ids) {
  const now = Date.now();
  const items = {};
  const missing = [];
  for (const id of ids) {
    const cached = cache.get(id);
    if (cached && now - cached.ts < CACHE_TTL_MS) {
      items[id] = cached.value;
    } else {
      missing.push(id);
    }
  }
  return { items, missing };
}

function mergeCache(items) {
  const ts = Date.now();
  for (const [id, value] of Object.entries(items)) {
    cache.set(id, { ts, value });
  }
}

chrome.runtime.onInstalled.addListener(() => connectNative());
chrome.runtime.onStartup.addListener(() => connectNative());
connectNative();

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== "get_scores") {
    return;
  }

  const ids = Array.isArray(msg.ids) ? msg.ids : [];
  if (ids.length === 0) {
    sendResponse({ items: {} });
    return;
  }

  const { items, missing } = getCached(ids);
  if (missing.length === 0) {
    sendResponse({ items });
    return;
  }

  sendNativeMessage({ type: "get_scores", ids: missing }).then((resp) => {
    const fetched = resp && resp.items ? resp.items : {};
    mergeCache(fetched);
    sendResponse({ items: { ...items, ...fetched } });
  });

  return true;
});
