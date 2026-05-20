#!/usr/bin/env python3
"""Static UI action inventory checks for dashboard/review.html."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard" / "review.html"
REPORT = ROOT / "analytics" / "dashboard_ui_action_report.json"


def unique(pattern: str, text: str) -> list[str]:
    return sorted(set(re.findall(pattern, text)))


def function_body(name: str, text: str) -> str:
    marker = f"function {name}"
    start = text.find(marker)
    if start < 0:
        return ""
    brace = text.find("{", start)
    if brace < 0:
        return ""
    depth = 0
    for index in range(brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1 : index]
    return ""


def object_keys(object_name: str, text: str) -> list[str]:
    match = re.search(rf"\b{re.escape(object_name)}\s*=\s*\{{(?P<body>.*?)\n\s*\}};", text, re.S)
    if not match:
        return []
    return unique(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:", match.group("body"))


def function_names(text: str) -> set[str]:
    names = set(unique(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", text))
    names.update(unique(r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\(", text))
    names.update(unique(r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?[A-Za-z_$][A-Za-z0-9_$]*\s*=>", text))
    return names


def main() -> int:
    html = DASHBOARD.read_text(encoding="utf-8")
    failures: list[str] = []
    warnings: list[str] = []

    desktop_actions = unique(r'data-desktop-action="([^"]+)"', html)
    wire_body = function_body("wireDesktopActions", html)
    handled_actions = set(unique(r'action\s*===\s*"([^"]+)"', wire_body))
    handled_actions.update(unique(r'!\[\s*"([^"]+)"', wire_body))
    handled_actions.update(unique(r'",\s*"([^"]+)"', re.search(r"!\[(.*?)\]\.includes\(action\)", wire_body, re.S).group(1) if re.search(r"!\[(.*?)\]\.includes\(action\)", wire_body, re.S) else ""))
    unhandled_actions = sorted(set(desktop_actions) - handled_actions)
    if unhandled_actions:
        failures.append(f"Unhandled data-desktop-action values: {', '.join(unhandled_actions)}")

    duplicate_actions = sorted(action for action in set(desktop_actions) if desktop_actions.count(action) > 1)
    stale_action_names = sorted(action for action in desktop_actions if action.endswith("-old") or action.startswith("old-"))
    if stale_action_names:
        failures.append(f"Stale action names found: {', '.join(stale_action_names)}")

    modes = unique(r'data-mode="([^"]+)"', html)
    views_keys = object_keys("views", html)
    view_set = set(views_keys)
    missing_modes = sorted(set(modes) - view_set)
    if missing_modes:
        failures.append(f"Modes without render view mapping: {', '.join(missing_modes)}")

    required_render_functions = {
        "command": "renderCommandView",
        "autopilot": "renderAutopilotView",
        "dashboard": "renderDashboardView",
        "queue": "renderQueueView",
        "media": "renderMediaView",
        "search": "renderIntelligenceView",
        "marketing": "renderMarketingView",
        "agents": "renderAgentsView",
        "analytics": "renderAnalyticsView",
        "social": "renderSocialExportsView",
        "diagnostics": "renderDiagnosticsView",
        "settings": "renderSettingsView",
    }
    funcs = function_names(html)
    missing_render_functions = sorted(name for mode, name in required_render_functions.items() if mode in modes and name not in funcs)
    if missing_render_functions:
        failures.append(f"Missing render functions: {', '.join(missing_render_functions)}")

    marketing_body = function_body("renderMarketingView", html)
    marketing_views = []
    marketing_array = re.search(r"\[\s*\[\"campaign\".*?\]\.map\(\(\[mode,\s*label\]\)", marketing_body, re.S)
    if marketing_array:
        marketing_views = unique(r'\["([^"]+)",\s*"[^"]+"\]', marketing_array.group(0))
    missing_marketing_logic = sorted(view for view in set(marketing_views) if view not in marketing_body)
    if missing_marketing_logic:
        failures.append(f"Marketing view tabs without render logic: {', '.join(missing_marketing_logic)}")
    if "wireMarketingViewActions" not in funcs:
        failures.append("wireMarketingViewActions missing")

    autopilot_body = function_body("renderAutopilotView", html)
    autopilot_views = unique(r'\["(overview|console|approvals|safety|history)",\s*"[^"]+"\]', autopilot_body)
    missing_autopilot_logic = sorted(view for view in set(autopilot_views) if view not in autopilot_body)
    if missing_autopilot_logic:
        failures.append(f"Autopilot view tabs without render logic: {', '.join(missing_autopilot_logic)}")
    if "wireAutopilotViewActions" not in funcs:
        failures.append("wireAutopilotViewActions missing")

    path_keys = set(object_keys("PATHS", html))
    path_refs = set(unique(r"PATHS\.([A-Za-z_][A-Za-z0-9_]*)", html))
    missing_path_defs = sorted(path_refs - path_keys)
    if missing_path_defs:
        failures.append(f"PATHS references without definition: {', '.join(missing_path_defs)}")
    loaded_path_refs = set(unique(r"optionalJson\(PATHS\.([A-Za-z_][A-Za-z0-9_]*)", html))
    bridge_loaded = {"trialReadiness", "localApiStatus"}
    not_loaded = sorted(key for key in path_keys if key not in loaded_path_refs and key not in bridge_loaded and key != "index")
    if not_loaded:
        warnings.append(f"PATHS keys not directly loaded through optionalJson: {', '.join(not_loaded)}")

    common_symbols = [
        "pipelineDisplay",
        "renderCommandView",
        "renderAutopilotView",
        "wireAutopilotViewActions",
        "wireMarketingViewActions",
        "openSocialExports",
        "buildProductionCommand",
        "buildAutopilotConsole",
        "retryAutopilotFailedDryRun",
    ]
    symbol_status = {}
    for symbol in common_symbols:
        referenced = bool(re.search(rf"\b{re.escape(symbol)}\b", html))
        defined = symbol in funcs
        symbol_status[symbol] = {"referenced": referenced, "defined": defined}
        if referenced and not defined and symbol not in {"openSocialExports"}:
            failures.append(f"Referenced top-level symbol is not defined: {symbol}")
        if symbol == "openSocialExports" and referenced and not defined and "window.higherkey.openSocialExports" not in html:
            failures.append("openSocialExports referenced without function or bridge handler")

    report = {
        "status": "fail" if failures else "pass",
        "dashboard": str(DASHBOARD.relative_to(ROOT)),
        "desktop_actions": desktop_actions,
        "handled_actions": sorted(handled_actions),
        "duplicate_action_values": duplicate_actions,
        "modes": modes,
        "view_mappings": views_keys,
        "marketing_views": sorted(set(marketing_views)),
        "autopilot_views": sorted(set(autopilot_views)),
        "path_keys": sorted(path_keys),
        "path_refs": sorted(path_refs),
        "symbol_status": symbol_status,
        "failures": failures,
        "warnings": warnings,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": failures, "warnings": warnings, "report": str(REPORT)}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
