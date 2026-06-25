# 17vin Web 界面导航模式（2026-05 实测）

浏览器 CDP 连接 17vin（https://www.17vin.com）的三种查询路径。

## 路径一：配件号码搜索（秒级，推荐优先）

```
https://www.17vin.com/partsearch/{OE号}.html
```

**OE 号格式：** 去掉特殊字符（`.` `-` 空格），只用字母数字。
- `5751.43` → `575143` ✓
- `16620-31070` → `1662031070` ✓
- `03C903315C` → `03C903315C` → 实测无结果（该 OE 不在 17vin partsearch 中）

**返回数据：**
- 配件品牌确认
- 替换号码列表（Gates/SKF/DAYCO/LEMFORDER 等品牌件号，关联度 1-4）
- "适用车型和替换号" 链接 → `/modellist/{OE}/{group_id}.html?p=...`

**验证案例（2026-05-29）：**
- `575143` → 标致,雪铁龙 ✓ → 分类：三角多楔带张紧器（V-ribbed belt tensioner）→ **确认为张紧器总成**
- 52 个替换号：Gates T38407、SKF VKM33311、DAYCO APV2226、LEMFORDER 2650301

## 路径二：车型 EPC 树导航（分钟级）

### 车型列表页

```python
import base64

# 注意：参数名是 chancjia 不是 changjia
params = "brand=大众&chancjia=上汽大众&series=朗逸"
b64 = base64.urlsafe_b64encode(params.encode()).decode().rstrip('=')
url = f"https://www.17vin.com/models.html?p={b64}"

# 已知可用品牌参数：
# brand: 大众/丰田/本田/日产/现代/标致/宝马/奔驰/福特/别克/雪佛兰/路虎...
# chancjia: 上汽大众/一汽大众/广汽本田/东风本田/一汽丰田/北京现代/东风标致...
# series: 朗逸/雅阁/卡罗拉/逍客/307/索纳塔...
```

### EPC 层级路径

| 层级 | URL 模式 | 说明 |
|------|---------|------|
| 一级目录 | `/{brand}/cata1/{hash}/{number}.html?p=aXNfbW9kZWw9MQ==` | 0-9 主门类 |
| 二级目录 | `/{brand}/cata2/{hash}/{number}/{section}.html?p=...` | 某门类的子项列表 |
| 配件图 | `/{brand}/partlist/{hash}/{number}/2-{subsection}.html?p=...` | 爆炸图 + 配件号 |

**品牌 EPC 前缀：**
- `audi_vw`：VW, Audi, 斯柯达, 西雅特
- `honda`：本田
- `toyota`：丰田, 雷克萨斯
- `peugeot`：标致, 雪铁龙

### ⚠️ 陷阱

1. **VW EPC Belt Drive 位置：** VW 的发动机二级目录（cata2/1）不含直接 Belt Drive 子项。
   V-ribbed belt 在更深的 9xx 编号段。需滚动或搜索"张紧"。

2. **动态加载：** 车型列表页（models.html）的表格数据由 JS 动态渲染。
   首次 snapshot 通常只有空表头。处理方式：
   - 等待 1-2 秒后重新 snapshot
   - 或用 console 直接取 `<a>` 的 href 属性

3. **搜索重定向：** "配件名称搜索" 可能重定向到 `/brand.html`，建议用 URL 构造而非搜索框。

## 路径三：API (api.17vin.com:8080) — 已停用

旧的付费 REST API（MD5 token 鉴权、按次收费）已停用，不再使用。17vin 查询统一走上面的浏览器 partsearch（路径一）与 EPC 树导航（路径二）。

## 已测试品牌覆盖

| 品牌 | models.html | EPC cata1 | partsearch | 备注 |
|------|-----------|-----------|------------|------|
| 大众/奥迪 | ✓ | ✓ (audi_vw) | 部分 | 03C903315C 无结果 |
| 标致/雪铁龙 | ✓ | 待测 (peugeot) | ✓ | 575143 确认 |
| 本田 | ✓（用户已测） | ✓ (honda) | 待测 | 思迪 EPC 可达 |
| 丰田 | ✓（用户已测） | 待测 | ✓ | 16620-F4020 有结果 |
| 吉利 | ✗ | ✗ | ✗ | 无覆盖，标记 Low |
| 北汽 | ✗ | ✗ | ✗ | 无覆盖，标记 Low |
