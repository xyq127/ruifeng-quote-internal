#!/usr/bin/env python3
"""泰安联 OE 搜索脚本（已优化等待时间）.

实测数据（已登录 CDP）:
  - 导航 domcontentloaded: ~1s
  - 内容就绪: 0.5s 即可获取完整结果
  - 等待 1s 保证稳定性

用法:
  python scripts/tecalliance_fast_oe_search.py --query 45840045
  python scripts/tecalliance_fast_oe_search.py --query MR594979 --json
"""

import sys
import json
import os
import argparse
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cli-platform-service'))

TAIANLIAN_SEARCH_URL = (
    "https://www.tecalliance.cn/cn/search/1?"
    "q={query}&numbersearchinput=1&searchtype=0&status=1"
)


def search(query: str, cdp_port: int = 9250, timeout: float = 10.0):
    """泰安联搜索（已优化等待）.

    Returns:
        list of dict: [{"brand": ..., "oes": [...]}, ...]
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"error": "playwright_not_installed",
                "message": "请先安装: pip install playwright && playwright install chromium"}

    search_url = TAIANLIAN_SEARCH_URL.format(query=query)

    with sync_playwright() as p:
        cdp_url = f"http://127.0.0.1:{cdp_port}"

        # 优先连接已有 CDP
        try:
            import urllib.request
            req = urllib.request.Request(f"{cdp_url}/json/version")
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    browser = p.chromium.connect_over_cdp(cdp_url)
                    context = browser.contexts[0]
                    page = context.new_page()
                else:
                    raise Exception("CDP not ready")
        except Exception:
            # 自启动 Chrome
            user_data_dir = os.path.join(
                os.path.expanduser("~"), ".claude", "browser-data", "ruifeng-chrome"
            )
            os.makedirs(user_data_dir, exist_ok=True)
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=True,
                args=[f"--remote-debugging-port={cdp_port}", "--remote-allow-origins=*", "--no-sandbox"],
                locale="zh-CN",
            )
            page = context.new_page()

        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
            # 实测 0.5s 即有内容，1s 保证稳定
            page.wait_for_timeout(1000)
            text = page.inner_text("body")
            return _parse_results(text)
        finally:
            page.close()


def _parse_results(text: str) -> list:
    """解析泰安联搜索结果页面文本."""
    if "搜索结果 0" in text or "总共 0" in text:
        return []

    results = []
    blocks = text.split("\n\n")
    current = {}

    for block in blocks:
        line = block.strip()
        if not line:
            continue
        if line.isupper() and len(line) > 2 and line not in ("ZH",):
            if current.get("brand"):
                results.append(current)
            current = {"brand": line, "oes": [], "source": "tecalliance"}
            continue
        oe_match = re.search(r"\b\d{6,15}\b", line)
        if oe_match and current:
            oe = oe_match.group()
            if oe not in current["oes"]:
                current["oes"].append(oe)

    if current.get("brand"):
        results.append(current)

    return results


# ── CLI ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="泰安联 OE 搜索（优化版，~2s）")
    parser.add_argument("--query", "-q", required=True, help="搜索关键词 (DAC编码/OE号/尺寸)")
    parser.add_argument("--cdp-port", type=int, default=9250, help="CDP 端口 (默认 9250)")
    parser.add_argument("--json", action="store_true", help="纯 JSON 输出")
    parser.add_argument("--timeout", type=float, default=10.0, help="超时秒数")
    args = parser.parse_args()

    query = args.query.strip()
    dims_match = re.match(r'^(\d{1,2})[xX*,\s](\d{1,2})[xX*,\s](\d{1,4})$', query)
    if dims_match:
        d, D, B = int(dims_match.group(1)), int(dims_match.group(2)), int(dims_match.group(3))
        query = f"{d:02d}{D:02d}00{B:02d}"
        if not args.json:
            print(f"尺寸 {d}x{D}x{B} → DAC 编码: {query}", file=sys.stderr)

    if not args.json:
        print(f"正在搜索泰安联: {query} ...", file=sys.stderr)

    result = search(query, cdp_port=args.cdp_port, timeout=args.timeout)

    if isinstance(result, dict) and "error" in result:
        print(json.dumps(result, ensure_ascii=False) if args.json else f"错误: {result['message']}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if not result:
            print("无搜索结果")
        else:
            print(f"\n找到 {len(result)} 条结果:\n")
            for i, r in enumerate(result, 1):
                brand = r.get("brand", "未知品牌")
                oes = ", ".join(r["oes"][:8])
                print(f"  {i}. {brand}")
                print(f"     OE: {oes}")
                if r.get("part_name"):
                    print(f"     名称: {r['part_name']}")
                if r.get("vehicles"):
                    print(f"     车型: {', '.join(r['vehicles'][:5])}")
                print()


if __name__ == "__main__":
    main()
