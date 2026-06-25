---
name: 02-vin17-epc-query
description: 当用户需要在 17vin（精时科技）网页端查询车型 EPC 目录、做 OE 反查、搜索轮毂轴承/张紧轮等配件，或做品牌-车型-年款-配件树遍历时使用。统一走浏览器 CDP（partsearch 快速验证 + EPC 树导航），不调用付费 API。
metadata:
  displayName: 17vin网页查询
  version: 2.0.0
  author: Hermes Agent
  category: data-cleaning
---

# 17vin 网页查询

## 概述

通过浏览器（CDP 连接 `https://www.17vin.com`）查询 17vin 的 EPC（Electronic Parts Catalog）目录与配件互换号，定位轮毂轴承、张紧轮等配件并验证 OE 号。这是数据清洗中 OE 匹配的关键步骤。

> **统一走浏览器 CDP，不再调用付费 API。** 旧的 `api.17vin.com:8080` REST 接口（MD5 token 鉴权、按次收费）已停用；本子技能与工作流涉及 17vin 时一律使用网页路径。两条路径详见 `references/17vin-web-navigation.md` 与 `references/17vin-partsearch-fast-verify.md`。

## 登录凭据

- **网页登录**：`https://www.17vin.com` 需账号登录后才能查询。账号密码**不在文档/代码中硬编码**，从个人配置 `~/.cli-anything-platform-service/config.json` 的 `vin17` 段读取（用 `python scripts/personal_config.py init` 录入），供人工或 CDP 自动登录使用。
- 浏览器登录态由 Chrome 持久化 user-data-dir 维持；登录流程见主 skill 的「CDP 连接与登录」。

## ⚠️ CDP 顺序执行约束

17vin 与泰安联共享同一 Chrome 实例，浏览器查询**不可并行**，必须顺序执行。无状态 HTTP 请求才可并行——但 17vin 已无 HTTP 路径，故 17vin 的所有查询都串行。

## 路径一：配件号码搜索（partsearch，秒级，优先）

**这是验证 OE 号最快的方式，远优于 EPC 树导航**（每 OE 约 10–30 秒，EPC 树每车需 3–5 分钟）。

```
https://www.17vin.com/partsearch/{OE号}.html
```

- OE 去掉横杠/点/空格，只保留字母数字：`25281-2G000` → `252812G000`，`5751.43` → `575143`。
- 页面返回：品牌名 + 标准化配件号 + 替换号列表（Gates/SKF/INA/DAYCO 等）+「适用车型和替换号」链接。
- 点链接进入 `modellist/{OE}/{group_id}.html` 可看**配件名称**（判断是张紧器/皮带/惰轮）、**配件分解图**、**原厂/普通替换号**、**适用车型列表**。
- 「无结果」= 17vin 未收录该 OE。

完整三级验证流程与实测案例见 `references/17vin-partsearch-fast-verify.md`。

## 路径二：车型 EPC 树导航（分钟级，partsearch 无果时）

不知道 OE、只知道车型时，从车型列表页逐级进 EPC 树：

```
车型列表页 → 一级目录(cata1) → 二级目录(cata2) → 配件图(partlist)
```

URL 构造模式、品牌 EPC 前缀（`audi_vw`/`honda`/`toyota`/`peugeot`）、动态加载与搜索重定向等陷阱见 `references/17vin-web-navigation.md`。

## 轮毂轴承 / 张紧器关键词

在配件列表/配件名称中匹配（中英文）：
- 轮毂轴承、前轮轴承、后轮轴承、轮毂单元；wheel bearing、hub bearing、hub assembly、bearing
- 张紧轮、涨紧轮、张紧器、惰轮、过渡轮；tensioner、idler、V-ribbed belt tensioner

## 品牌覆盖（2026-06 实测）

| 品牌集群 | partsearch | EPC 树 | 推荐路径 |
|----------|-----------|--------|---------|
| 日系(丰田/本田/日产/马自达) | ⚠️ 部分 | ✅ | partsearch 优先，无果转 EPC |
| 韩系(现代/起亚) | ✅ 良好 | ✅ | partsearch |
| 法系(标致/雪铁龙) | ✅ 良好 | ✅ | partsearch |
| 德系(大众/奥迪/宝马/奔驰) | ❌ 无收录 | ✅(audi_vw) | EPC 树导航 |
| 美系(福特/GM/克莱斯勒) | ❌ 无收录 | ⚠️ | 泰安联 / EPC 树 |
| 自主品牌(吉利/奇瑞/长城/北汽) | ❌ 无收录 | ❌ | 客户提供 VIN |

## 使用要点

1. **优先 partsearch，无果再 EPC 树** —— 速度差 10 倍以上。
2. **必须验证配件类型** —— 不能假设 OE 号段对应张紧器（如本田 `31110` 实为皮带，张紧器在 `31170`/`31180`）。
3. **必须验证车型/发动机** —— 同品牌不同排量的张紧器 OE 不同，以「适用车型列表」为准。
4. **德系/美系/自主品牌** —— partsearch 无收录，走 EPC 树或泰安联。
5. **不信任 AI 知识库** —— 以 17vin 直接查询结果为准；OE 兼容性最终由工厂确认。

## 数据清洗中的角色

1. 输入：OE 号 / 车型名称（如「福特嘉年华 11-15款」）。
2. partsearch 直接验证 OE / 或 EPC 树定位配件并取 OE。
3. 输出：17vin 上的 OE 号、替换号、适配车型。
4. 这些 OE 与泰安联、睿锋后台交叉验证（见主 skill Verify 与置信度分级）。
