console.log("[Feedly AI Overlay] Content script loaded!");

const STATE = {
  pending: new Map(),
  processed: new Set(),
  scheduled: false,
};

const SELECTORS = {
  entry: '[data-entry-id], [data-entryid], article.entry, .Entry, .entry--titleOnly, .entry--magazine, .entry--cards',
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
    }
    .ai-verdict {
      font-size: 12px;
      color: #6b7280;
      margin-right: 8px;
      vertical-align: middle;
      display: inline-block;
      max-width: 200px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    /* Tooltip 样式 */
    .ai-score-badge:hover::after {
      content: attr(data-tooltip);
      position: absolute;
      top: 100%;
      left: 0;
      z-index: 9999;
      background: #1f2937;
      color: #f3f4f6;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 400;
      width: 300px;
      white-space: normal;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      margin-top: 4px;
      line-height: 1.5;
      text-align: left;
    }
    /* 在深色模式下的适配 (可选) */
    [data-theme="dark"] .ai-verdict {
      color: #9ca3af;
    }
  `;
  document.head.appendChild(style);
}

function getEntryId(el) {
  const datasetId = el.getAttribute('data-entry-id') || el.getAttribute('data-entryid');
  if (datasetId) return datasetId;

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

    // 查找 Metadata 区域 (适用: Title-Only, Magazine, Cards, Article Detail)
    const metadata = el.querySelector('.Metadata, .entry-metadata, .EntryMetadata, .meta, .metadata');
    const title = el.querySelector('.EntryTitle, .entry-title, .title');

    // 1. Metadata 优先
    if (metadata) {
      metadata.style.display = 'flex';
      metadata.style.alignItems = 'center';
      metadata.insertAdjacentElement('afterbegin', container);
      return container;
    }

    // 2. Article View
    const entryInfo = el.querySelector('.EntryInfo, .entry-info');
    if (entryInfo) {
      entryInfo.insertAdjacentElement('afterbegin', container);
      return container;
    }

    // 3. Cards View / Magazine View
    if (title) {
      if (el.classList.contains('entry--cards') || el.classList.contains('u100Entry')) {
         title.insertAdjacentElement('afterend', container);
         container.style.marginTop = '4px';
      } else {
         container.style.marginLeft = '8px';
         title.appendChild(container);
      }
      return container;
    }

    // 4. 保底
    el.insertAdjacentElement('afterbegin', container);
  }
  return container;
}

function renderItem(el, item) {
  const container = ensureBadgeContainer(el);
  container.innerHTML = ''; // 清空内容重绘

  if (!item || !item.found) {
    // 没分不显示
    return;
  }

  const score = item.score;
  const verdict = item.data?.verdict || '';
  const summary = item.data?.summary || item.data?.reason || '无详细总结';

  // 1. 创建徽章
  const badge = document.createElement('span');
  badge.className = 'ai-score-badge';
  badge.textContent = score?.toFixed(1);

  // 颜色
  if (score >= 4.0) {
    badge.style.background = '#10b981';
  } else if (score >= 3.0) {
    badge.style.background = '#3b82f6';
  } else {
    badge.style.background = '#ef4444';
  }

  // Tooltip 内容
  const tooltipText = `【${verdict}】\n${summary}`;
  badge.setAttribute('data-tooltip', tooltipText);

  // 2. 创建 Verdict 文本 (显示在徽章旁边)
  const verdictEl = document.createElement('span');
  verdictEl.className = 'ai-verdict';
  verdictEl.textContent = verdict; // e.g. "值得阅读"

  container.appendChild(badge);
  container.appendChild(verdictEl);
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

    if (STATE.processed.has(id) || STATE.pending.has(id)) continue;

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
