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
const SCORE_BATCH_SIZE = 6;

function isVisibleEntry(el) {
  if (!el || !(el instanceof Element)) return false;

  const style = window.getComputedStyle(el);
  if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') {
    return false;
  }

  const rect = el.getBoundingClientRect();
  return rect.width > 20 && rect.height > 20;
}

function getEntryPriority(el) {
  if (!el || !(el instanceof Element)) return -1;

  let score = 0;
  const rect = el.getBoundingClientRect();
  score += Math.min(rect.width * rect.height, 500000) / 1000;

  if (isVisibleEntry(el)) score += 1000;
  if (el.querySelector('.EntryTitleLink, .entry-title-link, .entry__title, .ArticleTitle')) score += 300;
  if (el.querySelector('.EntrySummary, .entry__summary, .EntryBody, .entryBody, .ArticleBody, .entry__content')) score += 150;
  if (el.classList.contains('entry--selected') || el.classList.contains('entry--expanded')) score += 200;

  return score;
}

function preferBetterEntry(current, candidate) {
  if (!current) return candidate;
  if (!candidate) return current;
  return getEntryPriority(candidate) > getEntryPriority(current) ? candidate : current;
}

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
      const summaryEl = el.querySelector('.EntrySummary, .entry__summary, .content, .entryContent, .entry-content');
      const contentEl = el.querySelector('.EntryBody, .content, .entryContent, .entryBody, .entry__content, .ArticleBody, .Article__content, .entry-content'); // 尝试获取全文

      // 优先使用全文，其次摘要
      const contentText = contentEl ? contentEl.innerText.trim() : (summaryEl ? summaryEl.textContent.trim() : '');
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
          // Only show the reason (verdict is redundant with score)
          reasonEl.textContent = rawReason;
          container.appendChild(reasonEl);
      }
  } else if (verdict && !container.querySelector('.ai-reason-text')) {
      // Also add text for card/magazine view if possible, but keep it short
      // We only show verdict if space permits or user hovers (tooltip handles hover)
  }

  // --- NEW: Insert summary at the top of the article body if expanded ---
  if (entryInfo || isExpanded) {
      const contentBody = el.querySelector('.EntryBody, .entryBody, .ArticleBody, .entry__content');
      if (contentBody && summaryContent && summaryContent !== '无详细总结' && !contentBody.querySelector('.ai-summary-header')) {
          // Check if we are in list view or title-only view to avoid clutter
          // Usually expanded view has 'entry--selected' or 'entry--expanded' or is a full article page
          // We double check to ensure we don't insert into a small card preview

          const summaryDiv = document.createElement('div');
          summaryDiv.className = 'ai-summary-header';
          summaryDiv.style.marginBottom = '20px';
          summaryDiv.style.padding = '15px';
          summaryDiv.style.backgroundColor = '#f8fafc'; // Light gray background
          summaryDiv.style.borderLeft = '4px solid #8b5cf6'; // Purple border matching summary btn
          summaryDiv.style.borderRadius = '4px';
          summaryDiv.style.color = '#334155';
          summaryDiv.style.fontSize = '16px';
          summaryDiv.style.lineHeight = '1.6';

          const title = document.createElement('strong');
          title.textContent = 'AI 总结: ';
          title.style.display = 'block';
          title.style.marginBottom = '8px';
          title.style.color = '#8b5cf6';

          const text = document.createElement('div');
          text.innerHTML = marked.parse(summaryContent);

          summaryDiv.appendChild(title);
          summaryDiv.appendChild(text);

          // Insert at the very beginning of the content body
          contentBody.insertBefore(summaryDiv, contentBody.firstChild);
      }
  }
  // ---------------------------------------------------------------------

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

  // Add Related Articles Section
  if (entryInfo || isExpanded) {
      const contentBody = el.querySelector('.EntryBody, .entryBody, .ArticleBody, .entry__content');
      if (contentBody && !contentBody.querySelector('.ai-related-articles-section')) {
          // Check if we already have cached related articles for this entry
          const hasRelatedArticles = contentBody.querySelector('.ai-related-articles-results');

          if (!hasRelatedArticles) {
              // Show loading indicator
              const loadingDiv = document.createElement('div');
              loadingDiv.className = 'ai-related-articles-loading';
              loadingDiv.style.cssText = `
                  margin-top: 15px;
                  padding: 15px;
                  border: 1px solid #e2e8f0;
                  border-radius: 8px;
                  background-color: #f8fafc;
              `;

              const loadingTitle = document.createElement('h3');
              loadingTitle.textContent = 'Related Articles';
              loadingTitle.style.cssText = `
                  margin: 0 0 10px 0;
                  color: #7c3aed;
                  font-size: 16px;
                  font-weight: 600;
              `;

              const loadingText = document.createElement('div');
              loadingText.textContent = 'Finding related articles...';
              loadingText.style.cssText = `
                  color: #64748b;
                  font-style: italic;
              `;

              loadingDiv.appendChild(loadingTitle);
              loadingDiv.appendChild(loadingText);
              contentBody.appendChild(loadingDiv);

              // Automatically trigger semantic search
              const id = getEntryId(el);
              if (id) {
                  console.log(`[Feedly AI] Auto-finding related articles for: ${id}`);

                  // Send semantic search request
                  chrome.runtime.sendMessage({
                      type: 'semantic_search',
                      query: summaryContent || titleText, // Use summary or title as query
                      limit: 5,
                      current_article_id: id
                  }, (resp) => {
                      // Remove loading indicator
                      const loadingDiv = contentBody.querySelector('.ai-related-articles-loading');
                      if (loadingDiv) {
                          loadingDiv.remove();
                      }

                      if (chrome.runtime.lastError) {
                          console.error("Semantic search error:", chrome.runtime.lastError);

                          // Remove loading indicator
                          const loadingDiv = contentBody.querySelector('.ai-related-articles-loading');
                          if (loadingDiv) {
                              loadingDiv.remove();

                              // Show error message instead
                              const errorDiv = document.createElement('div');
                              errorDiv.className = 'ai-related-articles-error';
                              errorDiv.style.cssText = `
                                  margin-top: 15px;
                                  padding: 15px;
                                  border: 1px solid #fecaca;
                                  border-radius: 8px;
                                  background-color: #fef2f2;
                                  color: #dc2626;
                              `;

                              const errorTitle = document.createElement('h3');
                              errorTitle.textContent = 'Related Articles';
                              errorTitle.style.cssText = `
                                  margin: 0 0 10px 0;
                                  color: #dc2626;
                                  font-size: 16px;
                                  font-weight: 600;
                              `;

                              const errorText = document.createElement('div');
                              errorText.innerHTML = `
                                  Semantic search is not available: ${chrome.runtime.lastError.message}.<br>
                                  Please check that:<br>
                                  • API key is configured in your environment<br>
                                  • Native host is properly installed and running<br>
                                  • Vector database contains articles for semantic search
                              `;
                              errorText.style.cssText = `
                                  color: #991b1b;
                                  font-size: 14px;
                                  line-height: 1.5;
                              `;

                              errorDiv.appendChild(errorTitle);
                              errorDiv.appendChild(errorText);
                              contentBody.appendChild(errorDiv);
                          }
                          return;
                      }

                      if (resp && resp.results) {
                          // Remove loading indicator
                          const loadingDiv = contentBody.querySelector('.ai-related-articles-loading');
                          if (loadingDiv) {
                              loadingDiv.remove();
                          }

                          // Create related articles section with results
                          const relatedSection = document.createElement('div');
                          relatedSection.className = 'ai-related-articles-section';
                          relatedSection.style.cssText = `
                              margin-top: 15px;
                              padding: 15px;
                              border: 1px solid #e2e8f0;
                              border-radius: 8px;
                              background-color: #f8fafc;
                          `;

                          const relatedTitle = document.createElement('h3');
                          relatedTitle.textContent = 'Related Articles';
                          relatedTitle.style.cssText = `
                              margin: 0 0 10px 0;
                              color: #7c3aed;
                              font-size: 16px;
                              font-weight: 600;
                          `;

                          const relatedList = document.createElement('div');
                          relatedList.className = 'ai-related-articles-results';
                          relatedList.style.cssText = `
                              display: flex;
                              flex-direction: column;
                              gap: 10px;
                          `;

                          if (resp.results.length === 0) {
                              const noResults = document.createElement('div');
                              noResults.textContent = 'No related articles found.';
                              noResults.style.color = '#64748b';
                              noResults.style.fontSize = '14px';
                              relatedList.appendChild(noResults);
                          } else {
                              resp.results.forEach((result, index) => {
                                  if (result.id === id) return; // Skip current article

                                  const relatedItem = document.createElement('div');
                                  relatedItem.style.cssText = `
                                      padding: 8px;
                                      border: 1px solid #cbd5e1;
                                      border-radius: 4px;
                                      background: white;
                                  `;

                                  // Create a link to the article if URL is available in metadata
                                  const url = result.metadata.url || null;
                                  let titleElement;

                                  if (url) {
                                      const linkElement = document.createElement('a');
                                      linkElement.href = url;
                                      linkElement.target = '_blank';
                                      linkElement.rel = 'noopener noreferrer';
                                      linkElement.style.cssText = `
                                          font-weight: 600;
                                          color: #2563eb;
                                          text-decoration: none;
                                          display: block;
                                          margin-bottom: 4px;
                                          font-size: 14px;
                                      `;
                                      linkElement.textContent = result.metadata.title || 'Untitled';

                                      // Add hover effect
                                      linkElement.addEventListener('mouseover', () => {
                                          linkElement.style.textDecoration = 'underline';
                                      });
                                      linkElement.addEventListener('mouseout', () => {
                                          linkElement.style.textDecoration = 'none';
                                      });

                                      titleElement = linkElement;
                                  } else {
                                      titleElement = document.createElement('div');
                                      titleElement.textContent = result.metadata.title || 'Untitled';
                                      titleElement.style.cssText = `
                                          font-weight: 600;
                                          color: #1e293b;
                                          margin-bottom: 4px;
                                          font-size: 14px;
                                      `;
                                  }

                                  const relatedSummary = document.createElement('div');

                                  // Clean up content for display
                                  let displayText = result.text || "";

                                  // Remove "Content:" prefix if present
                                  displayText = displayText.replace(/^Content:\s*/i, '');
                                  displayText = displayText.replace(/\nContent:\s*/i, '\n');

                                  // Remove Title lines if present (since we already show clickable title)
                                  // This matches "Title: xxxx" at start or after newline
                                  displayText = displayText.replace(/^Title:.*$/im, '');
                                  displayText = displayText.replace(/\nTitle:.*$/im, '');

                                  // Clean up extra newlines
                                  displayText = displayText.trim();

                                  relatedSummary.textContent = displayText.substring(0, 150) + (displayText.length > 150 ? '...' : '');
                                  relatedSummary.style.cssText = `
                                      color: #64748b;
                                      font-size: 13px;
                                      margin-bottom: 4px;
                                      line-height: 1.4;
                                  `;

                                  const metaInfo = document.createElement('div');
                                  metaInfo.style.cssText = `
                                      display: flex;
                                      justify-content: space-between;
                                      font-size: 12px;
                                      color: #6b7280;
                                  `;

                                  const scoreSpan = document.createElement('span');
                                  scoreSpan.textContent = `AI Score: ${result.metadata.score || 'N/A'}`;
                                  scoreSpan.style.fontWeight = '600';

                                  const distanceSpan = document.createElement('span');
                                  distanceSpan.textContent = `Distance: ${(result.distance || 0).toFixed(3)}`;
                                  distanceSpan.style.fontWeight = '600';

                                  metaInfo.appendChild(scoreSpan);
                                  metaInfo.appendChild(distanceSpan);

                                  relatedItem.appendChild(titleElement);
                                  relatedItem.appendChild(relatedSummary);
                                  relatedItem.appendChild(metaInfo);
                                  relatedList.appendChild(relatedItem);
                              });
                          }

                          relatedSection.appendChild(relatedTitle);
                          relatedSection.appendChild(relatedList);

                          // Insert after the summary or at the end of content body
                          contentBody.appendChild(relatedSection);
                      } else if (resp && resp.error) {
                          // Remove loading indicator
                          const loadingDiv = contentBody.querySelector('.ai-related-articles-loading');
                          if (loadingDiv) {
                              loadingDiv.remove();

                              // Show error message
                              const errorDiv = document.createElement('div');
                              errorDiv.className = 'ai-related-articles-error';
                              errorDiv.style.cssText = `
                                  margin-top: 15px;
                                  padding: 15px;
                                  border: 1px solid #fecaca;
                                  border-radius: 8px;
                                  background-color: #fef2f2;
                                  color: #dc2626;
                              `;

                              const errorTitle = document.createElement('h3');
                              errorTitle.textContent = 'Related Articles';
                              errorTitle.style.cssText = `
                                  margin: 0 0 10px 0;
                                  color: #dc2626;
                                  font-size: 16px;
                                  font-weight: 600;
                              `;

                              const errorText = document.createElement('div');
                              errorText.textContent = `Semantic search failed: ${resp.message || resp.error}`;
                              errorText.style.cssText = `
                                  color: #991b1b;
                                  font-size: 14px;
                              `;

                              errorDiv.appendChild(errorTitle);
                              errorDiv.appendChild(errorText);
                              contentBody.appendChild(errorDiv);
                          }
                      }
                  });
              }
          }
      }
  }

  // Don't auto-show summary panel in list view - only show when user clicks Summary button
  // The summary will be shown in the Chrome side panel instead
}

function scheduleScan() {
  if (STATE.scheduled) return;
  STATE.scheduled = true;
  requestAnimationFrame(scanEntries);
}

function chunkItems(items, chunkSize) {
  const chunks = [];
  for (let i = 0; i < items.length; i += chunkSize) {
    chunks.push(items.slice(i, i + chunkSize));
  }
  return chunks;
}

function handleScoreResponse(itemsToFetch, entryMap, resp) {
  const items = resp?.items || {};
  for (const item of itemsToFetch) {
    const id = item.id;
    const entry = entryMap.get(id) || STATE.pending.get(id);
    if (items[id]) {
      STATE.itemCache.set(id, items[id]);
    }
    if (entry) {
      renderItem(entry, items[id]);
    }
    STATE.pending.delete(id);
    STATE.processed.add(id);
  }
}

function requestScoreChunk(itemsToFetch, entryMap) {
  chrome.runtime.sendMessage({ type: 'get_scores', items: itemsToFetch }, (resp) => {
    if (chrome.runtime.lastError) {
      console.error("[Feedly AI Overlay] Error:", chrome.runtime.lastError);
      for (const item of itemsToFetch) STATE.pending.delete(item.id);
      return;
    }

    handleScoreResponse(itemsToFetch, entryMap, resp);
  });
}

function requestScoresProgressively(itemsToFetch, map) {
  const chunks = chunkItems(itemsToFetch, SCORE_BATCH_SIZE);
  console.log(
    "[Feedly AI Overlay] Fetching scores for",
    itemsToFetch.length,
    "new articles in",
    chunks.length,
    "chunks"
  );

  for (const chunk of chunks) {
    const chunkMap = new Map();
    for (const item of chunk) {
      const entry = map.get(item.id) || STATE.pending.get(item.id);
      if (entry) {
        chunkMap.set(item.id, entry);
      }
    }
    requestScoreChunk(chunk, chunkMap);
  }
}

function scanEntries() {
  STATE.scheduled = false;
  const entries = Array.from(document.querySelectorAll(SELECTORS.entry));

  const itemsToFetch = [];
  const map = new Map();
  const itemMap = new Map();

  for (const entry of entries) {
    const id = getEntryId(entry);
    if (!id) continue;

    if (!isVisibleEntry(entry)) continue;

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
    const summaryEl = entry.querySelector('.EntrySummary, .entry__summary, .content, .entryContent, .entry-content');
    const contentEl = entry.querySelector('.EntryBody, .content, .entryContent, .entryBody, .entry__content, .ArticleBody, .Article__content, .entry-content');
    const link = titleEl ? titleEl.getAttribute('href') : null;

    // Fix relative URLs
    const url = link ? (link.startsWith('http') ? link : window.location.origin + link) : null;

    // 优先使用全文，其次摘要
    const fullText = contentEl ? contentEl.innerText.trim() : (summaryEl ? summaryEl.textContent.trim() : '');

    const item = {
      id: id,
      title: titleEl ? titleEl.textContent.trim() : 'Unknown Title',
      url: url,
      summary: summaryEl ? summaryEl.textContent.trim() : '',
      content: fullText // 同时发送 content 字段
    };

    const preferredEntry = preferBetterEntry(map.get(id), entry);
    map.set(id, preferredEntry);

    const existingItem = itemMap.get(id);
    if (!existingItem || preferredEntry === entry) {
      itemMap.set(id, item);
    }
  }

  for (const [id, entry] of map.entries()) {
    const item = itemMap.get(id);
    if (!item || !entry) continue;
    itemsToFetch.push(item);
    STATE.pending.set(id, entry);
  }

  if (itemsToFetch.length === 0) return;

  requestScoresProgressively(itemsToFetch, map);
}

let debounceTimer = null;
function debouncedScan() {
  if (debounceTimer) return;
  debounceTimer = setTimeout(() => {
    debounceTimer = null;
    scheduleScan();
  }, 200);
}

function getObserverRoot() {
  // Feedly 页面 DOM 变化非常频繁，尽量缩小观察范围，避免全量 scanEntries 过度触发。
  // 这些 selector 是经验候选；如果都找不到，回退到 document.body。
  return (
    document.querySelector('#feedlyPageFX') ||
    document.querySelector('#feedlyFrame') ||
    document.querySelector('#feedlyPage') ||
    document.querySelector('main') ||
    document.body ||
    document.documentElement
  );
}

function fastProcessEntry(entry, mapToFetch, itemsToFetch) {
  if (!entry || !(entry instanceof Element)) return;
  if (!isVisibleEntry(entry)) return;

  // Already rendered
  if (entry.querySelector('.ai-score-badge') || entry.querySelector('.ai-analyze-btn')) {
    return;
  }

  const id = getEntryId(entry);
  if (!id) return;

  // If we already have it locally, render immediately
  const cached = STATE.itemCache.get(id);
  if (cached) {
    renderItem(entry, cached);
    return;
  }

  // Otherwise request from background immediately
  if (STATE.pending.has(id)) return;

  const titleEl = entry.querySelector('.EntryTitleLink, .entry-title-link, .entry__title, .ArticleTitle');
  const summaryEl = entry.querySelector('.EntrySummary, .entry__summary, .content, .entryContent, .entry-content');
  const contentEl = entry.querySelector('.EntryBody, .content, .entryContent, .entryBody, .entry__content, .ArticleBody, .Article__content, .entry-content');
  const link = titleEl ? titleEl.getAttribute('href') : null;
  const url = link ? (link.startsWith('http') ? link : window.location.origin + link) : null;

  // 优先使用全文，其次摘要
  const fullText = contentEl ? contentEl.innerText.trim() : (summaryEl ? summaryEl.textContent.trim() : '');

  const item = {
    id: id,
    title: titleEl ? titleEl.textContent.trim() : 'Unknown Title',
    url: url,
    summary: summaryEl ? summaryEl.textContent.trim() : '',
    content: fullText
  };

  const preferredEntry = preferBetterEntry(mapToFetch.get(id), entry);
  mapToFetch.set(id, preferredEntry);

  const existingIndex = itemsToFetch.findIndex((candidate) => candidate.id === id);
  if (existingIndex >= 0) {
    if (preferredEntry === entry) {
      itemsToFetch[existingIndex] = item;
    }
  } else {
    itemsToFetch.push(item);
  }

  STATE.pending.set(id, preferredEntry);
}

function fastProcessMutations(mutations) {
  const itemsToFetch = [];
  const mapToFetch = new Map();

  for (const m of mutations) {
    if (!m.addedNodes || m.addedNodes.length === 0) continue;

    for (const node of m.addedNodes) {
      if (!(node instanceof Element)) continue;

      // 1) If node is inside an entry
      if (node.closest) {
        const parentEntry = node.closest(SELECTORS.entry);
        if (parentEntry) {
          fastProcessEntry(parentEntry, mapToFetch, itemsToFetch);
        }
      }

      // 2) If node itself is an entry
      if (node.matches && node.matches(SELECTORS.entry)) {
        fastProcessEntry(node, mapToFetch, itemsToFetch);
      }

      // 3) Any entries under this node
      const innerEntries = node.querySelectorAll ? node.querySelectorAll(SELECTORS.entry) : [];
      for (const entry of innerEntries) {
        fastProcessEntry(entry, mapToFetch, itemsToFetch);
      }
    }
  }

  if (itemsToFetch.length === 0) return false;

  requestScoresProgressively(itemsToFetch, mapToFetch);

  return true;
}

const observer = new MutationObserver((mutations) => {
  // Fast path: when user opens an article, Feedly often injects DOM; render badge immediately.
  // Fallback: if we didn't detect any entry nodes, use the original debounced full scan.
  try {
    if (!fastProcessMutations(mutations)) {
      debouncedScan();
    }
  } catch (e) {
    console.error("[Feedly AI] Mutation handling error:", e);
    debouncedScan();
  }
});

function startObserver() {
  const root = getObserverRoot();
  if (!root) {
    console.log("[Feedly AI] Observer root not found, retrying in 1s...");
    setTimeout(startObserver, 1000);
    return;
  }
  try {
    observer.observe(root, { childList: true, subtree: true });
    console.log("[Feedly AI] Observer started on:", root);
  } catch (e) {
    console.error("[Feedly AI] Failed to start observer:", e);
    // Fallback to body if specific root fails
    observer.observe(document.body, { childList: true, subtree: true });
  }
}

console.log("[Feedly AI Overlay] Starting initial scan...");
scheduleScan();
startObserver();
