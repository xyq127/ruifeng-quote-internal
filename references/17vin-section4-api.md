# 17vin API 完整参考 — OEM 反向查询 + 车型→EPC→OE 全管线

> **最后更新: 2026-05-29** — 重写，加入 Section 6 车型查全车件 API。
> 参考文档: `https://www.17vin.com/doc.html`（需登录，认证见 1003 页面）

## 概述

17vin 提供两套 API 路径：

| 路径 | Section | 方向 | 用途 |
|------|---------|------|------|
| **OE → 车型** | 4001/4004/40031 | 反向 | 已知 OE 号，查适配车型和替换号 |
| **车型 → OE** | 6003/6005/6101/6102/6105/6107 | 正向 | 已知车型，导航 EPC 目录找到配件 OE |

本文档涵盖 **全部可用端点**，认证方式统一。

## API 凭证

**切勿在代码/文档中硬编码账号密码。** 凭据从环境变量或个人配置读取（解析顺序见 `scripts/vin17_epc.py`：环境变量 → `~/.cli-anything-platform-service/config.json` 的 `vin17` 段）：

```python
import os

USERNAME = os.environ["17VIN_USERNAME"]   # 或从 personal_config 读取
PASSWORD = os.environ["17VIN_PASSWORD"]
BASE = os.environ.get("17VIN_API", "http://api.17vin.com:8080")
```

> 实际查询直接用封装好的 `python scripts/vin17_epc.py oe --oe <OE号>`，无需自己拼凭据；本文档的 Python 仅作算法说明。账号用 `python scripts/personal_config.py init` 录入。

## 认证（Token 算法）

来自官方文档 `1003.登录及Api密钥说明`：

```
Token = MD5( MD5(username) + MD5(password) + url_parameters )
```

其中 `url_parameters` 以 `/?` 开头，包含所有请求参数（不含 user 和 token 自身）：

```python
import hashlib

def gen_token(username, password, url_params):
    um = hashlib.md5(username.encode()).hexdigest()
    pm = hashlib.md5(password.encode()).hexdigest()
    return hashlib.md5(f"{um}{pm}{url_params}".encode()).hexdigest()

# 完整 URL 模板
url = f"{BASE}{url_params}&user={USERNAME}&token={token}"
```

**关键注意事项：**
- `url_params` 必须包含 `/?` 前缀
- 参数顺序在 token 计算和最终请求中必须一致
- URL 参数中的中文需要 URL 编码（`urllib.parse.quote`）
- WSL2 环境需设置 `no_proxy` 避免代理阻断（见下文）

---

## Part B: 车型正向查全车件 (Section 6)

用于 **不知道 OE、只知道车型** 的场景。步骤：

### B1. 车型模糊搜索 (6005 search_model)

```python
params = "/?action=search_model&query_model_name=" + urllib.parse.quote("朗逸")
# 返回: brand, factory, series, model, display_name
```

### B2. 车型列表 (6003 models)

拿到 brand/factory/series 后，获取具体年款和发动机：

```python
params = "/?action=models&brand=" + urllib.parse.quote("大众") + \
         "&factory=" + urllib.parse.quote("上汽大众") + \
         "&series=" + urllib.parse.quote("朗逸") + "&model="
```

返回关键字段：
- `model_id`: EPC 导航必需
- `epc`: EPC 品牌标识（如 `audi_vw`, `honda`, `toyota`）
- `engine_no`: 发动机代码（如 `CFN`, `G4KD`, `K24Z`）
- `hasPart`: 是否有配件数据
- `detail`, `model_year`, `cc`: 车型/年款/排量

### B3. 一级目录 (6101 cata1)

```python
params = f"/{epc}?action=cata1&model_id={model_id}"
# 返回 data.catalist: [{cata_code, name_en, name_zh}, ...]
# 选 cata_code='1' 进入发动机
```

### B4. 二级目录 (6102 cata2)

```python
params = f"/{epc}?action=cata2&model_id={model_id}&cata1_code=1"
# 返回发动机下所有子节（气缸体、凸轮轴、正时链等）
```

**注意：** 不同品牌 EPC 结构差异大：
- 大众/奥迪: 发动机 L2 中没有独立的皮带驱动节（可能在更深层级或其他分类）
- 日系/韩系: 皮带/张紧器通常在发动机分类下

### B5. 配件名称搜索 (6107 search_epc_part_name)

直接在当前车型 EPC 中搜索配件名：

```python
import base64
encoded = base64.urlsafe_b64encode("张紧轮".encode()).decode()
params = f"/{epc}?action=search_epc_part_name&model_id={model_id}" + \
         f"&query_match_type=exact&query_part_name={encoded}" + \
         f"&query_part_name_is_safebase64=1"
```

**实测：** 大众 EA111 上搜索"张紧轮/张紧器/tensioner/belt"均返回 1006（无结果），说明 VW EPC 配件名称索引不完整。

### B6. 配件列表 (6105 part)

获取某 EPC 分类下的全部配件：

```python
params = f"/{epc}?action=part&model_id={model_id}" + \
         f"&last_cata_code={cata_code}&last_cata_code_level=2"
```

---

## Part C: OE 反向查车型 (Section 4)

### C1. search_epc (4001) + interchange (4004) + modellist (40031)

保持原流程，但 **品牌覆盖有限**（见下方覆盖率表）。

## 品牌覆盖率（2026-05-29 实测）

### search_epc (4001) 按品牌

| 品牌集群 | search_epc | EPC 目录 (cata1/cata2) | 推荐路径 |
|----------|-----------|----------------------|---------|
| 丰田/本田/日产/马自达 | ✅ code=1 | ✅ 有 | API 全管线 |
| 现代/起亚 | ✅ code=1 | ✅ 有 | API 全管线 |
| 标致/雪铁龙 | ✅ code=1 | ✅ 有 | API 全管线 |
| 大众/奥迪 | ❌ code=1006 | ✅ 有目录 | 浏览器 EPC 导航 |
| 宝马/奔驰 | ❌ code=1006 | ⚠️ 待验证 | 浏览器 EPC 导航 |
| 福特/GM/克莱斯勒 | ❌ code=1006 | ⚠️ 待验证 | 电商平台搜索 / 浏览器 EPC |
| 吉利/长城/奇瑞 | ❌ | ❌ 无 | 客户提供 VIN |
| 北汽/其他自主 | ❌ | ❌ 无 | 客户提供 VIN |

### 具体 OE 测试结果

| OE 号 | 品牌 | search_epc | 备注 |
|-------|------|-----------|------|
| 252812G000 | 现代/起亚 | code=1 | ✅ Epc=audi_vw, Group=20 |
| 11955JA00A | 日产 | code=1 | ✅ Epc=nissan, Group=29 |
| 1662031070 | 丰田 | code=1 | ✅ Epc=toyota, Group=40 |
| 31110RAAA01 | 本田 | code=1 | ✅ Epc=honda, Group=19 |
| 03C903315C | 大众 | code=1006 | ❌ 不在 API 数据库中 |
| 06B903315A | 大众/奥迪 | code=1006 | ❌ 不在 API 数据库中 |

## 代理问题

**症状：** 所有 API 返回 503  
**原因：** WSL2 shell 中 `http_proxy` 环境变量让请求走了代理  
**修复：**
```python
import os
os.environ['no_proxy'] = '127.0.0.1,localhost,::1'
os.environ['NO_PROXY'] = '127.0.0.1,localhost,::1'
```
`execute_code` 沙盒环境无代理问题，可直接运行。

## API 文档入口

在线文档（需浏览器登录 17vin）：`https://www.17vin.com/doc.html`
关键端点文档：
- `https://www.17vin.com/doc/1003.html` — 认证说明
- `https://www.17vin.com/doc/6003.html` — 车型列表
- `https://www.17vin.com/doc/6005.html` — 车型模糊搜索
- `https://www.17vin.com/doc/6101.html` — 一级目录
- `https://www.17vin.com/doc/6102.html` — 二级目录
- `https://www.17vin.com/doc/6105.html` — 配件列表
- `https://www.17vin.com/doc/6107.html` — 配件名称搜索

---

*本文件于 2026-05-29 重写，整合了 Section 4 和 Section 6 两套 API 路径。*
