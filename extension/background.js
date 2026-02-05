// ============ 配置开关 ============
const USE_MOCK = false;  // true = 使用 Mock 数据, false = 使用 Native Host
// ==================================

const HOST_NAME = "feedly.ai.overlay";
const CACHE_TTL_MS = 30 * 1000;
const cache = new Map();
const summaryStates = new Map(); // windowId -> { title, content, status }

function updateSidePanelState(windowId, state) {
  if (!windowId) return;
  summaryStates.set(windowId, state);
  chrome.runtime.sendMessage({
    type: 'update_sidepanel',
    ...state
  }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'sidepanel_ready') {
    const windowId = msg.windowId || sender.tab?.windowId;
    if (windowId && summaryStates.has(windowId)) {
      const state = summaryStates.get(windowId);
      chrome.runtime.sendMessage({
        type: 'update_sidepanel',
        ...state
      }).catch(() => {});
    }
    return true;
  }
});

// Default settings for summary API
const DEFAULT_SETTINGS = {
  apiEndpoint: 'https://api.openai.com/v1',
  apiKey: '',
  model: 'gpt-4o-mini',
  summaryPrompt: `你是一位专业的内容分析专家。请对以下文章进行全面、详细的总结。

重要提示：不要只写简短概述，而是要深入分析并总结文章中的所有关键要点。

请按以下结构组织你的回答：

## 🎯 核心观点
用2-3句话清晰陈述文章的主要论点、事件或核心观点。

## 🔑 关键要点与细节
详细列出文章中的所有重要内容：
- 包含具体的事实、数据、统计信息
- 涵盖文章的所有主要章节和论点
- 记录重要的引用或声明
- 如有技术细节，请详细说明

## 💡 分析与启示
- 这对读者意味着什么？
- 有哪些更广泛的影响？
- 文章得出了什么结论或预测？

## 📝 补充说明
- 文章中提到的任何注意事项、局限性或反面观点
- 相关背景信息或上下文

请使用清晰简洁的语言，用要点列表提高可读性。目标是提供一份能够捕捉文章完整深度的详尽总结。`
};

// Get settings from storage
async function getSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(DEFAULT_SETTINGS, (items) => {
      resolve(items);
    });
  });
}

// Call OpenAI-compatible API with streaming support
async function callOpenAIStream(content, title, onChunk, onComplete, onError) {
  const settings = await getSettings();

  if (!settings.apiKey) {
    onError('API key not configured. Please set it in extension options.');
    return;
  }

  if (!content || content.length < 50) {
    onError('Article content is empty or too short to summarize.');
    return;
  }

  const endpoint = settings.apiEndpoint.replace(/\/$/, '') + '/chat/completions';

  try {
    console.log(`[Feedly AI] Calling OpenAI API (Stream) with ${content.length} chars`);

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${settings.apiKey}`
      },
      body: JSON.stringify({
        model: settings.model,
        messages: [
          { role: 'system', content: settings.summaryPrompt },
          { role: 'user', content: `文章标题: ${title}\n\n文章内容:\n\n${content}` }
        ],
        temperature: 0.5,
        stream: true
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('OpenAI API error:', response.status, errorText);
      onError(`API error: ${response.status} - ${errorText.substring(0, 200)}`);
      return;
    }

    if (!response.body) {
      onError('ReadableStream not supported in this browser.');
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let fullText = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const dataStr = line.slice(6);
          if (dataStr === '[DONE]') continue;

          try {
            const data = JSON.parse(dataStr);
            const content = data.choices?.[0]?.delta?.content;
            if (content) {
              fullText += content;
              onChunk(fullText);
            }
          } catch (e) {
            console.warn('Error parsing stream chunk', e);
          }
        }
      }
    }

    onComplete(fullText);

  } catch (err) {
    console.error('OpenAI API stream failed:', err);
    onError(`Request failed: ${err.message}`);
  }
}

// Fetch article content from URL
async function fetchArticleContent(url) {
  try {
    console.log(`[Feedly AI] Fetching article content from: ${url}`);

    // NOTE: Some headers (e.g. User-Agent) are forbidden in extension fetch().
    const response = await fetch(url, { credentials: 'omit' });

    if (!response.ok) {
      console.error(`Fetch failed: ${response.status}`);
      return null;
    }

    const html = await response.text();

    // Extract text content from HTML using regex (Service Worker doesn't have DOMParser)
    let content = html;

    // Remove script and style tags
    content = content.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '');
    content = content.replace(/<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>/gi, '');

    // Try to extract article content
    const articleMatch = content.match(/<article[^>]*>([\s\S]*?)<\/article>/i);
    if (articleMatch) {
      content = articleMatch[1];
    } else {
      // Try main tag
      const mainMatch = content.match(/<main[^>]*>([\s\S]*?)<\/main>/i);
      if (mainMatch) {
        content = mainMatch[1];
      } else {
        // Try common content divs
        const contentMatch = content.match(/<div[^>]*class="[^"]*(?:content|article|post)[^"]*"[^>]*>([\s\S]*?)<\/div>/i);
        if (contentMatch) {
          content = contentMatch[1];
        }
      }
    }

    // Remove all HTML tags
    content = content.replace(/<[^>]+>/g, ' ');

    // Decode HTML entities
    content = content
      .replace(/&nbsp;/g, ' ')
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&#x27;/g, "'")
      .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(code));

    // Clean up whitespace
    content = content.replace(/\s+/g, ' ').trim();

    console.log(`[Feedly AI] Fetched ${content.length} chars of content`);
    return content;
  } catch (err) {
    console.error('Fetch article failed:', err);
    return null;
  }
}

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

  const windowId = sender.tab?.windowId;
  console.log("Processing summarize_article for", msg.id);
  console.log("Content length:", msg.content?.length || 0, "URL:", msg.url);

  if (USE_MOCK) {
      setTimeout(() => {
          sendResponse({
              id: msg.id,
              summary: "## Mock Summary\n\n- Point 1: This is a mock summary point.\n- Point 2: Another key detail from the article.\n- Conclusion: This is a test conclusion."
          });
      }, 1500);
  } else {
      // If content is too short, try to fetch from URL first
    (async () => {
        let content = msg.content || '';

        // If content is very short (likely just a snippet), try to fetch from URL
        // Increased threshold to 500 to catch more incomplete previews
        // But respect user's request: if it's not "extremely short", don't fetch
        if (content.length < 200 && msg.url) {
            console.log('[Feedly AI] Content too short (< 200 chars), fetching from URL...');
            updateSidePanelState(windowId, {
                title: msg.title,
                content: '正在获取全文...',
                status: 'loading'
            });

            const fetched = await fetchArticleContent(msg.url);
            if (fetched && fetched.length > content.length) {
                content = fetched;
            }
        } else if (content.length < 50) {
             // Still too short even after check?
             updateSidePanelState(windowId, {
                title: msg.title,
                content: '文章内容过短，无法生成总结。',
                status: 'error'
             });
             sendResponse({ error: 'Content too short' });
             return;
        }

        // Use streaming API
        await callOpenAIStream(
            content,
            msg.title,
            (partialSummary) => {
                // onChunk
                updateSidePanelState(windowId, {
                    title: msg.title,
                    content: partialSummary,
                    status: 'streaming'
                });
            },
            (fullSummary) => {
                // onComplete
                console.log("Stream complete");
                updateSidePanelState(windowId, {
                    title: msg.title,
                    content: fullSummary,
                    status: 'success'
                });
                sendResponse({
                    id: msg.id,
                    summary: fullSummary
                });
            },
            (errorMsg) => {
                // onError
                console.error("Stream error:", errorMsg);
                updateSidePanelState(windowId, {
                    title: msg.title,
                    content: errorMsg,
                    status: 'error'
                });
                sendResponse({ error: errorMsg });
            }
        );
    })();
  }
  return true;
});

console.log(`Feedly AI Overlay background script loaded (${USE_MOCK ? 'MOCK' : 'NATIVE'} MODE)`);

// Handle side panel open request
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'open_sidepanel') {
    const windowId = sender.tab?.windowId;

    if (windowId) {
      updateSidePanelState(windowId, {
        title: msg.title,
        content: '',
        status: 'loading'
      });
    }

    // Try to open side panel (requires user gesture)
    chrome.sidePanel.open({ windowId: windowId }).catch(err => {
      console.error('Failed to open side panel:', err);
    });

    sendResponse({ ok: true });
    return true;
  }
});

// Handle semantic search requests
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || msg.type !== "semantic_search") {
    return;
  }

  console.log("Processing semantic_search for query:", msg.query);

  if (USE_MOCK) {
    // Mock semantic search
    setTimeout(() => {
      const mockResults = [
        {
          id: "mock_related_1",
          text: "This is a mock related article about similar topics.",
          metadata: { title: "Related Article 1", score: 4.2 },
          distance: 0.3
        },
        {
          id: "mock_related_2",
          text: "Another article with similar content and themes.",
          metadata: { title: "Related Article 2", score: 3.8 },
          distance: 0.4
        }
      ];
      sendResponse({
        query: msg.query,
        results: mockResults
      });
    }, 1000);
  } else {
    // Native Host mode - forward to native host
    sendNativeMessage(msg).then(resp => {
      console.log("Native Semantic Search Response:", resp);
      sendResponse(resp);
    });
  }
  return true;
});

// Enable side panel on Feedly
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(err => {
  console.error('Failed to set panel behavior:', err);
});
