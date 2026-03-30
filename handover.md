# 2026-03-30 会话交接

## 1. 本次会话目标 / 当前阶段目标

本次会话的目标是从零实现一个基于 `yt-dlp` 的 X/Twitter 视频下载 CLI，让用户在命令行中传入一条 X post URL 后即可自动下载视频。

这次落地的是一个可运行的 MVP 命令行工具，不是桌面应用，也不是最终分发方案。除基础下载能力外，本次还重点处理了 X 登录态获取、Chrome 多 profile 自动识别和自动回退的问题。

## 2. 当前仓库状态

- 当前目录不是 git 仓库，无法通过 `git status` / `git diff` 追踪变更，只能基于现有文件和本次实际操作记录交接。
- 当前主要文件：
  - `pyproject.toml`
  - `src/x_downloader/__init__.py`
  - `src/x_downloader/cli.py`
  - `README.md`
  - `handover.md`
- 本地已经安装过可编辑包，并实际运行过 `xdl`。
- 当前依赖 `yt-dlp` 的 Python API。
- 当前自动读取浏览器登录态的实现依赖 macOS 本机 Chrome 数据目录：`~/Library/Application Support/Google/Chrome`。
- `downloads/` 目录中已经存在本次验证过程中成功下载的样例视频文件，不是占位文件。

## 3. 今天实际遇到的问题

今天实际遇到的主要问题有 4 类：

- 仓库一开始是空目录，没有现成 CLI、项目结构或说明文档，需要从零搭建。
- 当前环境里没有安装 `yt_dlp`，直接 `import yt_dlp` 会报 `ModuleNotFoundError`。
- 机器环境里存在失效代理配置，`yt-dlp` 默认继承环境代理后，访问 X API 时出现 `Unable to connect to proxy` / 代理域名解析失败。
- 即使网络可达，X 的匿名抓取也不稳定，公开帖子在真实测试中出现过 `Bad guest token`，说明仅靠匿名 guest token 不能保证稳定下载。

这些问题直接影响核心能力：用户即使提供了合法 X 帖子链接，也可能因为环境代理或匿名鉴权不稳定而无法下载。

## 4. 原因判断与结论

当前结论如下：

- 下载核心能力本身不需要重新造轮子，`yt-dlp` 已经能处理 X/Twitter 提取和下载，项目应该做薄封装而不是自写抓取器。
- 失效代理问题不是 CLI 解析问题，而是 `yt-dlp` 默认会继承系统环境变量中的代理，导致被无效代理配置污染。
- X 当前的匿名访问不可靠，至少在本次会话的真实测试里出现了 `Bad guest token`，所以浏览器登录态是提升成功率的必要能力。
- 用户的 Chrome 存在多个 profile，单纯要求用户手工导出 cookies 可用但体验差，因此当前更合理的方案是：默认自动读取本机 Chrome profile，并优先尝试检测到 X 登录态的 profile。
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
  - 实现 macOS Chrome profile 扫描。
  - 读取 Chrome `Local State` 的 `profile.last_used` 和 `info_cache`。
  - 通过扫描 Cookies 数据库中 `auth_token` / `ct0` / `twid` 判断 profile 是否带 X 登录态。
  - 自动列出 profile，并用 `*` 标记 `last_used`，用 `x` 标记存在 X 登录态。
  - 默认自动选择候选 profile，并在鉴权类错误时按候选顺序自动回退重试。
  - 改进下载失败提示，让用户明确知道何时应改用 `--chrome-profile`、`--cookies-from-browser` 或 `--cookies`。

- `README.md`
  - 补充安装和使用说明。
  - 补充浏览器 cookies、Chrome profile、代理、自动 profile 检测与回退策略说明。
  - 明确当前自动 profile 逻辑是基于 macOS Chrome 路径的实现。

- `handover.md`
  - 新建交接文档，记录本次实现、验证、问题与后续工作。

## 6. 已验证结果

本次实际做过的验证如下：

- 运行 `python3 -m py_compile src/x_downloader/cli.py src/x_downloader/__init__.py`
  - 语法检查通过。

- 运行 `python -m pip install -e .`
  - 成功安装 `x-downloader-0.1.0` 和 `yt-dlp-2026.3.17`。

- 运行 `xdl --help`
  - CLI 帮助可正常展示。

- 运行 `xdl "https://example.com/test"`
  - 正确返回 URL 校验错误，说明 X/Twitter URL 校验生效。

- 运行 `xdl --list-chrome-profiles`
  - 成功列出本机 Chrome profiles。
  - 本机检测结果中 `Default` 被标记为 `*x`，表示既是 `last_used`，也检测到 X 登录态 cookies。

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

- 关键约束：当前 profile 自动识别只覆盖 macOS Chrome。
  - 原因：实现里直接使用了 macOS Chrome 数据目录。

- 关键约束：profile 是否“已登录 X”的判断是基于 Cookies 数据库里是否存在 `auth_token` / `ct0` / `twid`。
  - 这是经验性判断，不是 X 官方登录状态 API。

- 关键约束：项目现在没有自动化测试，也没有 CI。
  - 当前验证依赖本机命令和真实下载行为。

## 8. 接手后如何继续

接手时建议按下面顺序进行：

1. 先看 `src/x_downloader/cli.py`
   - 这里包含所有当前核心逻辑：URL 校验、yt-dlp 封装、Chrome profile 自动探测、回退策略。

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

5. 如果下载失败，优先排查
   - X 是否拒绝当前 profile 的登录态
   - 是否需要手动切换到另一个 Chrome profile
   - 是否是平台路径问题
   - 是否是 `yt-dlp` 对 X 当前接口的兼容性变化

## 9. 当前仍存在的问题 / 边界

- 当前不是跨平台实现，Chrome profile 自动识别仅按 macOS 处理。
- 仍然依赖用户本机浏览器里存在有效的 X 登录态 cookies。
- 仍然依赖 `yt-dlp` 对 X 的兼容性；如果 X 再次改接口，可能需要更新 `yt-dlp` 或调整错误处理。
- 目前没有单元测试、集成测试或自动化回归测试。
- 当前输出文件名仍直接依赖 yt-dlp 模板，长标题时虽已裁剪，但未额外做更精细的清洗策略。
- 当前项目仍是 CLI，不是 GUI，也没有安装包。

## 10. 最终想实现的产品目标

如果继续推进，这个项目的合理长期目标应该是：

- 面向普通用户提供一个稳定的 X 视频下载工具；
- 最好不要求用户理解 `yt-dlp`、cookies 文件或命令行细节；
- 最终形态可以是更完整的 CLI、桌面应用，或可分发安装包；
- 当前阶段只是先把“真实可下载 + 自动吃本机 Chrome 登录态 + 多 profile 自动回退”这条主链路打通。

## 11. 后续 TODO

1. 给 Chrome profile 自动识别补平台分支
   - 增加 Windows / Linux 的 Chrome 数据目录支持。
   - 这样当前自动读取浏览器登录态的逻辑才能真正跨平台。

2. 为自动回退增加更细的日志
   - 当前只在回退时打印 `Retrying with Chrome profile: ...`。
   - 后续可以打印更明确的候选来源、是否带 X 登录态、为什么切换。

3. 为真实下载流程补自动化测试策略
   - 可以先从纯函数级别的 URL 校验、profile 排序、cookies 状态判断开始。
   - 之后再考虑带 mock 的下载错误回退测试。

4. 评估是否支持更多浏览器的“自动多 profile 回退”
   - 目前只有 Chrome 被做成自动探测和优先排序。
   - Edge / Chromium / Brave 仍主要依赖手动参数。

5. 评估是否要增加更明确的“只探测不下载”诊断命令
   - 例如输出当前自动候选顺序、每个 profile 是否检测到 X 登录态。
   - 这样排查用户“为什么自动选错账号”会更快。
