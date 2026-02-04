// Default settings
const DEFAULTS = {
  apiEndpoint: 'https://api.openai.com/v1',
  apiKey: '',
  model: 'gpt-4o-mini',
  summaryPrompt: `你是一位专业的内容分析专家。请对以下文章进行全面、详细的总结。

重要提示：不要只写简短概述，而是要深入分析并总结文章中的所有关键要点。

请按以下结构组织你的回答：

## 🎯 核心观点
用2-3句话清晰陈述文章的主要论点、事件或核心观点。

## 🔑 关键要点与细节
详细列出文章中的所有重要内容：
- 包含具体的事实、数据、统计信息
- 涵盖文章的所有主要章节和论点
- 记录重要的引用或声明
- 如有技术细节，请详细说明

## 💡 分析与启示
- 这对读者意味着什么？
- 有哪些更广泛的影响？
- 文章得出了什么结论或预测？

## 📝 补充说明
- 文章中提到的任何注意事项、局限性或反面观点
- 相关背景信息或上下文

请使用清晰简洁的语言，用要点列表提高可读性。目标是提供一份能够捕捉文章完整深度的详尽总结。`
};

// Load settings
function loadSettings() {
  chrome.storage.sync.get(DEFAULTS, (items) => {
    document.getElementById('apiEndpoint').value = items.apiEndpoint;
    document.getElementById('apiKey').value = items.apiKey;
    document.getElementById('model').value = items.model;
    document.getElementById('summaryPrompt').value = items.summaryPrompt;
  });
}

// Save settings
function saveSettings() {
  const settings = {
    apiEndpoint: document.getElementById('apiEndpoint').value.trim(),
    apiKey: document.getElementById('apiKey').value.trim(),
    model: document.getElementById('model').value.trim(),
    summaryPrompt: document.getElementById('summaryPrompt').value.trim()
  };

  chrome.storage.sync.set(settings, () => {
    showStatus('Settings saved successfully!', 'success');
  });
}

// Reset to defaults
function resetSettings() {
  document.getElementById('apiEndpoint').value = DEFAULTS.apiEndpoint;
  document.getElementById('apiKey').value = DEFAULTS.apiKey;
  document.getElementById('model').value = DEFAULTS.model;
  document.getElementById('summaryPrompt').value = DEFAULTS.summaryPrompt;
  showStatus('Reset to default values (not saved yet)', 'success');
}

// Show status message
function showStatus(message, type) {
  const status = document.getElementById('status');
  status.textContent = message;
  status.className = 'status ' + type;
  setTimeout(() => {
    status.className = 'status';
  }, 3000);
}

// Test API connection
async function testAPI() {
  const endpoint = document.getElementById('apiEndpoint').value.trim();
  const apiKey = document.getElementById('apiKey').value.trim();
  const model = document.getElementById('model').value.trim();

  if (!apiKey) {
    showStatus('Please enter an API key first', 'error');
    return;
  }

  showStatus('Testing API connection...', 'success');

  try {
    const response = await fetch(endpoint.replace(/\/$/, '') + '/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`
      },
      body: JSON.stringify({
        model: model,
        messages: [
          { role: 'user', content: 'Say "API connection successful!" in exactly those words.' }
        ],
        max_tokens: 20
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      showStatus(`API Error: ${response.status} - ${errorText.substring(0, 100)}`, 'error');
      return;
    }

    const data = await response.json();
    const content = data.choices?.[0]?.message?.content || 'No response';
    showStatus(`✅ API Test Successful! Response: "${content}"`, 'success');
  } catch (err) {
    showStatus(`Connection failed: ${err.message}`, 'error');
  }
}

// Event listeners
document.getElementById('saveBtn').addEventListener('click', saveSettings);
document.getElementById('testBtn').addEventListener('click', testAPI);
document.getElementById('resetBtn').addEventListener('click', resetSettings);

// Load on page open
document.addEventListener('DOMContentLoaded', loadSettings);
