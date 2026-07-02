---
name: 睿锋-内部询价
description: "【内部版·面向内部人员，输出完整价格 采购价/P1/P2/P3，区别于只展示售价的客户版】睿锋-内部询价：汽车配件 OE/工厂编号(DAC/DU/RAH)/尺寸/车型配件 → 多源查询+交叉验证，命中睿锋后台后补全完整价格（采购价、OEM价P1、品牌一级销售价P2、品牌二级销售价P3）。当内部人员要查配件采购成本/进价、做内部报价、批量补全报价单的采购价与各级价格、或查 OE/关联编号/工厂编号/车型配件并要看全价时使用，即使没明说『内部询价』也应触发。遵循 Plan→Execute→Verify：数据源优先级 泰安联≈17vin > 睿锋后台 > 电商(需3家店铺一致)；编号选取 主机大厂OE > 大厂关联编号(SKF/NSK/FAG) > 其他小厂。"
metadata:
  displayName: 睿锋-内部询价
  version: 3.1.0
  author: Hermes Agent
  category: data-governance
  depends_on:
    - 01-factory-number-parser
    - 02-vin17-epc-query
    - 04-taianlian-tecdoc-search
    - 05-quick-oe-query
  changelog: |
    3.1.0 (2026-06-24): 内部版独立 — 命中后台补全完整价格(采购价/P1/P2/P3)，区别于客户版只展示售价；统一命名为 ruifeng-quote-internal /「睿锋-内部询价」；首次配置/依赖/CDP 细节下沉到 references/setup-and-credentials.md，精简正文；澄清自包含脚本为查询主路径、data-clean CLI 为可选重流程
    3.0.0 (2026-06-17): 架构重构 — Plan→Execute→Verify 循环框架；CLI 拆分为独立仓库 cli-anything-platform-service；新增 workflows/ 目录定义核心工作流
    2.2.0 (2026-06-15): 跨平台改造（自管 Chrome + Python 环境自动检测）；新增 CDP 连接与登录引导流程；新增子技能"快速OE查询"
    2.1.0 (2026-06-13): 新增产品报价核心链路 quote-match；地基改进：backend-search 归一化多轮重试链
    2.0.x (2026-06-04~12): 初始版本 — 工厂编号解析、OE交叉验证、多源查询、参数回写
---

# 睿锋-内部询价

## 概述

**内部版**汽车配件询价与数据治理技能：对配件数据做**获取 → 校验 → 补充**的闭环，确认"工厂编号 ↔ OE ↔ 车型"三位一体映射，并在命中睿锋后台时**补全完整价格——采购价、OEM价(P1)、品牌一级销售价(P2)、品牌二级销售价(P3)**。这是与客户版（只展示售价 `salePrice`）的核心区别：内部版面向内部人员，要看到进价/成本与各级价格。

## 首次配置与依赖（速览）

睿锋平台查询的**主路径是自包含脚本**（`scripts/ruifeng_platform.py`），仅需 Python3 + requests，装好本 skill 即可用，**不依赖 CLI**。17vin 查询走**浏览器 CDP**（`www.17vin.com` partsearch / EPC 树，付费 API 已停用）；泰安联浏览器搜索、报价匹配等重流程用可选的 `data-clean` CLI（见下方说明）。

个人凭据（睿锋手机号+密码、17vin 用户名+密码、SiliconFlow Key）集中存于 `~/.cli-anything-platform-service/config.json`（`0o600`，与各模块共用、token 互通），用 `python scripts/personal_config.py init` 录入。

> 完整的配置存储机制、各脚本用法示例、登录态自愈、可选 CLI 安装、Chrome CDP 细节 → **见 [references/setup-and-credentials.md](references/setup-and-credentials.md)**。

### 首次运行检测（Agent 必读，执行任何查询前先做）

**执行任何查询/识别前，先检测个人配置是否就绪：**

```bash
python scripts/personal_config.py check                 # 全部功能；退出码 0=就绪, 2=首次运行/缺项
python scripts/personal_config.py check --feature qwen  # 只查图片识别所需 Key（按本次任务需要）
```

- **退出码 0** → 配置就绪，正常执行。
- **退出码 2（首次运行 / 缺项）→ 不要尝试查询。** 把脚本输出的「缺少项」清单**转达给用户**，请用户**在自己的终端**运行 `python scripts/personal_config.py init` 录入。
  - 密码/Key 用 `getpass` 安全输入，**不要让用户把密码发给 Agent**，也不要由 Agent 代填（避免进入对话/命令行历史）。配置完成后再继续原任务。

> 任一自包含脚本在凭据缺失时也会打印同样的首次运行提示并非零退出——Agent 看到即按上述方式引导用户，不要反复重试。

---

## Plan → Execute → Verify 框架

Agent 执行数据治理任务时，严格遵循以下循环：

```
用户输入 → PLAN（识别+匹配工作流） → EXECUTE（按工作流执行） → VERIFY（校验结果）
                                                                    │
                                                    通过 ←──────────┘
                                                      │
                                                    不通过 → 标记问题 → 回到 PLAN
```

### 1. Plan（输入识别 + 匹配工作流）

首先识别用户输入的类型，然后匹配对应工作流：

| 输入类型 | 示例 | 匹配工作流 |
|---------|------|-----------|
| 工厂编号 (DAC/DU/RAH) | `DAC39720037` | [oe-lookup](workflows/oe-lookup.md) |
| 尺寸规格 | `45x84x45` | [oe-lookup](workflows/oe-lookup.md) |
| OE/关联编号 | `31110-RAA-A01` | [oe-lookup](workflows/oe-lookup.md) |
| 车型+配件名 | `本田雅阁2.4L 涨紧轮` | [oe-lookup](workflows/oe-lookup.md) |
| 客户报价单 (Excel) | `报价单.xlsx` | [quote-match](workflows/quote-match.md) |
| 待校验产品清单 (Excel) | `产品清单.xlsx` | cross-validate（CLI 直接调用） |
| 纯文本编号列表 | `DAC39720037, 45840045` | 按行拆分为多个 oe-lookup |
| **图片**（轴承钢印照/包装盒/报价单截图等） | `bearing.jpg` / `quote.png` | **先经「图片输入预处理」识别出编号/OE，再按识别结果路由到上表对应工作流** |

如输入类型无法识别，询问用户明确。

#### 图片输入预处理（识别 → 编号 → 再查询）

当输入是**图片格式**（`.jpg/.jpeg/.png/.webp/.bmp` 文件路径或图片 URL）时，**不可直接进入查询工作流**，必须先用 `qwen-vision` skill 把图片里的编号/OE/钢印文字识别出来，拿到文本编号后再回到上面的输入类型表正常路由。

```bash
# 封装命令：自动从个人配置取 SiliconFlow Key + 内置业务识别 prompt，再调 qwen-vision
python scripts/recognize_image.py --image-path "<图片路径或URL>"            # 单件编号识别(默认 --mode oe)
python scripts/recognize_image.py --image-path "<报价单图>" --mode quote     # 报价单逐行 OCR
```
> Key 取自 `personal_config`（首次配置已录入），无需手动 `export SILICONFLOW_API_KEY`。
> 底层仍是 qwen-vision skill 的 `vision.py`，仅封装了取 Key + 业务 prompt。

处理规则：
1. **识别优先级**：实物钢印 OE > 包装盒印刷编号 > 截图文字。多个候选时全部列出，交由后续工作流按「编号选取优先级」（主机大厂 OE > 大厂关联编号 > 小厂）取舍。
2. **拿到编号后**：把识别出的编号当作普通文本输入，按输入类型表重新判定（DAC→oe-lookup、OE→oe-lookup、报价单截图的多行→拆分多个 oe-lookup），执行后续多源查询/价格补充。
3. **必须复述识别结果让用户确认**再继续查询——视觉识别可能误读字符（0/O、8/B、5/S），错号会污染整条链路。
4. **失败处理**：未配置 SiliconFlow Key → 提示用户跑 `python scripts/personal_config.py init` 录入后重试；识别全模糊/无编号 → 请用户提供更清晰的图或直接文本编号，不强行查询。

### 2. Execute（执行工作流）

读取匹配的工作流文件（`workflows/*.md`），按其定义的步骤逐步执行。每条工作流定义了：
- 触发条件
- Plan 阶段输入识别规则
- Execute 阶段每步的 CLI 命令、输入输出 schema、失败处理
- Verify 阶段的校验规则和置信度分级

### 3. Verify（数据校验）

执行完成后进入校验阶段：
- 按工作流定义的校验规则比对多源结果
- 输出置信度标签（A/B/C/D）
- 通过 → 输出最终结果
- 不通过 → 标记具体问题，回到 Plan 阶段制定修正策略（如切换数据源、降级到电商搜索、标记待工厂确认）

---

## 工作流索引

| 工作流 | 文件 | 适用场景 |
|--------|------|---------|
| **OE 查询** | [workflows/oe-lookup.md](workflows/oe-lookup.md) | 单个 OE/工厂编号/尺寸/车型 → 多源查询+校验 |
| **报价匹配** | [workflows/quote-match.md](workflows/quote-match.md) | 客户报价清单 → 批量报价+三方补查 → 4-sheet Excel |
| 批量交叉验证 | 待迁移（当前用 CLI 直接调用） | `data-clean cross-validate --file <Excel>` |
| 车型行话翻译 | 待迁移 | `references/chinese-vehicle-slang-engine-translation.md` |

---

## 关键规则

以下为执行过程中容易出错的硬约束：

### 1. 后台搜索必须用 queryType=ENCODE

CLI 已内置此参数。响应字段为 `data.content`（不是 `records`）。分类搜索用 `categoryIds` 参数，涨紧轮分类 ID: `655709386127314944`。

### 2. 一代轴承泰安联 DAC 编码格式

格式：`{内径:02d}{外径:02d}00{高度:02d}`。例如 45×84×45 → `45840045`。用 `data-clean oe-query --query <编码>` 一步完成。

### 3. 工厂编号解析顺序

格式：`{前缀}{内径2位}{外径2位}{变型2位}{高度2位}{后缀}`。例 `DAC39720037` → 内径39, 外径72, **变型00**, 高度37。中间 `00` 是外径变型，不是高度！

### 4. CDP 必须顺序执行

Chrome 实例共享浏览器状态，并行操作导致页面冲突。泰安联/17vin 浏览器查询严格顺序执行。无状态 HTTP 请求可并行。

### 5. 17vin 品牌覆盖

配件搜索收录：日系(丰田/本田/日产/马自达) ✅、韩系(现代/起亚) ✅、法系(标致/雪铁龙) ✅。
不可收录：德系(大众/奥迪/宝马/奔驰)、美系(福特/GM)、中国自主品牌。不可收录品牌需走 EPC 浏览器导航或泰安联。

### 6. 切忌用 AI 知识替代实际数据查询

AI 训练知识在 OE 匹配中存在根本性错误（配件类型错误、发动机泛化错误）。正确流程：17vin 确认配件类型 → 车型列表确认适配 → 泰安联交叉验证。AI 知识仅作初步参考。

### 7. 电商平台验证规则

至少 3 家不同店铺列出相同 OE 号才可采纳。优先实物图 OE 钢印。冲突时标注"多源不一致，待工厂确认"。

### 8. 参数接近不排除

高度差异 1-2mm、外径小数位相近的产品标记"接近待确认"，由工厂技术人员判断。**OE 兼容性必须由工厂确认，AI 不能自行判断。**

### 9. Excel 列识别不要信表头

列名写"OE"但内容实际是关联编号、真正的 OE 在"工厂型号"列的情况常见。按内容格式特征识别，不依赖表头。

### 10. 防御性备注

每次车型翻译后必须备注匹配前提："按 [具体年份/底盘号] [发动机] 匹配，不适用于 [易混淆的其他代数]"

### 11. 命中睿锋平台数据必须补充价格

凡查询命中睿锋后台产品（拿到 productId），输出必须带四个价格：**采购价**（`/api/product/findById`）、**OEM价格(P1)**、**品牌一级销售价(P2)**、**品牌二级销售价(P3)**（`/api/product/priceDetail`）。统一用 `scripts/product_price_query.py` 查询。报价匹配（quote-match）的 Excel 已自带 OEM价格/P1/P2/P3 列，仅需补采购价；OE 查询（oe-lookup）四价全补。价格为空显示 `—`，不阻断流程。

### 12. 睿锋后台多产品优先级排序

当睿锋后台查询返回多个产品时，按以下优先级排序展示：

1. **status=1** 的产品排在前面（status 非 1 的排后面）
2. 同一 status 内，按 **targetPndSource**（数组）排序：**空数组（直接 OE 匹配）> 含 1 > 含 2（无1）> 仅含 0**

即最终排序：status=1 + targetPndSource 空 → status=1 + 含 1 → status=1 + 含 2 → status=1 + 仅 0 → 非1 + 空 → …

Agent 展示多个产品时遵循此顺序，最优匹配的产品排在最前面。

---

## 数据源优先级

| 优先级 | 数据源 | 查询方式 |
|--------|--------|---------|
| 1 | 泰安联 TecDoc | Chrome CDP 浏览器搜索 (`data-clean oe-query` 或 `taianlian-search`) |
| 1 | 17vin EPC | HTTP API + 配件搜索网页 (`data-clean oe-query` 或 `epc-query`) |
| 2 | 睿锋后台 API | `data-clean backend-search --keyword <关键词>` |
| 3 | 电商平台 | 淘宝/1688/京东，至少 3 家店铺一致才采纳 |

泰安联 ≈ 17vin 同级。同一 OE 在两者都能查到同一车型时，数据可信度最高。

## 编号选取优先级

| 优先级 | 编号来源 | 示例品牌 |
|--------|---------|---------|
| 1 | 主机大厂 OE（零件设计者） | 丰田/本田/日产/大众/奔驰/宝马/现代/福特 |
| 2 | 关联编号大厂（给主机厂代工） | SKF/NSK/FAG/冠盛/盖茨 |
| 3 | 其他小厂 | 识别度低，仅辅助参考 |

---

## CDP 连接与登录（仅泰安联 TecDoc 需要）

执行任何需要泰安联 TecDoc 的操作前，先确认 CDP（`GET http://127.0.0.1:9250/json/version`）与登录态：不可达则自动尝试启动 Chrome，未登录则引导用户在浏览器窗口登录后继续。完整步骤 → [references/setup-and-credentials.md](references/setup-and-credentials.md)。17vin 已改为自包含 HTTP，不需要 CDP。

---

## 置信度体系

所有工作流统一使用四级置信度：

| 等级 | 标签 | 条件 | 可执行操作 |
|------|------|------|-----------|
| **A** | 确认 | 泰安联+17vin+后台三者一致 | 可直接回写 |
| **B** | 待补充 | 两源一致，后台无记录 | 可回写，建议人工扫一眼 |
| **C** | 待确认 | 仅单源命中或源间不一致 | 必须人工确认后回写 |
| **D** | 兜底 | 全部未命中 | 需工厂提供 |

---

## 错误处理

| 错误 | 处理 |
|------|------|
| 泰安联+17vin 均无结果 | 走电商平台；仍无结果标记"待工厂确认" |
| 17vin 网页无收录该 OE | partsearch 无结果属正常（德系/美系/自主品牌）→ 转 EPC 树或泰安联 |
| CDP 9250 不通 | 检查 Chrome 调试端口，或自动尝试启动 |
| 电商结果不一致 | 多店铺一致的 + 实物图钢印优先；冲突标注"待工厂确认" |
| 后台搜索无结果 | 标记"需补充"继续，不阻断后续 |

---

## 命令速查

**主路径——自包含脚本（无需 CLI，优先使用）。** 日常 OE 查询、价格补全、17vin 互换都走这里。

### 睿锋平台（`scripts/ruifeng_platform.py`）

| 操作 | 命令 |
|------|------|
| 选择环境 | `python scripts/ruifeng_platform.py config-use <test\|prod>` |
| 登录(token落盘) | `python scripts/ruifeng_platform.py login --mobile <手机号>` |
| 查看配置 | `python scripts/ruifeng_platform.py config-show` |
| 后台产品搜索 | `python scripts/ruifeng_platform.py search --keyword <关键词> --json` |
| 产品详情 | `python scripts/ruifeng_platform.py product --product-id <ID>` |
| **价格查询(采购价/P1/P2/P3)** | `python scripts/ruifeng_platform.py price --product-id <ID> --json` |

### 17vin 网页查询（浏览器 CDP，付费 API 已停用）

| 操作 | 路径 |
|------|------|
| 配件号快速验证 | `https://www.17vin.com/partsearch/{去掉横杠点空格的OE}.html` |
| 适用车型/替换号 | partsearch 页内「适用车型和替换号」链接 → `modellist/{OE}/{group_id}.html` |
| 车型 EPC 树导航 | 车型列表页 → cata1 → cata2 → partlist（partsearch 无收录时） |

网页需登录（账号密码存于 config.json `vin17` 段）。操作细节见 `modules/02-vin17-epc-query/SKILL.md`、`references/17vin-web-navigation.md`、`references/17vin-partsearch-fast-verify.md`。与泰安联共享 Chrome，**顺序执行不可并行**。

**可选——`data-clean` CLI（`cli-anything-platform-service` 提供，仅自包含脚本未覆盖的重流程才用）：**

| 操作 | 命令 |
|------|------|
| 一站式 OE 查询（含泰安联 CDP） | `data-clean oe-query --query <尺寸/DAC/OE>` |
| 泰安联搜索 | `data-clean taianlian-search --query <编号>` |
| OE 交叉验证（批量 Excel） | `data-clean cross-validate --file <Excel>` |
| 报价匹配（批量 Excel） | `data-clean quote match --file <客户表>` |
| 工厂编号解析 | `data-clean parse <编号>` |
| 写入关联编号 | `data-clean num-save --product-id <ID> --num <OE>` |
| 批量写入编号 | `data-clean num-batch-save --product-id <ID> --nums "列表"` |
| 写入参数 | `data-clean param-save --product-id <ID> --name <名> --value <值>` |

> 工厂编号解析/后台搜索/价格查询自包含脚本已覆盖，无需 CLI；`data-clean` 的价值集中在泰安联浏览器搜索与批量 Excel 流程。

---

## 子技能索引

| 子技能 | 文件 | 用途 |
|--------|------|------|
| 工厂编号解析 | `modules/01-factory-number-parser/SKILL.md` | 解析 DAC/DU/RAH 格式 |
| 17vin网页查询 | `modules/02-vin17-epc-query/SKILL.md` | 17vin 网页端 CDP 查询（partsearch + EPC 树） |
| 泰安联TecDoc搜索 | `modules/04-taianlian-tecdoc-search/SKILL.md` | 浏览器 CDP 搜索 TecDoc |
| 快速OE查询 | `modules/05-quick-oe-query/SKILL.md` | 一键 OE 查询（CLI 优先） |

---

## 参考文件

| 文件 | 用途 |
|------|------|
| `references/setup-and-credentials.md` | 首次配置/凭据存储机制、自包含脚本用法、登录态自愈、可选 CLI 安装、Chrome CDP 细节 |
| `references/chinese-vehicle-slang-engine-translation.md` | 车型行话 → 发动机型号 + OE 号 (200+条目) |
| `references/17vin-web-navigation.md` | 17vin Web 界面导航 + CDP 操作技巧 |
| `references/17vin-partsearch-fast-verify.md` | 17vin 配件搜索快速验证方法 |
| `references/cross-catalog-dimension-matching.md` | 跨目录尺寸匹配规则 |
| `references/product-category-code-patterns.md` | 产品分类编号规律 — 一代/二三代对照表 |
| `references/excel-image-extraction.md` | Excel 内嵌图片提取规范 |
| `references/architecture-spec.md` | 系统架构说明 |
