// ==UserScript==
// @name         Workshop 简介文件导入
// @namespace    paradox-ai-translator
// @version      1.0.0
// @description  从 UTF-8 文本导入当前语言的简介，不自动保存
// @match        https://steamcommunity.com/sharedfiles/itemedittext/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(() => {
  'use strict';
  if (location.origin !== 'https://steamcommunity.com' ||
      !/^\/sharedfiles\/itemedittext\/?$/.test(location.pathname)) return;
  if (document.getElementById('translator-description-import')) return;
  const description = document.getElementById('description');
  const language = document.getElementById('language');
  if (!(description instanceof HTMLTextAreaElement) || !language) return;

  const panel = document.createElement('div');
  panel.id = 'translator-description-import';
  panel.style.cssText = 'padding:12px;margin:12px 0;border:1px solid #668096;color:#eee;display:grid;gap:8px';
  const label = document.createElement('strong');
  const note = document.createElement('span');
  note.textContent = '导入 UTF-8 的 .txt / .bbcode / .md；原样保留标记，不转换 Markdown。只修改简介，导入后请检查并点击 Steam 的“保存”。';
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.txt,.bbcode,.md,text/plain';
  input.setAttribute('aria-label', '选择简介文件');
  const undo = document.createElement('button');
  undo.type = 'button';
  undo.textContent = '撤销本次导入';
  undo.disabled = true;
  const status = document.createElement('span');
  status.setAttribute('role', 'status');
  let previous = null;
  let revision = 0;
  const selectedLanguage = () => language.options[language.selectedIndex]?.text || language.value;
  const refresh = () => {
    label.textContent = `工坊 ${new URL(location.href).searchParams.get('id') || '未知'} · 当前语言：${selectedLanguage()}`;
  };
  const notify = () => {
    description.dispatchEvent(new Event('input', { bubbles: true }));
    description.dispatchEvent(new Event('change', { bubbles: true }));
  };
  language.addEventListener('change', () => {
    revision++;
    previous = null;
    undo.disabled = true;
    input.value = '';
    status.textContent = '语言已切换，请为当前语言重新选择文件。';
    refresh();
  });
  input.addEventListener('change', async () => {
    const file = input.files[0];
    if (!file) return;
    const currentRevision = ++revision;
    const currentLanguage = language.value;
    const original = description.value;
    status.textContent = '正在读取文件…';
    try {
      if (!/\.(txt|bbcode|md)$/i.test(file.name)) throw new Error('请选择 .txt、.bbcode 或 .md 文件');
      if (file.size > 1024 * 1024) throw new Error('文件超过 1 MiB，请检查是否选错文件');
      const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      if (!text.trim()) throw new Error('简介文件为空');
      if (text.includes('\0')) throw new Error('文件包含空字符，不能导入');
      if (description.maxLength >= 0 && text.length > description.maxLength) throw new Error('简介超过当前编辑框的长度限制');
      if (currentRevision !== revision || currentLanguage !== language.value) return;
      if (description.value !== original) throw new Error('读取时简介已被修改，请重新选择文件');
      previous = { text: original, language: currentLanguage };
      description.value = text;
      notify();
      undo.disabled = false;
      status.textContent = `已导入 ${file.name}（${text.length} 字符），尚未保存到 Steam。`;
    } catch (error) {
      if (currentRevision === revision) status.textContent = `未导入：${error.message}`;
    } finally {
      if (currentRevision === revision) input.value = '';
    }
  });
  undo.addEventListener('click', () => {
    if (!previous || previous.language !== language.value) return;
    revision++;
    description.value = previous.text;
    notify();
    previous = null;
    undo.disabled = true;
    status.textContent = '已恢复导入前的简介，尚未保存到 Steam。';
  });
  refresh();
  panel.append(label, note, input, undo, status);
  description.before(panel);
})();
