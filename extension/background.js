// ============ 配置开关 ============
const USE_MOCK = false;
// ==================================

const CACHE_TTL_MS = 30 * 1000;
const REQUEST_TIMEOUT_MS = 120 * 1000;
const cache = new Map();
const summaryStates = new Map();

const DEFAULT_SETTINGS = {
  serverBaseUrl: 'http://127.0.0.1:8765'
};

function registerAsyncHandler(type, handler) {
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || msg.type !== type) {
      return;
    }

    Promise.resolve()
      .then(() => handler(msg, sender))
      .then((result) => sendResponse(result || {}))
      .catch((err) => {
        console.error(`[Feedly AI] ${type} failed:`, err);
        sendResponse({ error: err?.message || String(err) });
      });

    return true;
  });
}

function updateSidePanelState(windowId, state) {
  if (!windowId) {
    return;
  }
  summaryStates.set(windowId, state);
  chrome.runtime.sendMessage({
    type: 'update_sidepanel',
    ...state
  }).catch(() => {});
}

async function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(DEFAULT_SETTINGS, (items) => resolve(items));
  });
}

async function sendBackendMessage(payload) {
  const settings = await getSettings();
  const baseUrl = (settings.serverBaseUrl || DEFAULT_SETTINGS.serverBaseUrl).replace(/\/$/, '');

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${baseUrl}/api/message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    if (!response.ok) {
      const errorText = await response.text();
      return {
        error: `Backend request failed: ${response.status}`,
        message: errorText.substring(0, 300)
      };
    }

    return await response.json();
  } catch (err) {
    if (err?.name === 'AbortError') {
      return { error: 'Backend request timed out' };
    }
    return {
      error: 'Backend request failed',
      message: err?.message || String(err)
    };
  } finally {
    clearTimeout(timeoutId);
  }
}

async function fetchFromFeedlyAPI(entryId) {
  try {
    const encodedId = encodeURIComponent(entryId);
    const response = await fetch(`https://cloud.feedly.com/v3/entries/${encodedId}`);

    if (!response.ok) {
      console.warn(`[Feedly AI] Feedly API fetch failed: ${response.status}`);
      return null;
    }

    const data = await response.json();
    const content = data.content?.content || data.summary?.content || '';
    if (!content) {
      return null;
    }

    return content.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  } catch (err) {
    console.error('[Feedly AI] Feedly API fetch failed:', err);
    return null;
  }
}

async function fetchArticleContent(url) {
  try {
    const response = await fetch(url, { credentials: 'omit' });
    if (!response.ok) {
      console.error(`[Feedly AI] Article fetch failed: ${response.status}`);
      return null;
    }

    let content = await response.text();
    content = content.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '');
    content = content.replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '');

    const articleMatch = content.match(/<article[^>]*>([\s\S]*?)<\/article>/i);
    const mainMatch = content.match(/<main[^>]*>([\s\S]*?)<\/main>/i);
    const contentMatch = content.match(/<div[^>]*class="[^"]*(?:content|article|post)[^"]*"[^>]*>([\s\S]*?)<\/div>/i);
    content = articleMatch?.[1] || mainMatch?.[1] || contentMatch?.[1] || content;

    content = content.replace(/<[^>]+>/g, ' ');
    content = content
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&#x27;/g, "'")
      .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(code))
      .replace(/\s+/g, ' ')
      .trim();

    return content;
  } catch (err) {
    console.error('[Feedly AI] Fetch article failed:', err);
    return null;
  }
}

function getMockScores(ids) {
  const items = {};
  for (const id of ids) {
    const score = Math.round((Math.random() * 2 + 3) * 10) / 10;
    const verdict = score >= 4 ? '值得阅读' : score >= 3 ? '一般，可选' : '不值得读';
    items[id] = {
      id,
      score,
      data: {
        verdict,
        summary: '这是一篇关于技术的文章，内容涉及前沿开发实践。',
        reason: `AI评分: ${score}/5.0 - ${verdict}`
      },
      updated_at: new Date().toISOString(),
      found: true
    };
  }
  return items;
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

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.type !== 'sidepanel_ready') {
    return;
  }

  const windowId = msg.windowId || sender.tab?.windowId;
  if (!windowId || !summaryStates.has(windowId)) {
    return true;
  }

  chrome.runtime.sendMessage({
    type: 'update_sidepanel',
    ...summaryStates.get(windowId)
  }).catch(() => {});

  return true;
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type !== 'open_sidepanel') {
    return;
  }

  const windowId = sender.tab?.windowId;
  if (windowId) {
    updateSidePanelState(windowId, {
      title: msg.title,
      content: '',
      status: 'loading'
    });
  }

  chrome.sidePanel.open({ windowId }).catch((err) => {
    console.error('[Feedly AI] Failed to open side panel:', err);
  });

  sendResponse({ ok: true });
  return true;
});

registerAsyncHandler('get_scores', async (msg) => {
  let ids = [];
  const itemsMap = new Map();

  if (msg.items && Array.isArray(msg.items)) {
    ids = msg.items.map((item) => item.id);
    msg.items.forEach((item) => itemsMap.set(item.id, item));
  } else {
    ids = Array.isArray(msg.ids) ? msg.ids : [];
  }

  if (ids.length === 0) {
    return { items: {} };
  }

  const { items, missing } = getCached(ids);
  if (missing.length === 0) {
    return { items };
  }

  if (USE_MOCK) {
    const fetched = getMockScores(missing);
    mergeCache(fetched);
    return { items: { ...items, ...fetched } };
  }

  const missingItems = missing.map((id) => itemsMap.get(id) || { id });
  const resp = await sendBackendMessage({ type: 'get_scores', items: missingItems });
  const fetched = resp?.items || {};
  mergeCache(fetched);
  return { items: { ...items, ...fetched } };
});

registerAsyncHandler('analyze_article', async (msg) => {
  if (USE_MOCK) {
    const score = 4.5;
    const verdict = '值得阅读';
    const result = {
      id: msg.id,
      score,
      data: {
        verdict,
        summary: '这是实时分析的 Mock 结果。',
        reason: `实时AI评分: ${score}/5.0 - ${verdict}`
      },
      found: true
    };
    mergeCache({ [msg.id]: result });
    return result;
  }

  const resp = await sendBackendMessage(msg);
  if (resp && !resp.error) {
    mergeCache({ [msg.id]: resp });
  }
  return resp;
});

registerAsyncHandler('summarize_article', async (msg, sender) => {
  const windowId = sender.tab?.windowId;

  if (USE_MOCK) {
    return {
      id: msg.id,
      summary: '## Mock Summary\n\n- Point 1: This is a mock summary point.\n- Point 2: Another key detail from the article.\n- Conclusion: This is a test conclusion.'
    };
  }

  let content = msg.content || '';

  if (msg.id) {
    const feedlyContent = await fetchFromFeedlyAPI(msg.id);
    if (feedlyContent && feedlyContent.length > content.length) {
      content = feedlyContent;
    }
  }

  if (content.length < 200 && msg.url) {
    updateSidePanelState(windowId, {
      title: msg.title,
      content: '正在从原网页获取全文...',
      status: 'loading'
    });

    const fetched = await fetchArticleContent(msg.url);
    if (fetched && fetched.length > content.length) {
      content = fetched;
    }
  }

  if (content.length < 50) {
    const errorMessage = '文章内容过短，无法生成总结。';
    updateSidePanelState(windowId, {
      title: msg.title,
      content: errorMessage,
      status: 'error'
    });
    return { error: errorMessage };
  }

  updateSidePanelState(windowId, {
    title: msg.title,
    content: '正在调用本地服务生成总结...',
    status: 'loading'
  });

  const resp = await sendBackendMessage({
    ...msg,
    content
  });

  if (resp?.summary) {
    updateSidePanelState(windowId, {
      title: msg.title,
      content: resp.summary,
      status: 'success',
      id: msg.id
    });
    return resp;
  }

  const errorMessage = resp?.message || resp?.error || '总结生成失败';
  updateSidePanelState(windowId, {
    title: msg.title,
    content: errorMessage,
    status: 'error'
  });
  return { error: errorMessage };
});

registerAsyncHandler('semantic_search', async (msg) => {
  if (USE_MOCK) {
    return {
      query: msg.query,
      results: [
        {
          id: 'mock_related_1',
          text: 'This is a mock related article about similar topics.',
          metadata: { title: 'Related Article 1', score: 4.2 },
          distance: 0.3
        },
        {
          id: 'mock_related_2',
          text: 'Another article with similar content and themes.',
          metadata: { title: 'Related Article 2', score: 3.8 },
          distance: 0.4
        }
      ]
    };
  }

  return sendBackendMessage(msg);
});

registerAsyncHandler('get_article_tags', async (msg) => {
  if (USE_MOCK) {
    return {
      article_id: msg.article_id,
      tags: ['AI', 'Machine Learning', 'Technology', 'Innovation']
    };
  }

  return sendBackendMessage(msg);
});

registerAsyncHandler('discover_trending_topics', async (msg) => {
  if (USE_MOCK) {
    return {
      topics: [
        { topic: 'AI Development', frequency: 12, percentage: 25.3 },
        { topic: 'Cloud Computing', frequency: 8, percentage: 18.7 },
        { topic: 'Cybersecurity', frequency: 6, percentage: 15.2 },
        { topic: 'Web Development', frequency: 5, percentage: 12.1 },
        { topic: 'Data Science', frequency: 4, percentage: 9.8 }
      ],
      limit: msg.limit || 5
    };
  }

  return sendBackendMessage(msg);
});

registerAsyncHandler('delete_article', async (msg) => {
  if (USE_MOCK) {
    return { article_id: msg.article_id, success: true };
  }

  return sendBackendMessage(msg);
});

registerAsyncHandler('clear_vector_store', async (msg) => {
  if (USE_MOCK) {
    return {
      success: true,
      remaining_count: 0,
      message: 'Vector store cleared (mock).'
    };
  }

  return sendBackendMessage(msg);
});

registerAsyncHandler('get_vector_store_stats', async (msg) => {
  if (USE_MOCK) {
    return {
      article_count: 25,
      sample_ids: ['id1', 'id2', 'id3', 'id4', 'id5'],
      has_data: true
    };
  }

  return sendBackendMessage(msg);
});

registerAsyncHandler('cleanup_invalid_entries', async (msg) => {
  if (USE_MOCK) {
    return {
      removed_count: 3,
      remaining_count: 22,
      message: 'Cleaned up 3 invalid entries (mock).'
    };
  }

  return sendBackendMessage(msg);
});

chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((err) => {
  console.error('[Feedly AI] Failed to set panel behavior:', err);
});

console.log(`Feedly AI Overlay background script loaded (${USE_MOCK ? 'MOCK' : 'SERVER'} MODE)`);
