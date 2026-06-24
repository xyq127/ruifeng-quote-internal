---
name: 05-quick-oe-query
description: 根据 OE 号、DAC 编码或尺寸，快速查询泰安联 TecDoc + 17vin，返回 OE 互换号、品牌件和适用车型。优先使用 CLI 命令（秒级），不可用时降级浏览器操作。
metadata:
  displayName: 快速OE查询
  version: 1.0.0
  author: Hermes Agent
  category: data-cleaning
---

# 快速 OE 查询

## 概述

根据用户提供的 OE 号 / DAC 编码 / 轴承尺寸，一站式查询 TecDoc + 17vin，返回 OE 互换号、品牌件、适用车型。

## Agent 执行流程

### 优先：快速搜索脚本（推荐，~1 秒）

泰安联搜索已封装为快速脚本，通过 Playwright response 拦截直接捕获后台 API JSON 响应，
无需等待页面渲染和文本解析，比传统浏览器操作快 4-5 倍。

```bash
# 方式 1：独立脚本（最快）
python scripts/tecalliance_fast_oe_search.py --query <OE号/DAC编码/尺寸> --json

# 方式 2：CLI 命令（自动调用快速搜索）
data-clean oe-query --query <OE号/DAC编码/尺寸>
```

命令自动识别输入类型：
- `45x84x45` → 尺寸 → 转为 DAC 编码 `45840045`
- `45840045` → DAC 编码 → 搜泰安联
- `31110-RAA-A01` → OE 号 → 走 17vin

**Agent 只需执行这条命令，解析返回的 JSON，呈现给用户。**
无需打开浏览器、无需手动导航、无需解析页面。

### 降级：浏览器操作（CLI 不可用时）

如果 CLI 不可用（如 Work Buddy 环境未安装 Python CLI），按以下步骤操作：

1. **确认 CDP + 登录态**：按主 skill `CDP 连接与登录` 流程操作
2. **构建搜索 URL**：
   - 尺寸格式：先转 DAC 编码 `{d}{D}00{B}`
   - 搜索 URL：`https://www.tecalliance.cn/cn/search/1?q={关键词}&numbersearchinput=1&searchtype=0&status=1`
3. **导航到搜索 URL**（使用 CDP 连接）
4. **提取结果**：读取页面文本，识别品牌名（全大写行）和 OE 号（6-15 位数字）
5. **17vin 补充**：泰安联无结果时，调用 17vin Section 4 API 查互换号

## 输入类型自动识别

| 输入格式 | 示例 | 识别方式 | 处理 |
|---------|------|---------|------|
| 尺寸 `dxDxB` | `45x84x45` | 正则 `(\d+)[xX*,\s](\d+)[xX*,\s](\d+)` | → DAC 编码搜索泰安联 |
| DAC 编码 8-10位 | `45840045` | 正则 `^\d{8,10}$` | → 直接搜索泰安联 |
| OE 号 | `31110-RAA-A01` | 兜底 | → 走 17vin Section 4 |

## 结果输出格式

```json
{
  "query": "45840045",
  "parsed": {"type": "dac", "d": 45, "D": 84, "B": 45, "dac_code": "45840045"},
  "tecalliance": [{"brand": "SKF", "oes": ["VKBA1234"], "source": "tecalliance"}],
  "17vin": {"oes": ["31110-RAA-A01"], "brand_parts": ["SKF:VKBA1234"], "vehicles": ["本田 雅阁 2008-2012"]},
  "match_type": "fuzzy",
  "confidence": "medium",
  "from_cache": false
}
```
