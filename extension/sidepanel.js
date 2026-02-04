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
    contentEl.innerHTML = `<div class="summary-content">${formatMarkdown(content)}</div>`;
  }
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
    // Remove newlines between list items to clean up spacing
    const cleanMatch = match.replace(/<\/li>\s+<li>/g, '</li><li>');
    return '<ul>' + cleanMatch + '</ul>';
  });

  // Convert remaining double newlines to paragraph breaks
  html = html.replace(/\n\n+/g, '</p><p>');

  // Convert single newlines to line breaks (but not inside tags)
  html = html.replace(/\n/g, '<br>');

  // Wrap in paragraph if not already wrapped
  if (!html.startsWith('<h') && !html.startsWith('<ul') && !html.startsWith('<p>')) {
    html = '<p>' + html + '</p>';
  }

  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');
  html = html.replace(/<p>\s*<br>\s*<\/p>/g, '');

  return html;
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
