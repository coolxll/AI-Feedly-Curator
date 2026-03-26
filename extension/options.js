const DEFAULTS = {
  serverBaseUrl: 'http://127.0.0.1:8765'
};

function showStatus(message, type) {
  const status = document.getElementById('status');
  status.textContent = message;
  status.className = `status ${type}`;
  setTimeout(() => {
    status.className = 'status';
  }, 3000);
}

function loadSettings() {
  chrome.storage.sync.get(DEFAULTS, (items) => {
    document.getElementById('serverBaseUrl').value = items.serverBaseUrl;
  });
}

function saveSettings() {
  const settings = {
    serverBaseUrl: document.getElementById('serverBaseUrl').value.trim() || DEFAULTS.serverBaseUrl
  };

  chrome.storage.sync.set(settings, () => {
    showStatus('Settings saved successfully.', 'success');
  });
}

function resetSettings() {
  document.getElementById('serverBaseUrl').value = DEFAULTS.serverBaseUrl;
  showStatus('Reset to default values (not saved yet).', 'success');
}

async function testConnection() {
  const baseUrl = document.getElementById('serverBaseUrl').value.trim() || DEFAULTS.serverBaseUrl;
  showStatus('Testing backend connection...', 'success');

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, '')}/health`);
    if (!response.ok) {
      showStatus(`Backend error: ${response.status}`, 'error');
      return;
    }

    const data = await response.json();
    if (!data.ok) {
      showStatus('Backend responded but health check failed.', 'error');
      return;
    }

    showStatus(`Backend is reachable. DB: ${data.db_path}`, 'success');
  } catch (err) {
    showStatus(`Connection failed: ${err.message}`, 'error');
  }
}

document.getElementById('saveBtn').addEventListener('click', saveSettings);
document.getElementById('testBtn').addEventListener('click', testConnection);
document.getElementById('resetBtn').addEventListener('click', resetSettings);
document.addEventListener('DOMContentLoaded', loadSettings);
