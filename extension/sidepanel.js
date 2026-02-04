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
  } else if (content) {
    contentEl.innerHTML = `<div class="summary-content">${formatMarkdown(content)}</div>`;
  }
}

// Simple markdown to HTML formatter
function formatMarkdown(text) {
  if (!text) return '';

  return text
    // Escape HTML first
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Headers
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Bullet points
    .replace(/^\* (.+)$/gm, '<li>$1</li>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    // Wrap consecutive li elements in ul
    .replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>')
    // Paragraphs (double newlines)
    .replace(/\n\n/g, '</p><p>')
    // Line breaks
    .replace(/\n/g, '<br>')
    // Wrap in paragraph
    .replace(/^(.+)$/, '<p>$1</p>');
}

console.log('[Feedly AI] Side panel loaded');
