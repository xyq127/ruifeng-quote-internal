---
name: 04-taianlian-tecdoc-search
description: 当用户需要通过泰安联（TaiAnLian）或 TecDoc（TecAlliance）查询配件 OE 号、适配车型、物理参数，或进行第三方数据交叉验证时使用。包含浏览器 CDP 搜索和结果提取。
metadata:
  displayName: 泰安联TecDoc搜索
  version: 2.0.0
  author: Hermes Agent
  category: data-cleaning
---

# TecDoc 搜索（泰安联 + TecAlliance）

## 概述

通过浏览器 CDP 操作泰安联和 TecDoc（TecAlliance 中国站）网页，查询配件的 OE 号、适配车型、物理参数和产品图片。作为数据清洗中的第三方数据源，用于 OE 号交叉验证。

| 数据源 | 优先级 | 搜索方式 | 说明 |
|--------|--------|---------|------|
| 泰安联 | 主数据源 | 物理参数 / 工厂编号 | TecDoc 代理商平台，覆盖面广 |
| TecAlliance | S 级黄金标准 | OE 号 / 车型 / 工厂编号 | 全球权威目录，结果最可信 |

## CLI 快速操作

数据清洗流程已集成到 `cli-anything-platform-service` CLI：

```bash
# 泰安联搜索（通过 Chrome CDP）
data-clean taianlian-search --query <工厂编号>

# TecDoc 通用搜索（通过 Chrome CDP）
data-clean tecdoc-search --query <OE号>
```

**安装**: `pip install -e ~/web-project/backend-code-repo/agent-harness[data-clean]`

## 登录方式

- **用户先登录**：Agent 不处理登录页面的验证码或认证流程
- 登录态通过 Chrome `--user-data-dir` 持久化保存，后续使用无需重复登录

### 首次使用（一次性）
1. 启动 Windows Chrome 调试模式（端口 9250）
2. CDP 导航到对应站点（泰安联 或 `tecalliance.cn`）
3. 用户手动输入账号密码 + 完成验证码
4. 登录态自动保存到 `--user-data-dir` 指定的 profile

### 后续使用
1. 重启 Chrome 时指定同一 `--user-data-dir`
2. 登录态自动恢复，直接操作

## 数据提取目标

| 字段 | 用途 |
|------|------|
| OE 号 | 与睿锋后台、17vin 交叉验证 |
| 适配车型 | 验证 OE-车型映射是否正确 |
| 内径/外径/高度 | 与工厂编号解析结果一致性校验 |
| ABS 齿数 | 与工厂编号 ABS 参数比对 |
| 产品图片 | 与后台产品图肉眼比对 |
| 其他 OE/别名 | 补充关联编号列表 |
| 配件类别 | 确认是否为轮毂轴承 |
| 制造商信息 | 确认品牌来源 |

## 注意事项

1. **用户先登录**：Agent 不处理登录流程
2. **保持会话**：登录状态可能超时，操作前确认页面已登录
3. **反爬机制**：操作间隔保持 1-2 秒，避免频繁请求触发封禁
4. **图片比对由用户判断**：截图后发给用户肉眼判断
5. **搜索精度**：TecDoc 搜索可能需要精确的 OE 号格式（带/不带横杠都试一下）
6. **CDP 不可达**：检查 Windows Chrome 是否运行在端口 9250

## 异常处理

| 场景 | 策略 |
|------|------|
| 验证码触发 | 提示用户手动完成，检查 Cookie/登录态是否过期 |
| CDP 超时 | 重试 3 次，间隔 5s，仍失败则跳过该产品 |
| Chrome 未启动 | 提示用户在 Windows 端启动 Chrome 调试模式（端口 9250） |

## 与数据清洗流程的关系

```
工厂编号解析（模块1）→ 提取参数
    ↓
TecDoc 搜索（本模块）→ 获取第三方 OE + 适配车型
    ↓
交叉比对 → 与 17vin OE、后台 OE 对比
    ↓
输出清洗报告
```
