/* UI strings stay separate from Mod content; only the locale is persisted. */
(() => {
  const supported = ['zh-CN', 'en', 'zh-TW', 'ru', 'ko', 'ja'];
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

  let allCatalogs = {}, catalog = {}, fallbackCatalog = {}, phrasePattern = null;
  const originals = new WeakMap();
  const excluded = 'script,style,textarea,pre,code,.path,.entry-text,.entry-key,.mod strong,#selection h2,[data-i18n-skip]';

  function text(value) {
    if (!value || typeof value !== 'string') return value;
    const trimmed = value.trim();
    if (Object.hasOwn(catalog, trimmed)) return value.replace(trimmed, catalog[trimmed]);
    // Fallback to English or default if translation missing for this language
    if (language !== 'zh-CN' && language !== 'en' && fallbackCatalog && Object.hasOwn(fallbackCatalog, trimmed)) {
      return value.replace(trimmed, fallbackCatalog[trimmed]);
    }
    // Dynamic counts/headings contain known UI phrases and untouched data.
    return phrasePattern ? value.replace(phrasePattern, match => catalog[match] || (fallbackCatalog && fallbackCatalog[match]) || match) : value;
  }
  window.workshopText = text;

  // Key-value translation lookup with fallback & param interpolation
  window.t = function(key, fallback, params) {
    if (typeof fallback === 'object' && fallback !== null && params === undefined) {
      params = fallback;
      fallback = undefined;
    }
    let res = null;
    if (catalog && Object.hasOwn(catalog, key)) res = catalog[key];
    else if (fallbackCatalog && Object.hasOwn(fallbackCatalog, key)) res = fallbackCatalog[key];
    else if (allCatalogs && allCatalogs['en'] && Object.hasOwn(allCatalogs['en'], key)) res = allCatalogs['en'][key];
    else if (allCatalogs && allCatalogs['zh-CN'] && Object.hasOwn(allCatalogs['zh-CN'], key)) res = allCatalogs['zh-CN'][key];
    else res = fallback !== undefined ? fallback : key;
    if (params && typeof res === 'string') {
      for (const [pKey, pVal] of Object.entries(params)) {
        res = res.replaceAll('{' + pKey + '}', pVal);
      }
    }
    return res;
  };

  const defaultGames = {st:'群星', hoi4:'钢铁雄心4', eu4:'欧陆风云4', ck3:'十字军之王3', vic3:'维多利亚3'};
  window.getGameName = function(code) {
    return window.t('games.' + code, defaultGames[code] || code);
  };
  window.getGamesMap = function() {
    const map = {};
    for (const c of Object.keys(defaultGames)) map[c] = window.getGameName(c);
    return map;
  };

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
      if (node.hasAttribute('data-i18n')) {
        const k = node.getAttribute('data-i18n');
        const trans = window.t(k, null);
        if (trans) {
          node.textContent = trans;
          return;
        }
      }
      if (node.hasAttribute('data-i18n-val')) {
        const k = node.getAttribute('data-i18n-val');
        const trans = window.t(k, null);
        if (trans) node.value = trans;
      }
      if (node.hasAttribute('data-i18n-ph')) {
        const k = node.getAttribute('data-i18n-ph');
        const trans = window.t(k, null);
        if (trans) node.placeholder = trans;
      }
      if (node.hasAttribute('data-i18n-title')) {
        const k = node.getAttribute('data-i18n-title');
        const trans = window.t(k, null);
        if (trans) {
          node.title = trans;
          if (node.hasAttribute('aria-label')) node.setAttribute('aria-label', trans);
        }
      }
      if (node.tagName === 'INPUT' && (node.disabled || node.readOnly || node.type === 'button')) {
        const val = node.getAttribute('value');
        if (val) {
          const rendered = text(val);
          if (val !== rendered) node.value = rendered;
        }
      }
      if (node.matches(excluded) && node.tagName !== 'TEXTAREA') return;
      for (const name of ['title', 'placeholder', 'aria-label']) {
        if (node.hasAttribute(name)) {
          const value = node.getAttribute(name), rendered = text(value);
          if (value !== rendered) node.setAttribute(name, rendered);
        }
      }
      if (node.tagName === 'TEXTAREA') return;
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
      attributes:true, attributeFilter:['title', 'placeholder', 'aria-label', 'value']});
  }

  function updateHint() {
    const hint = document.getElementById('language_hint');
    if (hint) {
      hint.dataset.i18nSkip = '';
      const fallbackMap = {
        'zh-CN': '目标语言：简体中文',
        'en': 'Target language: English (Localisation slot: english)',
        'zh-TW': '繁體中文使用遊戲的簡體中文語言槽；請在遊戲內選擇中文。',
        'ru': 'Язык перевода: русский. Выберите русский язык в игре.',
        'ko': '번역 언어: 한국어. 게임의 한국어 지원 여부를 확인하세요.',
        'ja': '翻訳先：日本語。ゲームの日本語対応を確認してください。'
      };
      hint.textContent = window.t('hint.' + language, fallbackMap[language] || `目标语言：${language}`);
    }
  }
  updateHint();

  const select = document.getElementById('workshop_language');
  if (select) {
    select.value = language;
    select.onchange = async () => {
      const previous = language, next = select.value;
      if (!supported.includes(next)) return;
      if (typeof state !== 'undefined' && Object.values(state?.jobs || {}).some(job => job.running)) {
        select.value = previous;
        toast(window.t('toast.wait_task_lang', '请等待任务完成后切换语言'));
        return;
      }
      select.disabled = true;
      window.workshopLanguage = next;
      try {
        await api('state');
        localStorage.setItem('workshop_language', next);
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
    allCatalogs = languages;
    for (const code of Object.keys(languages)) {
      if (!supported.includes(code)) supported.push(code);
    }
    if (select) {
      for (const [code, cat] of Object.entries(languages)) {
        if (!select.querySelector(`option[value="${code}"]`)) {
          const opt = document.createElement('option');
          opt.value = code;
          opt.textContent = (typeof cat === 'object' && cat['__lang_name__']) || code;
          select.appendChild(opt);
        }
      }
      select.value = language;
    }
    catalog = languages[language] || {};
    fallbackCatalog = languages['en'] || languages['zh-CN'] || {};
    const keys = Object.keys(catalog).filter(k => !k.includes('.')).sort((a, b) => b.length - a.length);
    phrasePattern = keys.length ? new RegExp(keys.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g') : null;
    translateNode(document.documentElement);
    updateHint();
    observe();
  }).catch(error => {
    console.error('Localization:', error.message);
    if (select) select.title = 'Language catalog unavailable; reload to retry.';
  });
})();
