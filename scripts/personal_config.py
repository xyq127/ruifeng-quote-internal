#!/usr/bin/env python3
"""个人配置统管 —— 一份文件存齐本 skill 所需的所有个人密钥。

每个用户**首次使用前跑一次** `init` 向导，把以下个人凭据集中写入同一个配置文件
（默认 `~/.cli-anything-platform-service/config.json`，0o600 仅本人可读；
 `RUIFENG_CONFIG` 可改路径，与睿锋自包含模块共用同一文件）：

  - 睿锋平台：登录手机号 + 密码（+ 环境/base_url）   → ruifeng_platform.py 使用
  - 17vin   ：用户名 + 密码                          → 17vin 网页登录（浏览器 CDP）
  - qwen-vision：SiliconFlow API Key                 → recognize_image.py 使用

密钥全部由用户在交互式提示中输入（密码用 getpass，不进命令行/历史），
配置文件**不随 skill 分发**——它在用户 $HOME 下，npm 安装/重装不会覆盖它。

子命令:
  init    交互式向导，集中录入所有个人凭据（已存在的项可回车跳过保留）
  check   首次运行检测：各功能凭据是否就绪；缺项时打印录入提示并以退出码 2 返回
  show    查看配置状态（密码/Key 打码）
  get     输出单个值到 stdout（供 shell 注入，如 SILICONFLOW_API_KEY）
  set     非交互设置单个值（用于脚本化；密码类建议仍用 init）

用法示例:
  python personal_config.py init
  python personal_config.py show
  python personal_config.py get siliconflow_api_key
"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ruifeng_platform import (  # noqa: E402
    load_config, save_config, CONFIG_FILE, KNOWN_ENVS,
    resolve_base_url, _current_env, _env_cfg, first_run_hint,
)

SILICONFLOW_KEY = "siliconflow_api_key"


# ── 取值（供其他脚本 import） ─────────────────────────────────────────

def get_siliconflow_key(cfg=None):
    """qwen-vision 的 Key：环境变量优先，其次个人配置文件。"""
    cfg = load_config() if cfg is None else cfg
    return os.environ.get("SILICONFLOW_API_KEY") or cfg.get(SILICONFLOW_KEY)


def _mask(v):
    if not v:
        return "(未设置)"
    return (v[:3] + "***" + v[-2:]) if len(v) > 6 else "***"


def _prompt_keep(label, current, secret=False):
    """交互录入：有旧值则回车保留，secret 用 getpass。"""
    hint = f"（当前 {_mask(current) if secret else current}，回车保留）" if current else ""
    if secret:
        val = getpass.getpass(f"{label}{hint}: ")
    else:
        val = input(f"{label}{hint}: ").strip()
    return val or current


# ── 子命令 ────────────────────────────────────────────────────────────

def cmd_init(args):
    cfg = load_config()
    print("== 个人配置向导 ==  （密钥仅写入本机配置文件，不进命令行历史）\n")

    # 1) 睿锋平台
    print("— 睿锋平台 —")
    env = _current_env(cfg) or "prod"
    sel = input(f"环境 [{'/'.join(KNOWN_ENVS)}]（当前 {env}，回车保留）: ").strip()
    if sel:
        if sel not in KNOWN_ENVS:
            sys.exit(f"未知环境: {sel}")
        env = sel
    cfg["current_env"] = env
    ec = _env_cfg(cfg, env)
    default_base = resolve_base_url(cfg, env)
    base = _prompt_keep(f"base_url", ec.get("base_url") or default_base)
    if base:
        ec["base_url"] = base
    ec["mobile"] = _prompt_keep("睿锋登录手机号", ec.get("mobile"))
    pwd = _prompt_keep("睿锋登录密码", ec.get("password"), secret=True)
    if pwd:
        ec["password"] = pwd

    # 2) 17vin（网页登录凭据，供浏览器 CDP 使用）
    print("\n— 17vin 网页登录 —")
    v = cfg.setdefault("vin17", {})
    user = _prompt_keep("17vin 用户名", v.get("username"))
    if user:
        v["username"] = user
    vpwd = _prompt_keep("17vin 密码", v.get("password"), secret=True)
    if vpwd:
        v["password"] = vpwd

    # 3) qwen-vision
    print("\n— qwen-vision（SiliconFlow）—")
    key = _prompt_keep("SiliconFlow API Key (sk-...)", cfg.get(SILICONFLOW_KEY), secret=True)
    if key:
        cfg[SILICONFLOW_KEY] = key

    save_config(cfg)
    print(f"\n✅ 已写入 {CONFIG_FILE}（权限 0o600）。可用 `show` 查看状态。")


def cmd_show(args):
    cfg = load_config()
    cur = _current_env(cfg)
    print(f"个人配置文件: {CONFIG_FILE}")
    print(f"当前环境: {cur or '(未设置)'}")
    for env in KNOWN_ENVS:
        ec = _env_cfg(cfg, env)
        mark = "*" if env == cur else " "
        print(f" {mark} 睿锋[{env}] base_url={resolve_base_url(cfg, env) or '(无)'} "
              f"手机号={ec.get('mobile') or '(未设置)'} 密码={_mask(ec.get('password'))} "
              f"token={'有' if ec.get('token') else '无'}")
    v = cfg.get("vin17", {}) if isinstance(cfg.get("vin17"), dict) else {}
    print(f"   17vin（网页登录）用户名={v.get('username') or '(未设置)'} "
          f"密码={_mask(v.get('password'))}")
    print(f"   qwen-vision SiliconFlow Key={_mask(get_siliconflow_key(cfg))}")


_FEATURE_LABELS = {
    "ruifeng": "睿锋登录（手机号 + 密码）",
    "vin17": "17vin 网页登录（用户名 + 密码）",
    "qwen": "qwen-vision（SiliconFlow API Key）",
}


def feature_status(cfg) -> dict:
    """各功能凭据是否就绪：ruifeng / vin17 / qwen。"""
    env = _current_env(cfg)
    ec = cfg.get("environments", {}).get(env, {}) if env else {}
    v = cfg.get("vin17", {}) if isinstance(cfg.get("vin17"), dict) else {}
    return {
        # 睿锋：有手机号 + (密码或已存 token) 即可发起查询
        "ruifeng": bool(ec.get("mobile") and (ec.get("password") or ec.get("token"))),
        "vin17": bool(v.get("username") and v.get("password")),
        "qwen": bool(get_siliconflow_key(cfg)),
    }


def cmd_check(args):
    cfg = load_config()
    st = feature_status(cfg)
    want = list(_FEATURE_LABELS) if args.feature == "all" else [args.feature]
    for k in want:
        print(f"  [{'✓' if st[k] else '✗'}] {_FEATURE_LABELS[k]}")
    missing = [_FEATURE_LABELS[k] for k in want if not st[k]]
    if missing:
        print()
        print(first_run_hint("、".join(missing)))
        sys.exit(2)  # 首次运行 / 缺项：非零退出，便于调用方判断
    print("\n✅ 所需个人配置已就绪")


# get/set 支持的扁平键 → 配置中的实际位置
_FLAT_KEYS = {
    "siliconflow_api_key": ("root", SILICONFLOW_KEY),
    "vin17_username": ("vin17", "username"),
    "vin17_password": ("vin17", "password"),
    "ruifeng_mobile": ("env", "mobile"),
    "ruifeng_password": ("env", "password"),
    "ruifeng_base_url": ("env", "base_url"),
}


def _resolve_slot(cfg, key, create=False):
    if key not in _FLAT_KEYS:
        sys.exit(f"未知键: {key}，可用: {', '.join(_FLAT_KEYS)}")
    scope, name = _FLAT_KEYS[key]
    if scope == "root":
        return cfg, name
    if scope == "vin17":
        return (cfg.setdefault("vin17", {}) if create else cfg.get("vin17", {})), name
    # env
    env = _current_env(cfg)
    if not env:
        sys.exit("未设置当前环境，请先 `init`")
    return (_env_cfg(cfg, env) if create else cfg.get("environments", {}).get(env, {})), name


def cmd_get(args):
    cfg = load_config()
    # siliconflow 走带环境变量回退的取值，便于 shell 注入
    if args.key == "siliconflow_api_key":
        val = get_siliconflow_key(cfg)
    else:
        slot, name = _resolve_slot(cfg, args.key)
        val = (slot or {}).get(name)
    if not val:
        sys.exit(1)  # 无值：非零退出，便于 shell 判断
    sys.stdout.write(val)


def cmd_set(args):
    cfg = load_config()
    slot, name = _resolve_slot(cfg, args.key, create=True)
    slot[name] = args.value
    save_config(cfg)
    print(f"已设置 {args.key}")


def build_parser():
    p = argparse.ArgumentParser(description="个人配置统管（睿锋 / 17vin / qwen-vision 一处录入）")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="交互式录入所有个人凭据")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("show", help="查看配置状态（打码）")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("check", help="首次运行检测：凭据是否就绪（缺项退出码 2）")
    s.add_argument("--feature", choices=["all", *_FEATURE_LABELS], default="all",
                   help="只检测某项功能（默认 all）")
    s.set_defaults(func=cmd_check)

    s = sub.add_parser("get", help="输出单个值到 stdout（供 shell 注入）")
    s.add_argument("key", choices=list(_FLAT_KEYS))
    s.set_defaults(func=cmd_get)

    s = sub.add_parser("set", help="非交互设置单个值")
    s.add_argument("key", choices=list(_FLAT_KEYS))
    s.add_argument("value")
    s.set_defaults(func=cmd_set)

    return p


def main():
    args = build_parser().parse_args()
    try:
        args.func(args)
    except RuntimeError as exc:
        sys.exit(str(exc))


if __name__ == "__main__":
    main()
