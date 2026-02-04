console.log("[Feedly AI Overlay] Content script loaded!");

const STATE = {
  pending: new Map(),
  processed: new Set(), // Deprecated but kept for compatibility if needed, though we rely on DOM check now
  scheduled: false,
  itemCache: new Map(), // Cache items locally to handle re-rendering on expand
};

const SELECTORS = {
  entry: '[data-entry-id], [data-entryid], article.entry, .Entry, .entry--titleOnly, .entry--magazine, .entry--cards, .Article, .entry--overlay, article.Article',
};

// 注入样式
const STYLE_ID = 'feedly-ai-overlay-style';
if (!document.getElementById(STYLE_ID)) {
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    .ai-score-badge {
      margin-right: 8px;
      font-size: 11px;
      font-weight: 600;
      padding: 1px 6px;
      border-radius: 4px;
      color: #fff;
      display: inline-flex;
      align-items: center;
      vertical-align: middle;
      line-height: 1.3;
      cursor: help;
      position: relative;
      flex-shrink: 0; /* 防止被挤压 */
    }
    // 移除旧的 tooltip 样式
    /* .ai-score-badge:hover::after { ... } */

    /* 新增 JS Tooltip 容器样式 */
    #ai-tooltip-container {
      position: fixed; /* 改为 fixed 定位，彻底脱离文档流 */
      z-index: 2147483647; /* 最大 z-index */
      background: #1f2937;
      color: #f3f4f6;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 400;
      width: 300px;
      max-width: 90vw; /* 防止在小屏幕溢出 */
      white-space: pre-wrap;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      pointer-events: none;
      display: none;
      text-align: left;
      line-height: 1.5;
      border: 1px solid rgba(255,255,255,0.1); /* 增加微弱边框增加对比度 */
    }
    /* 详情页总结面板样式 */
    .ai-summary-panel {
      margin: 16px 0;
      padding: 12px 16px;
      background: #f9fafb;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      font-size: 14px;
      line-height: 1.6;
      color: #374151;
    }
    .ai-summary-title {
      font-weight: 600;
      margin-bottom: 4px;
      display: flex;
      align-items: center;
      color: #111827;
    }
    .ai-summary-content {
      white-space: pre-wrap;
    }
    /* 深色模式适配 */
    [data-theme="dark"] .ai-summary-panel { background: #1f2937; border-color: #374151; color: #d1d5db; }
    [data-theme="dark"] .ai-summary-title { color: #f3f4f6; }
  `;
  document.head.appendChild(style);
}

function getEntryId(el) {
  const datasetId = el.getAttribute('data-entry-id') || el.getAttribute('data-entryid');
  if (datasetId) return datasetId;

  // 尝试查找子元素中的 data-entry-id (针对 Overlay 容器包裹的情况)
  const childWithId = el.querySelector('[data-entry-id], [data-entryid]');
  if (childWithId) {
      const childId = childWithId.getAttribute('data-entry-id') || childWithId.getAttribute('data-entryid');
      if (childId) return childId;
  }

  const link = el.querySelector('a[href*="/entry/"]');
  if (link) {
    const match = link.getAttribute('href').match(/\/entry\/([^/?#]+)/i);
    if (match) return decodeURIComponent(match[1]);
  }

  const idAttr = el.getAttribute('data-id');
  if (idAttr) return idAttr;

  const elId = el.getAttribute('id');
  if (elId) {
    return elId.replace(/_main$/, '');
  }

  return null;
}

function ensureBadgeContainer(el) {
  let container = el.querySelector('.ai-score-container');
  if (!container) {
    container = document.createElement('span');
    container.className = 'ai-score-container';
    container.style.display = 'inline-flex';
    container.style.alignItems = 'center';
    container.style.verticalAlign = 'middle';

    // 查找关键元素
    const titleLink = el.querySelector('.EntryTitleLink, .entry-title-link, .entry__title, .ArticleTitle'); // 标题文字链接
    const titleContainer = el.querySelector('.EntryTitle, .entry-title, .title, .ArticleTitle'); // 标题容器
    const entryInfo = el.querySelector('.EntryInfo, .entry-info, .EntryMetadataWrapper'); // 详情页信息区
    const visual = el.querySelector('.Visual'); // 卡片视图的图片区

    // --- 视图适配逻辑 ---

    // 1. Title-Only View (列表模式) - 插入到标题链接内部的最前面
    if (el.classList.contains('entry--titleOnly') || (titleLink && !visual)) {
        if (titleLink) {
            titleLink.insertAdjacentElement('afterbegin', container);
            return container;
        }
    }

    // 2. Article View (详情页) - 插入到 Info 区域 (作者/时间行)
    if (entryInfo) {
      entryInfo.insertAdjacentElement('afterbegin', container);
      return container;
    }

    // 3. Magazine / Cards View
    if (titleContainer) {
      // 插入到标题容器的最前面
      titleContainer.insertAdjacentElement('afterbegin', container);
      return container;
    }

    // 4. 保底 - 插入到文章元素最前面
    el.insertAdjacentElement('afterbegin', container);
  }
  return container;
}

function ensureSummaryPanel(el, summaryText, verdictText) {
  const contentBody = el.querySelector('.EntryBody, .content, .entryContent, .entryBody');
  if (!contentBody) return;

  if (el.querySelector('.ai-summary-panel')) return;

  const panel = document.createElement('div');
  panel.className = 'ai-summary-panel';

  const title = document.createElement('div');
  title.className = 'ai-summary-title';
  title.textContent = `🤖 AI 总结: ${verdictText}`;

  const body = document.createElement('div');
  body.className = 'ai-summary-content';
  body.textContent = summaryText;

  panel.appendChild(title);
  panel.appendChild(body);

  contentBody.insertAdjacentElement('afterbegin', panel);
}

// 全局 Tooltip 元素管理
let tooltipEl = null;

function ensureTooltipEl() {
  if (!tooltipEl) {
    tooltipEl = document.createElement('div');
    tooltipEl.id = 'ai-tooltip-container';
    document.body.appendChild(tooltipEl);
  }
  return tooltipEl;
}

function showTooltip(e, text) {
  const el = ensureTooltipEl();
  el.textContent = text;
  el.style.display = 'block';
  updateTooltipPos(e);
}

function hideTooltip() {
  const el = ensureTooltipEl();
  el.style.display = 'none';
}

function updateTooltipPos(e) {
  if (!tooltipEl || tooltipEl.style.display === 'none') return;

  // 使用 clientX/Y 因为是 fixed 定位
  const x = e.clientX + 10;
  const y = e.clientY + 10;

  const rect = tooltipEl.getBoundingClientRect();
  const winWidth = window.innerWidth;
  const winHeight = window.innerHeight;

  let finalX = x;
  let finalY = y;

  // 右边界检测
  if (x + rect.width > winWidth) {
    finalX = x - rect.width - 20;
  }

  // 下边界检测
  if (y + rect.height > winHeight) {
    finalY = y - rect.height - 20;
  }

  tooltipEl.style.left = finalX + 'px';
  tooltipEl.style.top = finalY + 'px';
}

function renderItem(el, item) {
  const container = ensureBadgeContainer(el);
  container.innerHTML = '';

  if (!item || !item.found) {
    return;
  }

  const score = item.score;
  const verdict = item.data?.verdict || '';
  const summaryContent = item.data?.summary || '无详细总结';

  const rawReason = item.data?.reason;
  if (rawReason) {
      console.log(`[Feedly AI] ID: ${item.id} | Reason: ${rawReason}`);
  }
  const reasonContent = rawReason ? `\n\n📝 理由: ${rawReason}` : '';
  const summary = summaryContent; // For panel

  const badge = document.createElement('span');
  badge.className = 'ai-score-badge';
  badge.textContent = score?.toFixed(1);

  if (score >= 4.0) {
    badge.style.background = '#10b981';
  } else if (score >= 3.0) {
    badge.style.background = '#3b82f6';
  } else {
    badge.style.background = '#ef4444';
  }

  const tooltipText = `【${verdict}】\n${summaryContent}${reasonContent}`;

  // 绑定鼠标事件代替 CSS Hover
  badge.addEventListener('mouseenter', (e) => showTooltip(e, tooltipText));
  badge.addEventListener('mouseleave', () => hideTooltip());
  badge.addEventListener('mousemove', (e) => updateTooltipPos(e));

  container.appendChild(badge);

  if (summary && summary !== '无详细总结') {
    ensureSummaryPanel(el, summary, verdict);
  }
}

function scheduleScan() {
  if (STATE.scheduled) return;
  STATE.scheduled = true;
  requestAnimationFrame(scanEntries);
}

function scanEntries() {
  STATE.scheduled = false;
  const entries = Array.from(document.querySelectorAll(SELECTORS.entry));

  const ids = [];
  const map = new Map();

  for (const entry of entries) {
    const id = getEntryId(entry);
    if (!id) continue;

    // Check if we're already fetching this ID
    if (STATE.pending.has(id)) continue;

    // Check if this specific DOM element already has a badge
    if (entry.querySelector('.ai-score-badge')) {
        // Even if it has a badge, check if we need to add the summary panel (e.g. user expanded the article)
        // We can't easily do this without the item data, so we might need to refetch or cache locally.
        // For now, let's trust that if the badge exists, the main job is done.
        // BUT: if the user expanded the view, the .EntryBody might be new.
        const item = STATE.itemCache?.get(id); // We'll need to add a local item cache
        if (item) {
             const summary = item.data?.summary || item.data?.reason;
             const verdict = item.data?.verdict;
             if (summary) ensureSummaryPanel(entry, summary, verdict);
        }
        continue;
    }

    ids.push(id);
    map.set(id, entry);
    STATE.pending.set(id, entry);
  }

  if (ids.length === 0) return;

  console.log("[Feedly AI Overlay] Fetching scores for", ids.length, "new articles");

  chrome.runtime.sendMessage({ type: 'get_scores', ids }, (resp) => {
    if (chrome.runtime.lastError) {
      console.error("[Feedly AI Overlay] Error:", chrome.runtime.lastError);
      for (const id of ids) STATE.pending.delete(id);
      return;
    }

    const items = resp?.items || {};
    for (const id of ids) {
      const entry = map.get(id) || STATE.pending.get(id);
      if (items[id]) {
        STATE.itemCache.set(id, items[id]); // Cache the item data
      }
      if (entry) {
        renderItem(entry, items[id]);
      }
      STATE.pending.delete(id);
      STATE.processed.add(id);
    }
  });
}

let debounceTimer = null;
function debouncedScan() {
  if (debounceTimer) return;
  debounceTimer = setTimeout(() => {
    debounceTimer = null;
    scheduleScan();
  }, 200);
}

const observer = new MutationObserver(() => debouncedScan());
observer.observe(document.documentElement, { childList: true, subtree: true });

console.log("[Feedly AI Overlay] Starting initial scan...");
scheduleScan();
