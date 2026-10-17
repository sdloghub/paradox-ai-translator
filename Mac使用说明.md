# Workshop 翻译程序 · Mac

适用于 Apple Silicon（M 系列芯片），macOS 11 或更新版本。无需另装 Python。

1. 解压后，将整个 WorkshopTranslator-macOS-arm64 文件夹移到固定位置。
2. 双击 WorkshopTranslator.app，稍候会在默认浏览器打开本机工作台。
3. 填写 API 配置，刷新 Mod 目录，再按需扫描和翻译。

此版本未使用 Apple Developer ID 签名或公证。首次打开若被系统阻止，
确认文件来源后，在“系统设置 → 隐私与安全性”里允许打开；不要关闭系统整体安全保护。

默认配置、数据库和翻译备份保存在：
~/Library/Application Support/WorkshopTranslator/app_data

设置中的“本文件夹”模式会将 config.json 和 providers.json 保存在 .app 旁边，
不会写入 .app 内部。压缩包附有不含密钥的初始配置和空完成记录；
更新时请保留你已有的配置文件，替换 .app 即可。

工作台关闭浏览器后仍在后台运行。退出时可以打开“活动监视器”，
查找 WorkshopTranslator 并退出该进程。

启动日志：~/Library/Logs/WorkshopTranslator/application.log

## 从源码重新构建

在项目根目录创建 Python 3.12 虚拟环境，安装 requirements.txt、
packaging/requirements-build.txt 以及 pillow，然后运行：

```sh
python packaging/build_macos.py
```

输出位于 dist/WorkshopTranslator-macOS-arm64.zip。

使用 `python packaging/build_macos.py --update` 可生成仅包含应用与说明的覆盖更新包。

## 浏览与人工标注条目

选中 Mod 后，点击“浏览翻译条目”。尚未扫描时，在条目页面点击“扫描并更新条目”。
可以按已翻译、未翻译、已缓存、格式错误、需更新筛选，并搜索键名、英文、中文或文件路径。
列表显示键名、原文件行号、英文、中文和翻译来源，每页 50 条。

“手动标注”会保存到当前用户的 SQLite 数据库，筛选优先使用人工标注。
自动检测结果仍单独显示。标注只用于整理，不会伪造缓存、修改 Mod 文件或强制 AI 重翻。
选择“跟随自动检测”取消标注；英文变化后对应版本的旧标注失效。
格式错误保留原文件行，需更新条目会注明所显示的中文为历史译文。
扫描、导入、翻译和备份恢复后自动刷新条目索引；分页与搜索只查询本地数据库。

## 导入文件选择器

macOS 点击「选择文件 / 选择文件夹」使用系统原生 AppKit 选择器，不再额外启动 Python 或加载 Tkinter。窗口请求置前并居中显示，取消选择不会清空已填路径。选择期间按钮暂时禁用，避免重复打开窗口；异常时可直接在输入框粘贴本机路径。

源码更新后，请先退出旧后台，再重新运行「启动翻译程序.command」。已安装的旧版 `.app` 内含独立源码，不会随着项目文件自动更新。
