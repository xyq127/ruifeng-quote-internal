# 报价匹配工作流

## 触发条件

用户提供客户报价清单（Excel 或纯文本），需要匹配雷迪克产品并生成报价结果。

**示例输入：**
- `客户报价单.xlsx` — 含多个产品编号/OE/车型列的 Excel
- `请帮我报个价：DAC39720037, DAC45840045` — 纯文本编号列表

---

## Plan：输入分析与计划制定

### Step 1: 识别输入形态

| 输入形态 | 判断依据 | 处理方式 |
|---------|---------|---------|
| Excel (.xlsx/.xls) | 文件扩展名 | 读取全部 sheet，识别列语义 |
| CSV/文本 | 逗号/换行分隔 | 按行拆分，识别每行类型 |
| 单个编号/OE | 无分隔符的单行文本 | 降级为 oe-lookup 工作流 |
| **图片**（报价单照片/截图） | 图片扩展名/URL | 先用 `qwen-vision` skill OCR 成结构化编号清单，复述确认后按下方文本流程继续 |

**图片报价单预处理：** 调 `python scripts/recognize_image.py --image-path <图> --mode quote`（自动取个人配置里的 SiliconFlow Key + 内置报价单逐行 OCR prompt），把识别出的多行编号当作文本报价清单进入 Step 2 列识别。识别可能误读字符，**务必让用户核对后再批量查询**。未配置 Key 时先跑 `python scripts/personal_config.py init`。

### Step 2: 列语义识别（Excel 输入）

**不要仅凭表头判断列含义。** 按内容特征识别：

| 列内容特征 | 判定为 | 说明 |
|-----------|--------|------|
| 单一编号，6-15位字母数字 | OE 列 | `31110RAAA01`、`90363-45050` |
| 含逗号分隔的多个编号 | 关联编号列 | `90363-45050, VKBA-3560` |
| DAC/DU 开头 + 8位数字 | 工厂编号列 | `DAC39720037` |
| 含中文字符 | 车型列或产品名称列 | `本田雅阁2.4L`、`前轮轴承` |
| 纯数字+中文等级 | 销售等级/价格列 | `A级`、`优等品` |

⚠️ 列名写 "OE" 但内容实际是关联编号列表、真正的 OE 号在 "工厂型号" 列的情况经常出现。必须根据内容格式做最终判定。

### Step 3: 车型列处理

如识别到车型列：
1. 查 `references/chinese-vehicle-slang-engine-translation.md` 翻译表
2. 本地表命中 → 直接提取发动机型号+代表OE
3. 本地表未命中且 `--deep` → 走 17vin/泰安联查询

---

## Execute：逐步执行

### Step 1: 读取输入并生成报价模板

```bash
# 读取 Excel 并识别列 + 翻译车型
cli-anything-platform-service data-clean quote match --file <输入文件> --output <输出路径>
```

CLI 内部执行：
1. `load_client_input()` — 读取 Excel
2. `identify_columns()` — 按内容特征识别各列
3. 车型列 → `translate_vehicle_to_oe()` — 查翻译表
4. `build_template_excel()` — 生成标准模板 (表头: OE / 通用OE / 名称 / 标签车型 / 通用车型 / 销售等级)

**失败处理：**
- Excel 无法读取 → 提示用户检查文件格式
- 列识别失败 → 显示识别结果让用户确认
- 翻译表无匹配 → 标记 "待翻译"，继续执行

### Step 2: 提交批量报价接口

```bash
# POST /productAudit/parse 上传模板
# → 返回: { importFileName: "xxx" }

# 用 importFileName 查审核任务
# GET /productAudit/list?importFileName=xxx
# → 返回: [ { id: "audit_task_id", ... } ]

# 拉取明细
# GET /productAuditData/findAll?auditId=audit_task_id
# → 返回: [ { querySource, productId, oe, code, name, price, ... }, ... ]
```

这些步骤由 CLI `quote match` 命令自动完成。

### Step 3: 按 querySource 分流

| querySource | 含义 | 去向 |
|-------------|------|------|
| 1, 2, 3, 4, 6, 7 | 唯一精确命中 | → **报价结果** sheet |
| 5 | 模糊匹配（同一编号命中多行） | → **待技术员分辨** sheet |
| 0 | 未命中 | → 三方补查 (--deep) 或 **待工厂确认** |

### Step 4: 三方补查（仅 `--deep` 模式）

未命中行（querySource=0）走补查：

1. **检查 CDP 可用性：** `GET http://127.0.0.1:9250/json/version`
   - 不可达 → 跳过补查，全部标记 "待工厂确认"
2. **泰安联 17vin 查替换OE：** 用原始输入编号搜索
3. **拿新编号二次调用 parse：** `submit_and_fetch()` 回查
4. 新编号命中 → **三方补查待写入** sheet（记录新OE+来源）
5. 仍未命中 / CDP 不可达 → **待工厂确认** sheet（优雅降级，不中断）

### Step 5: 采购价补查（命中行）

报价接口返回的明细已带 **OEM价格 / P1 / P2 / P3**（`ProductAuditData` 字段），
Excel 各 sheet 已含这些列。**唯一缺采购价**（报价接口不返回 `purchasePrice`）。

对有 productId 的命中行（报价结果 / 待技术员分辨 / 三方补查待写入），批量补查采购价：

```bash
# 收集命中行的 productId，逗号分隔
python scripts/product_price_query.py --product-ids <id1,id2,...> --json
```

脚本对每个 productId 调 `/api/product/findById` 取 `purchasePrice`（同时返回的
P1/P2/P3 可与 Excel 既有列交叉核对）。把采购价回填到对应行的「采购价」列。

**失败处理：** 某行查询失败 / 采购价为空 → 该单元格留空，不阻断整体。

### 禁止返回未上架产品（最终输出前过滤）

最终报价结果**只允许包含 status=1 的上架产品**：

1. 报价接口明细（`ProductAuditData`）若无 `status` 列，命中行按 productId 调 `/api/product/findById`（或后台搜索）确认上架状态；
2. status≠1（未上架/下架）的命中行**移出报价结果**，不输出其价格，标记 "未上架"（可另列内部清单核对，不进入对外报价）；
3. 某行全部命中产品均未上架 → 该行归入「待工厂确认」或明确标注，**不报价**。

### 四 Sheet 输出结构

每个 sheet 均含价格列：**采购价**（Step 5 补查）、**售价**、**OEM价格**、**P1价格**、**P2价格**、**P3价格**（报价接口直接返回）。

| Sheet | 内容 | 说明 |
|-------|------|------|
| **报价结果** | querySource∈{1,2,3,4,6,7} 且不重复的命中行 | 含 productId/名称/雷迪克code/采购价/OEM价格/P1/P2/P3/置信度 |
| **待技术员分辨** | querySource=5 或同一编号命中多行 | 相邻排列候选行，附库存数供比对 |
| **三方补查待写入** | --deep 模式下新 OE 回查命中 | 新OE/来源/原始输入编号，供后续写入任务 |
| **待工厂确认** | 全部未命中 / CDP 不可达时的降级行 | 仍无法匹配的编号/车型 |

### 不写回后台

本链路**不调用** `num-save`/`param-save`/`priceAudit`。所有结果落地为 Excel 供人工确认。待技术员分辨、三方补查待写入、待工厂确认三类 sheet 经用户确认后，再单独派发写入任务。

### 置信度标识

| 标识 | 条件 |
|------|------|
| 🟢 高 | querySource=1 (精确OE匹配) |
| 🟡 中 | querySource=2,3,4 (编号匹配/关联匹配) |
| 🟠 低 | querySource=5 (模糊匹配); 三方补查命中 |
| 🔴 无 | querySource=0 (未命中) |

---

## 命令参考

```bash
# 基础用法
cli-anything-platform-service data-clean quote match --file 客户报价单.xlsx

# 启用三方补查 (需 CDP 9250)
cli-anything-platform-service data-clean quote match --file 客户报价单.xlsx --deep

# 指定输出路径
cli-anything-platform-service data-clean quote match --file 客户报价单.xlsx --output 报价结果.xlsx

# 指定商家/关联编号来源范围
cli-anything-platform-service data-clean quote match --file 客户报价单.xlsx \
  --supplier-range 123,456 --query-range 0,1,2,3,4

# 包含修理包
cli-anything-platform-service data-clean quote match --file 客户报价单.xlsx --query-repair-kit
```

## 错误处理

| 错误 | 处理 |
|------|------|
| CDP 9250 不通（--deep 模式） | 跳过三方补查，未命中行标记 "待工厂确认"，**不中断流程** |
| Excel 读取失败 | 检查文件格式，提示用户 |
| /productAudit/parse 失败 | 检查 token 有效性，重试登录 |
| 翻译表无匹配 | 标记 "待翻译"，不阻断后续匹配 |
| 某行完全无匹配且无降级方案 | 写入 "待工厂确认" sheet |
