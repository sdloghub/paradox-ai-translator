/* One compact, narrated tutorial page at a time. */
(() => {
  let index = 0, highlighted = null;
  const local = [
    ['刷新目录', '点击「刷新目录」读取本机 Steam 已安装的 Mod，不消耗 API 费用。', '#scan'],
    ['选择 Mod', '选择游戏分类，再点击要翻译的 Mod；可按名称或 UID 搜索。', '#categories'],
    ['扫描词条', '点击「扫描此 Mod」，检查词条数量、已有缓存和格式错误。', '#analyze'],
    ['填写 API', '展开设置，填写接口地址、模型名称与 API Key；电脑版可保存到本机。', '#settings'],
    ['开始翻译', '点击「开始 AI 翻译」并确认费用。程序仅处理缺失或原文变化的词条。', '#translate'],
    ['导出补丁', '完成后生成翻译 Mod，按提示放在原 Mod 后加载。也可导出中文和哈希备份。', '#generate_mod']
  ];
  const online = [
    ['查询工坊链接', '把 Steam 创意工坊 Mod 链接粘贴到输入框，点击「查询 Mod」。已有原文直接使用，未下载的点击「请求下载」。', '#search'],
    ['扫描词条', '选中 Mod 后点击「扫描此 Mod」，检查词条数量与格式。共享库中如有译文，可先复用，节省费用。', '#analyze'],
    ['填写本次 API', '展开「本次翻译 API」，填写 HTTPS 接口地址、模型和 API Key。密钥只在本次任务内存中使用，不写入配置或浏览器存储。', '#settings'],
    ['开始翻译', '点击「开始 AI 翻译」，确认接口和费用。可查看任务日志；失败或报错的行会保留原文。', '#translate'],
    ['选择是否共享', '翻译完成后可选择共享或不共享。共享时可填写署名（留空为匿名），模型自动记录。创意工坊发布许可默认不勾选。', '#share_translation'],
    ['下载汉化补丁', '点击「生成翻译 Mod」并下载。先订阅原 Mod，再将汉化补丁排在原 Mod 后加载。', '#generate_mod']
  ];
  function steps() { return window.serverWorkshopLinks ? online : local; }
  function clear() { highlighted?.classList.remove('tutorial-highlight'); highlighted = null; }
  function close() { clear(); $('beginner_tutorial').hidden = true; }
  function render() {
    const list = steps(), item = list[index], panel = $('beginner_tutorial');
    clear();
    panel.innerHTML = `<div class="row"><strong class="grow">新手教程 · ${index + 1} / ${list.length}</strong><button id="tutorial_skip">跳过教程</button></div><h3>${item[0]}</h3><p style="line-height:1.8">${item[1]}</p><div class="row" style="justify-content:space-between"><button id="tut_prev" ${index ? '' : 'disabled'}>上一页</button><button class="primary" id="tut_next">${index === list.length - 1 ? '完成教程' : '下一页'}</button></div>`;
    $('tutorial_skip').onclick = close;
    $('tut_prev').onclick = () => { index--; render(); };
    $('tut_next').onclick = () => { if (index === list.length - 1) close(); else { index++; render(); } };
    const target = document.querySelector(item[2]);
    if (target && !target.hidden && target.offsetParent !== null) { highlighted = target; target.classList.add('tutorial-highlight'); }
  }
  window.openWorkshopTutorial = () => { index = 0; $('beginner_tutorial').hidden = false; render(); };
  window.syncTutorialVisibility = () => {};
  $('open_tutorial').onclick = window.openWorkshopTutorial;
  $('beginner_tutorial').setAttribute('aria-label', '分步新手教程');
})();
