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
    /* 移除旧的 tooltip 样式 */
    /* .ai-score-badge:hover::after { ... } */

    /* 分析按钮样式 */
    .ai-analyze-btn, .ai-summary-btn {
      margin-right: 8px;
      font-size: 11px;
      font-weight: 600;
      padding: 2px 8px;
      border-radius: 4px;
      background: #2563eb;
      color: #fff;
      border: none;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      transition: background 0.2s;
      vertical-align: middle;
    }
    .ai-summary-btn {
      background: #8b5cf6; /* Purple for summary */
    }
    .ai-analyze-btn:hover {
      background: #1d4ed8;
    }
    .ai-summary-btn:hover {
      background: #7c3aed;
    }
    .ai-analyze-btn:disabled, .ai-summary-btn:disabled {
      background: #9ca3af;
      cursor: not-allowed;
    }
    .ai-analyze-btn .spinner, .ai-summary-btn .spinner {
      width: 10px;
      height: 10px;
      border: 2px solid #ffffff;
      border-top-color: transparent;
      border-radius: 50%;
      animation: spin 1s linear infinite;
      margin-right: 4px;
      display: none;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
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
    container.style.marginLeft = '8px'; // Add some spacing
    container.style.zIndex = '100'; // Ensure it's above other elements

    // 查找关键元素
    const titleLink = el.querySelector('.EntryTitleLink, .entry-title-link, .entry__title, .ArticleTitle'); // 标题文字链接
    const titleContainer = el.querySelector('.EntryTitle, .entry-title, .title, .ArticleTitle'); // 标题容器
    const entryInfo = el.querySelector('.EntryInfo, .entry-info, .EntryMetadataWrapper'); // 详情页信息区
    const visual = el.querySelector('.Visual'); // 卡片视图的图片区
    const metadata = el.querySelector('.Metadata, .entry__metadata'); // 列表视图的元数据区

    // --- 视图适配逻辑 ---

    // 1. Title-Only View (列表模式) - 插入到标题链接内部的最前面，或者标题后面
    if (el.classList.contains('entry--titleOnly')) {
        // Title Only 模式通常比较紧凑，尝试放在 metadata 里或者标题后
        if (metadata) {
            metadata.insertAdjacentElement('afterbegin', container);
            return container;
        }
        if (titleLink) {
            // 放在标题链接后面，避免破坏标题点击区域
            titleLink.insertAdjacentElement('afterend', container);
            return container;
        }
    }

    // 2. Article View (详情页) - 插入到 Info 区域 (作者/时间行)
    if (entryInfo) {
      entryInfo.insertAdjacentElement('beforeend', container); // 放在 info 的最后面
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

// Simple markdown to HTML formatter
function formatMarkdown(text) {
  if (!text) return '';

  // First escape any raw HTML that might be in the content (security)
  let html = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Then apply markdown formatting
  html = html
    // Headers (must come before other inline formatting)
    .replace(/^#### (.+)$/gm, '<h5>$1</h5>')
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    // Bold (use non-greedy matching)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    // Bullet points - convert to list items
    .replace(/^[\*\-] (.+)$/gm, '<li>$1</li>');

  // Wrap consecutive list items in ul tags
  html = html.replace(/(<li>[\s\S]*?<\/li>)(\s*<li>[\s\S]*?<\/li>)*/g, (match) => {
    return '<ul>' + match + '</ul>';
  });

  // Convert remaining double newlines to paragraph breaks
  html = html.replace(/\n\n+/g, '</p><p>');

  // Convert single newlines to line breaks
  html = html.replace(/\n/g, '<br>');

  return html;
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

  // 如果没有找到评分，显示"Analyze"按钮
  if (!item || !item.found) {
    const btn = document.createElement('button');
    btn.className = 'ai-analyze-btn';
    btn.innerHTML = '<span class="spinner"></span>Analyze AI';

    btn.onclick = (e) => {
      e.stopPropagation();
      e.preventDefault();

      const id = getEntryId(el);
      if (!id) return;

      const spinner = btn.querySelector('.spinner');

      // 更新按钮状态
      btn.disabled = true;
      spinner.style.display = 'inline-block';
      btn.childNodes[1].textContent = 'Analyzing...';

      // 提取内容
      const titleEl = el.querySelector('.EntryTitleLink, .entry-title-link, .entry__title, .ArticleTitle');
      const summaryEl = el.querySelector('.EntrySummary, .entry__summary, .content, .entryContent');
      const contentEl = el.querySelector('.EntryBody, .content, .entryContent, .entryBody'); // 尝试获取全文

      // 优先使用全文，其次摘要
      const contentText = contentEl ? contentEl.innerText : (summaryEl ? summaryEl.textContent.trim() : '');
      const titleText = titleEl ? titleEl.textContent.trim() : 'Unknown Title';

      console.log(`[Feedly AI] Analyzing article: ${id} - ${titleText}`);

      chrome.runtime.sendMessage({
        type: 'analyze_article',
        id: id,
        title: titleText,
        summary: summaryEl ? summaryEl.textContent.trim() : '',
        content: contentText
      }, (resp) => {
        if (chrome.runtime.lastError) {
          console.error("Analysis error:", chrome.runtime.lastError);
          btn.disabled = false;
          spinner.style.display = 'none';
          btn.childNodes[1].textContent = 'Error';
          return;
        }

        console.log("[Feedly AI] Analysis result:", resp);
        if (resp && (resp.found || resp.score !== undefined)) {
            // 缓存并重新渲染
            const resultItem = {
                id: id,
                found: true,
                score: resp.score,
                data: resp.data || resp // 兼容不同返回格式
            };
            STATE.itemCache.set(id, resultItem);
            renderItem(el, resultItem);
        } else {
            btn.disabled = false;
            spinner.style.display = 'none';
            btn.childNodes[1].textContent = 'Failed';
        }
      });
    };

    container.appendChild(btn);
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

  // 改为点击显示/隐藏 Tooltip，避免自动弹出干扰
  badge.style.cursor = 'pointer';
  badge.onclick = (e) => {
      e.stopPropagation();
      e.preventDefault();

      const el = ensureTooltipEl();
      if (el.style.display === 'block' && el.textContent === tooltipText) {
          hideTooltip();
      } else {
          showTooltip(e, tooltipText);
          // 点击其他地方关闭
          const closeHandler = () => {
              hideTooltip();
              document.removeEventListener('click', closeHandler);
          };
          setTimeout(() => document.addEventListener('click', closeHandler), 0);
      }
  };

  container.appendChild(badge);

  // If in detail view, show the reason text inline
  // Article view - usually has EntryInfo
  const entryInfo = el.querySelector('.EntryInfo, .entry-info, .EntryMetadataWrapper');
  // Title-only expanded view - might not have EntryInfo but is expanded
  const isExpanded = el.classList.contains('entry--selected') || el.classList.contains('entry--expanded');

  if ((entryInfo || isExpanded) && rawReason) {
      // Check if we already added it
      if (!container.querySelector('.ai-reason-text')) {
          const reasonEl = document.createElement('span');
          reasonEl.className = 'ai-reason-text';
          reasonEl.style.marginLeft = '12px';
          reasonEl.style.color = 'inherit';
          reasonEl.style.opacity = '0.8';
          reasonEl.style.fontSize = '14px';
          // Include verdict in the text
          reasonEl.textContent = verdict ? `【${verdict}】 ${rawReason}` : rawReason;
          container.appendChild(reasonEl);
      }
  } else if (verdict && !container.querySelector('.ai-reason-text')) {
      // Also add text for card/magazine view if possible, but keep it short
      // We only show verdict if space permits or user hovers (tooltip handles hover)
  }

  // Add Summary Button (Only if it doesn't exist)
  if (!container.querySelector('.ai-summary-btn')) {
    const summaryBtn = document.createElement('button');
    summaryBtn.className = 'ai-summary-btn';
    summaryBtn.innerHTML = '<span class="spinner"></span>Summary';

    summaryBtn.onclick = (e) => {
        e.stopPropagation();
        e.preventDefault();

        const id = getEntryId(el);
        if (!id) return;

        const spinner = summaryBtn.querySelector('.spinner');

        // Update button state
        summaryBtn.disabled = true;
        spinner.style.display = 'inline-block';
        summaryBtn.childNodes[1].textContent = 'Summarizing...';

        // Extract content
        const titleEl = el.querySelector('.EntryTitleLink, .entry-title-link, .entry__title, .ArticleTitle');
        const summaryEl = el.querySelector('.EntrySummary, .entry__summary');
        const contentEl = el.querySelector('.EntryBody, .entryBody, .ArticleBody, .entry__content');

        // Try multiple content sources
        let contentText = '';
        if (contentEl && contentEl.innerText.trim().length > 100) {
            contentText = contentEl.innerText.trim();
        } else if (summaryEl && summaryEl.innerText.trim().length > 50) {
            contentText = summaryEl.innerText.trim();
        }

        const titleText = titleEl ? titleEl.textContent.trim() : 'Unknown Title';
        const link = titleEl ? titleEl.getAttribute('href') : null;
        const url = link ? (link.startsWith('http') ? link : window.location.origin + link) : null;

        console.log(`[Feedly AI] Summarizing article: ${id} - ${titleText}`);
        console.log(`[Feedly AI] Content length: ${contentText.length} chars, URL: ${url}`);

        // If content is too short, we need to fetch from URL
        if (contentText.length < 100 && !url) {
            chrome.runtime.sendMessage({
              type: 'open_sidepanel',
              title: titleText
            }, () => {
              setTimeout(() => {
                chrome.runtime.sendMessage({
                  type: 'update_sidepanel',
                  title: titleText,
                  content: '无法获取文章内容：页面内容为空且没有可用的URL',
                  status: 'error'
                });
              }, 200);
            });
            summaryBtn.disabled = false;
            spinner.style.display = 'none';
            summaryBtn.childNodes[1].textContent = 'Summary';
            return;
        }

        // Open side panel first with loading state
        chrome.runtime.sendMessage({
          type: 'open_sidepanel',
          title: titleText
        });

        chrome.runtime.sendMessage({
            type: 'summarize_article',
            id: id,
            title: titleText,
            url: url,
            content: contentText,
            needFetch: contentText.length < 100  // Signal that we need to fetch content
        }, (resp) => {
             summaryBtn.disabled = false;
             spinner.style.display = 'none';
             summaryBtn.childNodes[1].textContent = 'Summary';

             console.log('[Feedly AI] Summary response:', resp);

             if (chrome.runtime.lastError) {
                console.error("Summary error:", chrome.runtime.lastError);
                chrome.runtime.sendMessage({
                  type: 'update_sidepanel',
                  title: titleText,
                  content: chrome.runtime.lastError.message,
                  status: 'error'
                });
                return;
             }

             if (resp && resp.summary) {
                 chrome.runtime.sendMessage({
                   type: 'update_sidepanel',
                   title: titleText,
                   content: resp.summary,
                   status: 'success'
                 });
             } else if (resp && resp.error) {
                 chrome.runtime.sendMessage({
                   type: 'update_sidepanel',
                   title: titleText,
                   content: resp.error,
                   status: 'error'
                 });
             } else {
                 chrome.runtime.sendMessage({
                   type: 'update_sidepanel',
                   title: titleText,
                   content: 'No response received. Check console for details.',
                   status: 'error'
                 });
             }
        });
    };
    container.appendChild(summaryBtn);
  }

  // Don't auto-show summary panel in list view - only show when user clicks Summary button
  // The summary will be shown in the Chrome side panel instead
}

function scheduleScan() {
  if (STATE.scheduled) return;
  STATE.scheduled = true;
  requestAnimationFrame(scanEntries);
}

function scanEntries() {
  STATE.scheduled = false;
  const entries = Array.from(document.querySelectorAll(SELECTORS.entry));

  const itemsToFetch = [];
  const map = new Map();

  for (const entry of entries) {
    const id = getEntryId(entry);
    if (!id) continue;

    // Check if we're already fetching this ID
    if (STATE.pending.has(id)) continue;

    // Check if this specific DOM element already has a badge OR an analyze button
    // This prevents re-fetching/re-rendering items that already have a status
    if (entry.querySelector('.ai-score-badge') || entry.querySelector('.ai-analyze-btn')) {
        // If it has a badge but is now expanded (has EntryInfo) and missing reason text, we should re-render
        const id = getEntryId(entry);
        const item = STATE.itemCache.get(id);
        if (item && item.found && item.data?.reason) {
             const entryInfo = entry.querySelector('.EntryInfo, .entry-info, .EntryMetadataWrapper');
             const existingReason = entry.querySelector('.ai-reason-text');
             // If we have entry info (expanded) but no reason text displayed yet
             if (entryInfo && !existingReason) {
                 renderItem(entry, item);
             }
        }
        continue;
    }
    const titleEl = entry.querySelector('.EntryTitleLink, .entry-title-link, .entry__title, .ArticleTitle');
    const summaryEl = entry.querySelector('.EntrySummary, .entry__summary, .content, .entryContent');
    const link = titleEl ? titleEl.getAttribute('href') : null;

    // Fix relative URLs
    const url = link ? (link.startsWith('http') ? link : window.location.origin + link) : null;

    itemsToFetch.push({
      id: id,
      title: titleEl ? titleEl.textContent.trim() : 'Unknown Title',
      url: url,
      summary: summaryEl ? summaryEl.textContent.trim() : ''
    });

    map.set(id, entry);
    STATE.pending.set(id, entry);
  }

  if (itemsToFetch.length === 0) return;

  console.log("[Feedly AI Overlay] Fetching scores for", itemsToFetch.length, "new articles");

  // Send items object containing metadata
  chrome.runtime.sendMessage({ type: 'get_scores', items: itemsToFetch }, (resp) => {
    if (chrome.runtime.lastError) {
      console.error("[Feedly AI Overlay] Error:", chrome.runtime.lastError);
      for (const item of itemsToFetch) STATE.pending.delete(item.id);
      return;
    }

    const items = resp?.items || {};
    for (const item of itemsToFetch) {
      const id = item.id;
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
