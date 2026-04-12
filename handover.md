# 2026-03-30 会话交接

## 1. 本次会话目标 / 当前阶段目标

本次会话的目标是从零实现一个基于 `yt-dlp` 的 X/Twitter 视频下载 CLI，让用户在命令行中传入一条 X post URL 后即可自动下载视频。

这次落地的是一个可运行的 MVP 命令行工具，不是桌面应用，也不是最终分发方案。除基础下载能力外，本次已经累计完成 3 类关键能力：

- X 登录态获取、Chrome 多 profile 自动识别和自动回退
- macOS / Windows / Linux 的 Chrome 数据目录探测
- 下载完成后直接用 `ffmpeg` 裁切片段，以及中英双语 `--help`

## 2. 当前仓库状态

- 当前目录已经初始化为 git 仓库。
- 当前仓库内容已经覆盖 3 个阶段：
  - 基础 X/Twitter 下载 CLI
  - 跨平台 Chrome profile 路径探测
  - 下载后裁切与中英双语 `--help`
- 当前主要文件：
  - `pyproject.toml`
  - `src/x_downloader/__init__.py`
  - `src/x_downloader/cli.py`
  - `README.md`
  - `handover.md`
- 本地已经安装过可编辑包，并实际运行过 `xdl`。
- 当前依赖 `yt-dlp` 的 Python API。
- 当前自动读取浏览器登录态已实现多平台 Chrome 数据目录探测：
  - macOS: `~/Library/Application Support/Google/Chrome`
  - Windows: `%LOCALAPPDATA%\\Google\\Chrome\\User Data`
  - Linux: `~/.config/google-chrome` 或 `$XDG_CONFIG_HOME/google-chrome`
- 当前裁切能力依赖本机 `ffmpeg`。
- `downloads/` 目录中已经存在本次验证过程中成功下载的样例视频文件，不是占位文件。

## 3. 今天实际遇到的问题

今天实际遇到的主要问题有 7 类：

- 仓库一开始是空目录，没有现成 CLI、项目结构或说明文档，需要从零搭建。
- 当前环境里没有安装 `yt_dlp`，直接 `import yt_dlp` 会报 `ModuleNotFoundError`。
- 机器环境里存在失效代理配置，`yt-dlp` 默认继承环境代理后，访问 X API 时出现 `Unable to connect to proxy` / 代理域名解析失败。
- 即使网络可达，X 的匿名抓取也不稳定，公开帖子在真实测试中出现过 `Bad guest token`，说明仅靠匿名 guest token 不能保证稳定下载。
- 后续用户补充了 Windows 使用场景，因此需要把原本只按 macOS 写的 Chrome profile 自动识别改成跨平台路径探测。
- 用户后续又提出“下载时顺手裁切视频”的需求，因此不能只停在“下载完让用户自己剪”，而是要在同一条 CLI 命令里串起下载和 `ffmpeg` 裁切。
- `argparse` 默认 help 虽然可用，但对中文用户不够直接，因此补了中英双语参数说明。

这些问题直接影响核心能力：用户即使提供了合法 X 帖子链接，也可能因为环境代理或匿名鉴权不稳定而无法下载。

## 4. 原因判断与结论

当前结论如下：

- 下载核心能力本身不需要重新造轮子，`yt-dlp` 已经能处理 X/Twitter 提取和下载，项目应该做薄封装而不是自写抓取器。
- 失效代理问题不是 CLI 解析问题，而是 `yt-dlp` 默认会继承系统环境变量中的代理，导致被无效代理配置污染。
- X 当前的匿名访问不可靠，至少在本次会话的真实测试里出现了 `Bad guest token`，所以浏览器登录态是提升成功率的必要能力。
- 用户的 Chrome 存在多个 profile，单纯要求用户手工导出 cookies 可用但体验差，因此当前更合理的方案是：默认自动读取本机 Chrome profile，并优先尝试检测到 X 登录态的 profile。
- 补 Windows 支持不要求先到 Windows 机器上开发；这部分主要是路径与 profile 探测逻辑，能先在 macOS 上完成代码实现，再去 Windows 实机验证。
- 裁切功能如果要保持“一条命令完成下载 + 裁切”，最简单可靠的做法是先下载完整文件，再调用本机 `ffmpeg` 输出裁切结果，而不是在下载阶段依赖远端媒体分片做部分抓取。
- 中英双语 `--help` 在当前终端环境可行，因为本机默认编码是 `UTF-8`，实测 `xdl --help` 中文可以正常显示。
- 当前最可信的 profile 选择策略是：
  1. 优先有 X 登录态 cookies 的 profile
  2. 同条件下优先 `last_used`
  3. 再按 cookies 数据库更新时间排序

## 5. 这次已经落地的修复

- `pyproject.toml`
  - 建立项目元数据和 `xdl` 命令入口。
  - 声明依赖 `yt-dlp`，让 CLI 可通过可编辑安装直接运行。

- `src/x_downloader/__init__.py`
  - 增加基础版本信息。

- `src/x_downloader/cli.py`
  - 实现基础 CLI 参数解析。
  - 支持 X/Twitter post URL 校验。
  - 通过 `yt_dlp.YoutubeDL` 执行真实下载。
  - 支持 `--output-dir`、`--name-template`、`--audio-only`、`--write-thumbnail`、`--write-info-json`。
  - 支持 `--cookies` 和 `--cookies-from-browser`。
  - 增加 `--chrome-profile` 和 `--list-chrome-profiles`。
  - 默认禁用环境代理继承，除非显式传 `--proxy` 或 `--use-env-proxy`。
  - 实现 macOS / Windows / Linux 的 Chrome 根目录探测。
  - 兼容 `Network/Cookies` 和 `Cookies` 两种 Chromium cookies 数据库位置。
  - 读取 Chrome `Local State` 的 `profile.last_used` 和 `info_cache`。
  - 通过扫描 Cookies 数据库中 `auth_token` / `ct0` / `twid` 判断 profile 是否带 X 登录态。
  - 自动列出 profile，并用 `*` 标记 `last_used`，用 `x` 标记存在 X 登录态。
  - 默认自动选择候选 profile，并在鉴权类错误时按候选顺序自动回退重试。
  - 增加 `--clip-start`、`--clip-end`、`--clip-duration`、`--keep-original`。
  - 下载完成后通过 `ffmpeg` 生成裁切结果；默认删除完整原文件，除非加 `--keep-original`。
  - 增加裁切参数冲突校验，例如 `--clip-end` 和 `--clip-duration` 不能同时传。
  - 将 `argparse` 的命令描述和参数帮助改成中英双语。
  - 改进下载失败提示，让用户明确知道何时应改用 `--chrome-profile`、`--cookies-from-browser` 或 `--cookies`。

- `README.md`
  - 补充安装和使用说明。
  - 补充浏览器 cookies、Chrome profile、代理、自动 profile 检测与回退策略说明。
  - 补充下载后裁切示例。
  - 补充 CLI 已支持中英双语 help 的说明。
  - 更新当前自动 profile 逻辑已扩展到 macOS / Windows / Linux。

- `handover.md`
  - 追加记录跨平台支持、下载后裁切和中英双语 help 的结论。

## 6. 已验证结果

本次实际做过的验证如下：

- 运行 `python3 -m py_compile src/x_downloader/cli.py src/x_downloader/__init__.py`
  - 语法检查通过。

- 运行 `python -m pip install -e .`
  - 成功安装 `x-downloader-0.1.0` 和 `yt-dlp-2026.3.17`。

- 运行 `xdl --help`
  - CLI 帮助可正常展示。
  - 本次已实测帮助文本中的中文可以正常显示。

- 运行 `xdl "https://example.com/test"`
  - 正确返回 URL 校验错误，说明 X/Twitter URL 校验生效。

- 运行 `xdl --list-chrome-profiles`
  - 成功列出本机 Chrome profiles。
  - 本机检测结果中 `Default` 被标记为 `*x`，表示既是 `last_used`，也检测到 X 登录态 cookies。

- 运行静态平台检查
  - 已在代码层补齐 Windows / Linux Chrome 数据目录分支。
  - 本次未在真实 Windows / Linux 机器上执行 `xdl --list-chrome-profiles` 或真实下载。

- 运行 `ffmpeg -version` / `ffprobe -version`
  - 本机存在可用的 `ffmpeg 7.1.1` / `ffprobe 7.1.1`，满足裁切功能依赖。

- 运行本地裁切验证
  - 使用现有下载文件 `downloads/Nucleus☕️-2038074558788562945-...mp4` 做了真实 5 秒裁切。
  - 成功生成文件 `downloads/Nucleus☕️-...clip.start-0.dur-5.mp4`，说明 `ffmpeg` 裁切链路可用。

- 运行裁切参数校验验证
  - 执行 `xdl "https://x.com/example/status/1" --clip-end 10 --clip-duration 5`
  - 正确返回 `Invalid arguments: --clip-end and --clip-duration cannot be used together`

- 运行内部检查，确认自动候选顺序
  - 当前自动顺序以 `Default` 为第一候选，之后才是其他 profile。

- 真实下载验证
  - 当前仓库 `downloads/` 下已有 3 个实际下载成功的视频文件：
    - `Nucleus☕️-2038074558788562945-...mp4`
    - `Kevin-2038246416922095616-...mp4`
    - `Ding-2038334861723971585-...mp4`
  - 用户在最后反馈“我试过了，运行正常”，说明当前 CLI 在用户实际环境中已完成可用性验证。

- 真实失败验证
  - 在匿名访问或环境代理异常时，实际出现过 `Unable to connect to proxy` 和 `Bad guest token`。
  - 这些失败记录推动了后续的代理直连默认值和 Chrome 登录态自动化实现。

## 7. 踩过的坑 / 已否定方案 / 关键约束

- 已否定方案：仅靠匿名下载。
  - 原因：X 匿名 guest token 不稳定，公开帖子也可能返回 `Bad guest token`。

- 已否定方案：默认继承系统环境代理。
  - 原因：当前环境代理配置失效时会直接导致下载失败。
  - 当前做法：默认直连，只在显式指定时使用代理。

- 已否定方案：只让用户手动导出 cookies。
  - 原因：在 Chrome 多账号场景下使用成本高，而且容易选错账号。
  - 当前做法：自动探测本机 Chrome profiles，优先尝试带 X 登录态的 profile。

- 已否定方案：把裁切工作留给用户手动执行第二条 `ffmpeg` 命令。
  - 原因：不满足“一条命令同时完成下载 + 裁切”的目标。
  - 当前做法：在 `xdl` 内部串起下载和 `ffmpeg` 裁切。

- 已否定方案：继续只保留英文 `--help`。
  - 原因：中文用户上手成本更高，而且当前终端环境已经验证可正常显示 UTF-8 中文。
  - 当前做法：帮助文本采用中英双语。

- 关键约束：虽然当前已补 macOS / Windows / Linux 路径探测，但真实行为只在 macOS 上验证过。
  - Windows / Linux 仍需要首次实机确认 Chrome profile 目录、Cookies 数据库位置和权限行为。

- 关键约束：profile 是否“已登录 X”的判断是基于 Cookies 数据库里是否存在 `auth_token` / `ct0` / `twid`。
  - 这是经验性判断，不是 X 官方登录状态 API。

- 关键约束：项目现在没有自动化测试，也没有 CI。
  - 当前验证依赖本机命令和真实下载行为。

- 关键约束：裁切能力依赖本机 `ffmpeg`。
  - 当前 CLI 会在裁切参数出现时检查 `ffmpeg` 是否存在，但不会自动安装。

## 8. 接手后如何继续

接手时建议按下面顺序进行：

1. 先看 `src/x_downloader/cli.py`
   - 这里包含所有当前核心逻辑：URL 校验、yt-dlp 封装、Chrome profile 自动探测、回退策略、下载后裁切、中英双语 help。

2. 再看 `README.md`
   - 确认对外行为、参数说明和边界条件是否仍准确。

3. 运行以下命令做基础检查
   - `python3 -m py_compile src/x_downloader/cli.py`
   - `xdl --help`
   - `xdl --list-chrome-profiles`

4. 做真实下载验证
   - 先直接跑：
     - `xdl "https://x.com/<user>/status/<tweet_id>"`
   - 如果结果不对，再显式指定：
     - `xdl "https://x.com/<user>/status/<tweet_id>" --chrome-profile "Default"`
   - 如果要验证裁切：
     - `xdl "https://x.com/<user>/status/<tweet_id>" --clip-duration 10`

5. 如果下载失败，优先排查
   - X 是否拒绝当前 profile 的登录态
   - 是否需要手动切换到另一个 Chrome profile
   - 是否是平台路径问题
   - 是否是 `yt-dlp` 对 X 当前接口的兼容性变化

## 9. 当前仍存在的问题 / 边界

- 当前已实现跨平台 Chrome 路径探测，但 Windows / Linux 还没有做真实机器验证。
- 仍然依赖用户本机浏览器里存在有效的 X 登录态 cookies。
- 仍然依赖 `yt-dlp` 对 X 的兼容性；如果 X 再次改接口，可能需要更新 `yt-dlp` 或调整错误处理。
- 目前没有单元测试、集成测试或自动化回归测试。
- 当前输出文件名仍直接依赖 yt-dlp 模板，长标题时虽已裁剪，但未额外做更精细的清洗策略。
- 当前裁切输出文件名会附带 `clip.start-...`、`dur-...` 这类后缀，便于区分，但还没有做更短的用户友好命名。
- 当前项目仍是 CLI，不是 GUI，也没有安装包。

## 10. 最终想实现的产品目标

如果继续推进，这个项目的合理长期目标应该是：

- 面向普通用户提供一个稳定的 X 视频下载工具；
- 最好不要求用户理解 `yt-dlp`、cookies 文件或命令行细节；
- 最终形态可以是更完整的 CLI、桌面应用，或可分发安装包；
- 当前阶段只是先把“真实可下载 + 自动吃本机 Chrome 登录态 + 多 profile 自动回退”这条主链路打通。

## 11. 后续 TODO

1. 在真实 Windows 机器上验证 Chrome profile 自动识别
   - 重点确认 `%LOCALAPPDATA%\\Google\\Chrome\\User Data`、`Local State`、`Network/Cookies` 是否和当前实现一致。
   - 做完后才能把 Windows 支持从“代码已实现”升级为“实机已验证”。

2. 在真实 Linux 机器上验证 Chrome profile 自动识别
   - 重点确认 `~/.config/google-chrome` 或 `$XDG_CONFIG_HOME/google-chrome` 的实际行为。
   - 做完后可进一步确认 Linux 下是否还要兼容 Chromium 路径。

3. 为自动回退增加更细的日志
   - 当前只在回退时打印 `Retrying with Chrome profile: ...`。
   - 后续可以打印更明确的候选来源、是否带 X 登录态、为什么切换。

4. 在真实 Windows 机器上验证“下载 + 裁切”完整链路
   - 除了验证 Chrome profile 自动识别，还要确认 Windows 上本机 `ffmpeg`、路径空格和输出命名都正常。

5. 为真实下载流程补自动化测试策略
   - 可以先从纯函数级别的 URL 校验、profile 排序、cookies 状态判断开始。
   - 之后再考虑带 mock 的下载错误回退测试和裁切参数测试。

6. 评估是否支持更多浏览器的“自动多 profile 回退”
   - 目前只有 Chrome 被做成自动探测和优先排序。
   - Edge / Chromium / Brave 仍主要依赖手动参数。

7. 评估是否要增加更明确的“只探测不下载”诊断命令
   - 例如输出当前自动候选顺序、每个 profile 是否检测到 X 登录态。
   - 这样排查用户“为什么自动选错账号”会更快。

8. 评估是否要给裁切能力增加更短别名
   - 例如 `--start` / `--end` / `--duration`。
   - 这样命令行输入会更自然，但要权衡与现有参数名的兼容性。

---

# 2026-03-30 Windows 跟进记录

## 1. 本次会话目标 / 当前阶段目标

这次跟进的目标不是新增下载能力，而是把项目在 Windows 上的实际使用链路补完整，主要处理两类问题：

- `python -m pip install -e .` 之后，`xdl` 命令在 PowerShell 中无法直接识别
- Windows 下通过 Chrome profile 读取 X 登录态时，`yt-dlp` 可能报 `Failed to decrypt with DPAPI`

这次改动仍然属于 CLI 可用性和说明性修复，不是新的产品能力。

## 2. 当前仓库状态

- 当前工作区有 3 个代码/文档改动文件：
  - `src/x_downloader/cli.py`
  - `README.md`
  - `.gitignore`
- 另外，仓库本地存在未纳入版本控制的 `cookies` 目录和 cookies 文件，用户已明确要求不要提交；目前 `cookies` 已被 `.gitignore` 忽略。
- 当前仓库还没有把这次 Windows 跟进提交成新 commit。

## 3. 今天实际遇到的问题

- 用户在 Windows PowerShell 中执行 `xdl` 时出现 `The term 'xdl' is not recognized`。
- 进一步核实后确认：`x-downloader` 已经安装到了 `%USERPROFILE%\.pyenv\pyenv-win\versions\3.14.2\Lib\site-packages`，说明不是包未安装，而是当前 Python 对应的 `Scripts` 目录没有进入 PATH。
- 用户把 `%USERPROFILE%\.pyenv\pyenv-win\versions\3.14.2\Scripts` 手动加到 PATH 后，`xdl` 可正常调用。
- 随后用户在 Windows 上执行：
  - `xdl "<x-url>" --chrome-profile "Profile 7"`
  出现 `Failed to decrypt with DPAPI`。
- 这个错误不是“没有登录 X”，而是 `yt-dlp` 读取 Windows Chrome 加密 cookies 时未能完成解密。

## 4. 原因判断与结论

当前判断如下：

- `xdl` 命令不可用的根因不是项目入口配置错误。`pyproject.toml` 里的 `project.scripts` 正常，问题是 Windows PATH 没包含当前 Python 版本的 `Scripts` 目录。
- Windows 下 `Failed to decrypt with DPAPI` 不是 X 账号状态丢失，而是浏览器 cookies 解密链路失败。
- 这类问题在 macOS 上不一定出现，但在 Windows + Chrome + `yt-dlp --cookies-from-browser` 组合下更常见。
- 对终端用户来说，最稳的回退方案仍然是导出 Netscape 格式的 `cookies.txt`，再用 `--cookies`。
- `document.cookie` 不能替代 `cookies.txt` 导出方案，因为拿不到 `HttpOnly` cookies，无法保证包含 X 登录所需字段。

## 5. 这次已经落地的修复

- `src/x_downloader/cli.py`
  - 新增 `is_browser_cookie_decrypt_error()`，单独识别 `Failed to decrypt with DPAPI` / `app-bound encryption` 一类报错。
  - 新增 `build_cookies_fallback_hint()`，在错误提示里直接拼出当前 URL 对应的 `--cookies` 示例命令。
  - 将浏览器 cookies 解密失败提示改成分行的中英双语说明，明确告诉用户：
    - 先彻底退出 Chrome 再试
    - 仍失败时改用 Netscape `cookies.txt`

- `README.md`
  - 补充 Windows 下 `Failed to decrypt with DPAPI` 的说明。
  - 明确写出这是浏览器 cookies 解密失败，不等于 X 未登录。
  - 明确写出 `cookies.txt` 必须是 Netscape cookie file 格式，不能直接用 `document.cookie` 手工保存。

- `.gitignore`
  - 新增 `cookies` 忽略规则，避免本地导出的 X cookies 文件被误提交。

## 6. 已验证结果

本次实际验证过的内容：

- 项目入口配置检查
  - 已确认 `pyproject.toml` 中存在 `xdl = "x_downloader.cli:main"`。

- Windows Python 安装位置核实
  - 用户确认当前解释器为 `%USERPROFILE%\.pyenv\pyenv-win\versions\3.14.2\python.exe`。
  - 用户确认 `python -m pip show x-downloader` 指向 `3.14.2` 环境。

- `xdl` 命令恢复验证
  - 用户将 `%USERPROFILE%\.pyenv\pyenv-win\versions\3.14.2\Scripts` 加入 PATH 后，确认 `xdl` 已可正常执行。

- README / CLI 改动后的基础回归
  - 已运行 `%USERPROFILE%\.pyenv\pyenv-win\versions\3.14.2\python.exe -m x_downloader.cli --help`
  - 命令执行成功，说明这次对 `cli.py` 的错误提示改动没有破坏 CLI 基础加载。

- `.gitignore` 核查
  - 已运行 `git check-ignore -v cookies cookies\\*`
  - 结果显示 `cookies` 目录已被 `.gitignore` 命中。

## 7. 踩过的坑 / 已否定方案 / 关键约束

- 已否定方案：把“`xdl` 不可用”判断成项目入口配置问题。
  - 实际不是 `console_scripts` 没生成，而是 PATH 没包含当前 Python 版本的 `Scripts` 目录。

- 已否定方案：用 `document.cookie` 手工拼一个 txt 文件代替浏览器导出。
  - 原因是拿不到 `HttpOnly` cookies，不可靠。

- 关键约束：Windows 下 `yt-dlp` 通过 Chrome 直接读 cookies 仍然受浏览器加密策略影响。
  - 当前 CLI 只能改进提示，不能在项目内部绕过 Chrome/Windows 的解密限制。

- 关键约束：仓库本地 `cookies/` 下现在已有真实 cookies 文件。
  - 提交时必须只 add 指定文件，不能使用会误带工作区未跟踪文件的提交方式。

## 8. 接手后如何继续

如果后续继续接手 Windows 兼容性问题，建议按这个顺序：

1. 先确认当前 Python 版本对应的 `Scripts` 目录是否在 PATH
   - Windows + pyenv-win 常见路径：
     - `%USERPROFILE%\.pyenv\pyenv-win\versions\<version>\Scripts`

2. 再确认 `xdl` 是否可调用
   - `xdl --help`

3. 如果命中浏览器 cookies 解密失败，优先让用户尝试：
   - 完全退出 Chrome
   - 重新运行 `xdl "<url>" --chrome-profile "<profile>"`

4. 如果仍失败，直接引导到：
   - `xdl "<url>" --cookies /path/to/cookies.txt`

5. 如需继续优化体验，优先从 `src/x_downloader/cli.py` 的错误分类和提示入手，而不是尝试在项目里自实现 Chrome cookies 解密。

## 9. 当前仍存在的问题 / 边界

- Windows 下直接读取 Chrome cookies 仍然不是 100% 可靠链路。
- 这次只是把报错和文档改得更明确，没有从根本上解决 Chrome/Windows 的解密限制。
- README 已补充 Windows 说明，但还没有单独增加“Windows 安装与排障”专门章节。
- 当前项目仍然没有自动化测试覆盖这类平台相关错误分支。

## 10. 最终想实现的产品目标

长期目标仍然应该是：

- 用户能在各平台上用一条命令稳定下载 X 视频；
- 普通用户不需要理解 `yt-dlp`、DPAPI、Chrome profile 或 cookies 解密机制；
- Windows 下遇到浏览器解密限制时，CLI 至少能给出明确、可执行的下一步，而不是只显示底层异常。

## 11. 后续 TODO

1. 补一个更明确的 Windows 使用章节
   - 包含 PATH、`Scripts` 目录、`cookies.txt` 导出方式和常见报错。

2. 评估是否要增加显式参数或文档示例，支持项目内 `cookies/` 目录用法
   - 用户当前已经开始把导出的 cookies 放到仓库 `cookies/` 目录里，README 可考虑给出明确示例，但要保留 `.gitignore` 保护。

3. 评估是否要在 `README.md` 中单独列出“为什么不能直接用 `document.cookie`”
   - 当前已经写了一句，但后续如果用户群体扩大，可能值得单独放进 FAQ。

4. 如果继续做 Windows 实机优化，优先收集更多失败样例
   - 比如不同 Chrome 版本、不同 profile、是否开启同步、是否仍有 Chrome 后台进程等。

---

# 2026-03-30 用户级配置补充记录

## 1. 本次会话目标 / 当前阶段目标

这次补充的目标是解决两个重复输入问题：

- 用户希望设置一次默认下载目录，之后在任意工作目录下执行 `xdl` 都能下载到同一个固定目录
- 用户希望设置一次默认 `cookies.txt` 路径，之后不必每次都手动传 `--cookies`

这次改动属于 CLI 配置能力补充，仍然是命令行工具体验优化，不是新的下载核心能力。

## 2. 当前仓库状态

- 当前工作区新增改动文件：
  - `src/x_downloader/cli.py`
  - `README.md`
- 本次新增的是用户级配置文件机制；配置文件不放在仓库里，而是放在操作系统用户目录下。
- 当前设计约定的配置文件路径为：
  - Windows: `%APPDATA%\x-downloader\config.json`

## 3. 今天实际遇到的问题

- 当前 `xdl` 的默认下载目录是相对路径 `downloads`，实际行为是“相对于当前命令执行目录”。
- 这意味着用户在不同目录下运行 `xdl` 时，下载结果会散落在不同位置，不符合“设置一次后全局固定”的使用预期。
- 当前 cookies 读取也依赖用户每次显式传 `--cookies`、`--cookies-from-browser` 或 `--chrome-profile`，在已经有固定 `cookies.txt` 的情况下操作重复。

## 4. 原因判断与结论

当前结论如下：

- 仅靠 `--output-dir` 不足以解决“长期默认目录”问题，因为它是单次命令级参数。
- 用用户级配置文件保存默认下载目录和默认 cookies 路径，是当前 CLI 最直接、最可控的方案。
- 这类配置不应写入仓库，也不应依赖当前工作目录；放到 `%APPDATA%\x-downloader\config.json` 更符合 Windows 用户习惯。
- 运行时优先级应该保持清晰：
  1. 命令行显式参数
  2. 用户配置文件
  3. 最终回退默认值

## 5. 这次已经落地的修复

- `src/x_downloader/cli.py`
  - 新增 `get_config_path()`、`load_user_config()`、`save_user_config()`，负责读写 `%APPDATA%\x-downloader\config.json`
  - 新增 `resolve_runtime_defaults()`，在普通下载流程里自动应用已保存的默认下载目录和默认 cookies 文件
  - 新增 `apply_config_actions()`，处理配置相关命令：
    - `--set-default-download`
    - `--clear-default-download`
    - `--set-default-cookies`
    - `--clear-default-cookies`
    - `--show-config`
  - 保持命令行参数优先级高于配置文件：
    - 显式传 `-o/--output-dir` 时，不使用保存的默认下载目录
    - 显式传 `--cookies` 或 `--cookies-from-browser` 时，不使用保存的默认 cookies 文件
  - 为 `--set-default-cookies` 增加存在性校验，避免把不存在的路径写进配置

- `README.md`
  - 补充了设置默认下载目录的示例
  - 补充了设置默认 cookies 文件路径的示例
  - 补充了 `--show-config` 用法
  - 补充了配置文件位置和优先级说明

## 6. 已验证结果

本次实际验证过的内容：

- 运行 `python -m x_downloader.cli --help`
  - 新参数已出现在帮助文本中：
    - `--set-default-download`
    - `--clear-default-download`
    - `--set-default-cookies`
    - `--clear-default-cookies`
    - `--show-config`

- 运行 `python -m x_downloader.cli --show-config`
  - 能正确打印配置文件路径和当前配置内容
  - 在配置文件不存在时，当前输出为空配置 `{}`，行为正常

- 运行 `python -m x_downloader.cli --set-default-cookies <missing-path>`
  - 能正确报错 `Invalid arguments: cookies file does not exist: ...`
  - 说明默认 cookies 配置在写入前已经做文件存在性校验

- 参数帮助兼容性修复
  - 在 `argparse` 帮助文本中，`%APPDATA%` 需要写成 `%%APPDATA%%`
  - 该问题已经修复，`--help` 可正常输出

## 7. 踩过的坑 / 已否定方案 / 关键约束

- 已踩坑：直接在 `argparse` help 文本中写 `%APPDATA%`
  - 原因：`argparse` 会把 `%` 当作格式占位符解析，导致 `ValueError: badly formed help string`
  - 当前做法：帮助文本中使用 `%%APPDATA%%`，最终显示给用户时仍是 `%APPDATA%`

- 已否定方案：只依赖环境变量来存默认目录
  - 对开发者可行，但对普通用户不够直观，且不方便为 cookies 路径提供一致的 CLI 设置入口

- 关键约束：默认 cookies 配置当前只支持文件路径
  - 不会自动保存浏览器 profile 选择，也不会自动持久化 `--cookies-from-browser`

- 关键约束：配置文件属于用户本地状态
  - 不能写入仓库文档中的真实绝对路径，也不能把具体 cookies 文件路径记录到 handover 里

## 8. 接手后如何继续

如果后续继续完善这套配置功能，建议按这个顺序：

1. 先看 `src/x_downloader/cli.py`
   - 重点看：
     - `get_config_path()`
     - `load_user_config()`
     - `save_user_config()`
     - `apply_config_actions()`
     - `resolve_runtime_defaults()`

2. 再看 `README.md`
   - 确认用户侧命令示例和优先级说明是否与代码一致

3. 先跑基础命令验证
   - `xdl --help`
   - `xdl --show-config`

4. 再做真实配置写入验证
   - `xdl --set-default-download "D:/Videos/xdl"`
   - `xdl --set-default-cookies "C:/path/to/cookies.txt"`
   - `xdl --show-config`

5. 最后验证优先级
   - 设置默认下载目录后，再显式传 `-o`，确认显式参数能覆盖默认值
   - 设置默认 cookies 后，再显式传 `--cookies-from-browser`，确认浏览器参数能覆盖默认 cookies 文件

## 9. 当前仍存在的问题 / 边界

- 当前只保存“默认下载目录”和“默认 cookies 文件路径”，没有保存默认 profile、默认代理或默认输出模板。
- 当前没有增加专门的配置 schema 校验；如果用户手工改坏 `config.json`，程序会回退为空配置。
- 这次只验证了 `--help`、`--show-config` 和缺失 cookies 文件报错，尚未在本次会话里做完整的“写入配置后执行真实下载”回归。

## 10. 最终想实现的产品目标

长期目标仍然应该是：

- 用户第一次做完基础配置后，之后日常只需要执行一条 `xdl "<url>"` 就能工作；
- 普通用户不需要每次重新输入下载目录或 cookies 路径；
- CLI 在保留显式参数控制力的同时，提供接近桌面应用偏好的“记住我的默认设置”体验。

## 11. 后续 TODO

1. 真实验证“保存默认下载目录后执行下载”
   - 确认未传 `-o` 时，文件确实落到配置文件指定目录

2. 真实验证“保存默认 cookies 后执行下载”
   - 确认未传 `--cookies` 时，CLI 会自动读取配置中的 cookies 文件

3. 评估是否要支持保存默认浏览器来源
   - 例如默认保存 `chrome + Profile 7`
   - 但这需要谨慎设计，避免和当前 `cookies.txt` 优先级冲突

4. 评估是否要增加配置清理/重置说明
   - 当前已经有 `--clear-default-download` / `--clear-default-cookies`
   - README 未来可以再补一个”如何重置配置”的专门小节

---

# 2026-04-06 YouTube 支持扩展记录

## 1. 本次会话目标 / 当前阶段目标

这次会话的目标是扩展 xdl 支持 YouTube 视频下载，让用户可以用同一条命令和同一套配置系统（默认下载目录、cookies、代理、裁切等）下载 X/Twitter 和 YouTube 两个平台的视频。

这次改动属于功能扩展，不涉及新的下载核心能力，只是放宽 CLI 层的 URL 校验逻辑。

## 2. 当前仓库状态

- 当前工作在 `feature/youtube-support` 分支
- 改动文件：
  - `src/x_downloader/cli.py`
  - `README.md`
- 改动尚未提交到 main，等待用户验证后再合并

## 3. 今天实际遇到的问题

- 当前 `SUPPORTED_HOSTS` 只包含 `x.com` 和 `twitter.com` 相关域名
- `validate_x_url()` 强制要求 URL 必须是 X/Twitter 帖子链接，且必须包含 `/status/` 路径
- 用户希望复用 xdl 的配置系统下载 YouTube 视频，而不是单独使用 yt-dlp

## 4. 原因判断与结论

当前结论如下：

- yt-dlp 本身已完美支持 YouTube，不需要额外的下载逻辑
- 只需在 CLI 层放宽 URL 校验，允许 YouTube 域名通过
- YouTube 链接不需要强制 `/status/` 路径校验，只需验证域名即可
- 可以通过返回平台类型（`x` 或 `youtube`）为后续可能的平台差异化逻辑预留扩展点

## 5. 这次已经落地的修复

- `src/x_downloader/cli.py`
  - 扩展 `SUPPORTED_HOSTS`，新增 YouTube 域名：`youtube.com`、`www.youtube.com`、`m.youtube.com`、`youtu.be`、`www.youtu.be`
  - 新增 `YOUTUBE_HOSTS` 常量，用于快速判断 URL 是否为 YouTube
  - 重命名 `validate_x_url()` 为 `validate_url()`，返回平台类型字符串
  - 更新 CLI 描述和参数帮助文本，支持中英双语
  - 更新错误提示信息

- `README.md`
  - 更新项目描述，支持 X/Twitter 和 YouTube 两个平台
  - 新增 YouTube 使用示例
  - 功能列表新增 YouTube 支持

## 6. 已验证结果

本次实际验证过的内容：

- 运行 `python -m x_downloader.cli --help`
  - CLI 描述已更新为 “Download videos from X/Twitter or YouTube”
  - 参数帮助已更新为 “X/Twitter or YouTube URL”

- 运行 URL 校验测试
  - `validate_url('https://www.youtube.com/watch?v=test')` 返回 `'youtube'`
  - `validate_url('https://youtu.be/abc123')` 返回 `'youtube'`
  - `validate_url('https://x.com/user/status/123')` 返回 `'x'`

- 运行无效 URL 测试
  - `xdl “https://example.com/test”` 正确返回 “Only x.com, twitter.com, or youtube.com URLs are supported”

## 7. 踩过的坑 / 已否定方案 / 关键约束

- 无特殊坑点，改动较为直接
- 关键约束：当前改动在 `feature/youtube-support` 分支，需要用户验证后再合并到 main

## 8. 接手后如何继续

接手时建议按下面顺序进行：

1. 切换到 feature 分支
   - `git checkout feature/youtube-support`

2. 验证 CLI 基础功能
   - `xdl --help`
   - 确认描述和参数帮助已更新

3. 验证 YouTube 下载
   - `xdl “https://www.youtube.com/watch?v=dQw4w9WgXcQ”`
   - 确认下载正常完成

4. 验证配置复用
   - `xdl --set-default-download “D:/Videos”`
   - `xdl “https://youtu.be/xxx”` 确认下载到指定目录

5. 验证通过后合并到 main
   - `git checkout main && git merge feature/youtube-support`

## 9. 当前仍存在的问题 / 边界

- 当前改动在 feature 分支，尚未合并到 main
- YouTube 下载功能尚未进行真实下载验证
- 当前未针对 YouTube 做特殊处理（如 age-restricted 视频、会员视频等），完全依赖 yt-dlp 默认行为

## 10. 最终想实现的产品目标

长期目标仍然应该是：

- 用户用一条命令就能下载 X/Twitter 和 YouTube 视频
- 复用同一套配置系统，无需为不同平台重复设置
- CLI 保持简洁，用户不需要关心底层是哪个平台

## 11. 后续 TODO

1. 真实验证 YouTube 下载
   - 测试普通 YouTube 视频
   - 测试 youtu.be 短链接
   - 测试使用代理下载

2. 验证通过后合并到 main
   - `git checkout main && git merge feature/youtube-support`

3. 评估是否需要针对 YouTube 的特殊处理
   - age-restricted 视频
   - 会员专属内容
   - 播放列表下载（当前 `noplaylist: True`）

4. 评估是否要支持更多平台
   - TikTok、Bilibili 等
   - 需要评估 URL 校验复杂度和维护成本

---

# 2026-04-12 合并与基础测试补齐记录

## 1. 本次会话目标 / 当前阶段目标

这次会话的目标有两件事：

- 把 `feature/youtube-support` 分支安全合并回 `main`
- 给当前 YouTube/X URL 校验和 CLI 帮助文案补最小自动化回归测试

## 2. 当前仓库状态

- `feature/youtube-support` 已提交并 push
- `main` 已 fast-forward 合并到同一提交
- 当前 `main` / `origin/main` 都在：
  - `f101612 Keep OMX runtime state out of repo history`

## 3. 这次已经落地的修复

- `.gitignore`
  - 新增 `.omx/`
  - 避免 OMX 运行时状态、日志、计划文件污染工作区

- `pyproject.toml`
  - 同步项目描述，明确当前 CLI 支持 X/Twitter 和 YouTube

- `tests/test_cli.py`
  - 新增基于 `unittest` 的最小自动化回归测试
  - 当前覆盖：
    - `validate_url()` 对 X / YouTube 的合法链接识别
    - 非法域名 / 非 X status 链接报错
    - `--help` 中的 YouTube 文案
    - 缺少 URL 时的提示文案

## 4. 已验证结果

- `python -m unittest discover -s tests -v`
  - 4 个测试全部通过

- `python -m py_compile src/x_downloader/cli.py src/x_downloader/__init__.py tests/test_cli.py`
  - 语法检查通过

- `python -m x_downloader.cli --help`
  - 仍可正常输出中英双语帮助

- 用户已确认：
  - YouTube 真实下载已在本机手动验证通过

## 5. 当前结论

- YouTube 支持现在已经：
  - 合并进 `main`
  - 与 README / 包描述保持一致
  - 具备最小自动化回归覆盖

- 当前项目仍然没有完整下载链路的自动化集成测试；
  但至少 URL 校验和帮助文案不再完全依赖手工回归。

## 6. 后续建议

1. 如果继续增强稳定性，优先补“无网络 / mock 下载”层的单元测试
   - 例如 `run()` 的参数错误分支
   - cookies 回退提示
   - clipping 参数校验

2. 如果准备发版，再决定版本策略
   - 当前已确定升级到 `0.2.0`
   - 并为该版本创建 tag / release notes
 
---

# 2026-04-12 v0.2.0 发版准备记录

## 1. 本次会话目标 / 当前阶段目标

这次会话只处理发版准备：

- 把项目版本从 `0.1.0` 升到 `0.2.0`
- 生成一份可直接用于 GitHub Release 的 release notes
- 为当前 `main` 创建并推送版本 tag

## 2. 这次已经落地的修复

- `pyproject.toml`
  - 版本号更新到 `0.2.0`

- `src/x_downloader/__init__.py`
  - 包内版本号同步更新到 `0.2.0`

- `release-notes/v0.2.0.md`
  - 新增版本说明，汇总本次发布的主要能力与已知边界

## 3. 当前结论

- 当前 `v0.2.0` 对应的是已经合并进 `main` 的稳定状态
- 该版本的主要增量包括：
  - YouTube 下载支持
  - 默认下载目录 / 默认 cookies 配置
  - Chrome profile 自动探测与回退
  - 下载后裁切
  - 基础自动化回归测试

---

# 2026-04-12 MissAV 支持开发记录

## 1. 本次会话目标 / 当前阶段目标

这次会话的目标是在 `main` 基础上拉新分支，为 `xdl` 增加 MissAV 页面下载支持。

## 2. 当前实现策略

- 当前新分支：`feature/missav-support`
- MissAV 采用两段式策略：
  - 先按现有 `yt-dlp` 直连页面逻辑尝试
  - 遇到 Cloudflare challenge / 403 时，自动回退到本机 Chrome + DevTools 解析真实 HLS `m3u8`
- 解析到的真实视频流会带着原页面 `Referer` 再交给 `yt-dlp` 下载

## 3. 已确认的站点行为

- MissAV 页面本身可在普通 Chrome 中打开，但直接用 `yt-dlp` 抓页面会被 Cloudflare challenge 拦截
- 页面脚本里会初始化 `window.hls`
- 可解析到类似：
  - `https://surrit.com/.../playlist.m3u8`
- 该 `m3u8` 只要带原页面 `Referer`，`yt-dlp` 就能正常识别格式
- 页面存在以下限制，但不影响当前解析思路：
  - 首次点击播放可能弹广告
  - 标签页失焦时视频自动暂停

## 4. 当前结论

- MissAV 最稳的下载入口不是页面 URL 本身，而是页面运行后暴露出的 HLS manifest
- 只要能用本机 Chrome 通过挑战并拿到 `window.hls.url`，后续下载仍可复用现有 `yt-dlp` + clip 流程

## 5. 后续补充

- MissAV 现在新增了交互式清晰度选择：
  - 不传 `--quality` 时，CLI 会列出当前视频支持的分辨率并要求用户选择
  - 传 `--quality low|medium|high` 时，CLI 会跳过交互，直接选对应档位
- `--chrome-profile` 现在会真正参与 MissAV fallback：
  - 会把指定 profile 拷贝到临时 Chrome user-data-dir 后再启动调试会话
  - 这样既能利用目标 profile 的状态，又能尽量避开原 profile 文件锁
