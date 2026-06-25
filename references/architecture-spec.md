# 睿锋数据清洗系统架构 Spec

> 版本: 2.0.0 | 日期: 2026-05-28 | 状态: 设计中

## 1. 系统全景图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户 / Hermes Agent                          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                ┌──────────────┴──────────────┐
                │                              │
                ▼                              ▼
┌──────────────────────────────┐ ┌──────────────────────────────┐
│ ruifeng-data-cleaning skill  │ │ cli-anything-platform-        │
│ (Hermes 主技能)              │ │ service CLI                   │
├──────────────────────────────┤ │ (Python CLI 工具)             │
│ 工作流编排 / 数据源选择       │ ├──────────────────────────────┤
│ 错误处理策略 / CLI 命令映射   │ │ data-clean 命令组             │
└────────┬─────────────────────┘ │  - parse                     │
         │ 引用                   │  - backend-search            │
         └──────────────────────►│  - epc-query                 │
                                 │  - taianlian-search          │
                                 │  - cross-validate            │
                                 │  - excel-process             │
                                 └──────────┬───────────────────┘
                                            │
                    ┌───────────────────────┼───────────────────┐
                    │                       │                   │
                    ▼                       ▼                   ▼
┌─────────────────────────┐    ┌───────────────────────┐    ┌─────────────────┐
│  Chrome CDP 浏览器       │    │  外部 API              │    │  文件系统        │
│  (Windows 调试端口)      │    │                       │    │                 │
├─────────────────────────┤    ├───────────────────────┤    ├─────────────────┤
│ localhost:9250           │    │ rfscm.com REST API    │    │ Excel .xlsx/.xls │
│ --user-data-dir 持久化   │    │ www.17vin.com (CDP)   │    │ CSV 输出         │
│ --remote-allow-origins=* │    │ 电商平台 (淘宝/京东/1688) │    │ Profile 持久化   │
│ 无头 / 有头模式           │    │ tecalliance.cn (CDP)  │    │                  │
└─────────────────────────┘    └───────────────────────┘    └─────────────────┘
```

## 2. 组件说明

### 2.1 Chrome CDP 浏览器

**职责**: 通过 Chrome 远程调试协议（CDP）操作浏览器页面，执行泰安联/TecDoc 搜索、17vin EPC 网页端查询等需要浏览器环境的操作。

**部署**: 用户 Windows 端启动 Chrome 调试模式，端口 9250

**关键配置**:
- `--remote-debugging-port=9250` — 固定调试端口
- `--remote-allow-origins=*` — Chrome 148+ 必需，否则 WebSocket 握手返回 403
- `--user-data-dir=C:\ChromeDebugProfile` — 持久化 profile，保存登录态
- `--no-first-run --no-default-browser-check` — 首次启动免配置

**启动命令**（Windows PowerShell）:
```powershell
Start-Process 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList @(
    '--remote-debugging-port=9250',
    '--remote-allow-origins=*',
    '--user-data-dir=C:\ChromeDebugProfile',
    '--no-first-run',
    '--no-default-browser-check'
)
```

### 2.2 cli-anything-platform-service (data-clean 命令组)

**职责**: 提供标准化的数据清洗 CLI 操作，封装浏览器自动化、API 调用、文件处理。

**位置**: `/home/stoic16/web-project/backend-code-repo/agent-harness/`

**命令结构**:
```
data-clean
├── parse              # 工厂编号解析
├── backend-search     # 后台 API 产品搜索
├── backend-detail     # 后台 API 产品详情(关联编号+参数)
├── epc-query          # 17vin EPC 查询
├── taianlian-search   # 泰安联 TecDoc 搜索 (CDP)
├── tecdoc-search      # TecDoc 通用搜索 (CDP)
├── cross-validate     # OE 交叉验证
└── excel-process      # Excel 处理 (read/images/cross-table-merge)
```

### 2.3 ruifeng-data-cleaning Skill

**职责**: Hermes 主技能，编排完整数据清洗工作流。

**位置**: `~/.hermes/skills/ruifeng-data-cleaning/SKILL.md`

**依赖**: cli-anything-platform-service, 以及 4 个原有模块

### 2.4 cloakbrowser-cli Skill（外部参考）

CloakBrowser 是一个隐形 Chromium 浏览器（58 个 C++ 隐身补丁），当前暂未在生产流程中使用。
参考文档位于 `~/.hermes/skills/browser-automation/cloakbrowser-cli/`。

### 2.5 外部数据源

| 数据源 | 访问方式 | 用途 | 覆盖率 |
|--------|---------|------|--------|
| rfscm.com | REST API (Bearer Token) | 内部产品库查询 | 已录入产品 |
| www.17vin.com | CDP 浏览器 | 网页端 EPC（partsearch + EPC 树；付费 API 已停用） | 欧美日系品牌 |
| tecalliance.cn | CDP 浏览器 | TecDoc 搜索 | 国际品牌为主 |
| yiparts.com | CDP 浏览器 | 辅助验证 | 中国品牌补充 |
| taobao.com/jd.com/1688.com | web_search 抓取 | OE 兜底验证 | 中国品牌及冷门车型 |

## 3. 数据流

```
Excel 文件 (工厂编号 + 车型 + 关联编号)
    │
    ▼
┌─────────────────────────────────────────────┐
│ 步骤 0: data-clean parse                    │
│ DAC39720037-2RZ(ABS88) → 内39/外72/高37    │
│ 提取 8位核心编号: 39720037                   │
│ 判断产品类型: 一代轴承 / 轮毂单元             │
└─────────────────┬───────────────────────────┘
                  │
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌──────────┐ ┌──────────┐ ┌──────────────┐
│步骤 1    │ │步骤 2    │ │步骤 3        │
│backend-  │ │taianlian │ │epc-query     │
│search    │ │-search   │ │              │
│          │ │          │ │              │
│rfscm.com │ │TecDoc    │ │17vin EPC     │
│产品库    │ │(CDP)     │ │(API + CDP)   │
└────┬─────┘ └────┬─────┘ └──────┬───────┘
     │            │              │
     └────────────┼──────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│ 步骤 4: data-clean cross-validate           │
│ 多源 OE 交叉比对                             │
│ A类: DAC格式 / B类: 归一化匹配 / C类: 缺失   │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│ 输出: data-clean excel-process              │
│ 清洗后 Excel + 置信度 + 防御性备注             │
└─────────────────────────────────────────────┘
```

## 4. 浏览器架构

Chrome 远程调试协议（CDP）是浏览器自动化操作的唯一入口。所有需要浏览器环境的查询（泰安联 TecDoc 搜索、17vin EPC 网页端导航）均通过 Windows Chrome 调试端口实现。

### 4.1 Chrome CDP 连接方式

```
Windows Chrome (Windows 端)
  --remote-debugging-port=9250
  --user-data-dir=C:\ChromeDebugProfile
  --remote-allow-origins=*

Hermes browser_* tools / Python 脚本
  → http://127.0.0.1:9250
  → ws://127.0.0.1:9250/... (WebSocket)
```

### 4.2 登录工作流

```
首次使用 (一次性):
  1. 启动 Windows Chrome 调试模式 (端口 9250)
  2. CDP 导航到目标站点 (tecalliance.cn / www.17vin.com)
  3. 用户手动输入账号密码 + 完成验证码
  4. 登录态保存在 --user-data-dir 指向的 profile

后续使用:
  1. 重启 Chrome 时指定同一 --user-data-dir
  2. 登录态自动恢复，直接操作
```

### 4.3 异常处理

| 场景 | 策略 |
|------|------|
| 验证码触发 | 提示用户手动完成，检查 Cookie/登录态是否过期 |
| CDP 超时 | 重试 3 次，间隔 5s，仍失败则跳过该产品 |

## 5. 配置参考

### 5.1 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PLATFORM_BASE_URL` | `https://rfscm.com` | 睿锋后台 API |
| `PLATFORM_TOKEN` | — | 后台 API Bearer Token |
| `PLATFORM_ENV` | — | 环境 (test/prod) |

### 5.2 Hermes Config (~/.hermes/config.yaml)

```yaml
browser:
  cdp_url: http://127.0.0.1:9250   # Chrome CDP (Windows 调试端口)
```

### 5.3 CLI Config (~/.cli-anything-platform-service/config.json)

```json
{
  "base_url": "https://rfscm.com",
  "token": "***",
  "env": "test"
}
```

## 6. 错误处理

### 6.1 CLI 层面

| 错误 | 处理 |
|------|------|
| 后台 API 401 | 提示 token 过期，引导重新登录 |
| 后台 API 404 | 产品未收录，标记"需录入" |
| 17vin API 503 | 标记"API 暂时不可用"，后续补查 |
| Excel 读取失败 | 检查文件格式 (.xls→xlrd, .xlsx→openpyxl)，指定正确 Python 解释器 |
| CDP 不可达 | 检查 Windows Chrome 是否运行在端口 9250，提示启动命令 |

### 6.2 Skill 层面

| 错误 | 处理 |
|------|------|
| 泰安联+17vin 均无结果 | 进入电商平台搜索兜底 |
| 泰安联无匹配 | 参数编码问题或 OE 不正确，标记异常 |
| 所有渠道无结果 | 标记"待工厂确认" |

## 7. 未来路线图

- **Redis 缓存**: 缓存 17vin API 结果 (3 分钱/次)，避免重复查询
- **并行批处理**: 非浏览器操作 (parse/backend-search/epc-api) 可并行
- **Excel 模板**: 标准化输入/输出格式，一键清洗
- **Web Dashboard**: 可视化清洗进度和结果

## 8. 文件清单

| 文件 | 位置 | 类型 |
|------|------|------|
| data_clean __init__ | `web-project/backend-code-repo/agent-harness/cli_anything/platform_service/core/data_clean/__init__.py` | Code (NEW) |
| factory_parser | `.../data_clean/factory_parser.py` | Code (NEW) |
| backend_api | `.../data_clean/backend_api.py` | Code (NEW) |
| epc | `.../data_clean/epc.py` | Code (NEW) |
| browser_search | `.../data_clean/browser_search.py` | Code (NEW) |
| cross_validate | `.../data_clean/cross_validate.py` | Code (NEW) |
| excel_processor | `.../data_clean/excel_processor.py` | Code (NEW) |
| CLI 主文件 | `.../platform_service_cli.py` | Code (MODIFIED) |
| setup.py | `web-project/backend-code-repo/agent-harness/setup.py` | Code (MODIFIED) |
| Skill 主文件 | `~/.hermes/skills/ruifeng-data-cleaning/SKILL.md` | Skill (MODIFIED) |
| 架构 Spec | `~/.hermes/skills/ruifeng-data-cleaning/references/architecture-spec.md` | Document (NEW) |
