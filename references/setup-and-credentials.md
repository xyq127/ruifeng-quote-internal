# 首次配置、凭据与依赖（详解）

SKILL.md 正文只保留 Agent 必须遵守的「首次运行检测」行为和关键命令；本文件是完整的配置存储机制、自包含脚本用法、可选 CLI 安装与 CDP 细节，供按需查阅。

## 个人配置文件

所有个人凭据集中在**一份**个人配置文件里——睿锋登录手机号+密码、17vin 用户名+密码、qwen-vision 的 SiliconFlow API Key 一处录入：

```bash
python scripts/personal_config.py init     # 交互式录入（密码用 getpass，不进命令行历史）
python scripts/personal_config.py show     # 查看状态（密码/Key 自动打码）
```

- **存储位置**：`~/.cli-anything-platform-service/config.json`（权限 `0o600` 仅本人可读；`RUIFENG_CONFIG` 可改路径）。与睿锋自包含模块、17vin 网页登录凭据、RayForm-CLI **共用同一文件**，token 互通。
- **不随 skill 分发**：该文件在用户 `$HOME` 下，`npm install` 重装 skill **不会覆盖或读取它**；仓库内只有无密钥的模板 `scripts/config.example.json` 供参考。
- 自包含脚本（`ruifeng_platform.py` / `recognize_image.py`）从这份配置读凭据；17vin 段（用户名/密码）供网页登录使用。环境变量（`SILICONFLOW_API_KEY`、`PLATFORM_*`）始终可临时覆盖。

### 首次运行检测的退出码语义

```bash
python scripts/personal_config.py check                 # 全部功能；退出码 0=就绪, 2=首次运行/缺项
python scripts/personal_config.py check --feature qwen  # 只查图片识别所需 Key（按本次任务需要）
```

- **退出码 0** → 配置就绪，正常执行。
- **退出码 2（首次运行 / 缺项）→ 不要尝试查询。** 把脚本输出的「缺少项」清单**转达给用户**，请用户**在自己的终端**运行 `python scripts/personal_config.py init` 录入。
  - 密码/Key 用 `getpass` 安全输入，**不要让用户把密码发给 Agent**，也不要由 Agent 代填（避免进入对话/命令行历史）。
  - 用户也可临时用环境变量提供（`SILICONFLOW_API_KEY` / `17VIN_*` / `PLATFORM_*`）。
  - 配置完成后再继续原任务。

> 任一自包含脚本在凭据缺失时也会自行打印同样的首次运行提示并非零退出——Agent 看到该提示即按上述方式引导用户，不要反复重试。

## 主路径：自包含脚本（仅需 Python3 + requests，无需安装 CLI）

装好本 skill 即可直接用，是查询的**默认主路径**。

### 睿锋平台（`scripts/ruifeng_platform.py`）

登录、后台产品搜索、产品详情、价格查询全部内置：

```bash
python scripts/ruifeng_platform.py config-use prod              # 选环境(test 需再 config-set --base-url)
python scripts/ruifeng_platform.py login --mobile <手机号>       # 密码交互输入，token 落盘
python scripts/ruifeng_platform.py search --keyword 90363-45050  # 后台搜索→productId
python scripts/ruifeng_platform.py price --product-id <ID> --json # 采购价/P1/P2/P3
```

**登录态自愈：** 查询链路优先直连睿锋平台；任意查询遇到登录态失效（HTTP 401/403，或 HTTP 200 但 `body.code=401` / `status=false` 且消息含「登录/token/失效/过期」）时，**立即用已存账号密码自动重登一次并重试**，新 token 落盘复用，全程无需人工介入。自动重登要求 `login` 时把密码写入配置（文件 `0o600` 仅本用户可读）；首次无 token 但已存凭据时也会自动登录。如需更高安全性，`login --no-save-password` 可不落盘密码（此时失效需手动重新 `login`）。

### 17vin 网页登录凭据（浏览器 CDP，付费 API 已停用）

17vin 查询统一走浏览器（`www.17vin.com` partsearch / EPC 树），需先登录网页。账号密码用 `python scripts/personal_config.py init` 录入到配置 `vin17` 段（用户名/密码，文件 `0o600`），供人工或 CDP 自动登录使用——**不在分发的 skill 里硬编码账号**。查询路径见 `modules/02-vin17-epc-query/SKILL.md` 与 `references/17vin-web-navigation.md`。

## 可选路径：CLI 工具（仅重流程需要）

`cli-anything-platform-service` 仅用于自包含脚本未覆盖的重流程——泰安联浏览器搜索（`oe-query`/`taianlian-search`，需 CDP）、报价匹配（`quote match`）、批量交叉验证（`cross-validate`）等。日常 OE 查询/价格补全**不需要**它。

```bash
pip install -e /path/to/cli-anything-platform-service[data-clean]
```

## Chrome CDP（仅泰安联 TecDoc 需要）

17vin 已改为自包含 HTTP，不再需要 CDP；只有泰安联 TecDoc 搜索需要 Chrome 调试端口 9250。

Agent 执行任何需要泰安联 TecDoc 的操作前，确认 CDP 连接和登录态：

1. **检测 CDP：** `GET http://127.0.0.1:9250/json/version`
2. **不可达** → 自动尝试启动 Chrome（CLI 已内置 `launch_persistent_context`）
3. **打开** `https://www.tecalliance.cn` 检测登录态
4. **未登录** → 引导用户在浏览器窗口登录，等待确认后继续
5. **浏览器 profile** 持久化到 `~/.claude/browser-data/ruifeng-chrome/`，后续会话无需重复登录
