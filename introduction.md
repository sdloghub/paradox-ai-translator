# Paradox AI Translator - 综合说明文档 (Introduction & Documentation)

欢迎使用 **Paradox AI Translator**（P社游戏工坊 Mod 本地与在线翻译工作台）。

本项目专为五款 Paradox 经典策略游戏设计：
- **群星 (Stellaris)**
- **钢铁雄心 4 (Hearts of Iron IV)**
- **欧陆风云 4 (Europa Universalis IV)**
- **十字军之王 3 (Crusader Kings III)**
- **维多利亚 3 (Victoria 3)**

核心特性在于：**精准保护变量格式**（`$variables$`、`[scripted_loc]`、`§` 颜色代码、图标与转义符）、**基于英文 SHA-256 哈希的严格缓存复用**（仅当 Mod、键名与英文原文完全匹配时复用，永不覆盖更新后的源文本），以及**本地与云端双架构支持**。

---

## 目录

- [1. macOS 桌面端指南](#1-macos-桌面端指南)
  - [1.1 快速上手](#11-快速上手)
  - [1.2 安全性与权限说明 (Gatekeeper)](#12-安全性与权限说明-gatekeeper)
  - [1.3 数据目录与便携模式](#13-数据目录与便携模式)
  - [1.4 原生文件选择器与后台退出](#14-原生文件选择器与后台退出)
  - [1.5 从源码运行与构建应用](#15-从源码运行与构建应用)
- [2. Windows 桌面端指南](#2-windows-桌面端指南)
  - [2.1 快速上手与运行](#21-快速上手与运行)
  - [2.2 数据目录与命令行参数](#22-数据目录与命令行参数)
  - [2.3 Steam 库检测机制](#23-steam-库检测机制)
  - [2.4 本机构建与打包](#24-本机构建与打包)
  - [2.5 GitHub Actions 自动构建](#25-github-actions-自动构建)
  - [2.6 扫描机制、哈希缓存与完成标记](#26-扫描机制哈希缓存与完成标记)
- [3. 服务器端 (Web 版本) 部署与运维指南](#3-服务器端-web-版本-部署与运维指南)
  - [3.1 架构与在线服务概览](#31-架构与在线服务概览)
  - [3.2 访客隔离与数据安全](#32-访客隔离与数据安全)
  - [3.3 SteamCMD 集成说明](#33-steamcmd-集成说明)
  - [3.4 Mod 权限管理与共享原文库](#34-mod-权限管理与共享原文库)
  - [3.5 系统服务与 Nginx 反向代理配置](#35-系统服务与-nginx-反向代理配置)
  - [3.6 多语言与术语表支持](#36-多语言与术语表支持)
  - [3.7 开发者维护终端 (PTY)](#37-开发者维护终端-pty)
- [4. 条目浏览、人工标注与高级功能](#4-条目浏览人工标注与高级功能)
- [5. 常见问题排查 (FAQ)](#5-常见问题排查-faq)

---

## 1. macOS 桌面端指南

适用于 Apple Silicon（M 系列芯片，arm64）及 macOS 11 或更新版本。使用 Release 打包版本无需另行安装 Python。

### 1.1 快速上手
1. 从 Releases 下载 `WorkshopTranslator-macOS-arm64.zip`。
2. 解压后，将整个 `WorkshopTranslator-macOS-arm64` 文件夹移到固定位置（例如 `/Applications` 或用户主目录）。
3. 双击 `WorkshopTranslator.app`，稍候会自动在默认浏览器打开本机工作台（默认端口 `8765`）。
4. 在页面展开「API 与 Steam 库设置」，填写你的 API 密钥配置，点击「刷新目录」，即可扫描并开始翻译。

### 1.2 安全性与权限说明 (Gatekeeper)
由于独立构建版本未购买 Apple Developer ID 签名与公证，首次双击打开若被 macOS 系统阻止：
- 打开 **系统设置 → 隐私与安全性**（System Settings → Privacy & Security）。
- 在安全性分栏中找到被拦截的 `WorkshopTranslator`，点击 **「仍要打开」**（Open Anyway）。
- 切勿关闭系统整体 SIP 安全防护，只需针对该应用授权一次即可正常运行。

### 1.3 数据目录与便携模式
- **默认存储路径**：
  配置、本地 SQLite 数据库和翻译备份保存在：
  `~/Library/Application Support/WorkshopTranslator/app_data`
- **运行日志**：
  `~/Library/Logs/WorkshopTranslator/application.log`
- **便携模式（本文件夹模式）**：
  在设置中若选择「本文件夹模式」，会将 `config.json` 和 `providers.json` 保存在 `.app` 同级目录下，不会写入 `.app` 内部结构中。
  更新程序时，请保留现有配置文件，直接替换 `.app` 即可保留所有已保存的密钥与设置。

### 1.4 原生文件选择器与后台退出
- **文件选择**：macOS 下点击「选择文件 / 选择文件夹」直接调用系统原生 AppKit 窗口，窗口居中置前，不额外加载 Tkinter 或弹出外部 Python 窗口；若窗口被取消不会清空已输入路径。
- **退出程序**：工作台在关闭浏览器标签后仍在后台保持服务。若需完全退出，可打开 macOS「活动监视器」（Activity Monitor），搜索 `WorkshopTranslator` 并结束进程；或在终端查找并终止相关 Python 进程。

### 1.5 从源码运行与构建应用
- **一键运行脚本**：在项目根目录下双击 `setup_mac.command`（或终端运行 `./setup_mac.command`），脚本会自动创建 `.venv`、检查依赖并启动工作台。
- **打包为 .app 与 .zip**：
  在根目录创建 Python 3.12 虚拟环境并安装依赖：
  ```sh
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt -r packaging/requirements-build.txt pillow
  .venv/bin/python packaging/build_macos.py
  ```
  打包产物将输出在 `dist/WorkshopTranslator-macOS-arm64.zip`。
  使用 `.venv/bin/python packaging/build_macos.py --update` 可生成仅含应用与说明的覆盖更新包。

---

## 2. Windows 桌面端指南

目标平台为 Windows 10 / Windows 11 x64。提供免 Python 环境的绿色分发包 `WorkshopTranslator.exe`，也支持从源码一键运行。

### 2.1 快速上手与运行
- **运行发行版**：
  1. 下载并解压发布压缩包 `WorkshopTranslator-Windows.zip`。
  2. 保持 `WorkshopTranslator.exe` 与 `_internal` 依赖文件夹处于同级目录。
  3. 双击 `WorkshopTranslator.exe` 启动。程序会保留一个控制台窗口，并自动打开默认浏览器访问控制台；关闭该控制台窗口或按下 `Ctrl+C` 即可停止服务。
- **从源码一键启动**：
  项目根目录下提供了 Windows 一键脚本 `start_windows.bat`。双击即可自动检测/配置 Python 虚拟环境并启动程序。
- **离线演示模式**：
  执行 `WorkshopTranslator.exe --demo`（或 `start_windows.bat --demo`）即可进入演示模式，无需连接真实 Steam 库或付费 API 即可体验完整流程。

### 2.2 数据目录与命令行参数
- **默认数据路径**：
  密钥配置、SQLite 历史备份及翻译缓存存储于：
  `%LOCALAPPDATA%\WorkshopTranslator\app_data`
- **演示数据路径**：
  演示数据保存在 `%LOCALAPPDATA%\WorkshopTranslator\app_data_demo`。
- **自定义数据目录**：
  可通过 `--data-dir` 参数指定数据目录，例如：
  ```cmd
  WorkshopTranslator.exe --data-dir "D:\WorkshopTranslatorData"
  ```
  数据与程序本体分离，升级或替换 EXE 不会遗失任何历史翻译数据。

### 2.3 Steam 库检测机制
程序启动时会自动检测 Windows 注册表中的 Steam 安装路径，并自动解析其主库与 `steamapps\libraryfolders.vdf` 中配置的所有附加游戏库目录。若你的 Mod 存放在特殊路径或非官方库中，可在界面设置面板的「Steam 库路径」文本框中手动追加，每行一个绝对路径。

### 2.4 本机构建与打包
在 Windows 机器上安装 Python 3.12 x64，在项目根目录运行 PowerShell：
```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```
脚本将自动创建 `.venv-build`、安装打包依赖、执行测试套件、调用 PyInstaller 打包并在本地执行 `--self-test` 自检。成功后将在 `dist\WorkshopTranslator` 生成完整运行目录，并在 `dist\` 下生成发布压缩包。

### 2.5 GitHub Actions 自动构建
仓库包含 `.github/workflows/build-windows.yml`。每次推送到打包分支或手动触发时：
- 在 Windows x64 虚拟环境中自动检出代码、安装依赖并运行测试；
- 生成 EXE 并运行 `--self-test` 端到端离线自检；
- 打包并生成包含 EXE、SHA-256 校验文件的 artifact 压缩包，保证构建环境无私有凭据泄漏。

### 2.6 扫描机制、哈希缓存与完成标记
- **Mod 状态识别**：
  - 「未扫描」：首次加载目录清单后默认显示。
  - 「扫描此 Mod」：提取本地中文与对应英文原句，实时计算并校验英文原句的 SHA-256 哈希值。
  - 统计指标：**总条目数、已翻译、未翻译、需更新、格式错误**。其中「需更新」表示同一键名在原翻译库中存在历史译文，但当前英文原文哈希与历史版本不一致，防止旧译文误覆盖改版后的新内容。
- **双重存储架构**：
  - `completed.json`：存储已完成的译文映射及对应英文 SHA-256 哈希标头，供快速检索。
  - `translations.sqlite3`：存储全量词条、历史版本映射、来源追踪（人工导入/AI 生成）及人工审核标记。

---

## 3. 服务器端 (Web 版本) 部署与运维指南

本项目支持作为公共 Web 服务部署（在线参考站点：`https://paradox-ai-translator.com/`），供外部访客直接在线汉化工坊 Mod。

### 3.1 架构与在线服务概览
- **标准部署路径**：
  - 应用代码目录：`/srv/workshop-translator/app`
  - 持久化数据目录：`/srv/workshop-translator/data`
  - 专用运行系统账户：`translator`
- **网络流转**：
  - Nginx 监听 80 (HTTP 重定向) 与 443 (HTTPS SSL)；
  - Nginx 反向代理将请求转发至本机后端内部端口 `8765`（后端服务绑定 `127.0.0.1:8765`，切勿向公网直接开放 8765 端口）；
  - 配置文件参考 `deploy/paradox-ai-translator-http.conf` 与 `deploy/paradox-ai-translator-https.conf`。

### 3.2 访客隔离与数据安全
1. **零持久化密钥**：
   访客在 Web 端提交的 API Key 仅保存在其单次浏览器内存与当前会话任务中，**服务器绝不将访客的 API Key 写入磁盘、日志或数据库**。
2. **工作区隔离**：
   每位访客基于独立的安全 Cookie 映射专属的沙盒工作区（Workspace），工作区之间相互隔离，无法读取或篡改其他访客的文件、任务与临时译文。
3. **临时文件清理**：
   任务完成后，工作区中的临时下载文件和日志按预定策略自动回收，防止磁盘被大量 Mod 占满。

### 3.3 SteamCMD 集成说明
Web 版允许访客直接输入 Steam 创意工坊链接或 Mod ID。服务器通过调用本地 SteamCMD 工具匿名下载 Mod 资产：
- SteamCMD 运行账户建议设为独立的非特权账户（如 `steamfetch`），与 `translator` 服务账号分离。
- 过滤机制：SteamCMD 下载完成后，后端服务仅提取 `localisation` 目录中的 YML 本地化文件及必要的描述文件，立刻清理其余无用的模型、材质、音频等庞大资源，极大节约磁盘与带宽。
- 详细环境准备与 32 位运行库配置请参阅 [deploy/steamcmd.md](deploy/steamcmd.md)。

### 3.4 Mod 权限管理与共享原文库
- **公共原文库**：管理员上传的原 Mod 压缩包将被提取并作为公共源，访客与管理员均可检索；
- **访客权限开关**：管理员登录后，可在工作台针对特定 Mod 取消「向访客开放此 Mod」。关闭后访客将无法通过链接查询、下载或在列表中浏览该 Mod；重新开放后立即恢复。
- **管理员凭据配置**：通过外部安全环境文件 `login.env` 注入，使用 PBKDF2 安全加盐哈希，源码及 Git 仓库中严禁硬编码任何密码。

### 3.5 系统服务与 Nginx 反向代理配置
- **systemd 服务配置**（见 `deploy/workshop-translator.service`）：
  启用了 `ProtectSystem=full`、`ProtectHome=true` 及严格的可写目录限制，保障宿主机系统文件免受意外篡改。
- **安全 Cookie 与代理协议头**：
  Nginx 反代必须正确转发：
  ```nginx
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto https;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  ```
  后端据此启用 Secure Cookie 策略，防止中间人窃取会话。
- **平滑更新与运维**：
  在服务器更新代码前，先备份持久化数据：
  ```sh
  cd /srv/workshop-translator/app
  python3 -m unittest discover -s tests
  sudo systemctl restart workshop-translator
  ```

### 3.6 多语言与术语表支持
- **界面语言与目标语言联动**：
  右上角提供 **简体中文 (zh-CN)**、**繁體中文 (zh-TW)**、**俄语 (ru)**、**韩语 (ko)**、**日语 (ja)** 五种语言切换。选择对应语言后，不仅切换界面文案，还会自动关联该语言的提示词模板与工坊语言槽（`simp_chinese`、`russian`、`korean`、`japanese`）。
- **术语表 (Glossary) 与提取**：
  依赖 `glossary.py`、`browser_translator.js` 及 SQLite 术语表。系统支持基于历史译文自动提取高频专用名词，并在 AI 翻译时注入上下文，保证人名、星系名、科技名在全 Mod 中译名高度统一。

### 3.7 开发者维护终端 (PTY)
- 仅在管理员/开发者登录且处于开发者模式时，网页底部会展示轻量级 Web 终端入口。
- 运行于 `translator` 账号上下文，受 systemd 安全沙盒约束，不具备 root 提权；
- 每次最长连接 15 分钟，最多支持 4 个并发连接，用于执行 `systemctl status`、查看日志、排查文件权限等轻量维护工作。
- 注：Codex CLI 相关旧接口已弃用并关闭。

---

## 4. 条目浏览、人工标注与高级功能

在 Mod 详情区点击 **「浏览翻译条目」** 即可进入专业级词条管理界面：
1. **多维度筛选**：
   支持按「全部」、「未翻译」、「已翻译」、「需更新（原文变化）」、「格式错误」及「人工标注」进行状态过滤。
2. **全局搜索与分页**：
   可按词条键名（Key）、英文原文、中文译文或所在文件路径进行毫秒级模糊查询。
3. **原位编辑与人工标注**：
   - 支持直接在网页表格中修改译文并即时保存回源文件；
   - 支持为词条打上「人工审核通过」或「待微调」等人工标注，人工标注优先于自动检测显示，但不会污染哈希比对基准。
4. **生成独立翻译 Mod**：
   点击「生成翻译 Mod」，工作台会在 Paradox 游戏本地的 Mod 目录（`Documents/Paradox Interactive/<游戏>/mod/`）中生成一个符合游戏官方加载规范的独立外挂汉化 Mod，避免 Steam 创意工坊更新时覆盖已有汉化成果。

---

## 5. 常见问题排查 (FAQ)

### Q1: 运行脚本或程序后，提示端口 8765 被占用？
**答**：说明旧版工作台进程仍在后台运行。
- **Windows**：打开任务管理器，结束 `WorkshopTranslator.exe` 或残留的 `python.exe` 进程。
- **macOS**：打开活动监视器，搜索并结束 `WorkshopTranslator` 进程；或在终端执行 `killall WorkshopTranslator`。

### Q2: 为什么 Mod 提示「格式错误」？
**答**：P社脚本本地化文本中包含 `$VARIABLE$`、`§Y黄色高亮§!`、`[Root.GetName]` 等特殊控制符。AI 在翻译时如果遗失或破坏了这部分符号，程序会自动捕获并阻止该错误行写入，该条目将保留英文原文，并在日志中输出具体文件与行号，以防止游戏启动时崩溃或文字乱码。你可以进入「浏览翻译条目」进行手动修复。

### Q3: 为什么扫描时显示「需更新」？
**答**：当 Mod 在工坊更新后，如果某条英文词条的文字发生变化，其 SHA-256 哈希值与历史缓存不再一致。程序会将其标记为「需更新」，并以历史中文译文作为参考，分批提交给 AI 重新翻译该句，既保证准确性，又避免重新翻译未变更的内容。

### Q4: 如何完全备份我的汉化成果？
**答**：在对应 Mod 下点击 **「导出中文 + 哈希 (.zip)」**，即可下载包含完整汉化 YML 与 SHA-256 哈希记录的压缩包。日后在任何电脑上点击「导入译文」选择该压缩包，即可瞬间秒级恢复 100% 缓存，无需消耗任何 API Token！
