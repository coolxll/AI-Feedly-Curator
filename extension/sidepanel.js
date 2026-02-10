// Listen for messages from content script via background
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'update_sidepanel') {
    // Switch to summary tab automatically when update comes in
    switchTab('summary');
    updatePanel(msg.title, msg.content, msg.status);

    // If we have an article ID and the summary is done/streaming, try to fetch tags
    if (msg.status === 'success' || msg.status === 'streaming') {
        if (msg.id) {
            fetchArticleTags(msg.id);
        }
    }
  }
});

function fetchArticleTags(articleId) {
    chrome.runtime.sendMessage({
        type: 'get_article_tags',
        article_id: articleId
    }, (resp) => {
        if (chrome.runtime.lastError) {
            console.warn('Failed to fetch tags:', chrome.runtime.lastError);
            return;
        }

        if (resp && resp.tags && resp.tags.length > 0) {
            displayTags(resp.tags);
        }
    });
}

function displayTags(tags) {
    // Only display tags if we are on the summary tab and the tags container doesn't exist or is empty
    const summaryContent = document.querySelector('.summary-content');
    if (!summaryContent) return;

    // improved check: check if tags are already displayed
    let tagsContainer = document.getElementById('article-tags');
    if (!tagsContainer) {
        tagsContainer = document.createElement('div');
        tagsContainer.id = 'article-tags';
        tagsContainer.className = 'tags-container';
        tagsContainer.innerHTML = '<div class="tags-label">Tags</div><div class="tag-cloud"></div>';
        summaryContent.appendChild(tagsContainer);
    }

    const cloud = tagsContainer.querySelector('.tag-cloud');
    cloud.innerHTML = ''; // clear existing

    tags.forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.textContent = tag;

        // Make tags clickable to search
        chip.style.cursor = 'pointer';
        chip.addEventListener('click', () => {
             document.getElementById('semanticSearchInput').value = tag;
             switchTab('search');
             document.getElementById('semanticSearchBtn').click();
        });

        cloud.appendChild(chip);
    });
}

// Tab Switching Logic
function switchTab(tabId) {
  // Update tab buttons
  document.querySelectorAll('.tab').forEach(tab => {
    if (tab.dataset.tab === tabId) {
      tab.classList.add('active');
    } else {
      tab.classList.remove('active');
    }
  });

  // Update tab content
  document.querySelectorAll('.tab-content').forEach(content => {
    if (content.id === `tab-${tabId}`) {
      content.classList.add('active');
    } else {
      content.classList.remove('active');
    }
  });

  // Trigger data loading for specific tabs
  if (tabId === 'trending') {
    loadTrendingTopics();
  } else if (tabId === 'manage') {
    loadStats();
  }
}

// Initialize Tabs
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      switchTab(tab.dataset.tab);
    });
  });

  // Manage Tab Buttons
  document.getElementById('refreshStatsBtn')?.addEventListener('click', loadStats);
  document.getElementById('cleanupBtn')?.addEventListener('click', cleanupInvalidEntries);
  document.getElementById('clearDbBtn')?.addEventListener('click', clearVectorStore);

  // Trending Tab Buttons
  document.getElementById('refreshTrendingBtn')?.addEventListener('click', loadTrendingTopics);
});

// --- Trending Topics ---
function loadTrendingTopics() {
  const contentEl = document.getElementById('trending-content');
  contentEl.innerHTML = `
    <div class="loading">
      <div class="spinner"></div>
      <div>Loading trending topics...</div>
    </div>
  `;

  chrome.runtime.sendMessage({
    type: 'discover_trending_topics',
    limit: 10
  }, (resp) => {
    if (chrome.runtime.lastError) {
      contentEl.innerHTML = `<div class="error">Error: ${chrome.runtime.lastError.message}</div>`;
      return;
    }

    if (!resp || !resp.topics || resp.topics.length === 0) {
      contentEl.innerHTML = `
        <div class="empty-state">
          <div class="icon">📉</div>
          <div>No trending topics found yet.<br>Add more articles to the vector store.</div>
        </div>
      `;
      return;
    }

    displayTrendingTopics(resp.topics);
  });
}

function displayTrendingTopics(topics) {
  const contentEl = document.getElementById('trending-content');
  contentEl.innerHTML = '';

  const list = document.createElement('div');

  // Find max frequency for bar scaling
  const maxFreq = Math.max(...topics.map(t => t.frequency));

  topics.forEach(t => {
    const item = document.createElement('div');
    item.className = 'trending-item';

    // Calculate width percentage relative to max
    const widthPercent = Math.max(5, (t.frequency / maxFreq) * 100);

    item.innerHTML = `
      <div style="width: 100%">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span class="trending-topic">${t.topic}</span>
          <span class="trending-count">${t.frequency}</span>
        </div>
        <div class="trending-bar">
          <div class="trending-fill" style="width: ${widthPercent}%"></div>
        </div>
      </div>
    `;

    // Clicking a topic could trigger a search
    item.style.cursor = 'pointer';
    item.addEventListener('click', () => {
      document.getElementById('semanticSearchInput').value = t.topic;
      switchTab('search');
      document.getElementById('semanticSearchBtn').click();
    });

    list.appendChild(item);
  });

  contentEl.appendChild(list);
}

// --- Management & Stats ---
function loadStats() {
  const statsEl = document.getElementById('stats-display');
  statsEl.innerHTML = 'Loading stats...';

  chrome.runtime.sendMessage({
    type: 'get_vector_store_stats'
  }, (resp) => {
    if (chrome.runtime.lastError) {
      statsEl.innerHTML = `<span style="color:red">Error: ${chrome.runtime.lastError.message}</span>`;
      return;
    }

    if (resp) {
      statsEl.innerHTML = `
        <div style="font-size: 24px; font-weight: 700; color: #111827;">${resp.article_count || 0}</div>
        <div>Articles in Vector Store</div>
        ${resp.last_updated ? `<div style="font-size: 11px; margin-top: 4px; color: #9ca3af;">Last updated: ${new Date(resp.last_updated).toLocaleString()}</div>` : ''}
      `;
    } else {
      statsEl.innerHTML = 'No stats available.';
    }
  });
}

function cleanupInvalidEntries() {
  const btn = document.getElementById('cleanupBtn');
  const originalText = btn.textContent;
  btn.textContent = 'Cleaning...';
  btn.disabled = true;

  chrome.runtime.sendMessage({
    type: 'cleanup_invalid_entries'
  }, (resp) => {
    btn.textContent = originalText;
    btn.disabled = false;

    if (chrome.runtime.lastError) {
      alert(`Error: ${chrome.runtime.lastError.message}`);
      return;
    }

    alert(resp.message || `Cleanup complete. Removed ${resp.removed_count} entries.`);
    loadStats(); // Refresh stats
  });
}

function clearVectorStore() {
  const btn = document.getElementById('clearDbBtn');
  if (!confirm('Are you sure you want to clear the entire vector database? This cannot be undone.')) {
    return;
  }

  const originalText = btn.textContent;
  btn.textContent = 'Clearing...';
  btn.disabled = true;

  chrome.runtime.sendMessage({
    type: 'clear_vector_store'
  }, (resp) => {
    btn.textContent = originalText;
    btn.disabled = false;

    if (chrome.runtime.lastError) {
      alert(`Error: ${chrome.runtime.lastError.message}`);
      return;
    }

    alert(resp.message || 'Vector store cleared successfully.');
    loadStats(); // Refresh stats

    // Also clear other views
    document.getElementById('trending-content').innerHTML = '';
    document.getElementById('search-results').innerHTML = `
      <div class="empty-state">
        <div class="icon">🔍</div>
        <div>Search your vector database<br>for similar articles</div>
      </div>
    `;
  });
}


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
    const contentEl = document.getElementById('search-results');
    contentEl.innerHTML = '';

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading';

    const spinner = document.createElement('div');
    spinner.className = 'spinner';

    const loadingText = document.createElement('div');
    loadingText.textContent = `Searching for "${query}"...`;

    loadingDiv.appendChild(spinner);
    loadingDiv.appendChild(loadingText);
    contentEl.appendChild(loadingDiv);

    console.log('[Feedly AI] Performing semantic search for:', query);

    // Send semantic search request
    chrome.runtime.sendMessage({
      type: 'semantic_search',
      query: query,
      limit: 10
    }, (resp) => {
      if (chrome.runtime.lastError) {
        console.error("Semantic search error:", chrome.runtime.lastError);
        contentEl.innerHTML = '';
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error';
        errorDiv.textContent = `Search failed: ${chrome.runtime.lastError.message}`;
        contentEl.appendChild(errorDiv);
        return;
      }

      if (resp && resp.results) {
        displaySearchResults(resp.results, query);
      } else {
        contentEl.innerHTML = '';
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error';
        errorDiv.textContent = 'No results found.';
        contentEl.appendChild(errorDiv);
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
  const contentEl = document.getElementById('search-results');
  contentEl.innerHTML = '';

  if (results.length === 0) {
    const emptyState = document.createElement('div');
    emptyState.className = 'empty-state';

    const icon = document.createElement('div');
    icon.className = 'icon';
    icon.textContent = '🔍';

    const text = document.createElement('div');
    text.innerHTML = `No articles found matching<br><strong></strong>`;
    text.querySelector('strong').textContent = query;

    emptyState.appendChild(icon);
    emptyState.appendChild(text);
    contentEl.appendChild(emptyState);
    return;
  }

  const resultsHeader = document.createElement('div');
  resultsHeader.style.padding = '10px 0';

  const summaryInfo = document.createElement('div');
  summaryInfo.style.cssText = 'margin-bottom: 15px; padding: 0 10px;';
  summaryInfo.innerHTML = `Found <strong>${results.length}</strong> articles for "<strong></strong>"`;
  summaryInfo.querySelectorAll('strong')[1].textContent = query;

  resultsHeader.appendChild(summaryInfo);
  contentEl.appendChild(resultsHeader);

  results.forEach((result, index) => {
    const title = result.metadata?.title || 'Untitled Article';
    const score = result.metadata?.score || 'N/A';
    const distance = result.distance ? result.distance.toFixed(3) : 'N/A';
    const preview = result.text ? result.text.substring(0, 200) + '...' : '';
    const url = result.metadata?.url || null;

    const resultCard = document.createElement('div');
    resultCard.style.cssText = `
        margin: 0 10px 15px 10px;
        padding: 12px 15px;
        border: 1px solid #e5e7eb;
        border-radius: 6px;
        background: #fff;
        box-shadow: 0 1px 2px rgba(0,0,0,0.05);
      `;

    const cardHeader = document.createElement('div');
    cardHeader.style.cssText = `
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 8px;
      `;

    let titleEl;
    if (url) {
      titleEl = document.createElement('a');
      titleEl.href = url;
      titleEl.target = '_blank';
      titleEl.rel = 'noopener noreferrer';
      titleEl.style.cssText = `
          font-size: 14px;
          font-weight: 600;
          color: #2563eb;
          text-decoration: none;
          flex: 1;
          display: block;
        `;
      titleEl.textContent = title;
      titleEl.onmouseover = () => { titleEl.style.textDecoration = 'underline'; };
      titleEl.onmouseout = () => { titleEl.style.textDecoration = 'none'; };
    } else {
      titleEl = document.createElement('h3');
      titleEl.style.cssText = `
          margin: 0;
          font-size: 14px;
          font-weight: 600;
          color: #111827;
          flex: 1;
        `;
      titleEl.textContent = title;
    }

    const scoreBadge = document.createElement('div');
    scoreBadge.style.cssText = `
        font-size: 12px;
        font-weight: 600;
        color: #6b7280;
        background: #f3f4f6;
        padding: 2px 6px;
        border-radius: 4px;
        white-space: nowrap;
        margin-left: 8px;
      `;
    scoreBadge.textContent = `Score: ${score}`;

    cardHeader.appendChild(titleEl);
    cardHeader.appendChild(scoreBadge);

    const previewEl = document.createElement('div');
    previewEl.style.cssText = `
        font-size: 13px;
        color: #6b7280;
        line-height: 1.5;
        margin-bottom: 8px;
      `;

    // Clean up content for display
    let displayText = result.text || "";

    // Remove "Content:" prefix if present
    displayText = displayText.replace(/^Content:\s*/i, '');
    displayText = displayText.replace(/\nContent:\s*/i, '\n');

    // Remove Title lines if present
    displayText = displayText.replace(/^Title:.*$/im, '');
    displayText = displayText.replace(/\nTitle:.*$/im, '');

    // Clean up extra newlines
    displayText = displayText.trim();

    previewEl.textContent = displayText.substring(0, 200) + (displayText.length > 200 ? '...' : '');

    const cardFooter = document.createElement('div');
    cardFooter.style.cssText = `
        font-size: 11px;
        color: #9ca3af;
        display: flex;
        justify-content: space-between;
      `;

    const distanceSpan = document.createElement('span');
    distanceSpan.textContent = `Distance: ${distance}`;

    const idSpan = document.createElement('span');
    idSpan.textContent = `ID: ${result.id.substring(0, 8)}...`;

    cardFooter.appendChild(distanceSpan);
    cardFooter.appendChild(idSpan);

    resultCard.appendChild(cardHeader);
    resultCard.appendChild(previewEl);
    resultCard.appendChild(cardFooter);
    contentEl.appendChild(resultCard);
  });
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
