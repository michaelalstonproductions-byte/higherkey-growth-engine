#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.marketing_intelligence import write_json
from growth_engine.operator_autopilot import POLICY_PATH, load_autopilot_policy, validate_autopilot_command
from growth_engine.index import utc_now


def _subprocess_shell_usage(path: Path) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception as error:
        return [{"path": str(path), "error": str(error)}]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name not in {"run", "Popen", "call", "check_call", "check_output"}:
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                findings.append({"path": str(path), "line": node.lineno, "issue": "shell_true"})
    return findings


def main() -> int:
    root = Path.cwd().resolve()
    policy_path = root / POLICY_PATH
    policy = load_autopilot_policy(root)
    checks: list[dict[str, object]] = []

    def check(name: str, ok: bool, **extra: object) -> None:
        checks.append({"name": name, "status": "pass" if ok else "fail", **extra})

    check("policy_exists", policy_path.exists(), path=POLICY_PATH)
    check("local_only", policy.get("local_only") is True)
    check("manual_upload_only", policy.get("manual_upload_only") is True)
    check("cloud_disabled", policy.get("cloud_apis_allowed") is False)
    check("social_posting_disabled", policy.get("social_posting_allowed") is False)
    check("destructive_disabled", policy.get("destructive_actions_allowed") is False)
    check("original_media_delete_disabled", policy.get("original_media_delete_allowed") is False)
    check("arbitrary_shell_disabled", policy.get("allow_arbitrary_shell") is False)

    safe_scripts = [script for script in policy.get("safe_auto_commands", []) if isinstance(script, str)]
    approval_scripts = [script for script in policy.get("approval_required_commands", []) if isinstance(script, str)]
    for script in safe_scripts:
        validation = validate_autopilot_command(root, ["python3", script], safety_level="safe_auto")
        check(f"safe_auto:{script}", bool(validation.get("ok")), reason=validation.get("reason"))
    for script in approval_scripts:
        validation = validate_autopilot_command(root, ["python3", script], safety_level="approval_required")
        check(f"approval_required:{script}", bool(validation.get("ok")), reason=validation.get("reason"))

    shell_findings = _subprocess_shell_usage(root / "growth_engine" / "operator_autopilot.py") + _subprocess_shell_usage(root / "scripts" / "run_operator_autopilot.py")
    check("no_shell_true_in_autopilot", not shell_findings, findings=shell_findings)

    protected = []
    for rel in policy.get("protected_paths", []):
        p = (root / str(rel)).resolve()
        try:
            p.relative_to(root)
            protected.append({"path": str(rel), "inside_project": True, "exists": p.exists()})
        except ValueError:
            protected.append({"path": str(rel), "inside_project": False, "exists": p.exists()})
    check("protected_original_paths", all(item["inside_project"] for item in protected), protected_paths=protected)

    receipt_source = (root / "growth_engine" / "operator_autopilot.py").read_text(encoding="utf-8")
    check("approval_receipt_handling", "autopilot_approval_receipts.json" in receipt_source and "approve_action" in receipt_source)

    status = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    report = {
        "version": 1,
        "updated_at": utc_now(),
        "status": status,
        "local_only": True,
        "manual_upload_only": True,
        "cloud_apis_allowed": False,
        "social_posting_allowed": False,
        "original_media_delete_allowed": False,
        "checks": checks,
    }
    out = root / "analytics" / "autopilot_safety_report.json"
    write_json(out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
