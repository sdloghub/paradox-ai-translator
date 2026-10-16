# Paradox Mod 翻译工具

Mac 用户可使用独立的 `WorkshopTranslator.app`（Apple Silicon），无需安装 Python。
安装、配置位置与重新构建方法见 [Mac使用说明.md](Mac使用说明.md)。
构建命令：`python packaging/build_macos.py`；发布包为 `dist/WorkshopTranslator-macOS-arm64.zip`。

首页顶部提供“条目浏览库”入口，浏览区常驻显示；选中 Mod 后自动加载索引。
可按状态筛选并查看键名、英文、中文、来源及原文件行号。
支持搜索、分页和持久化人工标注；英文变化后旧标注失效。人工标注不修改文件或缓存复用规则。

可在“编辑原文件行”中修改完整 YML 原行，保存前备份至数据目录的 `source_backups`，
保存后自动重新扫描并报告该行是否仍有格式错误。会保留 UTF-8 BOM、换行和其他行，
原文件已被外部修改时拒绝覆盖。EU4 文件已被中文回写覆盖时，需先恢复英文原文件后编辑。
工作台统计分两层展示：上方为总条目，下方为已翻译、已缓存、未翻译、需更新、格式错误。

当前入口为 `main.py`，核心模块为 `paradox.py`、`request.py`，提示词为 `rules.json`。
旧版实验脚本、历史压缩包、快捷方式和无关编辑器配置已清理。

## 运行

安装依赖：`python3 -m pip install -r requirements.txt`。
通过环境变量设置 `DEEPSEEK_API_KEY`，不要将密钥写入源码或提交到 Git。

```sh
python3 main.py --game hoi4 ck3
```

也可使用 `main.py` 的绝对路径从其他目录启动。省略 `--game` 时处理所有已有游戏目录。
输入放在 `localisation/<游戏>/`，文件名和原文件不会被修改。
输出写入 `chn/<游戏>/`，非 EU4 游戏仅在输出时更改语言头和文件名。

## 缓存与失败

`already/<原文件路径>.cache.json` 存储文本键、英文原文 SHA-256 和成功译文。
仅当原文哈希一致且变量校验通过时复用。旧的 YML 缓存无法证明原文版本，因此不自动导入；首次使用新版本会重新翻译并产生 API 费用。
每完成最多 150 条保存一次缓存。API 临时错误最多重试三次；分隔符或变量异常改为逐条翻译，变量校验最多尝试三次。
失败条目不写入成功缓存，下次运行继续尝试。运行日志追加到 `translation.log`。无法解析的疑似文本条目会报告文件和行号并停止该游戏的输出更新。

程序先在临时目录生成完整游戏输出；任一条目失败时保留该游戏之前的输出，并返回非零退出码。
全部成功后替换输出目录，替换异常时恢复备份。进程在目录切换瞬间被强制终止时，可能留下 `chn/.backup-*`，可用其恢复旧输出。
解析支持转义引号、尾部注释、无末尾换行和 UTF-8 BOM，保留原行缩进及注释。
变量校验检查 `$...$`、`[...]`、图标、颜色、格式及常见反斜杠转义的数量和内容；不保证术语或语义翻译正确。

## 测试

```sh
python3 -m unittest discover -s tests -v
```

测试使用模拟接口，不会调用真实 API。

曾写入源码的密钥应在服务商控制台撤销并重新创建；删除源码中的密钥不会使旧密钥失效，也不会清除 Git 历史。

## Git 文件管理

`localisation/`（翻译原文）、`chn/`（输出译文）、`already/`（翻译缓存）均只在本地保存，不提交到 Git。日志、Python 缓存、虚拟环境和本地密钥文件也已忽略。
Git 中保留源码、`rules.json`、依赖声明、测试和说明文档。克隆后按需创建 `localisation/<游戏>/` 并放入待翻译 YML 文件。

## macOS 图形试运行

双击 `演示程序.command` 可以完整演示扫描、翻译、回写、备份与一键恢复，无需 API Key。
真实使用请双击 `启动翻译程序.command`，在本地界面填写 OpenAI 兼容接口配置。
详细流程与数据存放位置见 [试运行说明.md](试运行说明.md)。

## Windows EXE

文件夹打包配置、Windows 本机构建脚本和 GitHub Actions 工作流已加入，避免单文件启动时反复解压依赖。
使用与构建方法见 [Windows使用说明.md](Windows使用说明.md)。

单个 Mod 扫描支持已有中文自动提取与翻译统计；可手动导入中文文件、文件夹和带原文哈希的缓存 JSON，或导出缓存。
对应关系保存在 SQLite `translation_entries` 表中，按 Mod、原文件、条目键与英文哈希保存历史译文。

### 聚合汉化目录

工作台中的「聚合汉化目录」开关默认开启，适用于所有 Mod。翻译或恢复缓存并成功回写原 Mod 后，程序会再复制一份中文文件到当前数据目录的 `aggregate_mods/<游戏 AppID>/`。不同游戏分别存放，保留本地化目录结构，并为文件名添加原 Mod UID，避免同名文件互相覆盖。点击「打开聚合文件夹」查看成果。

同一 Mod 再次回写时会更新聚合副本；覆盖前的文件保存在数据目录的 `aggregate_backups/`。已不再生成的旧文件只有在内容未被手动修改时才会移除，手动改过的旧文件保留并提示。关闭开关只停止后续复制，已有成果保留。开关随本机配置保存，切换 API 配置不会改变它。

各游戏的 `translation-manifest.json` 记录原 Mod 名称、UID、创意工坊链接和文件对应关系，不包含 API 密钥。聚合复制失败会单独写入日志，不影响原 Mod 已完成的回写。此目录用于整理聚合汉化内容；发布前仍需检查残留英文、格式错误、原作者授权，并准备游戏要求的 Mod 描述文件，程序不会自动上传 Steam。

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
