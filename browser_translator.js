/*
 * Paradox AI Translator - Browser-Side Translation & Glossary Engine (JavaScript)
 * Compiled & UMD-compatible runtime from browser_translator.ts.
 * Exposes `window.ParadoxBrowserEngine` in browsers and `module.exports` in Node.js.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.ParadoxBrowserEngine = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const ENTRY_RE = /^(\s*[^#\s][^"\r\n]*?:\s*\d*\s*)"((?:\\.|[^"\\])*)"("*)([ \t]*(?:#[^\r\n]*)?)(\r?\n)?$/;
  const TOKENS_RE = /\$[^$\r\n]*\$|\[[^\]\r\n]*\]|£[^£\s]+£?|@[A-Za-z0-9_]+!?|§(?:[^\r\n]|$)|#(?:[A-Za-z][A-Za-z0-9_]*|!)|\\+(?:[nrt"]|\\)/g;
  const WORD_RE = /[A-Za-z][A-Za-z'-]*/g;
  const PROPER_PHRASE_RE = /\b[A-Z][A-Za-z'-]{2,}(?:\s+(?:of\s+|the\s+)?[A-Z][A-Za-z'-]{2,}){0,3}\b/g;
  const CHINESE_PHRASE_RE = /[\u4e00-\u9fff]{2,8}/g;

  const ENGLISH_STOPWORDS = new Set([
    'a', 'an', 'the', 'and', 'or', 'but', 'if', 'then', 'else', 'when', 'at', 'by', 'for', 'with',
    'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 'above', 'below',
    'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further',
    'once', 'here', 'there', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few', 'more',
    'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
    'too', 'very', 'can', 'will', 'just', 'should', 'now', 'is', 'are', 'was', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'would',
    'could', 'might', 'must', 'shall', 'may', 'this', 'that', 'these', 'those', 'it', 'its',
    'they', 'them', 'their', 'theirs', 'we', 'us', 'our', 'ours', 'you', 'your', 'yours',
    'he', 'him', 'his', 'she', 'her', 'hers', 'who', 'whom', 'whose', 'which', 'what',
    'one', 'two', 'three', 'new', 'old', 'also', 'even', 'still', 'yet', 'every', 'much',
    'many', 'well', 'back', 'gain', 'lose', 'add', 'remove'
  ]);

  function canonicalKey(key) {
    return String(key || '').split(':', 1)[0].trim();
  }

  function cleanEnglishForGlossary(text) {
    if (typeof text !== 'string') return '';
    return text.replace(TOKENS_RE, ' ').replace(/\s+/g, ' ').trim();
  }

  function countWords(cleaned) {
    return cleaned.match(WORD_RE) || [];
  }

  function isTokenOnly(text) {
    if (typeof text !== 'string') return true;
    const stripped = text.replace(TOKENS_RE, '');
    return !/[A-Za-z]/.test(stripped);
  }

  function parseYmlEntries(files) {
    const result = [];
    for (const [filename, content] of Object.entries(files || {})) {
      const cleanContent = String(content || '').replace(/^\uFEFF/, '');
      const lines = cleanContent.split(/(?<=\n)/);
      lines.forEach((line, idx) => {
        const m = ENTRY_RE.exec(line);
        if (m) {
          const prefix = m[1];
          const rawText = m[2];
          const suffix = m[4] || '';
          const newline = m[5] || '';
          const key = prefix.trimStart();
          result.push({
            source_file: filename,
            key,
            canonical_key: canonicalKey(key),
            text: rawText,
            line: idx + 1,
            original_line: line.replace(/\r?\n$/, ''),
            prefix,
            suffix,
            newline
          });
        }
      });
    }
    return result;
  }

  function extractGlossaryCandidates(entries, existingTranslations = {}, extractMode = 'short_keys', minCount = 2, maxTerms = 0) {
    const shortCounts = new Map();
    const shortDisplay = new Map();
    const shortTrans = new Map();
    const allCleaned = [];

    for (const row of entries || []) {
      const raw = String(row.text ?? row.english ?? '').trim();
      if (!raw) continue;
      const cleaned = cleanEnglishForGlossary(raw);
      if (!cleaned) continue;
      const words = countWords(cleaned);
      if (!words.length) continue;
      allCleaned.push(cleaned);

      if (words.length >= 1 && words.length < 5 && cleaned.length <= 80) {
        const phrase = words.join(' ');
        const folded = phrase.toLowerCase();
        if (!ENGLISH_STOPWORDS.has(folded) && !words.every(w => ENGLISH_STOPWORDS.has(w.toLowerCase()))) {
          shortCounts.set(folded, (shortCounts.get(folded) || 0) + 1);
          const existingDisp = shortDisplay.get(folded);
          if (!existingDisp || (/^[A-Z]/.test(phrase) && !/^[A-Z]/.test(existingDisp))) {
            shortDisplay.set(folded, phrase);
          }
          const zh = row.chinese || existingTranslations[raw] || existingTranslations[phrase];
          if (zh && !shortTrans.has(folded)) {
            shortTrans.set(folded, zh);
          }
        }
      }
    }

    const resultsByFolded = new Map();
    const sortedShort = Array.from(shortCounts.entries()).sort((a, b) => b[1] - a[1]);
    for (const [folded, count] of sortedShort) {
      if (count < minCount) continue;
      const display = shortDisplay.get(folded) || folded;
      const zh = shortTrans.get(folded) || '';
      resultsByFolded.set(folded, {
        term: display,
        translation: zh,
        count,
        source_mode: 'short_keys',
        enabled: true,
        approved: Boolean(zh),
        note: `短键值高频术语（<5词，出现 ${count} 次）`
      });
      if (maxTerms > 0 && resultsByFolded.size >= maxTerms) break;
    }

    if (extractMode === 'long_extract' || extractMode === 'ai_extract') {
      const longCounts = new Map();
      const longDisplay = new Map();

      for (const cleaned of allCleaned) {
        const words = countWords(cleaned);
        const properMatches = cleaned.match(PROPER_PHRASE_RE) || [];
        for (const m of properMatches) {
          const phrase = m.trim().replace(/\s+/g, ' ');
          const pWords = countWords(phrase);
          if (pWords.length < 1 || pWords.length >= 5) continue;
          const folded = phrase.toLowerCase();
          if (ENGLISH_STOPWORDS.has(folded) || pWords.every(w => ENGLISH_STOPWORDS.has(w.toLowerCase()))) continue;
          longCounts.set(folded, (longCounts.get(folded) || 0) + 1);
          if (!longDisplay.has(folded)) longDisplay.set(folded, phrase);
        }
        if (words.length >= 5) {
          for (const w of words) {
            if (w.length < 4) continue;
            const folded = w.toLowerCase();
            if (ENGLISH_STOPWORDS.has(folded)) continue;
            longCounts.set(folded, (longCounts.get(folded) || 0) + 1);
            const prev = longDisplay.get(folded);
            if (!prev || (/^[A-Z]/.test(w) && !/^[A-Z]/.test(prev))) {
              longDisplay.set(folded, w);
            }
          }
        }
      }

      const sortedLong = Array.from(longCounts.entries()).sort((a, b) => b[1] - a[1]);
      for (const [folded, count] of sortedLong) {
        if (count < minCount) continue;
        const existing = resultsByFolded.get(folded);
        if (existing) {
          if (count > existing.count) existing.count = count;
          continue;
        }
        if (maxTerms > 0 && resultsByFolded.size >= maxTerms) break;
        const display = longDisplay.get(folded) || folded;
        const zh = existingTranslations[display] || '';
        resultsByFolded.set(folded, {
          term: display,
          translation: zh,
          count,
          source_mode: 'long_extract',
          enabled: true,
          approved: Boolean(zh),
          note: `长键值词云提取（出现 ${count} 次）`
        });
      }
    }

    return Array.from(resultsByFolded.values()).sort((a, b) => {
      const priA = a.source_mode === 'short_keys' ? 0 : 1;
      const priB = b.source_mode === 'short_keys' ? 0 : 1;
      if (priA !== priB) return priA - priB;
      if (b.count !== a.count) return b.count - a.count;
      return a.term.toLowerCase().localeCompare(b.term.toLowerCase());
    });
  }

  function extractGlossaryFromPackagePairs(englishEntries, translatedEntries, maxTerms = 0) {
    const byKey = new Map();
    for (const t of translatedEntries || []) {
      const ck = canonicalKey(t.key);
      const txt = String(t.text || '').trim();
      if (ck && txt && !byKey.has(ck)) byKey.set(ck, txt);
    }
    const counts = new Map();
    const display = new Map();
    const trans = new Map();

    for (const e of englishEntries || []) {
      const ck = canonicalKey(e.key);
      const zh = byKey.get(ck);
      if (!zh) continue;
      const cleaned = cleanEnglishForGlossary(e.text || '');
      const words = countWords(cleaned);
      if (words.length < 1 || words.length >= 5 || cleaned.length > 80) continue;
      const phrase = words.join(' ');
      const folded = phrase.toLowerCase();
      if (ENGLISH_STOPWORDS.has(folded)) continue;
      counts.set(folded, (counts.get(folded) || 0) + 1);
      if (!display.has(folded)) display.set(folded, phrase);
      if (!trans.has(folded)) trans.set(folded, zh);
    }

    const list = [];
    for (const [folded, count] of Array.from(counts.entries()).sort((a, b) => b[1] - a[1])) {
      list.push({
        term: display.get(folded) || folded,
        translation: trans.get(folded) || '',
        count,
        source_mode: 'package_import',
        enabled: true,
        approved: true,
        note: `导入包直接提取（<5词短键值，出现 ${count} 次）`
      });
      if (maxTerms > 0 && list.length >= maxTerms) break;
    }
    return list;
  }

  function extractChineseRepeatsLocal(ymlEntries, maxTerms = 100) {
    const zhCounts = new Map();
    for (const item of ymlEntries || []) {
      const zhText = String(item.text || '').replace(TOKENS_RE, ' ').trim();
      if (!zhText) continue;
      const matches = zhText.match(CHINESE_PHRASE_RE) || [];
      for (const frag of matches) {
        zhCounts.set(frag, (zhCounts.get(frag) || 0) + 1);
      }
    }
    return Array.from(zhCounts.entries())
      .filter(([, cnt]) => cnt >= 2)
      .sort((a, b) => b[1] - a[1])
      .slice(0, maxTerms)
      .map(([zh, count]) => ({
        term: zh,
        translation: zh,
        count,
        source_mode: 'yml_ai_import',
        enabled: true,
        approved: true,
        note: `纯 YML 高频中文词云（出现 ${count} 次）`
      }));
  }

  function formatGlossaryPromptForBatch(batchTexts, glossary, language = 'zh-CN') {
    const combined = (batchTexts || []).join('\n').toLowerCase();
    const entries = Object.entries(glossary || {}).sort((a, b) => b[0].length - a[0].length);
    const matched = [];
    for (const [term, translation] of entries) {
      if (!term || !translation) continue;
      if (combined.includes(term.toLowerCase())) {
        matched.push(`- ${term} = ${translation}`);
        if (matched.length >= 80) break;
      }
    }
    if (!matched.length) return '';
    const header = language === 'zh-TW'
      ? '\n\n【本批術語表（若原文出現以下術語，請嚴格採用指定譯名以保持全 Mod 統一）】：\n'
      : '\n\n【本批术语表（若原文出现以下术语，请严格采用指定译名以保持全 Mod 统一）】：\n';
    return header + matched.join('\n');
  }

  return {
    canonicalKey,
    cleanEnglishForGlossary,
    countWords,
    isTokenOnly,
    parseYmlEntries,
    extractGlossaryCandidates,
    extractGlossaryFromPackagePairs,
    extractChineseRepeatsLocal,
    formatGlossaryPromptForBatch
  };
});
