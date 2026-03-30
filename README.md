# x-downloader

一个基于 [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) 的 X/Twitter 视频下载 CLI。  
用户提供一条 X post URL，工具会自动抓取并下载其中的视频。

## 功能

- 支持 `x.com` / `twitter.com` 帖子链接
- 直接复用 `yt-dlp` 的提取和下载能力
- 可指定输出目录
- 可传入 cookies 下载需要登录才能访问的帖子
- 支持直接从浏览器读取登录 cookies
- 默认自动读取 Chrome 最近使用的 profile
- 已实现 macOS / Windows / Linux 的 Chrome 数据目录探测
- 默认忽略系统环境中的代理变量，避免被失效代理影响
- 支持下载后直接调用 `ffmpeg` 裁切视频或音频片段
- `xdl --help` 已提供中英双语参数说明
- 可选保存缩略图和元数据 JSON

## 安装

### 方式一：本地开发安装

```bash
python3 -m pip install -e .
```

安装后可直接使用：

```bash
xdl "https://x.com/<user>/status/<tweet_id>"
```

### 方式二：直接运行模块

如果你不想安装命令：

```bash
python3 -m x_downloader.cli "https://x.com/<user>/status/<tweet_id>"
```

## 用法

```bash
xdl "https://x.com/Interior/status/463440424141459456"
```

默认情况下，如果你没有传 `--cookies` 或 `--cookies-from-browser`，程序会自动尝试读取：

- 当前平台上的 Chrome 最近使用 profile
- 找不到 `last_used` 时，回退到最近活跃的 Chrome profile

下载到指定目录：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" -o ./videos
```

设置全局默认下载目录（保存到 `%APPDATA%/x-downloader/config.json`）：

```bash
xdl --set-default-download "D:/Videos/xdl"
```

设置后，即使你在任意目录下执行 `xdl`，未显式传 `-o` 时也会默认下载到这个目录。

需要登录的帖子：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --cookies ~/Downloads/cookies.txt
```

设置全局默认 cookies 文件（保存到 `%APPDATA%/x-downloader/config.json`）：

```bash
xdl --set-default-cookies "C:/path/to/cookies.txt"
```

设置后，未显式传 `--cookies` 或 `--cookies-from-browser` 时，CLI 会优先使用这个默认 cookies 文件。

查看当前配置：

```bash
xdl --show-config
```

直接读取浏览器登录态：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --cookies-from-browser chrome
```

如果你的 Chrome 有多个账号，可指定具体 profile：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --chrome-profile "Profile 5"
```

在 Windows 上，如果你看到类似 `Failed to decrypt with DPAPI` 的报错，这通常不是因为你没有登录 X，而是 `yt-dlp` 无法解密 Chrome 的加密 cookies。先彻底退出 Chrome 后重试；如果仍然失败，建议改用导出的 `cookies.txt` 文件：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --cookies C:/path/to/cookies.txt
```

注意：`cookies.txt` 需要是浏览器扩展或其他工具导出的 Netscape cookie file 格式；不能直接用 `document.cookie` 手工保存，因为它通常拿不到 `HttpOnly` 登录 cookies。

先查看本机有哪些 Chrome profiles：

```bash
xdl --list-chrome-profiles
```

输出里：

- `*` 表示 Chrome `last_used` profile
- `x` 表示该 profile 检测到了 X/Twitter 登录态 cookies
- `*x` 表示两者同时满足，CLI 会优先尝试它

如果你显式指定浏览器读取，也可以和 profile 一起用：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --cookies-from-browser chrome --chrome-profile "Default"
```

如果你确实需要走代理：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --proxy http://127.0.0.1:7890
```

如果你希望继承系统环境变量里的代理配置：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --use-env-proxy
```

同时保存缩略图和元数据：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --write-thumbnail --write-info-json
```

下载并裁切前 10 秒：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --clip-duration 10
```

下载并裁切从第 15 秒开始的 30 秒：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --clip-start 15 --clip-duration 30
```

下载并裁切第 20 秒到第 50 秒，同时保留完整原视频：

```bash
xdl "https://x.com/<user>/status/<tweet_id>" --clip-start 20 --clip-end 50 --keep-original
```

## 常用参数

- `-o, --output-dir`：下载目录，默认 `./downloads`
- `-n, --name-template`：输出文件命名模板
- `--cookies`：cookies 文件路径
- `--set-default-download`：保存默认下载目录到用户配置
- `--clear-default-download`：清除默认下载目录
- `--set-default-cookies`：保存默认 cookies 文件路径到用户配置
- `--clear-default-cookies`：清除默认 cookies 文件路径
- `--show-config`：查看当前用户配置
- `--cookies-from-browser`：直接从本机浏览器读取 cookies
- `--chrome-profile`：指定 Chrome profile，比如 `Default`、`Profile 5`
- `--list-chrome-profiles`：列出本机 Chrome profiles，`*` 表示最近使用，`x` 表示检测到 X 登录态
- `--proxy`：代理地址
- `--use-env-proxy`：使用环境变量中的代理配置
- `--audio-only`：只下载音频
- `--write-thumbnail`：保存缩略图
- `--write-info-json`：保存元数据 JSON
- `--clip-start`：下载后裁切起始时间
- `--clip-end`：下载后裁切结束时间
- `--clip-duration`：下载后裁切时长
- `--keep-original`：裁切后保留完整原文件

## 说明

- X 上的受保护内容、仅登录可见内容，或者遇到 guest token 问题时，CLI 会优先尝试“有 X 登录态”的 Chrome profile，再按最近活跃顺序自动回退；不对时再用 `--chrome-profile` 手动切换
- 用户配置文件默认保存在 Windows 的 `%APPDATA%\x-downloader\config.json`；当前可保存默认下载目录和默认 cookies 文件路径。命令行显式参数优先级高于配置文件
- 当前已经实现 macOS / Windows / Linux 的 Chrome 数据目录探测；但这次只在 macOS 上做了真实验证，Windows / Linux 仍建议首次使用时实机检查
- Windows 下如果遇到 `Failed to decrypt with DPAPI` 一类错误，通常是浏览器 cookie 解密失败，不等于 X 未登录。此时优先尝试彻底关闭 Chrome；仍失败时，改用导出的 Netscape `cookies.txt` 文件最稳
- 传入 `--clip-start` / `--clip-end` / `--clip-duration` 时，CLI 会先下载，再调用本机 `ffmpeg` 生成裁切结果；默认会删除刚下载的完整原文件，除非加 `--keep-original`
- 实际解析、鉴权和下载逻辑由 `yt-dlp` 提供，因此兼容性会跟随 `yt-dlp` 更新
