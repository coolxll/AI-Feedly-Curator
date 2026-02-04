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

  // Support both old (ids array) and new (items array) formats
  let ids = [];
  let itemsMap = new Map();

  if (msg.items && Array.isArray(msg.items)) {
      ids = msg.items.map(i => i.id);
      msg.items.forEach(i => itemsMap.set(i.id, i));
  } else {
      ids = Array.isArray(msg.ids) ? msg.ids : [];
  }

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

    // Construct items list for native host, including metadata if available
    const missingItems = missing.map(id => itemsMap.get(id) || { id: id });

    sendNativeMessage({ type: "get_scores", items: missingItems }).then((resp) => {
      console.log("Native Host Response:", JSON.stringify(resp, null, 2));
      const fetched = resp && resp.items ? resp.items : {};
      mergeCache(fetched);
      sendResponse({ items: { ...items, ...fetched } });
    });
  }

  return true;
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== "analyze_article") {
    return;
  }

  console.log("Processing analyze_article for", msg.id);

  if (USE_MOCK) {
     // Mock analysis
     setTimeout(() => {
         const score = 4.5;
         const verdict = "值得阅读";
         const result = {
             id: msg.id,
             score: score,
             data: {
                 verdict: verdict,
                 summary: "这是实时分析的Mock结果。",
                 reason: `实时AI评分: ${score}/5.0 - ${verdict}`
             },
             found: true
         };
         mergeCache({[msg.id]: result});
         sendResponse(result);
     }, 1500);
  } else {
      sendNativeMessage(msg).then(resp => {
          console.log("Native Analysis Response:", resp);
          if (resp && !resp.error) {
              mergeCache({[msg.id]: resp});
          }
          sendResponse(resp);
      });
  }
  return true;
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== "summarize_article") {
    return;
  }

  console.log("Processing summarize_article for", msg.id);

  if (USE_MOCK) {
      setTimeout(() => {
          sendResponse({
              id: msg.id,
              summary: "## Mock Summary\n\n- Point 1: This is a mock summary point.\n- Point 2: Another key detail from the article.\n- Conclusion: This is a test conclusion."
          });
      }, 1500);
  } else {
      sendNativeMessage(msg).then(resp => {
          console.log("Native Summarize Response:", resp);
          sendResponse(resp);
      });
  }
  return true;
});

console.log(`Feedly AI Overlay background script loaded (${USE_MOCK ? 'MOCK' : 'NATIVE'} MODE)`);
