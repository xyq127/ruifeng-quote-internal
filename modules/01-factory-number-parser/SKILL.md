---
name: 01-factory-number-parser
description: 当用户需要解析雷迪克（Radick）工厂编号（DAC/DU/RAH 格式），提取内径、外径、变型、高度、ABS 齿数等物理参数，或生成 8 位核心编号用于后续 TecDoc/17vin 搜索时使用。数据治理流程的起点。
metadata:
  displayName: 工厂编号解析
  version: 1.0.1
  author: Hermes Agent
  category: data-governance
---

# 雷迪克工厂编号解析

## 概述

将雷迪克工厂的产品编号拆解为物理参数，作为数据治理的起点。这些参数用于在泰安联等第三方平台进行参数逆向匹配。

## 编号规则

工厂编号格式：`{前缀}{内径2位}{外径2位}{变型2位}{高度2位}-{后缀}(ABS{齿数})`

### 示例：`DAC39720037-2RZ(ABS88)`

| 位置 | 值 | 含义 |
|------|-----|------|
| 前缀 | DAC | 品牌/系列前缀（DAC/DU/GDU = 一代轴承） |
| 内径 | 39 | 内径 39mm |
| 外径 | 72 | 外径 72mm |
| 变型 | 00 | 外径变型代号（中间两位） |
| 高度 | 37 | 高度编码（最后两位） |
| 后缀 | -2RZ | 密封形式（2RZ = 双面接触式密封） |
| ABS 齿数 | 88 | ABS 齿圈 88 齿 |
| 核心8位 | 39720037 | 内径+外径+变型+高度，用于泰安联搜索 |

### 解析规则

```
DAC 39 72 00 37 -2RZ (ABS88)
 │   │  │  │  │   │      │
 │   │  │  │  │   │      └─ ABS齿数：ABS后面的数字
 │   │  │  │  │   └─ 后缀：横杠后的密封/结构代码
 │   │  │  │  └─ 高度：最后2位数字
 │   │  │  └─ 变型：外径变型，第5-6位数字
 │   │  └─ 外径：第3-4位数字
 │   └─ 内径：第1-2位数字
 └─ 前缀：DAC 开头
```

⚠️ 注意：中间 `00` 是外径变型，不是高度。高度是最后 2 位数字（37）。

## Python 解析脚本

```python
import re

def parse_factory_number(code: str) -> dict:
    """
    解析雷迪克工厂编号
    
    Args:
        code: 工厂编号，如 'DAC39720037-2RZ(ABS88)'
    
    Returns:
        dict: {
            'prefix': 'DAC',
            'inner_diameter': 39,
            'outer_diameter': 72,
            'variant': 0,       # 外径变型，第3组数字
            'height': 37,        # 高度，第4组数字
            'suffix': '-2RZ',
            'abs_teeth': 88,
            'core_number': '39720037',
            'full_match': True/False
        }
    """
    result = {
        'prefix': '',
        'inner_diameter': 0,
        'outer_diameter': 0,
        'variant': 0,
        'height': 0,
        'suffix': '',
        'abs_teeth': 0,
        'core_number': '',
        'full_match': False
    }
    
    code = code.strip().upper()
    
    # 正则: {前缀}{内径2位}{外径2位}{变型2位}{高度2位}{后缀}
    pattern = r'^([A-Z]+)(\d{2})(\d{2})(\d{2})(\d{2})(.*)$'
    match = re.match(pattern, code)
    
    if not match:
        return result
    
    result['prefix'] = match.group(1)
    result['inner_diameter'] = int(match.group(2))
    result['outer_diameter'] = int(match.group(3))
    result['variant'] = int(match.group(4))     # 变型在高度之前
    result['height'] = int(match.group(5))       # 高度在变型之后
    result['core_number'] = match.group(2) + match.group(3) + match.group(4) + match.group(5)
    
    remainder = match.group(6)
    
    # 提取 ABS 齿数
    abs_match = re.search(r'ABS(\d+)', remainder)
    if abs_match:
        result['abs_teeth'] = int(abs_match.group(1))
    
    # 提取后缀
    suffix_match = re.match(r'(-[^(\s]*)', remainder)
    if suffix_match:
        result['suffix'] = suffix_match.group(1)
    
    result['full_match'] = True
    return result
```

## 命令行使用

本功能已集成到 `cli-anything-platform-service` CLI：

```bash
cli-anything-platform-service data-clean parse "DAC39720037-2RZ(ABS88)"
cli-anything-platform-service --json data-clean parse "DAC45840045"
```

## 注意事项

1. **高度字段不是直接的 mm 值**，是工厂内部编码，需要在泰安联等平台按原样搜索
2. **变型代号**用于区分同一尺寸的不同产品版本
3. **ABS 齿数是可选字段**，不是所有产品都有
4. **前缀可能不只有 DAC**，也包含 DU、GDU（一代轴承）及 RAH/RAW（二三代轮毂单元）
5. **核心8位编号** = 内径+外径+变型+高度，用于泰安联 DAC 编码格式搜索 `{d}{D}00{B}`

## 使用场景

- 数据治理：用内径/外径/高度在泰安联搜索，获取第三方 OE 进行交叉验证
- 参数逆向法：不依赖 OE 编号，只用物理参数匹配配件
- 产品入库校验：确认工厂编号与物理参数的一致性
