# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 这个仓库是什么

本仓库是一个 **skill 分发包**，不是可运行的应用。它的产物是一份 Markdown 驱动的 Agent 技能 `ruifeng-data-governance-internal`（睿锋智链汽车配件数据治理），通过 `npm install` 安装到本地两个位置供 Claude Code / Hermes 加载：

- `~/.claude/skills/ruifeng-data-governance-internal/`
- `~/.hermes/skills/ruifeng-data-governance-internal/`

仓库本身几乎不含业务执行代码 —— 真正干活的 `data-clean` CLI 命令由**独立仓库** `cli-anything-platform-service` 提供（Python，`pip install -e <path>[data-clean]`）。本仓库只定义工作流、规则、参考资料，告诉 Agent **何时、如何**调用那些 CLI 命令。

> 注意：磁盘目录名为 `ruifeng-quote-internal`，但包名/技能名已更名为 `ruifeng-data-governance-internal`（v3.0.0 重构）。两个名字在文档里都会出现。

## 常用命令
```bash
# 安装/同步技能到 ~/.claude 和 ~/.hermes（postinstall 自动触发 install.js）
npm install

# 仅运行同步逻辑（复制 SKILL.md + workflows/references/scripts/modules，并清理已删除的陈旧文件）
node install.js

# 每周一手动扫描后端 Controller 变更，判断 CLI 是否需要跟进更新
bash scripts/scan-backend.sh
```

**提交规范（强约束）：** 每次改动 `SKILL.md` 或 `workflows/` `references/` `scripts/` `modules/` 后，必须执行 `npm install` 重新同步到上述两个 skill 目录，否则本地 Agent 加载的仍是旧版本。

本仓库没有测试套件、没有 lint、没有构建步骤。

## 架构与核心概念

### 三层架构

```
用户 / Hermes Agent
   │  加载技能
   ▼
ruifeng-data-governance-internal skill（本仓库）   ──引用──►   cli-anything-platform-service CLI（独立 Python 仓库）
   编排工作流 / 数据源选择 / 规则约束                    data-clean 命令组：parse / oe-query /
                                                       backend-search / epc-query /
                                                       taianlian-search / cross-validate / ...
                                                          │
                              ┌───────────────────────────┼────────────────────────┐
                              ▼                            ▼                         ▼
                       Chrome CDP (9250)             外部 API                   文件系统 (Excel)
                       泰安联/17vin 网页            rfscm.com / 17vin            .xls/.xlsx
```

详见 `references/architecture-spec.md`。

### Plan → Execute → Verify 循环

整个技能围绕一个固定循环组织（`SKILL.md` 是入口）：

1. **Plan** — 识别用户输入类型（工厂编号 / 尺寸 / OE / 车型+配件名 / Excel 报价单），匹配 `workflows/` 下对应工作流。
2. **Execute** — 读取该工作流 `.md`，按其定义的 CLI 命令逐步执行。
3. **Verify** — 多源结果交叉比对，输出 A/B/C/D 四级置信度；不通过则回到 Plan 调整策略（换源 / 降级电商 / 标记待工厂确认）。

工作流不是代码，是 `workflows/*.md` 里的步骤化文档。要理解一个流程必须读对应工作流文件，而非搜代码。

### 目录职责

| 目录 | 内容 | 说明 |
|------|------|------|
| `SKILL.md` | 技能主入口 | Plan/Execute/Verify 框架、关键规则、数据源优先级、CLI 速查、置信度体系 |
| `workflows/` | 核心工作流 | `oe-lookup.md`（单编号查询）、`quote-match.md`（批量报价匹配） |
| `references/` | 领域知识库 | 17vin API、车型行话翻译表、尺寸匹配规则、分类编号规律等，被工作流按需引用 |
| `modules/` | 子技能 | 工厂编号解析 / 17vin-EPC / 泰安联 / 快速OE 各自的 SKILL.md |
| `scripts/` | 运维与一次性脚本 | bash 维护脚本 + Python 数据清洗脚本（如 `tensioner-pricing-cleaner-full.py`） |
| `install.js` | 同步脚本 | 复制到两个 skill 目录并清理陈旧文件 |

### 业务硬约束（最易出错处）

这些规则在 `SKILL.md` 有完整列表，修改文档时不要破坏它们：

- **数据源优先级：** 泰安联 TecDoc ≈ 17vin EPC（同级）> 睿锋后台 API > 电商平台（需 3 家店铺一致）。
- **编号选取优先级：** 主机大厂 OE > 关联编号大厂（SKF/NSK/FAG）> 其他小厂。
- **工厂编号格式：** `{前缀}{内径2}{外径2}{变型2}{高度2}{后缀}`，中间的 `00` 是外径变型，**不是高度**。
- **一代轴承 DAC 编码：** `{内径:02d}{外径:02d}00{高度:02d}`，如 45×84×45 → `45840045`。
- **CDP 必须顺序执行：** Chrome 实例共享浏览器状态，泰安联/17vin 浏览器查询不可并行；无状态 HTTP 请求才可并行。
- **不可用 AI 知识替代实际查询：** OE 匹配必须走真实数据源，OE 兼容性最终由工厂确认。
- **后台搜索：** 必须带 `queryType=ENCODE`（CLI 已内置），响应字段是 `data.content` 而非 `records`。

### 后端联动（CLI 维护节奏）

`data-clean` CLI 对接睿锋后端接口。`scripts/scan-backend.sh` / `cron-check-backend.sh` 每周一拉取后端仓库（`git@gitee.com:rayform_0/backend-code-repo.git`，本地 `~/web-project/ruifeng-platform/backend-code-repo`）对比 Controller 变更，`.last-backend-sha` 记录上次同步的 commit。若后端接口变了，需要同步更新独立的 CLI 仓库（不在本仓库内）。
