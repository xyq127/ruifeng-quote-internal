#!/usr/bin/env python3
"""睿锋平台自包含客户端 —— 登录 + 查询，无需安装 RayForm-CLI。

本模块把睿锋平台的登录、认证、HTTP 调用、配置持久化内置到本 skill，
仅依赖标准库 + requests。装好这个 skill 即可完成睿锋平台登录与查询，
不再依赖 cli-anything-platform-service / data-clean 命令。

登录态优化（本次重点）：
  - 查询前确保持有有效会话：有 token 直接用；无 token 但已存账号密码则自动登录。
  - 请求遇到登录态失效（HTTP 401/403，或 HTTP 200 但 body.code=401 / status=false
    且消息含「登录/token/失效/过期」等）时，立即用账号密码重登一次并重试，新 token 落盘复用。
  - 自动重登需要密码可用：login 默认把密码写入配置（文件 0o600，仅本用户可读）；
    用 --no-save-password 可关闭，但失效后需手动重新 login。

配置文件（默认与 RayForm-CLI 兼容，便于复用已有 token）：
  ~/.cli-anything-platform-service/config.json
  可用环境变量 RUIFENG_CONFIG 覆盖路径。
  结构: {"current_env": "prod",
         "environments": {"prod": {"base_url": ..., "token": ..., "mobile": ..., "password": ...}}}

子命令:
  login          登录获取并保存 token（密码不传则交互式安全输入）
  config-use     切换当前环境 (test/prod)
  config-set     设置 base_url / token
  config-show    查看配置状态
  price          按产品 ID 查询四个价格（采购价/P1/P2/P3）
  product        按产品 ID 查询产品详情 (findById)
  vin            按车架号(VIN)分页查询产品（/inventory/vin/list）
  vin-vehicle    按车架号(VIN)查询车型信息（/api/v1/sfh/vin/query）

用法示例:
  python ruifeng_platform.py config-use prod
  python ruifeng_platform.py login --mobile 13800000000
  python ruifeng_platform.py price --product-id 123 --json
  python ruifeng_platform.py vin --vin LMXA15CF5MZ469515 --json
  python ruifeng_platform.py vin-vehicle --vin LMXA15CF5MZ469515 --json
"""

import argparse
import getpass
import json
import os
import socket
import ssl
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests


CONFIG_FILE = Path(
    os.environ.get("RUIFENG_CONFIG")
    or (Path.home() / ".cli-anything-platform-service" / "config.json")
)

# 预置环境默认值（与 RayForm-CLI 对齐）
ENV_DEFAULT_BASE_URL = {
    "prod": "https://rfscm.com/api/principal",
    "test": "",  # 测试环境地址各异，用 config-set --base-url 指定
}
KNOWN_ENVS = ["test", "prod"]
# 直连（不走系统代理）的主机：正式域名 + 预置服务器 IP
_DIRECT_HOSTS = {"rfscm.com", "8.155.167.214", "8.155.164.3"}


def first_run_hint(missing: str = "") -> str:
    """首次运行 / 凭据缺失时的统一提示（各自包含脚本共用）。"""
    need = f"（缺少：{missing}）" if missing else ""
    return (
        f"⚠️ 首次使用，需要先配置个人凭据{need}。\n"
        "请在【你自己的终端】运行配置向导（密码用安全输入，不经过 Agent / 命令行历史）：\n"
        "  python scripts/personal_config.py init\n"
        "向导会引导录入：① 睿锋登录手机号 + 密码  ② 17vin 用户名 + 密码  "
        "③ qwen-vision 的 SiliconFlow API Key\n"
        f"凭据仅写入本机 {CONFIG_FILE}（权限 0o600，不随 skill 分发）。"
    )


# ── 配置读写 ──────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    # 配置含 token，仅限本用户读写
    os.chmod(CONFIG_FILE, 0o600)


def _current_env(cfg: dict) -> str:
    return cfg.get("current_env") or os.environ.get("PLATFORM_ENV") or ""


def _env_cfg(cfg: dict, env: str) -> dict:
    return cfg.setdefault("environments", {}).setdefault(env, {})


def resolve_base_url(cfg: dict, env: str) -> str:
    return (
        _env_cfg(cfg, env).get("base_url")
        or ENV_DEFAULT_BASE_URL.get(env, "")
        or os.environ.get("PLATFORM_BASE_URL", "")
    )


# ── HTTP 客户端 ───────────────────────────────────────────────────────

def _direct_connect_ok(host: str, port: int = 443, timeout: float = 2.0) -> bool:
    """探测能否直连并完成 TLS 握手（用于决定是否绕过系统代理）。"""
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                ssock.do_handshake()
        return True
    except (OSError, ssl.SSLError):
        return False


# 业务层登录过期关键词（HTTP 200 但 body 表达 token 失效）
_AUTH_EXPIRE_KEYWORDS = ("登录", "token", "Token", "失效", "过期",
                         "未授权", "重新登录", "认证", "凭据", "expired", "unauthorized")


def _is_auth_expired(body) -> bool:
    """判断响应体是否表示登录态失效（覆盖网关 200+code=401 / status=false 两种约定）。"""
    if not isinstance(body, dict):
        return False
    if body.get("code") in (401, 403):
        return True
    if body.get("status") is False:
        msg = str(body.get("msg") or "")
        return any(k in msg for k in _AUTH_EXPIRE_KEYWORDS)
    return False


class RuifengClient:
    """睿锋平台 REST 客户端：登录 + 带 token 的 GET/POST。"""

    def __init__(self, base_url, token=None, mobile=None, password=None):
        if not base_url:
            raise RuntimeError(
                "未配置 base_url。请先执行：\n"
                "  python ruifeng_platform.py config-use <test|prod>\n"
                "  python ruifeng_platform.py config-set --base-url <URL>  # test 环境需手动指定"
            )
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.mobile = mobile
        self.password = password
        self.session = requests.Session()

        parsed = urlparse(self.base_url)
        if parsed.hostname in _DIRECT_HOSTS and parsed.scheme == "https":
            # 正式环境域名直连，不走系统代理（代理会破坏 TLS 握手）
            if _direct_connect_ok(parsed.hostname):
                self.session.trust_env = False
        # 测试环境用 HTTP，trust_env 默认 True，由系统代理转发到内网 IP

        self.headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def set_token(self, token: str):
        self.token = token
        self.headers["Authorization"] = f"Bearer {token}"

    # ── 自动重登 ──────────────────────────────────────────────────────

    def _can_relogin(self) -> bool:
        """是否具备用账号密码自动重登的条件。"""
        return bool(self.mobile and self.password)

    def _relogin(self):
        """登录态失效时立即用账号密码重登，并把新 token 落盘复用。"""
        self.login(self.mobile, self.password)
        _persist_token(self.token)
        return self.token

    # ── 登录 ──────────────────────────────────────────────────────────

    def login(self, mobile=None, password=None, timeout=30) -> dict:
        """登录获取 token。端点在网关根路径，不含 base_url 的服务前缀。"""
        mobile = (mobile or self.mobile or "").strip()
        password = password or self.password
        if not mobile or not password:
            raise RuntimeError("缺少登录凭据（mobile/password）")

        parsed = urlparse(self.base_url)
        login_url = f"{parsed.scheme}://{parsed.netloc}/api/oauth/login/customer"
        try:
            resp = self.session.post(
                login_url,
                data={"mobile": mobile, "password": password},
                headers={"Accept": "application/json"},
                timeout=timeout,
            )
            resp.raise_for_status()
            body = resp.json()
        except requests.exceptions.Timeout:
            raise RuntimeError(f"登录超时（{timeout}秒），请检查网络连接")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"无法连接到 {login_url}")
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            raise RuntimeError(f"登录失败（HTTP {status}），请检查手机号和密码")
        except ValueError:
            raise RuntimeError("登录失败: 服务器返回异常响应")

        if body.get("code") != 200 or not body.get("status"):
            raise RuntimeError(f"登录失败: {body.get('msg', '未知错误')}")
        data = body.get("data") or {}
        token = data.get("token") if isinstance(data, dict) else None
        if not token or not isinstance(token, str) or len(token) < 20:
            raise RuntimeError("登录失败: 服务器未返回有效 token")

        self.set_token(token)
        return data

    # ── 请求 ──────────────────────────────────────────────────────────

    def _request(self, method, path, params=None, data=None, timeout=30, _retry=True,
                 origin=False):
        if origin:
            # 根域接口（如 /api/v1/sfh/vin/query）：不经 base_url 的 /api/principal 前缀
            parsed = urlparse(self.base_url)
            url = f"{parsed.scheme}://{parsed.netloc}{path}"
        else:
            # base_url 已含 /api/principal 前缀时，去掉 path 的重复前缀
            if path.startswith("/api/principal/"):
                path = path[len("/api/principal"):]
            elif path.startswith("/api/"):
                path = path[len("/api"):]
            if not path.startswith("/"):
                path = f"/{path}"
            url = f"{self.base_url}{path}"

        try:
            resp = self.session.request(
                method, url, headers=self.headers, params=params,
                json=data if method.upper() != "GET" else None, timeout=timeout,
            )
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"无法连接到平台服务: {self.base_url}（确认服务已启动/网络正常）")

        # ① HTTP 层登录态失效（401/403）→ 立即用账号密码重登一次后重试
        if resp.status_code in (401, 403) and _retry and self._can_relogin():
            self._relogin()
            return self._request(method, path, params=params, data=data,
                                 timeout=timeout, _retry=False, origin=origin)

        if resp.status_code == 204:
            return {"code": 204, "msg": "操作成功", "status": True, "data": None}

        try:
            body = resp.json()
        except ValueError:
            if resp.status_code >= 400:
                raise RuntimeError(f"请求失败 HTTP {resp.status_code}: {path}")
            raise RuntimeError(f"服务器返回非 JSON 响应: {path}")

        # ② 业务层登录态失效（HTTP 200 但 body.code=401 / status=false+失效消息）
        if _retry and self._can_relogin() and _is_auth_expired(body):
            self._relogin()
            return self._request(method, path, params=params, data=data,
                                 timeout=timeout, _retry=False, origin=origin)

        if resp.status_code >= 400:
            raise RuntimeError(f"请求失败 HTTP {resp.status_code}: {path}")
        return body

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def post(self, path, data=None, params=None):
        return self._request("POST", path, params=params, data=data)

    def post_origin(self, path, data=None, timeout=30):
        """POST 平台根域接口（不经 base_url 的 /api/principal 前缀）。"""
        return self._request("POST", path, data=data, timeout=timeout, origin=True)


# ── 从配置构造客户端 ──────────────────────────────────────────────────

def _persist_token(token):
    cfg = load_config()
    env = _current_env(cfg)
    if env:
        _env_cfg(cfg, env)["token"] = token
        save_config(cfg)


def get_client() -> RuifengClient:
    cfg = load_config()
    env = _current_env(cfg)
    if not env:
        raise RuntimeError(first_run_hint("睿锋环境/账号"))
    ec = _env_cfg(cfg, env)
    return RuifengClient(
        resolve_base_url(cfg, env),
        token=ec.get("token") or os.environ.get("PLATFORM_TOKEN"),
        mobile=ec.get("mobile") or os.environ.get("PLATFORM_MOBILE"),
        password=ec.get("password") or os.environ.get("PLATFORM_PASSWORD"),
    )


# ── 高层查询 ──────────────────────────────────────────────────────────

def _num(value):
    if value is None or value == "":
        return None
    try:
        f = float(value)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return value


def query_search(client: RuifengClient, keyword: str, query_type="ENCODE",
                 page=1, size=10, with_details=False) -> list:
    """后台产品库搜索（queryType=ENCODE），返回 content 列表。"""
    resp = client.get("/api/principal/product/list", params={
        "page": page, "size": size, "queryType": query_type,
        "keyword": keyword, "queryThird": "true" if with_details else "false",
    })
    data = resp.get("data", {})
    if not isinstance(data, dict):
        return []
    return data.get("content", data.get("records", []))


def query_inventory(client: RuifengClient, keyword: str, page=1, size=10) -> dict:
    """查询产品库存信息。

    使用产品 code 作为 keyword 搜索库存，返回与 /product/list 类似的分页结构。
    单个产品调用建议 size=10，从返回的 content 中匹配对应 code 的库存记录。

    Returns:
        {
            "content": [{"code": "...", "count": 100, "available": 80, ...}, ...],
            "totalElements": ...,
            "totalPages": ...,
        }
    """
    resp = client.get("/api/principal/inventory/list", params={
        "keyword": keyword, "page": page, "size": size,
    })
    data = resp.get("data", {})
    if not isinstance(data, dict):
        return {"content": [], "totalElements": 0, "totalPages": 0}
    return data


def query_vin(client: RuifengClient, vin: str, page=1, size=10) -> dict:
    """按车架号(VIN)分页查询产品。

    走 /inventory/vin/list 分页接口，返回与 /product/list 一致的分页结构
    （data.content / totalElements / totalPages）。拿到 content 中的
    productId 后可继续用 query_prices / findById 做后续查询。

    Returns:
        {
            "content": [{"id"或"productId": ..., "code": ..., "oe": ..., ...}, ...],
            "totalElements": ...,
            "totalPages": ...,
        }
    """
    resp = client.get("/api/principal/inventory/vin/list", params={
        "vin": vin, "page": page, "size": size,
    })
    data = resp.get("data", {})
    if not isinstance(data, dict):
        return {"content": [], "totalElements": 0, "totalPages": 0}
    return data


def query_vin_vehicle(client: RuifengClient, vin: str) -> dict:
    """按车架号(VIN)查询车型信息。

    走平台根域接口 POST /api/v1/sfh/vin/query（body: {"vin": ...}），返回原始响应。
    命中车型在 data.vehicles 列表，未命中时 data.matched=false、vehicles 为空。

    Returns:
        {"code": "SUCCESS", "data": {"vin": ..., "matched": bool,
         "vehicles": [{"brandName": ..., "seriesName": ..., "commonName": ...}, ...]}, ...}
    """
    return client.post_origin("/api/v1/sfh/vin/query", data={"vin": vin})


def query_prices(client: RuifengClient, product_id: str) -> dict:
    """查询单个产品的四个价格：采购价 + P1/P2/P3。"""
    result = {"productId": product_id, "purchasePrice": None,
              "p1Price": None, "p2Price": None, "p3Price": None, "errors": []}
    try:
        detail = client.get("/api/product/findById", params={"id": product_id})
        if detail.get("code") == 200 and isinstance(detail.get("data"), dict):
            result["purchasePrice"] = _num(detail["data"].get("purchasePrice"))
        else:
            result["errors"].append(f"findById: {detail.get('msg') or detail.get('code')}")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"findById: {exc}")
    try:
        price = client.get("/api/product/priceDetail", params={"productId": product_id})
        if price.get("code") == 200 and isinstance(price.get("data"), dict):
            d = price["data"]
            result["p1Price"] = _num(d.get("p1Price"))
            result["p2Price"] = _num(d.get("p2Price"))
            result["p3Price"] = _num(d.get("p3Price"))
        else:
            result["errors"].append(f"priceDetail: {price.get('msg') or price.get('code')}")
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"priceDetail: {exc}")
    if not result["errors"]:
        result.pop("errors")
    return result


# ── 子命令 ────────────────────────────────────────────────────────────

def cmd_config_use(args):
    if args.env not in KNOWN_ENVS:
        sys.exit(f"未知环境: {args.env}，可选: {', '.join(KNOWN_ENVS)}")
    cfg = load_config()
    cfg["current_env"] = args.env
    save_config(cfg)
    base = resolve_base_url(cfg, args.env)
    print(f"已切换到 {args.env} 环境" + (f"（base_url: {base}）" if base else "（尚未配置 base_url）"))


def cmd_config_set(args):
    cfg = load_config()
    env = args.env or _current_env(cfg)
    if not env:
        sys.exit("请先 config-use <env> 或用 --env 指定")
    ec = _env_cfg(cfg, env)
    if args.base_url:
        ec["base_url"] = args.base_url
    if args.token:
        ec["token"] = args.token
    save_config(cfg)
    print(f"[{env}] 配置已更新")


def cmd_config_show(args):
    cfg = load_config()
    cur = _current_env(cfg)
    print(f"配置文件: {CONFIG_FILE}")
    print(f"当前环境: {cur or '(未设置)'}")
    for env in KNOWN_ENVS:
        ec = _env_cfg(cfg, env)
        mark = "*" if env == cur else " "
        base = resolve_base_url(cfg, env)
        tok = "有token" if ec.get("token") else "无token"
        print(f" {mark} [{env}] {base or '(无base_url)'} — {tok}")


def cmd_login(args):
    cfg = load_config()
    env = args.env or _current_env(cfg)
    if not env:
        sys.exit("请先 config-use <env> 或用 --env 指定")
    if args.env:
        cfg["current_env"] = args.env
    base_url = args.base_url or resolve_base_url(cfg, env)
    password = args.password or os.environ.get("PLATFORM_PASSWORD") or getpass.getpass("密码: ")

    client = RuifengClient(base_url, mobile=args.mobile, password=password)
    data = client.login()
    ec = _env_cfg(cfg, env)
    ec["base_url"] = base_url
    ec["token"] = client.token
    ec["mobile"] = args.mobile  # 存手机号，配合密码用于登录态失效时自动重登
    if args.no_save_password:
        ec.pop("password", None)  # 不落盘密码：失效后需重新交互式 login
    else:
        ec["password"] = password  # 落盘密码（配置文件 0o600，仅本用户可读）以支持自动重登
    save_config(cfg)
    nick = data.get("nickName") or data.get("name") or ""
    pw_note = "（密码未保存，失效需手动重登）" if args.no_save_password else "（已启用登录态失效自动重登）"
    print(f"✅ [{env}] 登录成功" + (f"，欢迎 {nick}" if nick else "")
          + f"，token 已保存到 {CONFIG_FILE} {pw_note}")


def _require_login(client):
    """确保查询前持有有效会话：有 token 直接用；无 token 但有账号密码则自动登录。"""
    if client.token:
        return
    if client._can_relogin():
        client._relogin()
        return
    sys.exit(first_run_hint("睿锋登录手机号+密码"))


def cmd_price(args):
    client = get_client()
    _require_login(client)
    ids = [args.product_id] if args.product_id else \
        [p.strip() for p in args.product_ids.split(",") if p.strip()]
    rows = [query_prices(client, pid) for pid in ids]
    if args.json:
        out = rows[0] if (args.product_id and len(rows) == 1) else {"results": rows}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        labels = [("采购价", "purchasePrice"), ("OEM价格(P1)", "p1Price"),
                  ("品牌一级销售价(P2)", "p2Price"), ("品牌二级销售价(P3)", "p3Price")]
        for r in rows:
            print(f"产品 {r['productId']} 价格:")
            for name, key in labels:
                v = r.get(key)
                print(f"  {name}: {'—' if v is None else v}")
            if r.get("errors"):
                print(f"  ⚠️ {'; '.join(r['errors'])}")
            print()


def cmd_product(args):
    client = get_client()
    _require_login(client)
    resp = client.get("/api/product/findById", params={"id": args.product_id})
    print(json.dumps(resp.get("data", resp), ensure_ascii=False, indent=2))


def cmd_search(args):
    client = get_client()
    _require_login(client)
    rows = query_search(client, args.keyword, query_type=args.query_type,
                        page=args.page, size=args.size, with_details=args.with_details)
    if args.json:
        print(json.dumps({"keyword": args.keyword, "content": rows},
                         ensure_ascii=False, indent=2))
    else:
        if not rows:
            print(f"未找到匹配产品: {args.keyword}")
            return
        print(f"关键词 [{args.keyword}] 命中 {len(rows)} 条:")
        for r in rows:
            print(f"  productId={r.get('id', '')}  code={r.get('code', '')}  "
                  f"oe={r.get('oe', '')}  {r.get('name', '')}")


def cmd_vin(args):
    client = get_client()
    _require_login(client)
    data = query_vin(client, args.vin, page=args.page, size=args.size)
    content = data.get("content", data.get("records", []))
    if args.json:
        print(json.dumps({"vin": args.vin, **data}, ensure_ascii=False, indent=2))
    else:
        if not content:
            print(f"未找到该车架号匹配的产品: {args.vin}")
            return
        total = data.get("totalElements", 0)
        print(f"车架号 [{args.vin}] 命中 {len(content)} 条（共 {total} 条）:")
        for r in content:
            pid = r.get("id") or r.get("productId") or ""
            print(f"  productId={pid}  code={r.get('code', '')}  "
                  f"oe={r.get('oe', '')}  {r.get('name', '')}")


def cmd_vin_vehicle(args):
    client = get_client()
    _require_login(client)
    resp = query_vin_vehicle(client, args.vin)
    if args.json:
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        return
    data = resp.get("data") or {}
    vehicles = data.get("vehicles") or []
    if not data.get("matched") or not vehicles:
        print(f"未匹配到车型信息: {args.vin}")
        return
    print(f"车架号 [{args.vin}] 命中 {len(vehicles)} 个车型（数据源: {data.get('sourceType', '')}）:")
    for v in vehicles:
        print(f"  - {v.get('commonName') or v.get('vehicleName', '')}")
        detail = " | ".join(
            str(v.get(k))
            for k in ("brandName", "seriesName", "modelYear", "cylinderCapacityLiter",
                      "engineCode", "transmissionType", "fuelType")
            if v.get(k)
        )
        if detail:
            print(f"    ({detail})")


def build_parser():
    p = argparse.ArgumentParser(description="睿锋平台自包含客户端（登录 + 查询）")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("config-use", help="切换当前环境")
    s.add_argument("env", choices=KNOWN_ENVS)
    s.set_defaults(func=cmd_config_use)

    s = sub.add_parser("config-set", help="设置 base_url / token")
    s.add_argument("--env", choices=KNOWN_ENVS)
    s.add_argument("--base-url")
    s.add_argument("--token")
    s.set_defaults(func=cmd_config_set)

    s = sub.add_parser("config-show", help="查看配置状态")
    s.set_defaults(func=cmd_config_show)

    s = sub.add_parser("login", help="登录获取并保存 token")
    s.add_argument("--mobile", required=True, help="登录手机号")
    s.add_argument("--password", help="密码（不传则交互式安全输入）")
    s.add_argument("--env", choices=KNOWN_ENVS, help="目标环境（默认当前环境）")
    s.add_argument("--base-url", help="覆盖 base_url")
    s.add_argument("--no-save-password", action="store_true",
                   help="不在配置中保存密码（登录态失效后需手动重新 login，关闭自动重登）")
    s.set_defaults(func=cmd_login)

    s = sub.add_parser("price", help="按产品 ID 查询四个价格")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--product-id")
    g.add_argument("--product-ids", help="逗号分隔")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_price)

    s = sub.add_parser("product", help="按产品 ID 查询产品详情")
    s.add_argument("--product-id", required=True)
    s.set_defaults(func=cmd_product)

    s = sub.add_parser("search", help="后台产品库搜索（关键词/编号/OE）")
    s.add_argument("--keyword", required=True)
    s.add_argument("--query-type", dest="query_type", default="ENCODE")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--size", type=int, default=10)
    s.add_argument("--with-details", action="store_true", help="附带第三方详情")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("vin", help="按车架号(VIN)分页查询产品")
    s.add_argument("--vin", required=True, help="17位车架号 VIN 码")
    s.add_argument("--page", type=int, default=1)
    s.add_argument("--size", type=int, default=10)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_vin)

    s = sub.add_parser("vin-vehicle", help="按车架号(VIN)查询车型信息")
    s.add_argument("--vin", required=True, help="17位车架号 VIN 码")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_vin_vehicle)

    return p


def main():
    args = build_parser().parse_args()
    try:
        args.func(args)
    except RuntimeError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
