# SteamCMD 群星匿名下载实验

2026-10-21 在 `translator-server` 实测成功。未使用 Steam 账号或密码。

- 游戏：Stellaris，AppID `281990`
- 原模组：`[4.5+] Stellaris Ascended`，Workshop ID `3393552523`
- 下载结果：SteamCMD 返回 `Success. Downloaded item 3393552523`，7,103,186 字节
- 下载目录：`/srv/steamcmd/library/steamapps/workshop/content/281990/3393552523`
- 文件：463 个，含 `descriptor.mod`、`thumbnail.png` 和 2 个英文 localisation YML（合计 212,366 字节）
- 本结果仅验证上述模组，其他游戏或模组需分别测试权限。

## 服务器安装

SteamCMD 位于 `/srv/steamcmd/client`，由独立账号 `steamfetch` 运行。入口为 `/usr/local/bin/steamcmd`。
Alibaba Cloud Linux 4 缺少 32 位运行库，已将 Debian bookworm 的 i386 libc6、libgcc-s1 解压到 `/srv/steamcmd/runtime`，未替换系统运行库。
官方安装包来自 Valve CDN；完整更新 ZIP 按更新清单 SHA256 校验。`run32` 使用 patchelf 指定独立 ELF 解释器。
标准证书路径 `/etc/ssl/certs/ca-certificates.crt` 链接到系统现有 CA 文件。

## 重复实验

在服务器执行：

```sh
runuser -u steamfetch -- timeout 180 /usr/local/bin/steamcmd \
  -skipinitialbootstrap -inhibitbootstrap \
  +@ShutdownOnFailedCommand 1 +@NoPromptForPassword 1 \
  +force_install_dir /srv/steamcmd/library \
  +login anonymous \
  +workshop_download_item 281990 3393552523 validate \
  +quit
```

以上参数跳过自动引导更新，使用本次已安装的客户端。客户端更新需单独维护，不能永久依赖跳过更新。
下载成功应同时检查输出中的 Success 和实际文件；不能只看退出码。

成功实验日志：`/srv/steamcmd/logs/stellaris-anonymous-download.log`。
Steam 连接日志：`/srv/steamcmd/Steam/logs/connection_log.txt`。

现已接入网页链接导入。网页使用 translator 账号的独立环境 `/srv/workshop-translator/data/steamcmd`，不使用本实验 steamfetch 账号。实际网页导入 Ascended 后保留 4 个文件、666,690 字节，临时完整下载已清理；详细流程见服务器部署说明。
实验后确认 `workshop-translator` 和 `nginx` 均为 active。
