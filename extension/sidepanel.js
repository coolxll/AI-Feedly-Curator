// Listen for messages from content script via background
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'update_sidepanel') {
    updatePanel(msg.title, msg.content, msg.status);
  }
});

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
