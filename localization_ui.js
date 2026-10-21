/* UI strings stay separate from Mod content; only the locale is persisted. */
(() => {
  const supported = ['zh-CN', 'zh-TW', 'ru'];
  let language = 'zh-CN';
  try { language = localStorage.getItem('workshop_language') || language; } catch (_) {}
  if (!supported.includes(language)) language = 'zh-CN';
  window.workshopLanguage = language;
  document.documentElement.lang = language;

  // Cover normal API calls, ZIP downloads and multipart uploads alike.
  const originalFetch = window.fetch.bind(window);
  window.fetch = (input, options = {}) => {
    const url = new URL(input instanceof Request ? input.url : input, location.href);
    if (url.origin === location.origin && url.pathname.startsWith('/api/')) {
      const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
      headers.set('X-Translation-Language', window.workshopLanguage);
      options = {...options, headers};
    }
    return originalFetch(input, options);
  };

  let catalog = {}, phrasePattern = null;
  const originals = new WeakMap();
  const excluded = 'script,style,textarea,pre,code,.path,.entry-text,.entry-key,.mod strong,#selection h2,[data-i18n-skip]';
  function text(value) {
    const trimmed = value.trim();
    if (Object.hasOwn(catalog, trimmed)) return value.replace(trimmed, catalog[trimmed]);
    // Dynamic counts/headings contain known UI phrases and untouched data.
    return phrasePattern ? value.replace(phrasePattern, match => catalog[match]) : value;
  }
  window.workshopText = text;
  function translateNode(node) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (!node.parentElement || node.parentElement.closest(excluded)) return;
      const old = originals.get(node);
      const original = old && node.nodeValue === old.rendered ? old.original : node.nodeValue;
      const rendered = text(original);
      originals.set(node, {original, rendered});
      if (node.nodeValue !== rendered) node.nodeValue = rendered;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_NODE) return;
    if (node.nodeType === Node.ELEMENT_NODE) {
      if (node.matches(excluded)) return;
      for (const name of ['title', 'placeholder', 'aria-label']) {
        if (node.hasAttribute(name)) {
          const value = node.getAttribute(name), rendered = text(value);
          if (value !== rendered) node.setAttribute(name, rendered);
        }
      }
    }
    for (const child of node.childNodes) translateNode(child);
  }
  const observer = new MutationObserver(records => {
    observer.disconnect();
    for (const record of records) {
      if (record.type === 'characterData') translateNode(record.target);
      else if (record.type === 'attributes') translateNode(record.target);
      else for (const node of record.addedNodes) translateNode(node);
    }
    observe();
  });
  function observe() {
    observer.observe(document.documentElement, {subtree:true, childList:true, characterData:true,
      attributes:true, attributeFilter:['title', 'placeholder', 'aria-label']});
  }
  const hint = document.getElementById('language_hint');
  if (hint) hint.textContent = language === 'zh-TW' ? '繁體中文使用遊戲的簡體中文語言槽；請在遊戲內選擇中文。' : language === 'ru' ? 'Язык перевода: русский. Выберите русский язык в игре.' : '目标语言：简体中文';
  const select = document.getElementById('workshop_language');
  if (select) {
    select.value = language;
    select.onchange = async () => {
      const previous = language, next = select.value;
      if (!supported.includes(next)) return;
      if (typeof state !== 'undefined' && Object.values(state?.jobs || {}).some(job => job.running)) {
        select.value = previous;
        toast(text('请等待任务完成后切换语言'));
        return;
      }
      select.disabled = true;
      window.workshopLanguage = next;
      try {
        await api('state');
        localStorage.setItem('workshop_language', next);
        // A fresh page clears unsaved keys and all language-specific UI state.
        location.reload();
      } catch (error) {
        window.workshopLanguage = previous;
        select.value = previous;
        select.disabled = false;
        toast(text(error.message));
      }
    };
  }
  window.i18nReady = originalFetch('/ui_languages.json').then(response => {
    if (!response.ok) throw Error('Language catalog unavailable');
    return response.json();
  }).then(languages => {
    catalog = languages[language] || {};
    const keys = Object.keys(catalog).sort((a, b) => b.length - a.length);
    phrasePattern = keys.length ? new RegExp(keys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g') : null;
    translateNode(document.documentElement);
    observe();
  }).catch(error => {
    console.error('Localization:', error.message);
    if (select) select.title = 'Language catalog unavailable; reload to retry.';
  });
})();
