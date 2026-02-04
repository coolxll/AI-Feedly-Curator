// ============ 配置开关 ============
const USE_MOCK = false;  // true = 使用 Mock 数据, false = 使用 Native Host
// ==================================

const HOST_NAME = "feedly.ai.overlay";
const CACHE_TTL_MS = 30 * 1000;
const cache = new Map();

// Mock 数据：模拟 Native Host 返回的评分
function getMockScores(ids) {
  const items = {};
  for (const id of ids) {
    const score = Math.round((Math.random() * 2 + 3) * 10) / 10; // 3.0 - 5.0
    const verdicts = ["值得阅读", "一般，可选", "不值得读"];
    const verdict = score >= 4 ? verdicts[0] : score >= 3 ? verdicts[1] : verdicts[2];

    items[id] = {
      id: id,
      score: score,
      data: {
        verdict: verdict,
        summary: "这是一篇关于技术的文章，内容涉及前沿开发实践。",
        reason: `AI评分: ${score}/5.0 - ${verdict}`
      },
      updated_at: new Date().toISOString(),
      found: true
    };
  }
  return items;
}

// Native Host 通信
function sendNativeMessage(payload) {
  return new Promise((resolve) => {
    chrome.runtime.sendNativeMessage(HOST_NAME, payload, (response) => {
      if (chrome.runtime.lastError) {
        console.error("Native messaging error:", chrome.runtime.lastError.message);
        resolve({ error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || {});
    });
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

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  console.log("Background received message:", msg);

  if (!msg || msg.type !== "get_scores") {
    return;
  }

  const ids = Array.isArray(msg.ids) ? msg.ids : [];
  console.log("Processing get_scores for", ids.length, "articles");

  if (ids.length === 0) {
    sendResponse({ items: {} });
    return;
  }

  const { items, missing } = getCached(ids);
  if (missing.length === 0) {
    console.log("All from cache");
    sendResponse({ items });
    return;
  }

  if (USE_MOCK) {
    // Mock 模式
    console.log("[MOCK MODE] Generating mock scores for", missing.length, "articles");
    const fetched = getMockScores(missing);
    mergeCache(fetched);
    sendResponse({ items: { ...items, ...fetched } });
  } else {
    // Native Host 模式
    console.log("[NATIVE MODE] Fetching scores from Native Host for", missing.length, "articles");
    sendNativeMessage({ type: "get_scores", ids: missing }).then((resp) => {
      const fetched = resp && resp.items ? resp.items : {};
      mergeCache(fetched);
      sendResponse({ items: { ...items, ...fetched } });
    });
  }

  return true;
});

console.log(`Feedly AI Overlay background script loaded (${USE_MOCK ? 'MOCK' : 'NATIVE'} MODE)`);
