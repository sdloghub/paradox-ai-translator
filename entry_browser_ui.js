/* Shares the local workbench's authenticated API and selected Mod. */
(() => {
  const t = (key, fallback, params) => (typeof window.t === 'function' ? window.t(key, fallback, params) : fallback);
  const getLabels = () => ({
    translated: t('entry.filter_translated', '已翻译'),
    untranslated: t('entry.filter_untranslated', '待翻译'),
    cached: t('entry.filter_cached', '已缓存'),
    format_error: t('entry.filter_format_error', '格式错误'),
    needs_update: t('entry.filter_needs_update', '需更新')
  });
  const view = {id:null, data:null, status:'all', query:'', page:1, request:0, loading:false, saving:false};
  let searchTimer;
  const drafts = new Map();
  let pendingEdit = null;
  let pendingTranslation = null;
  const chineseDrafts = new Map();
  const draftKey = (entryId, modId = view.id) => modId + '|' + entryId;

  function render() {
    const data = view.data;
    const busy = modBusy(view.id) || view.saving;
    const labels = getLabels();
    $('entry_loading').textContent = view.loading ? t('entry.loading', '正在读取索引…') : '';
    $('entry_scan').disabled = !view.id || busy || view.loading;
    $('entry_refresh').disabled = !view.id || view.loading;
    $('entry_query').disabled = !view.id;
    $('entry_prev').disabled = view.loading || !data || data.page <= 1;
    $('entry_next').disabled = view.loading || !data || data.page >= data.pages;
    const allLabel = t('entry.filter_all', '全部');
    $('entry_filters').innerHTML = ['all', ...Object.keys(labels)].map(status => {
      const count = status === 'all' ? Object.values(data?.counts || {}).reduce((a,b)=>a+b,0) : (data?.counts[status] || 0);
      return `<button type="button" class="entry-filter" data-entry-filter="${status}" aria-pressed="${view.status === status}" ${!view.id ? 'disabled' : ''}>${labels[status] || allLabel} <span>${count}</span></button>`;
    }).join('');
    document.querySelectorAll('[data-entry-filter]').forEach(button => button.onclick = () => {
      view.status = button.dataset.entryFilter; view.page = 1; load();
    });
    $('entry_note').textContent = !view.id ? t('entry.empty', '先在上方选择游戏和 Mod；展开此栏即可查看或修改文件条目。首次使用请扫描该 Mod。') : !data?.ready
      ? t('entry.no_index_note', '尚无条目索引。点击“扫描并更新条目”读取此 Mod；刷新目录不会自动扫描文本。')
      : t('entry.index_note', '{manual} 条人工标注。筛选优先使用手动状态；自动检测结果始终保留。标注只用于整理，不会修改译文或改变 AI 的缓存复用规则。英文变化后对应标注失效。{busy}{scan_state}', {
          manual: data.manual_count,
          busy: busy ? (' ' + t('entry.note_busy', '当前任务执行中，显示上次结果，暂不能标注。')) : '',
          scan_state: data.scan_state === '待复查' ? (' ' + t('entry.note_rescan', 'Mod 已更新，请重新扫描。')) : ''
        });
    $('entry_page').textContent = data?.ready ? t('entry.page_info', '匹配 {total} 条 · 第 {page} / {pages} 页', {total: data.total, page: data.page, pages: data.pages}) : '';
    $('entry_empty').hidden = !!data?.entries.length;
    $('entry_empty').textContent = !view.id ? t('entry.empty', '选择 Mod 后查看键名、英文、中文和状态。') : !data?.ready ? t('entry.scan_to_view', '扫描后可查看键值和中英文对照。') : t('entry.no_entries_filter', '当前筛选下没有条目。');
    $('entry_rows').innerHTML = (data?.entries || []).map(row => `
      <tr>
        <td><strong class="entry-key">${escapeText(row.entry_key)}</strong>
          <details class="entry-editor"><summary>${t('entry.edit_key_summary', '修改键值')}</summary><label for="key-${row.entry_id}">${t('entry.key_label', '键名（不含冒号及版本号）')}</label><input id="key-${row.entry_id}" data-key-edit="${row.entry_id}" value="${escapeText(row.entry_key)}" ${busy?'disabled':''}><button data-key-save="${row.entry_id}" ${busy?'disabled':''}>${t('entry.key_save_btn', '保存键值并重新扫描')}</button><div class="sub">${t('entry.key_sub_note', '只改当前行键名；原文件会先备份。游戏脚本中的引用需相应调整。')}</div></details><div class="path">${escapeText(row.source_file)}<br>${t('entry.line_num', '第 {line} 行', {line: row.line})}</div>
          <details class="entry-original"><summary>${t('entry.view_orig_line', '查看原文件行')}</summary><pre>${escapeText(row.original_line)}</pre></details></td>
        <td><div class="entry-text" lang="en">${escapeText(row.english)}</div>${row.reason ? `<div class="entry-error">${escapeText(row.reason)}</div>` : ''}
          <details class="entry-editor" ${drafts.has(draftKey(row.entry_id)) ? 'open' : ''}>
            <summary>${t('entry.edit_orig_line', '编辑原文件行')}</summary>
            <label for="edit-${row.entry_id}">${t('entry.orig_yml_label', '原始 YML 行（含键名和引号）')}</label>
            <textarea id="edit-${row.entry_id}" data-entry-edit="${row.entry_id}" rows="4" spellcheck="false" ${busy || view.loading ? 'disabled' : ''}>${escapeText(drafts.get(draftKey(row.entry_id)) ?? row.original_line)}</textarea>
            <div class="row"><button class="primary" data-entry-save="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>${t('entry.save_recheck_btn', '保存并重新扫描')}</button><button data-entry-reset="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>${t('entry.reset_input_btn', '撤销输入')}</button></div>
            <div class="sub">${t('entry.save_backup_note', '保存前备份原文件，随后自动复查，不调用 AI 翻译正文。')}</div>
          </details></td>
        <td><div class="entry-text">${escapeText(row.chinese || t('entry.no_chinese', '暂无中文'))}</div>${row.historical ? `<div class="entry-error">${t('entry.historical_trans', '历史译文：英文已变化，尚未验证适用性。')}</div>` : ''}<div class="sub">${escapeText(row.origin || '')}</div>
          ${['translated','cached'].includes(row.auto_status) && !row.historical ? `<details class="entry-editor" ${chineseDrafts.has(draftKey(row.entry_id)) ? 'open' : ''}>
            <summary>${t('entry.edit_chinese_summary', '修改中文译文')}</summary><label for="chinese-${row.entry_id}">${t('entry.chinese_trans_label', '中文译文（保留变量与格式标记）')}</label>
            <textarea id="chinese-${row.entry_id}" data-chinese-edit="${row.entry_id}" rows="4" spellcheck="false" ${busy || view.loading ? 'disabled' : ''}>${escapeText(chineseDrafts.get(draftKey(row.entry_id)) ?? row.chinese)}</textarea>
            <div class="row"><button class="primary" data-chinese-save="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>${row.auto_status === 'translated' ? t('entry.save_deploy_btn', '保存并回写中文') : t('entry.save_cache_btn', '保存中文缓存')}</button><button data-chinese-reset="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>${t('entry.reset_input_btn', '撤销输入')}</button></div>
            <div class="sub">${row.auto_status === 'translated' ? t('entry.trans_sub_deployed', '保留修订记录，备份后同步原 Mod；开发者模式下同步独立翻译 Mod。') : t('entry.trans_sub_cached', '只更新匹配当前英文的缓存，下次翻译自动复用。')}${t('entry.no_ai_note', '不调用 AI 翻译正文。')}</div>
          </details>` : ''}</td>
        <td><span class="entry-badge ${row.status}">${labels[row.status]}</span><div class="sub">${t('entry.auto_prefix', '自动：')}${labels[row.auto_status]}</div>
          <label class="entry-status-label" for="mark-${row.entry_id}">${t('entry.manual_mark_label', '手动标注')}</label>
          <select id="mark-${row.entry_id}" data-entry-mark="${row.entry_id}" ${busy || view.loading ? 'disabled' : ''}>
            <option value="" ${!row.manual_status ? 'selected' : ''}>${t('entry.mark_auto_follow', '跟随自动检测')}</option>
            ${Object.entries(labels).map(([value,label])=>`<option value="${value}" ${row.manual_status === value ? 'selected' : ''}>${label}</option>`).join('')}
          </select></td>
      </tr>`).join('');
    document.querySelectorAll('[data-key-save]').forEach(button=>button.onclick=async()=>{
      if(modBusy(view.id)||view.saving)return;
      const modId=view.id,id=button.dataset.keySave,key=$('key-'+id).value;
      view.saving=true;render();
      try{await api('entry-key',{id:modId,entry_id:id,key});pendingEdit={id:modId,entry_id:id};await refresh();}
      catch(error){toast(error.message);}
      finally{view.saving=false;render();}
    });
    document.querySelectorAll('[data-entry-mark]').forEach(select => select.onchange = async () => {
      select.disabled = true;
      try {
        await api('entry-status', {id:view.id, entry_id:select.dataset.entryMark, status:select.value || null});
        await refresh();
        if (typeof renderMods === 'function') { renderMods(); renderSelection(); }
        await load();
        toast(t('entry.mark_saved_toast', '条目状态已保存并重新扫描更新目录状态；选择“跟随自动检测”可取消人工标注。'));
      } catch (error) { toast(error.message); render(); }
    });
    document.querySelectorAll('[data-entry-edit]').forEach(textarea => textarea.oninput = () => {
      const id = textarea.dataset.entryEdit;
      drafts.set(draftKey(id), textarea.value);
    });
    document.querySelectorAll('[data-chinese-edit]').forEach(textarea => textarea.oninput = () => {
      const id = textarea.dataset.chineseEdit;
      chineseDrafts.set(draftKey(id), textarea.value);
    });
    document.querySelectorAll('[data-entry-reset]').forEach(button => button.onclick = () => {
      const id = button.dataset.entryReset;
      drafts.delete(draftKey(id));
      render();
    });
    document.querySelectorAll('[data-chinese-reset]').forEach(button => button.onclick = () => {
      const id = button.dataset.chineseReset;
      chineseDrafts.delete(draftKey(id));
      render();
    });
    document.querySelectorAll('[data-entry-save]').forEach(button => button.onclick = async () => {
      if (modBusy(view.id) || view.saving) return;
      const modId = view.id; const id = button.dataset.entrySave;
      const line = drafts.get(draftKey(id));
      if (line === undefined) return;
      view.saving = true; render();
      try {
        await api('entry-edit', {id:modId, entry_id:id, line});
        pendingEdit = {id:modId, entry_id:id};
        await refresh();
      } catch (error) { toast(error.message); }
      finally { view.saving = false; render(); }
    });
    document.querySelectorAll('[data-chinese-save]').forEach(button => button.onclick = async () => {
      if (modBusy(view.id) || view.saving) return;
      const modId = view.id; const id = button.dataset.chineseSave;
      const text = chineseDrafts.get(draftKey(id));
      if (text === undefined) return;
      view.saving = true; render();
      try {
        await api('entry-translate', {id:modId, entry_id:id, text});
        pendingTranslation = {id:modId, entry_id:id};
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
        ? t('entry.backend_not_supported', '当前后台不支持条目接口。请退出旧程序，重新运行当前文件夹的启动脚本（Mac: setup_mac.command / Windows: start_windows.bat）。') : error.message);
    }
    finally { if (request === view.request) { view.loading = false; render(); } }
  }

  function clear() {
    view.id = null; view.data = null; ++view.request; view.loading = false;
    clearTimeout(searchTimer);
    $('entry_title').textContent = t('entry.title', '条目浏览库（查看 / 修改文件）');
    render();
  }
  function activate(mod) {
    view.id = mod.id; view.data = null; view.status = 'all'; view.query = ''; view.page = 1;
    $('entry_query').value = ''; $('entry_title').textContent = t('entry.title_with_mod', '条目浏览库（查看 / 修改文件） · {title}', {title: mod.title});
    $('entry_edit_result').hidden = true;
    load();
  }
  function open() {
    if (!state?.mods.some(mod => mod.id === selected)) return;
    const panel = $('entry_browser');
    if (panel && panel.tagName === 'DETAILS') panel.open = true;
    const mod = state?.mods.find(mod => mod.id === selected);
    if (mod && view.id !== mod.id) activate(mod);
    $('entry_title').focus({preventScroll:true});
    panel.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'start'});
  }
  $('browse_entries').onclick = open;
  if ($('open_entry_library')) $('open_entry_library').onclick = open;
  $('entry_close').onclick = () => {
    const panel = $('entry_browser');
    if (panel && panel.tagName === 'DETAILS') panel.open = false;
    $('selection').scrollIntoView({behavior:'smooth', block:'center'});
  };
  $('entry_refresh').onclick = async () => {
    if (!view.id) return;
    if (!modBusy(view.id)) {
      try { await api('analyze', {id:view.id}); await refresh(); } catch (error) { toast(error.message); }
    }
    await load();
  };
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
    const enabled = state.mods.some(mod => mod.id === selected);
    const summary = $('entry_browser').querySelector('summary');
    summary.setAttribute('aria-disabled', String(!enabled));
    summary.tabIndex = enabled ? 0 : -1;
    if (!enabled) $('entry_browser').open = false;
    let shouldReload = false;
    if (pendingEdit && modJob(pendingEdit.id).kind === 'edit-entry' && !modJob(pendingEdit.id).running) {
      const finished = pendingEdit; const job=modJob(finished.id); pendingEdit = null;
      if (!job.error && job.result) {
        const result = job.result;
        drafts.delete(draftKey(finished.entry_id, finished.id));
        const message = `${result.file} · ${t('entry.line_num', '第 {line} 行', {line: result.line})}：${result.parse_error ? t('entry.edit_saved_error_part', '已保存，复查仍有格式错误') : t('entry.edit_saved_ok_part', '已保存，复查未发现格式错误')}。${t('entry.current_err_count', '当前 Mod 格式错误 {count} 行。', {count: result.counts.parse_errors})}`;
        if (finished.id === view.id) {
          $('entry_edit_result').textContent = message + (result.backup_path ? (t('entry.backup_path_prefix', '\n原文件备份：') + result.backup_path) : '');
          $('entry_edit_result').dataset.error = String(result.parse_error);
          $('entry_edit_result').hidden = false;
        }
        toast(message);
        if (typeof renderMods === 'function') { renderMods(); renderSelection(); }
        shouldReload = true;
      }
    }
    if (pendingTranslation && modJob(pendingTranslation.id).kind === 'edit-translation' && !modJob(pendingTranslation.id).running) {
      const finished = pendingTranslation; const job=modJob(finished.id); pendingTranslation = null;
      if (!job.error && job.result) {
        const result = job.result;
        chineseDrafts.delete(draftKey(finished.entry_id, finished.id));
        const message = result.saved === false ? t('entry.trans_saved_same', '中文未变化，已重新扫描并同步目录状态。') : result.deployed ? t('entry.trans_saved_deployed', '中文已保存并回写原 Mod，旧文件已备份并重新扫描更新目录状态；开发者翻译 Mod 按开关设置同步。') : t('entry.trans_saved_cached', '中文缓存已保存并重新扫描更新目录状态，下次翻译自动复用；尚未回写 Mod。');
        if (finished.id === view.id) {
          $('entry_edit_result').textContent = message;
          $('entry_edit_result').dataset.error = 'false';
          $('entry_edit_result').hidden = false;
        }
        toast(message);
        if (typeof renderMods === 'function') { renderMods(); renderSelection(); }
        shouldReload = true;
      }
    }
    const selectedMod = state.mods.find(mod => mod.id === selected);
    if (selectedMod && selectedMod.id !== view.id) { activate(selectedMod); return; }
    if (!view.id) return;
    const mod = state.mods.find(mod => mod.id === view.id);
    if (selected !== view.id || !mod) { clear(); return; }
    if (shouldReload || (!view.loading && !modBusy(view.id) && mod.counts?.entry_revision && mod.counts.entry_revision !== view.data?.revision)) load();
    else {
      $('entry_scan').disabled = !!modBusy(view.id) || view.loading;
      document.querySelectorAll('[data-key-edit], [data-key-save], [data-entry-mark], [data-entry-edit], [data-entry-save], [data-entry-reset], [data-chinese-edit], [data-chinese-save], [data-chinese-reset]').forEach(control => control.disabled = !!modBusy(view.id) || view.loading || view.saving);
    }
  };
  render();
  $('entry_browser').querySelector('summary').addEventListener('click', event => {
    if (!state?.mods.some(mod => mod.id === selected)) event.preventDefault();
  });
  window.syncEntryBrowser();
})();
