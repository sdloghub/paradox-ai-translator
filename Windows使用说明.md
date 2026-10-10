# Windows 可执行程序

目标产物：`WorkshopTranslator.exe`（Windows 10/11 x64，文件夹发布包）。
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
成功后程序为 `dist\WorkshopTranslator\WorkshopTranslator.exe`，发布压缩包为 `dist\WorkshopTranslator-Windows.zip`。

也可依次手动运行脚本中的命令。

## GitHub Actions 打包

仓库包含 `.github/workflows/build-windows.yml`。
在独立 `codex/windows-exe...` 分支推送打包源码时自动运行，或从 Actions 页面手动启动。
构建环境是 Windows x64；先运行测试，再生成 EXE 并执行 `--self-test` 离线端到端自检。
成功后下载 `WorkshopTranslator-Windows-x64` artifact，其中包含程序发布 ZIP、EXE 和 SHA-256 校验文件。
只上传必要源码与配置，不包含本机 API 密钥、Mod、数据库或翻译缓存。

macOS 上运行 PyInstaller 不能生成 Windows EXE，因此最终编译和运行验证必须在 Windows 上执行。

## 中文扫描与缓存

目录刷新后选择具体 Mod 扫描，显示已翻译、未翻译、需更新及总条目数。
预览区“打开 Steam 网页窗口”使用命名浏览器窗口；再次点击会复用该窗口并跳转到当前 Mod。
Steam 自身的浏览器隔离策略或弹窗拦截可能要求浏览器允许打开窗口。

可选择中文 YML 文件/目录或已有缓存 JSON 提取译文，也可粘贴本机路径。
系统文件选择框不可用时使用路径输入。支持导出当前 Mod 的带哈希 JSON 缓存。
缓存严格按 Mod、文件、条目键和英文 SHA-256 匹配，并保存历史对应关系。
英文变化后旧译文不会直接复用；重新翻译成功后记录新版本哈希。

普通中文 YML 没有历史英文哈希，首次提取仅能以当前英文建立基准，无法证明它原先对应的英文版本。
后续检测能识别英文变化并阻止未变化的旧中文被重新标记为新译文。
来自另一个 Mod、原文哈希不一致、变量损坏、同键多文件无法唯一对应或存在冲突的译文会跳过。

### 游戏分类、扫描与来源

点击搜索栏下方的游戏分类后显示对应 Mod。「刷新目录」只读取目录、描述文件及 Steam 清单，不递归读取模组内容。首次显示「未扫描」；进入具体 Mod 后点击「扫描此 Mod」，才提取中文并校验英文 SHA-256。名称查询针对新增、目录清单变化或上次查询失败的记录。本机清单重启后直接加载。

目录元数据无法发现所有深层文件修改，因此使用旧扫描结果时仍建议扫描所选 Mod；已发现目录变化的旧结果标注「待复查」。扫描后显示总条目、已翻译、未翻译、需更新；需更新表示同一条目已有旧译文但原文不匹配。API 待处理数量为未翻译与需更新之和。

API 设置填写提供商名称，配置保存在本机 config.json 与 providers.json。手动导入也可填写汉化组或译者名称。留空时按「翻译-日期-版次」命名，版次持续累加。来源按有效条目汇总，补充翻译不会改写原有导入来源。completed.json 保存译文及原文哈希的完成标记，后续操作更新已有文件。SQLite 继续保存完整备份。

### 程序发布压缩包

每次打包生成 dist/WorkshopTranslator-Windows.zip。解压后的 WorkshopTranslator 文件夹内，EXE、Python 工具、config.json、providers.json、completed.json 并列，资源位于 assets/vendor，EXE 运行依赖位于 _internal。请完整解压并保留 _internal，不要单独移动 EXE。发布包 API Key 留空；本机保存的密钥保留原值。

运行 `python packaging/build_release.py --data-dir app_data` 会复制指定数据目录的最新配置与完成记录，更新已有发布 ZIP。首次运行读取包内配置；已有本机保存时保留现有配置，完成标记按英文哈希合并。Windows 数据仍保存于 %LOCALAPPDATA%/WorkshopTranslator/app_data/。完整历史备份以本机数据库为准，JSON 完成标记用于恢复缓存。

GitHub 构建只使用空配置模板，不上传本机密钥、Mod、数据库或完成记录。Steam 投稿仅预留界面和本机接口，显示「尚未启用」，不会上传内容。

### 保存与切换 API 配置

在「API 与 Steam 库设置」填写配置名称，再点击「保存配置」。同名配置更新保存，不同名称可分别保存同一提供商的不同模型。下拉选取已保存配置后点击「使用此配置」，加载对应接口、模型和本地密钥，Steam 库目录保持当前设置。翻译任务运行期间不能切换。API Key 保存在本机 providers.json，页面只显示是否已保存密钥；发布 ZIP 中密钥留空。

### 提示词与启动优化

rules.json 的提示词统一保护变量、图标、颜色格式、转义符和批次分隔符；各游戏保留独立风格，允许必要的括号与专名。启动时延迟加载模型 SDK，未改变的完成记录不重复导入，缓存目录清单直接读取。`--startup-check` 输出内部启动耗时且不调用外部接口。Windows 构建额外比较同代码单文件与文件夹模式，每种测量三次，结果保存在 startup-benchmark.json；该测量不包含浏览器渲染，也不代表所有用户电脑的耗时。
