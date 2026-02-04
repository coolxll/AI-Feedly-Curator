const STATE = {
  pending: new Map(),
  scheduled: false,
};

const SELECTORS = {
  entry: '[data-entry-id], [data-entryid], article, .Entry',
};

function getEntryId(el) {
  const datasetId = el.getAttribute('data-entry-id') || el.getAttribute('data-entryid');
  if (datasetId) return datasetId;

  const link = el.querySelector('a[href*="/entry/"]');
  if (link) {
    const match = link.getAttribute('href').match(/\/entry\/([^/?#]+)/i);
    if (match) return decodeURIComponent(match[1]);
  }

  const idAttr = el.getAttribute('data-id');
  if (idAttr) return idAttr;

  return null;
}

function ensureBadge(el) {
  let badge = el.querySelector('.ai-score-badge');
  if (!badge) {
    badge = document.createElement('span');
    badge.className = 'ai-score-badge';
    badge.style.cssText = 'margin-left:8px;font-size:12px;padding:2px 6px;border-radius:10px;background:#1f2937;color:#fff;';
    const title = el.querySelector('h2, h3, .title, .entry-title, .Title');
    if (title && title.parentElement) {
      title.parentElement.appendChild(badge);
    } else {
      el.appendChild(badge);
    }
  }
  return badge;
}

function ensurePanel(el) {
  let panel = el.querySelector('.ai-summary-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.className = 'ai-summary-panel';
    panel.style.cssText = 'margin:12px 0;padding:12px;border:1px solid #e5e7eb;border-radius:8px;background:#f9fafb;font-size:13px;line-height:1.4;color:#111827;';
    const content = el.querySelector('.Entry__content, .entry-body, .Content, .entry-content');
    if (content && content.parentElement) {
      content.parentElement.insertBefore(panel, content);
    } else {
      el.insertBefore(panel, el.firstChild);
    }
  }
  return panel;
}

function renderItem(el, item) {
  const badge = ensureBadge(el);
  if (!item || !item.found) {
    badge.textContent = 'AI: -';
    badge.style.background = '#6b7280';
    return;
  }

  const score = item.score;
  const verdict = item.data?.verdict || '';
  badge.textContent = `AI: ${score?.toFixed ? score.toFixed(1) : score} ${verdict}`.trim();
  badge.style.background = score >= 4 ? '#059669' : score >= 3 ? '#2563eb' : '#dc2626';

  if (item.data?.summary || item.data?.reason) {
    const panel = ensurePanel(el);
    const summary = item.data.summary || '';
    const reason = item.data.reason || '';
    panel.textContent = '';

    const titleEl = document.createElement('div');
    titleEl.style.fontWeight = '600';
    titleEl.style.marginBottom = '6px';
    titleEl.textContent = 'AI Summary';

    const bodyEl = document.createElement('div');
    bodyEl.style.marginBottom = '6px';
    bodyEl.textContent = summary || reason;

    const metaEl = document.createElement('div');
    metaEl.style.color = '#6b7280';
    metaEl.textContent = `Updated: ${item.updated_at || 'N/A'}`;

    panel.append(titleEl, bodyEl, metaEl);
  }
}

function scheduleScan() {
  if (STATE.scheduled) return;
  STATE.scheduled = true;
  requestAnimationFrame(scanEntries);
}

function scanEntries() {
  STATE.scheduled = false;
  const entries = Array.from(document.querySelectorAll(SELECTORS.entry));
  const ids = [];
  const map = new Map();

  for (const entry of entries) {
    const id = getEntryId(entry);
    if (!id) continue;
    if (STATE.pending.has(id)) continue;
    ids.push(id);
    map.set(id, entry);
    STATE.pending.set(id, entry);
  }

  if (ids.length === 0) return;

  chrome.runtime.sendMessage({ type: 'get_scores', ids }, (resp) => {
    const items = resp?.items || {};
    for (const id of ids) {
      const entry = map.get(id) || STATE.pending.get(id);
      if (entry) {
        renderItem(entry, items[id]);
      }
      STATE.pending.delete(id);
    }
  });
}

const observer = new MutationObserver(() => scheduleScan());
observer.observe(document.documentElement, { childList: true, subtree: true });

scheduleScan();
