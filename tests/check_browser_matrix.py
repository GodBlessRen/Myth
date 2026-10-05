"""真实 Chromium 的双主题/五视口/十二状态验收；截图不替代 Runtime 或模型质量证据。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    """仅在独立测试服务操作 UI；每个状态单独页面，避免偏好和抽屉状态串扰。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root / ".work/browser-fixture.json").read_text(encoding="utf-8"))
    base, ids = fixture["base"], fixture["ids"]
    output = root / ".work/browser-evidence"
    output.mkdir(exist_ok=True)
    report = {"boundary": fixture["boundary"], "baseline": args.baseline, "cases": [], "errors": []}
    scenarios = [
        ("home", "http://127.0.0.1:8773/#chat", None),
        ("chat", base + "/#chat/" + ids["completed"], None),
        ("execution", base + "/#chat/" + ids["completed"], "execution"),
        ("waiting", base + "/#chat/" + ids["waiting"], None),
        ("recovery", base + "/#chat/" + ids["unknown"], "execution"),
        ("settings", base + "/#settings", None),
        ("model-pool", base + "/#settings", "pool"),
        ("statistics", base + "/#chat/" + ids["completed"], "overview"),
        ("empty", "http://127.0.0.1:8773/#projects", None),
        ("error", base + "/#chat/" + ids["failed"], None),
        ("focus", base + "/#chat/" + ids["completed"], "focus"),
        ("drawer", base + "/#chat/" + ids["interrupted"], "resources"),
    ]
    widths = [1440] if args.baseline else [1440, 1280, 1024, 768, 390]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width in widths:
                for mode in ("light", "dark"):
                    for name, url, action in scenarios:
                        context = browser.new_context(viewport={"width": width, "height": 960 if width >= 1024 else 844}, color_scheme=mode)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        entry = {"state": name, "width": width, "theme": mode}
                        try:
                            page.goto(url, wait_until="networkidle")
                            page.evaluate("document.fonts.ready")
                            page.wait_for_timeout(400)
                            if action in ("overview", "execution", "resources"):
                                if width <= 1120:
                                    page.locator("#inspectorToggle").click()
                                page.locator('[data-inspector-lens="' + action + '"]').click()
                            elif action == "focus" and width > 1120:
                                page.locator("#focusMode").click()
                            elif action == "pool":
                                page.locator("#poolAdd").click()
                                page.locator("#poolChildren").scroll_into_view_if_needed()
                            page.wait_for_timeout(300)
                            filename = f"{width}-{mode}-{name}.png"
                            page.screenshot(path=str(output / filename), full_page=True)
                            entry.update(page.evaluate("""() => ({
                              scrollWidth:document.documentElement.scrollWidth,
                              viewport:innerWidth,
                              background:getComputedStyle(document.body).backgroundColor,
                              fonts:[...document.fonts].map(f=>({family:f.family,status:f.status})),
                              imageFailures:[...document.images].filter(i=>!i.complete || !i.naturalWidth).map(i=>i.getAttribute('src')),
                              bodyFont:getComputedStyle(document.body).fontSize,
                              textWeight:getComputedStyle(document.querySelector('.message-content') || document.body).fontWeight
                            })"""))
                            entry["screenshot"] = filename
                            assert entry["scrollWidth"] <= width + 1, "horizontal overflow"
                            assert not entry["imageFailures"], "broken local image"
                            assert not errors, str(errors)
                            if not args.baseline:
                                assert entry["background"] == ("rgb(255, 254, 248)" if mode == "light" else "rgb(14, 16, 15)"), "theme contract"
                            entry["status"] = "PASS"
                        except Exception as exc:
                            entry["status"] = "FAIL"
                            entry["error"] = str(exc)
                            report["errors"].append({"case": f"{width}/{mode}/{name}", "error": str(exc)})
                            page.screenshot(path=str(output / f"failure-{width}-{mode}-{name}.png"))
                        finally:
                            report["cases"].append(entry)
                            context.close()
        finally:
            browser.close()
            (output / "matrix.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(report["cases"]), "failures": len(report["errors"])}))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
