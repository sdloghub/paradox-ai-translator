# Windows 可执行程序

目标产物：`WorkshopTranslator.exe`（Windows 10/11 x64，单文件）。
用户不需要另外安装 Python 或模型 SDK。

## 使用

双击 EXE 后自动打开本机浏览器界面。程序保留一个控制台窗口，关闭该窗口或按 Ctrl+C 停止服务。
在界面中保存 API 配置、扫描 Steam Mod，然后选择翻译或从中文备份库一键复制。
可运行 `WorkshopTranslator.exe --demo` 离线演示，不访问真实 Steam 或付费 API。

密钥、SQLite 备份和缓存保存在 `%LOCALAPPDATA%\WorkshopTranslator\app_data`；
演示数据保存在同级 `app_data_demo`。数据与 EXE 分开，升级或更换 EXE 不会清除记录。
可以通过 `--data-dir "D:\WorkshopTranslatorData"` 指定数据目录。

默认检测注册表中的 Steam 安装目录及 `steamapps\libraryfolders.vdf`，也支持手动填写其他库目录。

## 本机 Windows 打包

安装 Python 3.12 x64，在项目目录中执行 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

这里的执行策略参数仅用于本次脚本进程，不更改系统执行策略。
脚本创建 `.venv-build`、安装依赖、运行测试、打包并验证 EXE。
成功后文件为 `dist\WorkshopTranslator.exe`。

也可依次手动运行脚本中的命令。

## GitHub Actions 打包

仓库包含 `.github/workflows/build-windows.yml`。
在独立 `codex/windows-exe...` 分支推送打包源码时自动运行，或从 Actions 页面手动启动。
构建环境是 Windows x64；先运行测试，再生成 EXE 并执行 `--self-test` 离线端到端自检。
成功后下载 `WorkshopTranslator-Windows-x64` artifact，其中包含 EXE 和 SHA-256 校验文件。
只上传必要源码与配置，不包含本机 API 密钥、Mod、数据库或翻译缓存。

macOS 上运行 PyInstaller 不能生成 Windows EXE，因此最终编译和运行验证必须在 Windows 上执行。

## 中文扫描与缓存

扫描会按游戏分类，并为每个 Mod 提取本机中文，显示已翻译、待翻译和总条目数。
预览区“打开 Steam 网页窗口”使用命名浏览器窗口；再次点击会复用该窗口并跳转到当前 Mod。
Steam 自身的浏览器隔离策略或弹窗拦截可能要求浏览器允许打开窗口。

可选择中文 YML 文件/目录或已有缓存 JSON 提取译文，也可粘贴本机路径。
系统文件选择框不可用时使用路径输入。支持导出当前 Mod 的带哈希 JSON 缓存。
缓存严格按 Mod、文件、条目键和英文 SHA-256 匹配，并保存历史对应关系。
英文变化后旧译文不会直接复用；重新翻译成功后记录新版本哈希。

普通中文 YML 没有历史英文哈希，首次提取仅能以当前英文建立基准，无法证明它原先对应的英文版本。
后续检测能识别英文变化并阻止未变化的旧中文被重新标记为新译文。
来自另一个 Mod、原文哈希不一致、变量损坏、同键多文件无法唯一对应或存在冲突的译文会跳过。

### 游戏分类与本地清单

搜索栏下方按游戏切换，点击分类后才显示对应 Mod。清单与翻译统计保存到本地 SQLite，重启直接加载；点击「扫描更新」时对文件名及内容计算 SHA-256，只有新增、变化或上次检测失败的 Mod 重新分析，Steam 名称查询仅针对新增、变化或上次查询失败的记录。已卸载的 Mod 从当前清单移除，翻译备份仍保留。

扫描仍需要读取本机文件以确认内容变化，大型 Mod 首次或再次校验可能耗时；不会重复发送未变化 Mod 的名称查询。Steam 页面单独改名而本地文件不变时，名称继续使用缓存。重新检测中文、导入缓存和翻译后的统计也会保存。界面动效库随程序打包，离线可用，并遵循系统减少动态效果设置。
