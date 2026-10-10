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
