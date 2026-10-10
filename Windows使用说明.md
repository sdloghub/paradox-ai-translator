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

点击搜索栏下方的游戏分类后显示对应 Mod。「刷新目录」优先解析 steamapps/workshop/appworkshop_<AppID>.acf，以 WorkshopItemsInstalled 为安装清单，并检查 content/<AppID>/<UID> 目录是否存在；不枚举整游戏 Mod 目录，不递归读取翻译内容。首次显示「未扫描」；进入具体 Mod 后点击「扫描此 Mod」，才提取中文并校验英文 SHA-256。名称查询针对新增、已安装版本指纹变化或上次查询失败的记录。已安装版本指纹由 manifest、timeupdated、size 组成；timetouched、subscribedby 与 latest_* 不影响本机版本判定。本机清单重启后直接加载。

ACF 无法发现用户手动修改的深层文件，因此使用旧统计时仍建议扫描所选 Mod；已安装版本变化的旧结果标注「待复查」。扫描后显示总条目、已翻译、未翻译、需更新；需更新表示同一条目已有旧译文但原文不匹配。API 待处理数量为未翻译与需更新之和。

API 设置填写提供商名称，配置保存在本机 config.json 与 providers.json。手动导入也可填写汉化组或译者名称。留空时按「翻译-日期-版次」命名，版次持续累加。来源按有效条目汇总，补充翻译不会改写原有导入来源。completed.json 保存译文及原文哈希的完成标记，后续操作更新已有文件。SQLite 继续保存完整备份。

### 程序发布压缩包

每次打包生成 dist/WorkshopTranslator-Windows.zip。解压后的 WorkshopTranslator 文件夹内，EXE、Python 工具、config.json、providers.json、completed.json 并列，资源位于 assets/vendor，EXE 运行依赖位于 _internal。请完整解压并保留 _internal，不要单独移动 EXE。发布包 API Key 留空；本机保存的密钥保留原值。

运行 `python packaging/build_release.py --data-dir app_data` 会复制指定数据目录的最新配置与完成记录，更新已有发布 ZIP。首次运行读取包内配置；已有本机保存时保留现有配置，完成标记按英文哈希合并。Windows 数据仍保存于 %LOCALAPPDATA%/WorkshopTranslator/app_data/。完整历史备份以本机数据库为准，JSON 完成标记用于恢复缓存。

GitHub 构建只使用空配置模板，不上传本机密钥、Mod、数据库或完成记录。Steam 投稿仅预留界面和本机接口，显示「尚未启用」，不会上传内容。

### 保存与切换 API 配置

在「API 与 Steam 库设置」填写配置名称，再点击「保存配置」。同名配置更新保存，不同名称可分别保存同一提供商的不同模型。下拉选取已保存配置后点击「使用此配置」，加载对应接口、模型和本地密钥，Steam 库目录保持当前设置。翻译任务运行期间不能切换。API Key 保存在本机 providers.json，页面只显示是否已保存密钥；发布 ZIP 中密钥留空。

### 提示词与启动优化

rules.json 的提示词统一保护变量、图标、颜色格式、转义符和批次分隔符；各游戏保留独立风格，允许必要的括号与专名。启动时延迟加载模型 SDK，未改变的完成记录不重复导入，缓存目录清单直接读取。`--startup-check` 输出内部启动耗时且不调用外部接口。Windows 构建额外比较同代码单文件与文件夹模式，每种测量三次，结果保存在 startup-benchmark.json；该测量不包含浏览器渲染，也不代表所有用户电脑的耗时。

### ACF 清单与交接

每个游戏库的每个游戏 ACF 每次刷新只读取一次，保留 manifest 为字符串。WorkshopItemDetails 单独出现的物品不视为已安装；latest_manifest 不同或 latest_timeupdated 较新时提示 Steam 有待安装更新。完整的空安装清单会清空当前列表，历史备份仍保留。清单缺失、无效或写入不完整时提示并回退到目录检查。仅支持五个 Paradox 游戏；ACF兼容范围以用户样例与测试为准，未找到官方公开字段规范。

阅读「交接说明.md」了解开发上下文。运行 python packaging/build_handoff.py 会将必要源码、测试、交接说明和 Windows 发布 ZIP 打包为 dist/WorkshopTranslator-Codex-Handoff.zip，不收录 .git、密钥、Mod、数据库或完整聊天原始记录。


## 报错保留英文与缓存状态（2026-10-10）

Workshop 工作台遇到本地化解析异常或模型返回 ValueError 时，不再中止整个 Mod：问题行保留英文，其余条目继续，结束后返回报错行数、文件与行号，明细保存在工作目录 translation-report.json；已有中文文件仍先备份，失败条目不写入成功缓存。

已翻译表示有效缓存译文已写入本机 Mod；已缓存表示英文哈希匹配但尚未写入的译文。旧统计字段 translated 保留内部“有效译文总数”含义，界面采用 deployed 显示已写入数量，cached 显示待写入缓存。

导入时提示：带哈希缓存只核对本机英文，无法检查 Steam 尚未安装的更新；无哈希中文无法判断原文是否更新，需要用户确认来源版本。扫描按钮改为橙色，开始AI翻译保持蓝色。
