(function (root) {
  'use strict';

  const ALLOWED_PROTOCOLS = new Set(['http:', 'https:']);

  const ALLOWED_TAGS = new Set([
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'del',
    'code', 'pre', 'blockquote',
    'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'hr', 'a',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'span', 'div'
  ]);

  const DROP_CONTENT_TAGS = new Set([
    'script', 'style', 'iframe', 'object', 'embed',
    'svg', 'math', 'noscript', 'template', 'head', 'title',
    'form', 'input', 'textarea', 'select', 'option', 'button',
    'img', 'audio', 'video', 'source', 'picture', 'canvas',
    'applet', 'link', 'meta', 'base'
  ]);

  const SAFE_CLASS_TOKEN_RE = /^[a-zA-Z0-9_-]+$/;

  /**
   * Validate a URL string and allow only http: and https: protocols.
   * Returns normalized href string on success, or null if invalid/unsafe.
   */
  function sanitizeUrl(url) {
    if (typeof url !== 'string') {
      return null;
    }
    const trimmed = url.trim();
    if (!trimmed) {
      return null;
    }
    try {
      const parsed = new URL(trimmed);
      if (!ALLOWED_PROTOCOLS.has(parsed.protocol)) {
        return null;
      }
      return parsed.href;
    } catch (_err) {
      return null;
    }
  }

  function sanitizeClassAttr(value) {
    if (typeof value !== 'string') {
      return '';
    }
    return value
      .split(/\s+/)
      .filter((token) => token && SAFE_CLASS_TOKEN_RE.test(token))
      .join(' ');
  }

  function sanitizeNodeInto(node, parent, targetDoc) {
    // Node.TEXT_NODE === 3
    if (node.nodeType === 3) {
      parent.appendChild(targetDoc.createTextNode(node.nodeValue || ''));
      return;
    }

    // Node.ELEMENT_NODE === 1
    if (node.nodeType !== 1) {
      return;
    }

    const tag = String(node.tagName || '').toLowerCase();
    if (!tag || DROP_CONTENT_TAGS.has(tag)) {
      return;
    }

    if (!ALLOWED_TAGS.has(tag)) {
      for (const child of Array.from(node.childNodes || [])) {
        sanitizeNodeInto(child, parent, targetDoc);
      }
      return;
    }

    const cleanEl = targetDoc.createElement(tag);

    if (tag === 'a') {
      const safeHref = sanitizeUrl(node.getAttribute('href'));
      if (safeHref) {
        cleanEl.setAttribute('href', safeHref);
        cleanEl.setAttribute('target', '_blank');
        cleanEl.setAttribute('rel', 'noopener noreferrer');
      }
    }

    const rawClass = node.getAttribute('class');
    if (rawClass) {
      const safeClass = sanitizeClassAttr(rawClass);
      if (safeClass) {
        cleanEl.setAttribute('class', safeClass);
      }
    }

    for (const child of Array.from(node.childNodes || [])) {
      sanitizeNodeInto(child, cleanEl, targetDoc);
    }

    parent.appendChild(cleanEl);
  }

  /**
   * Parse dirty HTML using DOMParser and return a sanitized DocumentFragment.
   */
  function sanitizeHtmlToFragment(dirtyHtml, targetDoc) {
    const doc = targetDoc || (typeof document !== 'undefined' ? document : null);
    if (!doc) {
      throw new Error('sanitizeHtmlToFragment requires a DOM document');
    }

    const fragment = doc.createDocumentFragment();
    if (typeof dirtyHtml !== 'string' || !dirtyHtml) {
      return fragment;
    }

    const Parser = root.DOMParser || (typeof DOMParser !== 'undefined' ? DOMParser : null);
    if (!Parser) {
      fragment.appendChild(doc.createTextNode(dirtyHtml));
      return fragment;
    }

    const parsedDoc = new Parser().parseFromString(dirtyHtml, 'text/html');
    const body = parsedDoc && parsedDoc.body;
    if (!body) {
      return fragment;
    }

    for (const child of Array.from(body.childNodes || [])) {
      sanitizeNodeInto(child, fragment, doc);
    }

    return fragment;
  }

  /**
   * Sanitize an HTML string and return a safe HTML string.
   */
  function sanitizeHtml(dirtyHtml, targetDoc) {
    const doc = targetDoc || (typeof document !== 'undefined' ? document : null);
    if (!doc) {
      throw new Error('sanitizeHtml requires a DOM document');
    }
    const container = doc.createElement('div');
    container.appendChild(sanitizeHtmlToFragment(dirtyHtml, doc));
    return container.innerHTML;
  }

  /**
   * Replace an element's contents with sanitized DOM nodes (avoids re-parsing innerHTML).
   */
  function setSanitizedHtml(targetEl, dirtyHtml) {
    if (!targetEl) {
      return;
    }
    targetEl.textContent = '';
    const fragment = sanitizeHtmlToFragment(dirtyHtml, targetEl.ownerDocument);
    targetEl.appendChild(fragment);
  }

  const api = {
    ALLOWED_TAGS,
    DROP_CONTENT_TAGS,
    sanitizeUrl,
    sanitizeHtml,
    sanitizeHtmlToFragment,
    setSanitizedHtml
  };

  if (root) {
    root.sanitizeUrl = sanitizeUrl;
    root.sanitizeHtml = sanitizeHtml;
    root.sanitizeHtmlToFragment = sanitizeHtmlToFragment;
    root.setSanitizedHtml = setSanitizedHtml;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);
