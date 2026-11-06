/* One compact, narrated tutorial page at a time with bordered card styling. */
(() => {
  let index = 0, highlighted = null;
  function getLocalSteps() {
    return [
      [window.t('tutorial.local_1_title', '1. 扫描目录'), window.t('tutorial.local_1_desc', '点击左侧「刷新目录」读取本机 Steam 已安装的 Mod 清单，不会消耗 API 费用。'), '#scan'],
      [window.t('tutorial.local_2_title', '2. 点击 Mod'), window.t('tutorial.local_2_desc', '先选择游戏分类标签，再在列表里点击要翻译的 Mod；也可按名称或 UID 搜索。'), '#categories'],
      [window.t('tutorial.local_3_title', '3. 扫描 Mod'), window.t('tutorial.local_3_desc', '点击右侧「扫描此 Mod」，统计词条总数、已有缓存与格式报错行。'), '#analyze'],
      [window.t('tutorial.local_4_title', '4. 可选：导入'), window.t('tutorial.local_4_desc', '若有旧版汉化文件或他人分享的译文包，点击「导入译文」即可自动匹配复用；没有可直接跳过。'), '#import_btn'],
      [window.t('tutorial.local_5_title', '5. 翻译'), window.t('tutorial.local_5_desc', '展开设置保存 API Key 后，点击「开始 AI 翻译」，程序仅翻译缺失或原文有变动的词条。'), '#translate'],
      [window.t('tutorial.local_6_title', '6. 完成！'), window.t('tutorial.local_6_desc', '当状态变为绿色的「已完全翻译」时，中文已写回 Mod 目录，直接启动游戏即可体验汉化！'), '#selection'],
      [window.t('tutorial.local_7_title', '7. 可选：导出'), window.t('tutorial.local_7_desc', '点击「生成翻译 Mod」可在文档目录生成独立汉化补丁，或点击「导出中文 + 哈希 (.zip)」留档分享。'), '#generate_mod']
    ];
  }
  function getOnlineSteps() {
    return [
      [window.t('tutorial.online_1_title', '1. 查询工坊链接'), window.t('tutorial.online_1_desc', '把 Steam 创意工坊 Mod 链接粘贴到输入框，点击「查询 Mod」。已有原文直接使用，未下载的点击「请求下载」。'), '#search'],
      [window.t('tutorial.online_2_title', '2. 扫描词条'), window.t('tutorial.online_2_desc', '选中 Mod 后点击「扫描此 Mod」，检查词条数量与格式。共享库中如有译文，可先复用，节省费用。'), '#analyze'],
      [window.t('tutorial.online_3_title', '3. 填写本次 API'), window.t('tutorial.online_3_desc', '展开「本次翻译 API」，填写 HTTPS 接口地址、模型和 API Key。密钥只在本次任务内存中使用，绝不保存。'), '#settings'],
      [window.t('tutorial.online_4_title', '4. 开始翻译'), window.t('tutorial.online_4_desc', '点击「开始 AI 翻译」，确认接口和费用。下方「任务进度」会实时显示该 Mod 的翻译进度。'), '#translate'],
      [window.t('tutorial.online_5_title', '5. 选择是否共享'), window.t('tutorial.online_5_desc', '翻译完成后可自愿选择是否共享译文。署名留空即为匿名，模型由系统自动记录。'), '#share_translation'],
      [window.t('tutorial.online_6_title', '6. 下载汉化补丁'), window.t('tutorial.online_6_desc', '点击「生成翻译 Mod」并下载 ZIP。先订阅原 Mod，再将汉化补丁排在原 Mod 之后加载。'), '#generate_mod']
    ];
  }
  function isDev() { return !window.serverWorkshopLinks; }
  function steps() { return window.serverWorkshopLinks ? getOnlineSteps() : getLocalSteps(); }
  function clear() { highlighted?.classList.remove('tutorial-highlight'); highlighted = null; }
  function close() {
    clear();
    $('beginner_tutorial').hidden = true;
    try { sessionStorage.setItem('workshop_tutorial_skipped', '1'); } catch (e) {}
  }
  function render() {
    const list = steps(), item = list[index], panel = $('beginner_tutorial');
    clear();
    const dots = list.map((_, i) => `<span class="tutorial-dot ${i === index ? 'active' : ''}"></span>`).join('');
    panel.innerHTML = `
      <div class="tutorial-header">
        <div class="row" style="gap:8px">
          <span class="badge purple">${window.t('tutorial.badge', '新手引导')}</span>
          <span class="sub">${window.t('tutorial.step_progress', '步骤 {current} / {total}', {current: index + 1, total: list.length})}</span>
        </div>
        <button type="button" id="tutorial_skip" class="tutorial-skip-btn">${window.t('tutorial.skip', '跳过教程 ✕')}</button>
      </div>
      <div class="tutorial-body">
        <h3>${item[0]}</h3>
        <p>${item[1]}</p>
      </div>
      <div class="tutorial-footer">
        <div class="tutorial-dots" aria-hidden="true">${dots}</div>
        <div class="row" style="gap:8px">
          <button type="button" id="tut_prev" ${index ? '' : 'disabled'}>${window.t('tutorial.prev', '上一步')}</button>
          <button type="button" class="primary" id="tut_next">${index === list.length - 1 ? window.t('tutorial.finish', '完成教程') : window.t('tutorial.next', '下一步 →')}</button>
        </div>
      </div>`;
    $('tutorial_skip').onclick = close;
    $('tut_prev').onclick = () => { if (index > 0) { index--; render(); } };
    $('tut_next').onclick = () => { if (index === list.length - 1) close(); else { index++; render(); } };
    const target = document.querySelector(item[2]);
    if (target && !target.hidden && target.offsetParent !== null) {
      highlighted = target;
      target.classList.add('tutorial-highlight');
    }
  }
  window.openWorkshopTutorial = (stepIndex = 0) => {
    if (isDev()) return;
    const list = steps();
    index = Math.max(0, Math.min(Number(stepIndex) || 0, list.length - 1));
    $('beginner_tutorial').hidden = false;
    render();
  };
  let prompted = false;
  window.syncTutorialVisibility = () => {
    const dev = isDev();
    if ($('open_tutorial')) $('open_tutorial').hidden = !!window.serverWorkshopLinks;
    if (dev) {
      clear();
      $('beginner_tutorial').hidden = true;
      return;
    }
    if (!prompted && window.state) {
      prompted = true;
      let skipped = false;
      try { skipped = !!sessionStorage.getItem('workshop_tutorial_skipped'); } catch (e) {}
      if (!skipped) window.openWorkshopTutorial(0);
    }
  };
  if ($('open_tutorial')) $('open_tutorial').onclick = () => window.openWorkshopTutorial(0);
  $('beginner_tutorial').setAttribute('aria-label', window.t('tutorial.aria_label', '分步新手教程'));
})();
