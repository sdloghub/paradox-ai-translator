用于 Paradox 游戏创意工坊 Mod 翻译的预览版，包含 Windows、macOS 和完整源码。

## 下载

- **Windows x64**：下载 `windows-x64.zip`，完整解压后运行 `WorkshopTranslator.exe`，保留 `_internal` 文件夹，无需安装 Python。
- **macOS**：下载与你的芯片架构对应的 `macos-*.zip`，完整解压后打开 `WorkshopTranslator.app`。本应用未进行 Apple Developer ID 签名或公证；首次启动可能需要在“系统设置 → 隐私与安全性”确认来源后允许打开。
- **源码**：下载 `source.zip`，或使用 GitHub 自动提供的 Source code。按 README 安装依赖后运行。
- 已安装用户请先退出旧程序，保留现有配置和数据，再替换应用程序。完整发行包附带空白配置，覆盖时不要替换自己已有的 `config.json`、`providers.json`、`completed.json`。

## 本版更新

- 多个 Mod 可同时翻译；只锁定正在操作的 Mod，其余 Mod 可扫描、编辑和翻译，任务日志分别显示。
- 重复键标记为格式错误，列出键值及所有文件、行号；可直接修改键值并重扫。修改键值后需同步游戏脚本中的对应引用。
- 四个主题统一同行按钮颜色；直接显示选定 Mod 的翻译版本；关闭缓存复用时隐藏缓存选项。
- 支持按版本选择、删除缓存，直接修改中文译文；修复缓存整合、格式标记保护与无效翻译结果被误存的问题。
- 可生成独立翻译 Mod，填写或通过默认 API 生成简介。Steam Workshop 投稿入口仍为预留功能。

## 验证与数据

Windows 和 macOS 分别在 GitHub Actions 上构建，通过自动测试、打包可执行文件离线自检；Mac 应用另进行签名完整性验证。未使用真实付费 API 验证本次发行包，也未验证 Steam 投稿。

发行包包含空白默认配置，不含个人 API Key、翻译数据库、Mod 文件或已完成记录。API 调用费用取决于所选提供商。

`SHA256SUMS.txt` 提供各附件的 SHA-256 校验值。
