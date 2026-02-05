// Listen for messages from content script via background
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'update_sidepanel') {
    updatePanel(msg.title, msg.content, msg.status);
  }
});

// Semantic Search functionality
document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('semanticSearchInput');
  const searchBtn = document.getElementById('semanticSearchBtn');

  // Function to perform semantic search
  const performSemanticSearch = () => {
    const query = searchInput.value.trim();
    if (!query) {
      alert('Please enter a search query');
      return;
    }

    // Show loading state
    const contentEl = document.getElementById('content');
    contentEl.innerHTML = `
      <div class="loading">
        <div class="spinner"></div>
        <div>Searching for "${query}"...</div>
      </div>
    `;

    console.log('[Feedly AI] Performing semantic search for:', query);

    // Send semantic search request
    chrome.runtime.sendMessage({
      type: 'semantic_search',
      query: query,
      limit: 10
    }, (resp) => {
      if (chrome.runtime.lastError) {
        console.error("Semantic search error:", chrome.runtime.lastError);
        contentEl.innerHTML = `<div class="error">Search failed: ${chrome.runtime.lastError.message}</div>`;
        return;
      }

      if (resp && resp.results) {
        displaySearchResults(resp.results, query);
      } else {
        contentEl.innerHTML = '<div class="error">No results found.</div>';
      }
    });
  };

  // Add event listeners
  searchBtn.addEventListener('click', performSemanticSearch);

  searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      performSemanticSearch();
    }
  });
});

// Function to display search results
function displaySearchResults(results, query) {
  const contentEl = document.getElementById('content');

  if (results.length === 0) {
    contentEl.innerHTML = `
      <div class="empty-state">
        <div class="icon">🔍</div>
        <div>No articles found matching<br><strong>"${query}"</strong></div>
      </div>
    `;
    return;
  }

  let resultsHtml = `
    <div style="padding: 10px 0;">
      <div style="margin-bottom: 15px; padding: 0 10px;">
        Found <strong>${results.length}</strong> articles for "<strong>${query}</strong>"
      </div>
  `;

  results.forEach((result, index) => {
    const title = result.metadata?.title || 'Untitled Article';
    const score = result.metadata?.score || 'N/A';
    const distance = result.distance ? result.distance.toFixed(3) : 'N/A';
    const preview = result.text ? result.text.substring(0, 200) + '...' : '';
    const url = result.metadata?.url || null;

    // Create title element (with link if URL is available)
    let titleHtml = '';
    if (url) {
      titleHtml = `
        <a href="${url}" target="_blank" rel="noopener noreferrer"
           style="
             font-size: 14px;
             font-weight: 600;
             color: #2563eb;
             text-decoration: none;
             flex: 1;
             display: block;
           "
           onmouseover="this.style.textDecoration='underline'"
           onmouseout="this.style.textDecoration='none'">
          ${title}
        </a>
      `;
    } else {
      titleHtml = `
        <h3 style="
          margin: 0;
          font-size: 14px;
          font-weight: 600;
          color: #111827;
          flex: 1;
        ">${title}</h3>
      `;
    }

    resultsHtml += `
      <div style="
        margin: 0 10px 15px 10px;
        padding: 12px 15px;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        background: #fff;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
      ">
        <div style="
          display: flex;
          justify-content: space-between;
          align-items: flex-start;
          margin-bottom: 8px;
        ">
          ${titleHtml}
          <div style="
            font-size: 12px;
            font-weight: 600;
            color: #6b7280;
            background: #f3f4f6;
            padding: 2px 6px;
            border-radius: 4px;
            white-space: nowrap;
            margin-left: 8px;
          ">
            Score: ${score}
          </div>
        </div>
        <div style="
          font-size: 13px;
          color: #6b7280;
          line-height: 1.5;
          margin-bottom: 8px;
        ">${preview}</div>
        <div style="
          font-size: 11px;
          color: #9ca3af;
          display: flex;
          justify-content: space-between;
        ">
          <span>Distance: ${distance}</span>
          <span>ID: ${result.id.substring(0, 8)}...</span>
        </div>
      </div>
    `;
  });

  resultsHtml += '</div>';
  contentEl.innerHTML = resultsHtml;
}

const RENDER_INTERVAL_MS = 180;
let renderTimer = null;
let lastRenderAt = 0;
let pendingRender = null;
let lastRenderedKey = null;

function _renderPanel(title, content, status) {
  const titleEl = document.getElementById('articleTitle');
  const contentEl = document.getElementById('content');

  if (title) {
    titleEl.textContent = title;
  }

  if (status === 'loading') {
    contentEl.innerHTML = `
      <div class="loading">
        <div class="spinner"></div>
        <div>正在生成总结...</div>
      </div>
    `;
    return;
  }

  if (status === 'error') {
    contentEl.innerHTML = `<div class="error">${content}</div>`;
    return;
  }

  if (status === 'streaming' || content) {
    // Use marked.parse for markdown rendering (throttled during streaming)
    try {
      contentEl.innerHTML = `<div class="summary-content">${marked.parse(content || '')}</div>`;
    } catch (e) {
      console.error("Markdown parse error:", e);
      contentEl.textContent = content;
    }
  }
}

function _scheduleRender(title, content, status) {
  pendingRender = { title, content, status };
  if (renderTimer) return;

  const now = Date.now();
  const delay = Math.max(0, RENDER_INTERVAL_MS - (now - lastRenderAt));

  renderTimer = setTimeout(() => {
    renderTimer = null;
    lastRenderAt = Date.now();

    if (!pendingRender) return;

    const { title, content, status } = pendingRender;
    pendingRender = null;

    const key = `${status || ''}::${title || ''}::${content || ''}`;
    if (key === lastRenderedKey) return;
    lastRenderedKey = key;

    _renderPanel(title, content, status);
  }, delay);
}

function updatePanel(title, content, status) {
  // Streaming 会非常频繁更新，避免每个 chunk 都触发 marked.parse
  if (status === 'streaming') {
    _scheduleRender(title, content, status);
    return;
  }

  // 非 streaming 状态优先立即渲染（并清理队列）
  if (renderTimer) {
    clearTimeout(renderTimer);
    renderTimer = null;
  }
  pendingRender = null;

  const key = `${status || ''}::${title || ''}::${content || ''}`;
  if (key === lastRenderedKey) return;
  lastRenderedKey = key;

  _renderPanel(title, content, status);
}

console.log('[Feedly AI] Side panel loaded');

// Notify background that we are ready to receive data
if (chrome.windows && chrome.windows.getCurrent) {
  chrome.windows.getCurrent((win) => {
    chrome.runtime.sendMessage({ type: 'sidepanel_ready', windowId: win.id });
  });
} else {
  chrome.runtime.sendMessage({ type: 'sidepanel_ready' });
}
