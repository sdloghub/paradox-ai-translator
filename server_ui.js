/* Personal server controls; loaded only in --server-mode. */
(() => {
  window.serverWorkshopLinks = true;
  document.querySelector('h1').textContent = 'Paradox AI Translator';
  const headerSub = document.querySelector('header .sub');
  if (headerSub) {
    headerSub.innerHTML = 'Your world, Your word! · 面向五款 Paradox 游戏的在线创意工坊汉化工作台：保留变量、颜色与格式标记，只在英文哈希仍然匹配时复用旧译文。<div style="margin-top:4px"><a href="https://github.com/sdloghub/paradox-ai-translator" target="_blank" rel="noopener noreferrer" style="color:var(--accent);font-weight:500">GitHub: sdloghub/paradox-ai-translator</a></div>';
  }
  $('mode').className = '';
  $('mode').innerHTML = '<a href="#" id="tutorial_help">不会使用？</a>';
  $('tutorial_help').onclick = event => { event.preventDefault(); window.openWorkshopTutorial(); };
  $('open_tutorial').hidden = true;
  document.querySelector('.workflow').hidden = true;
  $('scan').hidden = true;
  // Shared refresh code still updates this node in server mode.
  if ($('storage')) $('storage').hidden = true;
  if ($('config_location')) $('config_location').hidden = true;
  const settings = $('settings');
  settings.querySelector('summary').textContent = '本次翻译 API';
  let field = settings.querySelector('[for="storage_mode"]');
  while (field) {
    field.dataset.savedSetting = '1';
    if (field === $('provider')) break;
    field = field.nextElementSibling;
  }
  $('save').parentElement.dataset.savedSetting = '1';
  $('save').textContent = '保存接口设置（不含密钥）';
  $('save').nextElementSibling.textContent = '仅开发者可保存非密钥设置；API Key 不保存。';
  $('libraries').hidden = true;
  $('libraries').previousElementSibling.hidden = true;
  $('api_key').previousElementSibling.textContent = 'API Key（仅用于本次翻译）';
  $('api_key').placeholder = '每次翻译前填写，不保存';
  const privacy = document.createElement('p');
  privacy.className = 'notice';
  privacy.textContent = '本站不会以任何形式保存用户 API Key，若不放心请使用一次性 API Key。密钥仅在本次翻译任务内存中临时使用，任务结束后清除，不写入配置、数据库、日志或浏览器存储。';
  $('api_key').after(privacy);
  const originalApi = api;
  api = (path, body) => {
    if (path === 'config' && body) { body = {...body}; delete body.api_key; }
    return originalApi(path, body);
  };
  window.startServerTranslation = async () => {
    const mod = state?.mods.find(m => m.id === selected);
    if (!mod) return;
    const settings = {base_url:$('base_url').value.trim(), model:$('model').value.trim(),
      api_key:$('api_key').value.trim(), batch_size:Number($('batch_size').value), concurrency:Number($('concurrency').value)};
    if (!settings.api_key && mod.counts?.untranslated > 0) { toast('请先在「本次翻译 API」填写自己的 API Key。'); return; }
    if (!await ask(`翻译「${mod.title}」？英文文本将发往 ${settings.base_url}，模型为 ${settings.model}，可能产生费用。密钥不保存；译文只在你的工作区内处理，完成后由你选择是否共享。`, '开始AI翻译')) return;
    try {
      await api('translate', {id:selected, api:settings});
      $('api_key').value = '';
      settings.api_key = '';
      await refresh();
    } catch (error) { settings.api_key = ''; toast(error.message); }
  };
  const sharing = document.createElement('section');
  sharing.innerHTML = '<h3>共享翻译</h3><p class="sub">共享由你自愿选择。不共享的译文仅在当前访客工作区使用；允许共享不代表允许发布创意工坊。</p><button type="button" id="share_translation" disabled>将本次翻译共享到服务器</button><div id="shared_translations"></div>';
  $('actions').appendChild(sharing);
  const shareDialog = document.createElement('dialog');
  shareDialog.setAttribute('aria-label', '自愿共享翻译');
  shareDialog.style.maxWidth = '440px';
  shareDialog.innerHTML = `<h2>是否共享这份翻译？</h2><p>共享后，其他访客可以复用译文，并看到你的署名和翻译模型。不共享也可正常下载自己的补丁。</p><div id="share_fields" hidden><label for="share_author">翻译者名称（可留空）</label><input id="share_author" maxlength="80" placeholder="留空显示匿名"><p id="share_model" class="sub"></p><label><input type="checkbox" id="share_publish">允许网站开发者使用这份译文发布到创意工坊，并保留翻译者署名和模型</label><p class="sub">此项默认不勾选；仅共享到本站不需要授权创意工坊发布。</p></div><p id="share_error" role="status"></p><div class="row"><button id="share_cancel">暂不共享</button><button id="share_accept" class="primary">愿意共享</button></div>`;
  document.body.appendChild(shareDialog);
  const offered = new Set();
  let sharingId = null, sharingJob = null, consentStep = false;
  function offer(id, job) {
    if (shareDialog.open) return;
    sharingId = id; sharingJob = job; consentStep = false;
    $('share_fields').hidden = true; $('share_author').value = ''; $('share_publish').checked = false;
    $('share_error').textContent = ''; $('share_accept').textContent = '愿意共享';
    $('share_model').textContent = '翻译模型：' + (job.result.model || '未知模型');
    shareDialog.showModal();
  }
  $('share_cancel').onclick = () => shareDialog.close();
  $('share_accept').onclick = async () => {
    if (!consentStep) { consentStep = true; $('share_fields').hidden = false; $('share_accept').textContent = '确认共享'; return; }
    $('share_accept').disabled = true;
    try {
      await api('share-translation', {id:sharingId, author:$('share_author').value, publish_allowed:$('share_publish').checked});
      shareDialog.close(); toast('已共享，并保存署名、模型和发布许可。'); await refresh();
    } catch (error) { $('share_error').textContent = error.message; }
    finally { $('share_accept').disabled = false; }
  };
  $('share_translation').onclick = () => {
    const job = state.jobs?.[selected];
    if (job?.kind === 'translate' && job.result && !job.error && !job.running) offer(selected, job);
  };
  window.syncServerUI = () => {
    if (!state) return;
    const developer = !!state.dev_logged_in;
    settings.querySelectorAll('[data-saved-setting]').forEach(el => el.hidden = !developer);
    $('dev_login_btn').textContent = developer ? '开发者已登录 · 退出' : '开发者登录';
    $('api_key').placeholder = '每次翻译前填写，不保存';
    const job = state.jobs?.[selected];
    $('share_translation').disabled = !job || job.running || job.kind !== 'translate' || !!job.error || !job.result;
    const key = selected + ':' + job?.result?.version_id;
    if (job?.kind === 'translate' && !job.running && !job.error && job.result && !offered.has(key)) {
      offered.add(key); if (!document.querySelector('dialog[open]')) offer(selected, job);
    }
    const records = (state.shared_translations || []).filter(record => record.mod_id === selected);
    $('shared_translations').innerHTML = records.length ? records.map(record => `<p><strong>翻译者：${escapeText(record.author)}</strong> · 模型：${escapeText(record.model)}<br><span class="sub">创意工坊发布许可：${record.publish_allowed ? '已授权，须保留署名和模型' : '未授权'}</span><br><button type="button" data-shared-id="${record.id}">复用此翻译</button></p>`).join('') : '<p class="sub">此 Mod 暂无自愿共享的翻译。</p>';
    document.querySelectorAll('[data-shared-id]').forEach(button => {
      button.disabled = modBusy(selected);
      button.onclick = async () => {
        try { const result = await api('use-shared', {id:selected, share_id:Number(button.dataset.sharedId)}); await refresh(); toast(`已导入 ${result.author}（${result.model}）的匹配译文，可生成汉化补丁；原文变化的条目需重新翻译。`); }
        catch (error) { toast(error.message); }
      };
    });
  };
  $('scan').parentElement.querySelector('h2').textContent = '服务器 Mod 库';
  document.querySelector('.library-note').textContent = '粘贴创意工坊链接查询；已有 Mod 直接使用，未下载的 Mod 可请求匿名下载。仅保留本地化、描述和封面。';
  $('search').placeholder = '粘贴 Steam 创意工坊 Mod 链接';
  $('search').setAttribute('aria-label', 'Steam 创意工坊链接');
  $('search').oninput = null;
  const lookupRow = document.createElement('div');
  lookupRow.className = 'lookup-actions';
  lookupRow.style.cssText = 'display:flex;gap:10px;align-items:center;margin-top:12px;margin-bottom:4px;flex-wrap:wrap';
  const lookupButton = document.createElement('button');
  lookupButton.textContent = '查询 Mod';
  lookupButton.type = 'button';
  lookupButton.className = 'primary';
  const downloadButton = document.createElement('button');
  downloadButton.type = 'button';
  downloadButton.className = 'scan-action';
  downloadButton.textContent = '请求下载';
  downloadButton.hidden = true;
  lookupRow.append(lookupButton, downloadButton);
  $('search').after(lookupRow);
  const linkStatus = document.createElement('p');
  linkStatus.className = 'sub';
  linkStatus.style.margin = '6px 0 4px';
  linkStatus.setAttribute('role', 'status');
  lookupRow.after(linkStatus);
  let checkedLink = '', pending = false;
  async function choose(id) {
    selected = id;
    await refresh();
    activeGame = state.mods.find(m => m.id === id)?.game || activeGame;
    renderMods(); renderSelection();
  }
  $('search').oninput = () => { downloadButton.hidden = true; checkedLink = ''; };
  lookupButton.onclick = async () => {
    if (pending) return;
    lookupButton.disabled = true;
    downloadButton.hidden = true;
    const link = $('search').value.trim();
    linkStatus.textContent = '正在查询 Steam…';
    try {
      const item = await api('workshop-lookup', {link});
      if ($('search').value.trim() !== link) { linkStatus.textContent = '链接已改变，请重新查询。'; return; }
      checkedLink = link;
      linkStatus.textContent = item.title + (item.downloaded ? ' · 已在服务器，已选中。' : ' · 尚未下载，可请求下载。');
      downloadButton.hidden = item.downloaded;
      if (item.downloaded) await choose(item.id);
    } catch (e) { linkStatus.textContent = e.message; }
    finally { lookupButton.disabled = false; }
  };
  $('search').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); lookupButton.click(); } };
  downloadButton.onclick = async () => {
    if (pending || !checkedLink) return;
    pending = true; downloadButton.disabled = true; lookupButton.disabled = true;
    linkStatus.textContent = '正在下载，完成后自动清理其他文件；请稍候…';
    try {
      const result = await api('workshop-download', {link: checkedLink});
      if (result.job_id) {
        while (true) {
          await new Promise(resolve => setTimeout(resolve, 2000));
          const current = await api('state');
          const job = current.jobs?.__global__;
          if (!job || job.id !== result.job_id) throw Error('下载任务状态已改变，请重新查询链接。');
          linkStatus.textContent = job.messages?.at(-1) || '正在连接 Steam 并下载…';
          if (!job.running) { if (job.error) throw Error(job.error); break; }
        }
      }
      await choose(result.id);
      downloadButton.hidden = true;
      linkStatus.textContent = 'Mod 已就绪。点击「扫描此 Mod」，配置自己的 API 后开始翻译。';
    } catch (e) { linkStatus.textContent = e.message; }
    finally { pending = false; downloadButton.disabled = false; lookupButton.disabled = false; }
  };

  const triggerBtn = document.createElement('button');
  triggerBtn.id = 'open_upload_mod';
  triggerBtn.type = 'button';
  triggerBtn.className = 'upload-trigger-btn';
  triggerBtn.textContent = '上传 Mod';
  $('scan').before(triggerBtn);

  const dialog = document.createElement('dialog');
  dialog.id = 'upload_mod_dialog';
  dialog.setAttribute('aria-labelledby', 'upload_mod_title');
  dialog.innerHTML = `
    <div class="row"><h2 id="upload_mod_title" class="grow" style="margin:0">上传原 Mod</h2><button id="close_upload_mod" type="button">关闭</button></div>
    <p class="sub" style="margin:10px 0 14px">选择包含 localisation / localization 目录的 ZIP（最大 32 MB，解压后最大 128 MB）。只修改服务器副本，完成后下载汉化补丁。相同工坊 ID 的已有 Mod 不会被覆盖。</p>
    <label for="upload_game">游戏</label>
    <select id="upload_game">
      <option value="281990">群星</option>
      <option value="394360">钢铁雄心4</option>
      <option value="236850">欧陆风云4</option>
      <option value="1158310">十字军之王3</option>
      <option value="529340">维多利亚3</option>
    </select>
    <label for="upload_uid">原 Mod 工坊 ID（工坊链接中 id= 后的数字）</label>
    <input id="upload_uid" inputmode="numeric" placeholder="例如 3393552523">
    <label for="upload_zip">Mod ZIP 文件</label>
    <input id="upload_zip" type="file" accept=".zip">
    <p id="upload_status" class="sub" role="status" style="margin:10px 0 0"></p>
    <div class="row" style="margin-top:16px;justify-content:flex-end">
      <button id="cancel_upload_mod" type="button">取消</button>
      <button id="upload_mod" type="button" class="primary">确认上传</button>
    </div>`;
  document.body.appendChild(dialog);

  triggerBtn.onclick = () => {
    $('upload_status').textContent = '';
    dialog.showModal();
  };
  $('close_upload_mod').onclick = () => dialog.close();
  $('cancel_upload_mod').onclick = () => dialog.close();

  // 网页版浏览器文件导入对话框
  const importDialog = document.createElement('dialog');
  importDialog.id = 'upload_import_dialog';
  importDialog.setAttribute('aria-labelledby', 'upload_import_title');
  importDialog.innerHTML = `
    <div class="row"><h2 id="upload_import_title" class="grow" style="margin:0">导入译文 / 缓存</h2><button id="close_upload_import" type="button">关闭</button></div>
    <p class="sub" style="margin:10px 0 14px">选择本地中文本地化文件 (.yml)、哈希缓存 (.json) 或此前导出的 ZIP 包（最大 32 MB）。系统将提取匹配条目并导入当前 Mod 工作区。</p>
    <label for="upload_import_file">选择本地文件</label>
    <input id="upload_import_file" type="file" accept=".yml,.yaml,.json,.zip">
    <label for="upload_import_provider" style="margin-top:12px">导入者名称（可留空自动命名）</label>
    <input id="upload_import_provider" maxlength="80" placeholder="例如：某汉化组、个人译者（留空将自动命名）">
    <p id="upload_import_status" class="sub" role="status" style="margin:10px 0 0"></p>
    <div class="row" style="margin-top:16px;justify-content:flex-end">
      <button id="cancel_upload_import" type="button">取消</button>
      <button id="confirm_upload_import" type="button" class="primary">确认导入</button>
    </div>`;
  document.body.appendChild(importDialog);

  $('close_upload_import').onclick = () => importDialog.close();
  $('cancel_upload_import').onclick = () => importDialog.close();

  let importTarget = null;
  // 网页版拦截原导入按钮：调用浏览器文件选择
  $('import_btn').onclick = () => {
    if (!selected) { toast('请先在左侧选择一个 Mod'); return; }
    importTarget = selected;
    $('upload_import_status').textContent = '';
    $('upload_import_file').value = '';
    importDialog.showModal();
  };

  $('confirm_upload_import').onclick = async () => {
    if (!selected) { toast('请先在左侧选择一个 Mod'); return; }
    const file = $('upload_import_file').files[0];
    if (!file) { $('upload_import_status').textContent = '请选择要导入的文件'; return; }
    if (file.size > 32 * 1024 * 1024) { $('upload_import_status').textContent = '文件最大为 32 MB'; return; }
    $('confirm_upload_import').disabled = true;
    $('upload_import_status').textContent = '正在上传文件并解析条目，请稍候…';
    try {
      const query = new URLSearchParams({
        id: importTarget,
        provider: $('upload_import_provider').value.trim(),
        filename: file.name
      });
      const response = await fetch('/api/upload-import?' + query, {
        method: 'POST',
        headers: {'X-App-Token': token, 'Content-Type': 'application/octet-stream'},
        body: file
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.error || '导入失败');
      while (true) {
        const current = await api('state');
        const job = current.jobs?.[importTarget];
        if (!job || job.id !== result.job_id) throw Error('导入任务状态已改变，请检查任务记录。');
        if (!job.running) {
          if (job.error) throw Error(job.error);
          toast(`导入完成：新增 ${job.result.imported} 条，跳过 ${job.result.rejected} 条。`);
          break;
        }
        $('upload_import_status').textContent = '正在比对原文并导入译文…';
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
      importDialog.close();
      await refresh();
    } catch (error) {
      $('upload_import_status').textContent = error.message;
    } finally {
      $('confirm_upload_import').disabled = false;
    }
  };

  for (const id of ['open', 'open_aggregate', 'open_mod_export']) $(id).hidden = true;
  $('pick_file').hidden = true;
  $('pick_folder').hidden = true;
  $('import_path').placeholder = '服务器上的译文 / 缓存文件路径';
  $('upload_mod').onclick = async () => {
    const file = $('upload_zip').files[0];
    if (!file || !/^[1-9][0-9]{0,19}$/.test($('upload_uid').value.trim())) {
      $('upload_status').textContent = '请选择 ZIP 并填写正确的工坊 ID'; return;
    }
    if (file.size > 32 * 1024 * 1024) { $('upload_status').textContent = 'ZIP 最大为 32 MB'; return; }
    $('upload_mod').disabled = true;
    $('upload_status').textContent = '正在上传和检查文件，请稍候…';
    try {
      const query = new URLSearchParams({appid: $('upload_game').value, uid: $('upload_uid').value.trim()});
      const response = await fetch('/api/upload-mod?' + query, {
        method: 'POST', headers: {'X-App-Token': token, 'Content-Type': 'application/zip'}, body: file
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.error || '上传失败');
      selected = result.id;
      await refresh();
      activeGame = state.mods.find(m => m.id === selected)?.game || activeGame;
      renderMods(); renderSelection();
      $('upload_status').textContent = '上传成功。点击「扫描此 Mod」，然后配置 API 并开始翻译。';
      dialog.close();
      toast('Mod 上传成功！请点击「扫描此 Mod」后开始翻译。');
    } catch (error) { $('upload_status').textContent = error.message; }
    finally { $('upload_mod').disabled = false; }
  };
})();
