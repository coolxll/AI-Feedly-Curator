// Listen for messages from content script via background
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'update_sidepanel') {
    updatePanel(msg.title, msg.content, msg.status);
  }
});

function updatePanel(title, content, status) {
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
  } else if (status === 'error') {
    contentEl.innerHTML = `<div class="error">${content}</div>`;
  } else if (status === 'streaming' || content) {
    // Use marked.parse for markdown rendering
    try {
      contentEl.innerHTML = `<div class="summary-content">${marked.parse(content)}</div>`;
    } catch (e) {
      console.error("Markdown parse error:", e);
      contentEl.textContent = content;
    }
  }
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
