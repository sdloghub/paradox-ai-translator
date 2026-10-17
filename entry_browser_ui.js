/* Shares the local workbench's authenticated API and selected Mod. */
(() => {
  const labels = {translated:'已翻译', untranslated:'未翻译', cached:'已缓存', format_error:'格式错误', needs_update:'需更新'};
  const view = {id:null, data:null, status:'all', query:'', page:1, request:0, loading:false, saving:false};
  let searchTimer;
  const drafts = new Map();
  let pendingEdit = null;
  let pendingTranslation = null;
  const chineseDrafts = new Map();
  const draftKey = (entryId, modId = view.id) => modId + '|' + entryId;

  function render() {
    const data = view.data;
    const busy = !!state?.job.running || view.saving;
    $('entry_loading').textContent = view.loading ? '正在读取索引…' : '';
    $('entry_scan').disabled = !view.id || busy || view.loading;
    $('entry_refresh').disabled = !view.id || view.loading;
    $('entry_query').disabled = !view.id;
    $('entry_prev').disabled = view.loading || !data || data.page <= 1;
    $('entry_next').disabled = view.loading || !data || data.page >= data.pages;
    $('entry_filters').innerHTML = ['all', ...Object.keys(labels)].map(status => {
      const count = status === 'all' ? Object.values(data?.counts || {}).reduce((a,b)=>a+b,0) : (data?.counts[status] || 0);
      return `<button type="button" class="entry-filter" data-entry-filter="${status}" aria-pressed="${view.status === status}" ${!view.id ? 'disabled' : ''}>${labels[status] || '全部'} <span>${count}</span></button>`;
    }).join('');
    document.querySelectorAll('[data-entry-filter]').forEach(button => button.onclick = () => {
      view.status = button.dataset.entryFilter; view.page = 1; load();
    });
    $('entry_note').textContent = !view.id ? '先在上方选择游戏和 Mod；展开此栏即可查看或修改文件条目。首次使用请扫描该 Mod。' : !data?.ready
      ? '尚无条目索引。点击“扫描并更新条目”读取此 Mod；刷新目录不会自动扫描文本。'
      : `${data.manual_count} 条人工标注。筛选优先使用手动状态；自动检测结果始终保留。标注只用于整理，不会修改译文或改变 AI 的缓存复用规则。英文变化后对应标注失效。${busy ? ' 当前任务执行中，显示上次结果，暂不能标注。' : ''}${data.scan_state === '待复查' ? ' Mod 已更新，请重新扫描。' : ''}`;
    $('entry_page').textContent = data?.ready ? `匹配 ${data.total} 条 · 第 ${data.page} / ${data.pages} 页 · 每页 ${data.page_size} 条` : '';
    $('entry_empty').hidden = !!data?.entries.length;
    $('entry_empty').textContent = !view.id ? '选择 Mod 后查看键名、英文、中文和状态。' : !data?.ready ? '扫描后可查看键值和中英文对照。' : '当前筛选下没有条目。';
    $('entry_rows').innerHTML = (data?.entries || []).map(row => `
      <tr>
        <td><strong class="entry-key">${escapeText(row.entry_key)}</strong><div class="path">${escapeText(row.source_file)}<br>第 ${row.line} 行</div>
          <details class="entry-original"><summary>查看原文件行</summary><pre>${escapeText(row.original_line)}</pre></details></td>
        <td><div class="entry-text" lang="en">${escapeText(row.english)}</div>${row.reason ? `<div class="entry-error">${escapeText(row.reason)}</div>` : ''}
          <details class="entry-editor" ${drafts.has(draftKey(row.entry_id)) ? 'open' : ''}>
            <summary>编辑原文件行</summary>
            <label for="edit-${row.entry_id}">原始 YML 行（含键名和引号）</label>
            <textarea id="edit-${row.entry_id}" data-entry-edit="${row.entry_id}" rows="4" spellcheck="false" ${busy || view.loading ? 'disabled' : ''}>${escapeText(drafts.get(draftKey(row.entry_id)) ?? row.original_line)}</textarea>
            <div class="row"><button class="primary" data-entry-save="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>保存并重新扫描</button><button data-entry-reset="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>撤销输入</button></div>
            <div class="sub">保存前备份原文件，随后自动复查，不调用 AI。</div>
          </details></td>
        <td><div class="entry-text">${escapeText(row.chinese || '暂无中文')}</div>${row.historical ? '<div class="entry-error">历史译文：英文已变化，尚未验证适用性。</div>' : ''}<div class="sub">${escapeText(row.origin || '')}</div>
          ${['translated','cached'].includes(row.auto_status) && !row.historical ? `<details class="entry-editor" ${chineseDrafts.has(draftKey(row.entry_id)) ? 'open' : ''}>
            <summary>修改中文译文</summary><label for="chinese-${row.entry_id}">中文译文（保留变量与格式标记）</label>
            <textarea id="chinese-${row.entry_id}" data-chinese-edit="${row.entry_id}" rows="4" spellcheck="false" ${busy || view.loading ? 'disabled' : ''}>${escapeText(chineseDrafts.get(draftKey(row.entry_id)) ?? row.chinese)}</textarea>
            <div class="row"><button class="primary" data-chinese-save="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>${row.auto_status === 'translated' ? '保存并回写中文' : '保存中文缓存'}</button><button data-chinese-reset="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>撤销输入</button></div>
            <div class="sub">${row.auto_status === 'translated' ? '保留修订记录，备份后同步原 Mod 与已开启的聚合目录。' : '只更新匹配当前英文的缓存，下次翻译自动复用。'}不调用 AI。</div>
          </details>` : ''}</td>
        <td><span class="entry-badge ${row.status}">${labels[row.status]}</span><div class="sub">自动：${labels[row.auto_status]}</div>
          <label class="entry-status-label" for="mark-${row.entry_id}">手动标注</label>
          <select id="mark-${row.entry_id}" data-entry-mark="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>
            <option value="" ${!row.manual_status ? 'selected' : ''}>跟随自动检测</option>
            ${Object.entries(labels).map(([value,label])=>`<option value="${value}" ${row.manual_status === value ? 'selected' : ''}>${label}</option>`).join('')}
          </select></td>
      </tr>`).join('');
    document.querySelectorAll('[data-entry-mark]').forEach(select => select.onchange = async () => {
      select.disabled = true;
      try {
        await api('entry-status', {id:view.id, entry_id:select.dataset.entryMark, status:select.value || null});
        await load();
        toast('条目状态已保存；选择“跟随自动检测”可取消人工标注。');
      } catch (error) { toast(error.message); render(); }
    });
    document.querySelectorAll('[data-chinese-edit]').forEach(input => input.oninput = () => chineseDrafts.set(draftKey(input.dataset.chineseEdit), input.value));
    document.querySelectorAll('[data-chinese-reset]').forEach(button => button.onclick = () => {
      const id = button.dataset.chineseReset;
      chineseDrafts.delete(draftKey(id));
      $('chinese-' + id).value = view.data.entries.find(row => row.entry_id === id).chinese;
    });
    document.querySelectorAll('[data-chinese-save]').forEach(button => button.onclick = async () => {
      if (state.job.running || view.saving) return;
      const id = button.dataset.chineseSave, modId = view.id;
      const row = view.data.entries.find(row => row.entry_id === id);
      const text = $('chinese-' + id).value;
      chineseDrafts.set(draftKey(id, modId), text); view.saving = true; render();
      try {
        await api('translation-edit', {id:modId, entry_id:id, text, expected:row.chinese});
        pendingTranslation = {id:modId, entry_id:id};
        await refresh();
      } catch (error) { toast(error.message); }
      finally { view.saving = false; render(); }
    });
    document.querySelectorAll('[data-entry-edit]').forEach(input => input.oninput = () => drafts.set(draftKey(input.dataset.entryEdit), input.value));
    document.querySelectorAll('[data-entry-reset]').forEach(button => button.onclick = () => {
      const id = button.dataset.entryReset;
      drafts.delete(draftKey(id));
      $('edit-' + id).value = view.data.entries.find(row => row.entry_id === id).original_line;
    });
    document.querySelectorAll('[data-entry-save]').forEach(button => button.onclick = async () => {
      if (state.job.running || view.saving) return;
      const id = button.dataset.entrySave;
      const text = $('edit-' + id).value;
      const modId = view.id;
      drafts.set(draftKey(id, modId), text); view.saving = true; render();
      try {
        await api('entry-edit', {id:modId, entry_id:id, text});
        pendingEdit = {id:modId, entry_id:id};
        await refresh();
      } catch (error) { toast(error.message); }
      finally { view.saving = false; render(); }
    });
  }

  async function load() {
    if (!view.id) return;
    const request = ++view.request;
    view.loading = true; render();
    try {
      const data = await api('entries', {id:view.id, status:view.status, query:view.query, page:view.page});
      if (request !== view.request) return;
      view.data = data; view.page = data.page;
    } catch (error) {
      if (request === view.request) toast(error.message === '未找到'
        ? '当前后台不支持条目接口。请退出旧程序，重新运行当前文件夹的“启动翻译程序.command”。' : error.message);
    }
    finally { if (request === view.request) { view.loading = false; render(); } }
  }

  function clear() {
    view.id = null; view.data = null; ++view.request; view.loading = false;
    clearTimeout(searchTimer);
    $('entry_title').textContent = '条目浏览库（查看 / 修改文件）';
    render();
  }
  function activate(mod) {
    view.id = mod.id; view.data = null; view.status = 'all'; view.query = ''; view.page = 1;
    $('entry_query').value = ''; $('entry_title').textContent = `条目浏览库（查看 / 修改文件） · ${mod.title}`;
    $('entry_edit_result').hidden = true;
    load();
  }
  function open() {
    const panel = $('entry_browser');
    if (panel && panel.tagName === 'DETAILS') panel.open = true;
    const mod = state?.mods.find(mod => mod.id === selected);
    if (mod && view.id !== mod.id) activate(mod);
    $('entry_title').focus({preventScroll:true});
    panel.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'start'});
  }
  $('browse_entries').onclick = open;
  $('open_entry_library').onclick = open;
  $('entry_close').onclick = () => {
    const panel = $('entry_browser');
    if (panel && panel.tagName === 'DETAILS') panel.open = false;
    $('selection').scrollIntoView({behavior:'smooth', block:'center'});
  };
  $('entry_refresh').onclick = load;
  $('entry_prev').onclick = () => { --view.page; load(); };
  $('entry_next').onclick = () => { ++view.page; load(); };
  $('entry_query').oninput = () => {
    clearTimeout(searchTimer);
    view.query = $('entry_query').value; view.page = 1;
    searchTimer = setTimeout(load, 220);
  };
  $('entry_scan').onclick = async () => {
    try { await api('analyze', {id:view.id}); await refresh(); }
    catch (error) { toast(error.message); }
  };
  window.syncEntryBrowser = () => {
    if (!state) return;
    if (pendingEdit && state.job.kind === 'edit-entry' && !state.job.running) {
      const finished = pendingEdit; pendingEdit = null;
      if (!state.job.error && state.job.result) {
        const result = state.job.result;
        drafts.delete(draftKey(finished.entry_id, finished.id));
        const message = `${result.file} · 第 ${result.line} 行：${result.parse_error ? '已保存，复查仍有格式错误' : '已保存，复查未发现格式错误'}。当前 Mod 格式错误 ${result.counts.parse_errors} 行。`;
        if (finished.id === view.id) {
          $('entry_edit_result').textContent = message + (result.backup_path ? '\n原文件备份：' + result.backup_path : '');
          $('entry_edit_result').dataset.error = String(result.parse_error);
          $('entry_edit_result').hidden = false;
        }
        toast(message);
      }
    }
    if (pendingTranslation && state.job.kind === 'edit-translation' && !state.job.running) {
      const finished = pendingTranslation; pendingTranslation = null;
      if (!state.job.error && state.job.result) {
        const result = state.job.result;
        chineseDrafts.delete(draftKey(finished.entry_id, finished.id));
        const message = result.saved === false ? '中文未变化，无需保存。' : result.deployed ? '中文已保存并回写原 Mod，旧文件已备份；聚合副本按开关设置同步。' : '中文缓存已保存，下次翻译自动复用；尚未回写 Mod。';
        if (finished.id === view.id) {
          $('entry_edit_result').textContent = message;
          $('entry_edit_result').dataset.error = 'false';
          $('entry_edit_result').hidden = false;
        }
        toast(message);
      }
    }
    const selectedMod = state.mods.find(mod => mod.id === selected);
    if (selectedMod && selectedMod.id !== view.id) { activate(selectedMod); return; }
    if (!view.id) return;
    const mod = state.mods.find(mod => mod.id === view.id);
    if (selected !== view.id || !mod) { clear(); return; }
    if (!view.loading && !state.job.running && mod.counts?.entry_revision && mod.counts.entry_revision !== view.data?.revision) load();
    else {
      $('entry_scan').disabled = !!state.job.running || view.loading;
      document.querySelectorAll('[data-entry-mark], [data-entry-edit], [data-entry-save], [data-entry-reset], [data-chinese-edit], [data-chinese-save], [data-chinese-reset]').forEach(control => control.disabled = !!state.job.running || view.loading || view.saving);
    }
  };
  render();
  window.syncEntryBrowser();
})();
