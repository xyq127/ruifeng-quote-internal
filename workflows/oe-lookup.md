# OE 查询工作流

## 触发条件

用户输入：OE 号 / 工厂编号(DAC/DU/RAH) / 尺寸规格 / 车型+配件名 / **图片**（轴承钢印照、包装盒、单个编号截图）

**示例：**
- `DAC39720037-2RZ(ABS88)` — 工厂编号
- `45x84x45` — 尺寸规格
- `31110-RAA-A01` — OE 号
- `本田雅阁2.4L 涨紧轮` — 车型+配件名
- `bearing.jpg` — 图片输入，先经 Step 0 识别出编号再查询

---

## Plan：输入识别与策略制定

### Step 1: 识别输入类型

| 正则模式 | 类型 | 采样 |
|---------|------|------|
| `^DAC\d{8}` `^DU\d{8}` `^GDU\d{8}` | 一代轴承工厂编号 | `DAC39720037` |
| `^RAH\d+` `^RAW\d+` | 轮毂单元编号 | `RAH123456` |
| `^\d{2,3}[x×]\d{2,3}[x×]\d{2,3}` | 尺寸规格 | `45x84x45` |
| `^[A-Z]{1,3}\d{6,15}` | OEM/关联编号 (疑似) | `31110RAAA01` |
| 含中文 | 车型描述 | `本田雅阁2.4L` |

### Step 2: 根据输入类型制定计划

| 输入类型 | 执行策略 |
|---------|---------|
| **一代轴承工厂编号** | parse → 提取8位核心编号 → oe-query(DAC编码) → backend-search → verify |
| **轮毂单元编号** | 从后台取参数 → oe-query → verify |
| **尺寸规格** | oe-query(dimensions) → backend-search → verify |
| **OE/关联编号** | backend-search → backend-detail → cross-validate → verify |
| **车型描述** | 行话翻译(查表) → 17vin 网页 EPC 搜索(CDP) / 泰安联 → verify |
| **无法识别** | 询问用户明确输入类型 |

### Step 3: 数据源策略

| 产品类型 | 优先数据源 | 备选 |
|---------|-----------|------|
| 一代轴承 | 泰安联 DAC编码搜索 `{d}{D}00{B}` | 17vin → 电商平台 |
| 轮毂单元 | 17vin EPC / 后台 API | 泰安联 → 电商平台 |
| 涨紧轮/惰轮 | 17vin 配件搜索 | 后台 API → 泰安联 |
| 中国自主品牌 | 电商平台 (3店铺验证) | 17vin → 后台 |

泰安联和 17vin 同级并行查询，任一命中即可进入 verify。

---

## Execute：逐步执行

### Step 0: 图片识别（仅图片输入）

输入是图片（`.jpg/.jpeg/.png/.webp/.bmp` 路径或图片 URL）时，先用 `qwen-vision` skill 识别出编号，**不可跳过直接查询**：

```bash
# 自动从个人配置取 SiliconFlow Key + 内置编号识别 prompt
python scripts/recognize_image.py --image-path "<图片路径或URL>"
```

**处理：**
1. 解析识别出的编号文本，**复述给用户确认**（视觉易误读 0/O、8/B、5/S，错号会污染整链）。
2. 把确认后的编号当普通文本输入，回到「Step 1 输入类型识别」正常路由：DAC/DU/RAH → Step 1 解析；OE/尺寸 → 跳过 Step 1 进 Step 2。
3. 图中含多个编号 → 按「编号选取优先级」（主机大厂 OE > 大厂关联编号 > 小厂）选主编号查询，其余作为关联编号备用。

**失败处理：**
- 未配置 SiliconFlow Key → 提示用户 `python scripts/personal_config.py init` 录入后重试。
- 识别结果全模糊 / 无可用编号 → 请用户提供更清晰图片或直接给文本编号，**不强行查询**。

> 非图片输入直接从 Step 1 开始，本步跳过。

### Step 1: 工厂编号解析（仅工厂编号输入）

```bash
# 命令
cli-anything-platform-service --json data-clean parse <编号>

# 输入: factory_number (string)
# 输出:
# {
#   "prefix": "DAC",
#   "inner_diameter": 39,
#   "outer_diameter": 72,
#   "variant": 0,
#   "height": 37,
#   "core_8digit": "39720037",
#   "has_abs": true,
#   "abs_teeth": 88,
#   "is_parsable": true
# }
```

**失败处理：** `is_parsable: false` → 标记 "无法解析"，跳过 Step 2，直接进入 Step 3 用原始编号搜索后台。

### Step 2: 多源 OE 查询（17vin 网页 CDP + 泰安联 CLI）

17vin 与泰安联**都走浏览器 CDP**（17vin 付费 API 已停用）。两者共享同一 Chrome
实例，**必须顺序执行、不可并行**；任一命中即可进 verify。

**2a — 17vin（浏览器 CDP，partsearch 优先，OE 互换/品牌件/车型）：**
以 **OE 号**为输入，导航到配件搜索页快速验证：
```
https://www.17vin.com/partsearch/31110RAAA01.html
```
- OE 去掉横杠/点/空格只保留字母数字；页面返回品牌、标准化配件号、替换号列表（SKF/Gates/INA…）、「适用车型和替换号」链接。
- 点链接进 `modellist/{OE}/{group_id}.html` 看配件名称（判断张紧器/皮带/惰轮）、原厂/普通替换号、适用车型。
- partsearch 无收录（德系/美系/自主品牌）→ 转 EPC 树导航。
- 详见 `references/17vin-partsearch-fast-verify.md`、`references/17vin-web-navigation.md`，操作要点见 `modules/02-vin17-epc-query/SKILL.md`。

> DAC 编码/尺寸输入应先经 Step 1 解析或泰安联拿到 OE，再回喂本步。

**2b — 泰安联（CLI，浏览器 CDP；DAC 编码/尺寸首选）：**
```bash
# 一代轴承 DAC 编码；--skip-17vin 因 17vin 已由 2a 浏览器完成
cli-anything-platform-service --json data-clean oe-query --query "45840045" --skip-17vin
# 尺寸规格
cli-anything-platform-service --json data-clean oe-query --query "45x84x45" --skip-17vin
```

**失败处理：**
- 泰安联不可达（CDP 9250 不通）→ 跳过 2b，仅用 17vin（2a）
- 17vin 网页无结果 / 未收录该 OE → 该源标记空，继续其他源
- 两源均无结果 → 进入电商兜底 (Step 4)

### Step 3: 后台已有记录查询

```bash
# 用 Step 2 获取的 OE 号回查后台
cli-anything-platform-service --json data-clean backend-search --keyword "90363-45050" --with-details
```

**注意：** 必须带 `queryType=ENCODE`（CLI 已内置），返回字段为 `data.content`（不是 `records`）。

**输出：** 匹配到的产品列表，含 productId、code、oe、关联编号、参数。

**过滤：** **只保留 status=1 的上架产品**；status≠1（未上架/下架）一律剔除，不展示、不补价格。全部命中均未上架 → 标记 "后台匹配但未上架"，不输出产品与价格。

**失败处理：** 后台无匹配 → 标记 "需补充"，跳过。不阻断后续。

### Step 3.5: 价格查询（仅当 Step 3 命中后台、拿到 productId 时）

后台命中后，用 productId 查询睿锋平台价格。脚本直接集成后端两个接口
（`/api/product/findById` 取采购价 + `/api/product/priceDetail` 取 P1/P2/P3），
复用 CLI 的认证配置：

```bash
python scripts/product_price_query.py --product-id <productId> --json
```

**输出：**
```json
{
  "productId": "123",
  "purchasePrice": 18.5,   // 采购价
  "p1Price": 32,           // OEM价格(P1)
  "p2Price": 28,           // 品牌一级销售价(P2)
  "p3Price": 25            // 品牌二级销售价(P3)
}
```

**失败处理：** 接口报错 / 价格为空 → 该价格显示 `—`，不阻断后续。后台未命中（无 productId）→ 跳过本步。

### Step 4: 电商平台兜底（仅当 Step 2 两源全空时）

搜索 `"{车型} {配件名} OE号"`（淘宝/京东/1688）。

**可靠性要求：** 至少 3 家不同店铺列出相同的 OE 号才可采纳。
优先采信实物图 OE 钢印。

---

## Verify：数据校验

### 校验规则

| # | 规则 | 判定 |
|---|------|------|
| 1 | 泰安联 ∩ 17vin 交集非空 | ✅ 高可信 |
| 2 | 泰安联 ∩ 17vin 交集为空，但各有一致车型 | ⚠️ 需人工确认，可能同一零件不同代工厂 |
| 3 | 后台已有匹配 | 记录 productId，标记 "已入库" |
| 4 | 后台无匹配 | 标记 "需补充"，输出可回写的 OE 列表 |
| 5 | 电商平台 3+ 店铺一致 | ⚠️ 采纳但标记 "电商验证"，可信度较低 |
| 6 | 仅单源命中 | ⚠️ 标记 "单源待确认" |
| 7 | 全部未命中 | ❌ 标记 "待工厂确认" |

### 置信度分级

| 等级 | 条件 | 说明 |
|------|------|------|
| **A-确认** | 泰安联+17vin+后台三者一致 | 可直接回写，无需人工审核 |
| **B-待补充** | 两源一致，后台无记录 | 可回写，建议人工扫一眼 |
| **C-待确认** | 仅单源命中或源间不一致 | 必须人工确认后回写 |
| **D-兜底** | 全部未命中，仅有电商数据或完全无数据 | 需工厂提供 OE |

---

## 输出格式

执行完成后，Agent 应按以下结构输出结果：

```
## OE 查询结果

**输入:** DAC39720037-2RZ(ABS88)
**类型:** 一代轴承

### 解析参数
| 内径 | 外径 | 变型 | 高度 | ABS |
|------|------|------|------|-----|
| 39mm | 72mm | 00 | 37 | 88齿 |

### 多源查询结果
| 数据源 | OE 号 | 品牌 | 车型 | 状态 |
|--------|-------|------|------|------|
| 泰安联 | 90363-45050 | TOYOTA | Corolla 2003 | ✅ |
| 17vin | 90363-45050 | TOYOTA | Corolla (E120) | ✅ |
| 后台 | — | — | — | 未入库 |

### 价格信息（后台命中时）
| 采购价 | OEM价格(P1) | 品牌一级(P2) | 品牌二级(P3) |
|--------|-------------|--------------|--------------|
| 18.5 | 32 | 28 | 25 |

> 后台未命中（无 productId）则省略本节。价格为空显示 `—`。后台命中但产品未上架（status≠1）→ 不展示产品、不输出价格，回复「后台有匹配但未上架，暂无法报价」。

### 校验结论
**置信度: B-待补充** — 泰安联与17vin一致，但后台未找到对应产品。

### 可执行操作
- [ ] 回写 OE `90363-45050` 到后台产品 `productId=xxx`
- [ ] 补充参数：内径 39mm, 外径 72mm
```
