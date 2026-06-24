---
name: 02-vin17-epc-query
description: 当用户需要通过 17vin API 查询车型 EPC 目录、进行 OE 反向查询、搜索轮毂轴承配件，或进行品牌-车型-年款-配件树遍历时使用。包含 token 生成、车型查询、目录遍历、配件搜索全流程。
metadata:
  displayName: 17vin-EPC查询
  version: 1.0.0
  author: Hermes Agent
  category: data-cleaning
---

# 17vin EPC 查询

## 概述

通过 17vin（精时科技）API 查询车型的 EPC（Electronic Parts Catalog）目录，定位轮毂轴承配件。这是数据清洗中 OE 号匹配的关键步骤。

## 认证信息

- **API 基础地址**: `http://api.17vin.com:8080`（可用环境变量 `17VIN_API` 覆盖）
- **用户名 / 密码**: **不在文档或代码中硬编码。** 从环境变量 `17VIN_USERNAME` / `17VIN_PASSWORD` 或个人配置 `~/.cli-anything-platform-service/config.json` 的 `vin17` 段读取（用 `python scripts/personal_config.py init` 录入；解析顺序见 `scripts/vin17_epc.py`）。
- **文档地址**: `https://www.17vin.com/doc/1003.html`（登录后查看；账号见个人配置）

## Token 生成算法

```python
import hashlib

def generate_token(username: str, password: str, url_params: str) -> str:
    """
    Token 算法: MD5(MD5(username) + MD5(password) + url_parameters)
    
    ⚠️ 关键：url_params 必须包含开头的 /?
    例如: "/?action=brands&user=<USERNAME>"
    """
    username_md5 = hashlib.md5(username.encode()).hexdigest()
    password_md5 = hashlib.md5(password.encode()).hexdigest()
    token_string = f"{username_md5}{password_md5}{url_params}"
    return hashlib.md5(token_string.encode()).hexdigest()
```

## 核心接口

### 1. 6001 — 品牌列表

```
GET http://api.17vin.com:8080/?action=brands&user={username}&token={token}
```

返回所有支持的品牌列表，每个品牌包含 `epc` 字段（品牌标识符）。

### 2. 6003 — 车型列表（⚠️ 重点）

```
GET http://api.17vin.com:8080/?action=models&brand={brand}&factory={factory}&series={series}&model=&user={username}&token={token}
```

**⚠️ 三个参数都必须传**：
- `brand`: 品牌名（中文，需 URL 编码），如 "福特"
- `factory`: 厂家名（中文，需 URL 编码），如 "长安福特"
- `series`: 车系名（中文，需 URL 编码），如 "嘉年华"

返回车型列表，每条包含 `model_id` 和 `epc`，这是后续查询的关键。

### 3. 6101 — 一级目录

```
GET http://api.17vin.com:8080/{epc}?action=cata1&model_id={model_id}&user={username}&token={token}
```

返回一级分类目录。关注包含以下关键词的目录：
- "底盘"、"悬挂"、"车轮"、"轮毂"、"轴承"、"传动"、"前桥"、"后桥"、"车轴"

### 4. 6102/6103/6104 — 二/三/四级目录

```
GET http://api.17vin.com:8080/{epc}?action=cata{level}&model_id={model_id}&cata1={cata1}&cata2={cata2}&user={username}&token={token}
```

逐级深入，直到 `is_last=1`。

### 5. 6105 — 配件列表

```
GET http://api.17vin.com:8080/{epc}?action=part&model_id={model_id}&last_cata_code={cata_code}&last_cata_code_level={level}&user={username}&token={token}
```

返回配件列表，从中筛选轮毂轴承。

### 6. 6108 — 配件标准名称搜索（⚠️ 部分品牌不支持）

```
GET http://api.17vin.com:8080/{epc}?action=search_std_part_name&model_id={model_id}&query_match_type=exact&query_part_name={base64_name}&query_part_name_is_safebase64=1&user={username}&token={token}
```

部分品牌返回 `code: 1003` 不支持，此时回退到目录遍历法。

## 轮毂轴承关键词

在配件列表中匹配以下关键词（中英文）：
- 轮毂轴承、前轮轴承、后轮轴承、轮毂单元
- wheel bearing、hub bearing、hub assembly
- 轴承、bearing

## 完整查询流程

```python
import urllib.request
import urllib.parse
import json
import time
import os

# 凭据从环境变量/个人配置读取，切勿硬编码（解析顺序见 scripts/vin17_epc.py）
USERNAME = os.environ["17VIN_USERNAME"]
PASSWORD = os.environ["17VIN_PASSWORD"]
BASE_URL = os.environ.get("17VIN_API", "http://api.17vin.com:8080")

def call_api(url: str) -> dict:
    """调用 API，返回 JSON"""
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))

def find_models(brand: str, factory: str, series: str) -> list:
    """查询车型列表，返回 model_id + epc 列表"""
    encoded_brand = urllib.parse.quote(brand)
    encoded_factory = urllib.parse.quote(factory)
    encoded_series = urllib.parse.quote(series)
    
    url_params = f"/?action=models&brand={encoded_brand}&factory={encoded_factory}&series={encoded_series}&model="
    token = generate_token(USERNAME, PASSWORD, url_params)
    url = f"{BASE_URL}{url_params}&user={USERNAME}&token={token}"
    
    data = call_api(url)
    if data.get('code') != 1:
        return []
    return data.get('data', [])

def find_wheel_bearing_parts(epc: str, model_id: str) -> list:
    """
    通过逐级目录遍历法查找轮毂轴承配件
    返回所有匹配的配件列表
    """
    results = []
    wheel_keywords = ['轮毂', '轴承', '车轮', '悬挂', '底盘', '传动', '车轴', '前桥', '后桥']
    
    # 一级目录
    url_params = f"/{epc}?action=cata1&model_id={model_id}"
    token = generate_token(USERNAME, PASSWORD, url_params)
    data = call_api(f"{BASE_URL}{url_params}&user={USERNAME}&token={token}")
    if data.get('code') != 1:
        return []
    
    for l1 in data.get('data', {}).get('catalist', []):
        if not any(kw in l1.get('name_zh', '') for kw in wheel_keywords):
            continue
        results.extend(_traverse_catalog(epc, model_id, l1, level=1))
    
    # 筛选轮毂轴承
    bearing_keywords = ['轮毂轴承', '前轮轴承', '后轮轴承', '轮毂单元', 'wheel bearing', 'hub bearing']
    return [
        p for p in results
        if any(kw in (p.get('std_name_zh', '') or p.get('name_zh', '')) for kw in bearing_keywords)
    ]

def _traverse_catalog(epc, model_id, node, level):
    """递归遍历目录"""
    results = []
    if node.get('is_last') == 1:
        url_params = f"/{epc}?action=part&model_id={model_id}&last_cata_code={node['cata_code']}&last_cata_code_level={level}"
        token = generate_token(USERNAME, PASSWORD, url_params)
        data = call_api(f"{BASE_URL}{url_params}&user={USERNAME}&token={token}")
        if data.get('code') == 1:
            return data.get('data', {}).get('partlist', [])
    else:
        next_level = level + 1
        cata_param = f"cata{level}"
        parent_params = ""
        if level >= 1:
            parent_params = f"&cata1={node['cata_code']}"
        if level >= 2:
            parent_params += f"&cata2={node.get('cata2_code', '')}"
        
        url_params = f"/{epc}?action=cata{next_level}&model_id={model_id}{parent_params}"
        token = generate_token(USERNAME, PASSWORD, url_params)
        data = call_api(f"{BASE_URL}{url_params}&user={USERNAME}&token={token}")
        if data.get('code') == 1:
            for child in data.get('data', {}).get('catalist', []):
                results.extend(_traverse_catalog(epc, model_id, child, level=next_level))
    return results
```

## 错误码

| 错误码 | 含义 | 处理 |
|--------|------|------|
| 1002 | token 值生成错误 | 检查 url_params 是否包含 `/?` 前缀 |
| 1003 | 不支持的品牌接口 | 该 epc 不支持此接口，换用目录遍历法 |
| 1006 | query no result | 查询无结果，检查参数 |
| 503 | Service Unavailable | API 服务器维护/过载，稍后重试 |

## 成本注意

- API 按调用收费，约 3 分钱/次
- 必须建立本地缓存，避免重复查询
- 批量查询时建议每批 10-16 个车型，避免超时
- 建议请求间隔 0.5-1 秒

## 数据清洗中的角色

1. 输入：车型名称（如"福特嘉年华 11-15款"）
2. 通过 6003 接口找到对应的 `model_id` 和 `epc`
3. 通过目录遍历找到轮毂轴承配件
4. 输出：17vin 上的 OE 号和配件号
5. 这些 OE 号与泰安联、睿锋后台的 OE 进行交叉验证
