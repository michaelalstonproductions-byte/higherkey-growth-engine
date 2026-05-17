#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from growth_engine.analytics import save_json
from growth_engine.config import load_config
from growth_engine.diagnostics import command_result, run_diagnostics, summarize_report
from growth_engine.index import relative_path, utc_now


EXCLUDED_DIRS = {"node_modules", "dist", ".git", "__pycache__", "analytics", "out", "clips", "captions", "queue", "content_inbox", "logs"}
SCAN_PATTERN = re.compile(r"https?://|fetch\(|axios|openai|api\.|graph\.facebook|instagram|tiktok|youtube|twitter|x\.com|cloud|social", re.IGNORECASE)


def dashboard_js_check(root: Path) -> dict[str, object]:
    script = (
        "const fs=require('fs');"
        "const html=fs.readFileSync('dashboard/review.html','utf8');"
        "const scripts=[...html.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)].map(m=>m[1]);"
        "for (const script of scripts) new Function(script);"
        "console.log(JSON.stringify({scripts:scripts.length}));"
    )
    return command_result("dashboard_js_syntax", ["node", "-e", script], root, timeout=30)


def packaged_path_check(root: Path) -> dict[str, object]:
    resources = root / "dist" / "mac-arm64" / "HigherKey Operator OS.app" / "Contents" / "Resources"
    if not resources.exists():
        return {"name": "packaged_path_verification", "status": "warn", "message": "dist:dir output not found"}
    required = [
        resources / "app.asar",
        resources / "app-assets" / "dashboard" / "review.html",
        resources / "app-assets" / "growth_engine" / "diagnostics.py",
        resources / "app-assets" / "growth_engine" / "media_cache.py",
        resources / "app-assets" / "scripts" / "run_full_qa.py",
        resources / "app-assets" / "scripts" / "build_media_cache.py",
    ]
    forbidden = [resources / "app-assets" / name for name in ("analytics", "queue", "clips", "captions", "out", "logs", "content_inbox")]
    missing = [relative_path(path, root) for path in required if not path.exists()]
    present_forbidden = [relative_path(path, root) for path in forbidden if path.exists()]
    status = "pass" if not missing and not present_forbidden else "fail"
    return {
        "name": "packaged_path_verification",
        "status": status,
        "missing": missing,
        "forbidden_runtime_dirs": present_forbidden,
    }


def external_api_scan(root: Path) -> dict[str, object]:
    hits = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name == "package-lock.json":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if SCAN_PATTERN.search(line):
                hits.append({"path": relative_path(path, root), "line": line_no, "text": line.strip()[:220]})
    risky = [
        hit
        for hit in hits
        if not (
            "README.md" in hit["path"]
            or "CLIENT_HANDOFF_GUIDE.md" in hit["path"]
            or "CLIENT_QUICK_START.md" in hit["path"]
            or "BETA_READINESS_CHECKLIST.md" in hit["path"]
            or "TRIAL_LIMITATIONS.md" in hit["path"]
            or "TRIAL_DELIVERY_CHECKLIST.md" in hit["path"]
            or "CLIENT_TRIAL_QA_SUMMARY.md" in hit["path"]
            or "scripts/run_full_qa.py" in hit["path"]
            or "scripts/package_client_handoff.py" in hit["path"]
            or "scripts/package_trial_release.py" in hit["path"]
            or "scripts/validate_trial_package.py" in hit["path"]
            or "scripts/build_trial_readiness_report.py" in hit["path"]
            or "scripts/run_client_trial_qa.py" in hit["path"]
            or "scripts/check_client_language.py" in hit["path"]
            or "scripts/build_marketing_plan.py" in hit["path"]
            or "scripts/import_instagram_insights.py" in hit["path"]
            or "scripts/collect_client_feedback.py" in hit["path"]
            or "scripts/create_issue_report.py" in hit["path"]
            or ("dashboard/review.html" in hit["path"] and "renderMarketingView" in hit["text"])
            or ("dashboard/review.html" in hit["path"] and "renderSocialExportsView" in hit["text"])
            or "growth_engine/marketing_intelligence.py" in hit["path"]
            or "growth_engine/local_api.py" in hit["path"]
            or "growth_engine/observability.py" in hit["path"]
            or "growth_engine/security.py" in hit["path"]
            or "growth_engine/cache_manager.py" in hit["path"]
            or "scripts/run_security_check.py" in hit["path"]
            or "scripts/manage_storage.py" in hit["path"]
            or "config/security_policy.json" in hit["path"]
            or "config/retention_policy.json" in hit["path"]
            or "config/marketing_profile.example.json" in hit["path"]
            or "config/social_connectors.example.json" in hit["path"]
            or "scripts/run_local_api.py" in hit["path"]
            or "run_local_api.py" in hit["text"]
            or "local api" in hit["text"].lower()
            or "No cloud" in hit["text"]
            or "no cloud" in hit["text"]
            or "localhost" in hit["text"]
            or "127.0.0.1" in hit["text"]
            or "fetch(`${path}" in hit["text"]
            or "w3.org" in hit["text"]
            or "platform_notes" in hit["text"]
            or "manual upload" in hit["text"].lower()
            or "posting integration" in hit["text"].lower()
            or "social export" in hit["text"].lower()
            or "social_export" in hit["text"].lower()
            or ("social" in hit["text"].lower() and "api" not in hit["text"].lower())
            or "instagram" in hit["text"].lower()
            or "tiktok" in hit["text"].lower()
            or "youtube" in hit["text"].lower()
            or "youtube_shorts" in hit["text"].lower()
        )
    ]
    return {"name": "external_api_scan", "status": "pass" if not risky else "fail", "hits": hits, "risky_hits": risky}


def event_log_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path; "
        "from growth_engine.config import load_config; "
        "from growth_engine.events import append_event; "
        "config=load_config(Path('.')); "
        "event=append_event(config, 'qa.completed', severity='info', source='run_full_qa', summary={'check':'event_log'}); "
        "print(event['event_id'])"
    )
    return command_result("event_log_write", ["python3", "-c", script], root, timeout=30)


def runtime_lock_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path\n"
        "from growth_engine.config import load_config\n"
        "from growth_engine.runtime_lock import acquire_lock, release_lock\n"
        "config=load_config(Path('.'))\n"
        "acquire_lock(config, 'qa_runtime_lock', force=True)\n"
        "blocked=False\n"
        "try:\n"
        "    acquire_lock(config, 'qa_runtime_lock_second')\n"
        "except RuntimeError:\n"
        "    blocked=True\n"
        "finally:\n"
        "    release_lock(config)\n"
        "assert blocked\n"
        "print('runtime lock ok')\n"
    )
    return command_result("runtime_lock_test", ["python3", "-c", script], root, timeout=30)


def task_queue_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path\n"
        "from growth_engine.config import load_config\n"
        "from growth_engine.task_queue import enqueue_task, cancel_task, retry_task, add_dependency, dependencies_satisfied, complete_task, claim_next_task, task_summary\n"
        "config=load_config(Path('.'))\n"
        "parent=enqueue_task(config, 'build_runtime_snapshot', {'qa':'parent'}, source='qa')\n"
        "child=enqueue_task(config, 'build_runtime_snapshot', {'qa':'child'}, source='qa')\n"
        "add_dependency(config, child['task_id'], parent['task_id'])\n"
        "assert dependencies_satisfied(config, child['task_id']) is False\n"
        "claimed=claim_next_task(config)\n"
        "assert claimed and claimed['task_id'] == parent['task_id']\n"
        "complete_task(config, parent['task_id'], {'qa':'complete'})\n"
        "assert dependencies_satisfied(config, child['task_id']) is True\n"
        "cancelled=cancel_task(config, child['task_id'], 'qa cancellation test')\n"
        "retry=retry_task(config, child['task_id'])\n"
        "assert cancelled and retry\n"
        "cancel_task(config, child['task_id'], 'qa cleanup')\n"
        "summary=task_summary(config)\n"
        "print(summary['total'])\n"
    )
    return command_result("task_queue_validation", ["python3", "-c", script], root, timeout=30)


def worker_runtime_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path\n"
        "from growth_engine.config import load_config\n"
        "from growth_engine.worker_runtime import write_status, cleanup_stale, request_pause, request_resume, health, stop_session\n"
        "config=load_config(Path('.'))\n"
        "write_status(config, 'running', pid=999999, heartbeat_at='2000-01-01T00:00:00+00:00')\n"
        "stale=cleanup_stale(config)\n"
        "assert stale['state'] == 'stale'\n"
        "paused=request_pause(config)\n"
        "assert paused['pause_requested'] is True\n"
        "resumed=request_resume(config)\n"
        "assert resumed['pause_requested'] is False\n"
        "status=health(config)\n"
        "stop_session(config, reason='qa cleanup')\n"
        "print(status['state'])\n"
    )
    return command_result("worker_runtime_validation", ["python3", "-c", script], root, timeout=30)


def audit_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path\n"
        "from growth_engine.config import load_config\n"
        "from growth_engine.audit import write_audit_event, read_recent_audit_events, audit_summary\n"
        "config=load_config(Path('.'))\n"
        "event=write_audit_event(config, 'qa.run', source='run_full_qa', summary={'fixture': True})\n"
        "events=read_recent_audit_events(config, limit=5)\n"
        "summary=audit_summary(config)\n"
        "assert any(item['audit_id'] == event['audit_id'] for item in events)\n"
        "print(summary['recent_count'])\n"
    )
    return command_result("audit_event_fixture", ["python3", "-c", script], root, timeout=30)


def error_taxonomy_check(root: Path) -> dict[str, object]:
    path = root / "config" / "error_taxonomy.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        required = {"media_missing", "task_failed", "worker_stale", "api_offline", "unknown"}
        missing = sorted(required - set(payload))
        return {"name": "error_taxonomy_load", "status": "pass" if not missing else "fail", "missing": missing, "categories": len(payload)}
    except Exception as error:
        return {"name": "error_taxonomy_load", "status": "fail", "message": str(error)}


def state_contract_check(root: Path) -> dict[str, object]:
    path = root / "config" / "state_contract.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        required = {"db_tables", "required_folders", "required_runtime_files", "client_facing_files"}
        missing = sorted(required - set(payload))
        return {"name": "state_contract_load", "status": "pass" if not missing else "fail", "missing": missing, "version": payload.get("version")}
    except Exception as error:
        return {"name": "state_contract_load", "status": "fail", "message": str(error)}


def retention_policy_check(root: Path) -> dict[str, object]:
    path = root / "config" / "retention_policy.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rules = payload.get("rules", {})
        required = {"source_footage", "runtime_database", "media_cache", "qa_reports"}
        missing = sorted(required - set(rules))
        protected = rules.get("source_footage", {}).get("protected") is True and rules.get("source_footage", {}).get("delete_allowed") is False
        return {"name": "retention_policy_load", "status": "pass" if not missing and protected else "fail", "missing": missing, "source_footage_protected": protected}
    except Exception as error:
        return {"name": "retention_policy_load", "status": "fail", "message": str(error)}


def version_contract_check(root: Path) -> dict[str, object]:
    path = root / "config" / "version_contract.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        required = {"app_version", "schema_version", "required_db_tables", "required_config_files", "required_scripts"}
        missing = sorted(required - set(payload))
        return {"name": "version_contract_load", "status": "pass" if not missing else "fail", "missing": missing, "version": payload.get("app_version")}
    except Exception as error:
        return {"name": "version_contract_load", "status": "fail", "message": str(error)}


def client_workflow_check(root: Path) -> dict[str, object]:
    path = root / "analytics" / "client_workflow.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        required = {"current_step", "steps", "completed_steps", "next_action", "client_message", "warnings_summary", "last_updated", "demo_checklist"}
        missing = sorted(required - set(payload))
        step_ids = {step.get("id") for step in payload.get("steps", []) if isinstance(step, dict)}
        expected = {"import_footage", "process_media", "review_clips", "approve_clips", "export_social_packs", "upload_manually"}
        missing_steps = sorted(expected - step_ids)
        checklist_ok = isinstance(payload.get("demo_checklist"), list) and len(payload.get("demo_checklist", [])) >= 5
        status = "pass" if not missing and not missing_steps and checklist_ok else "fail"
        return {"name": "client_workflow_validation", "status": status, "missing": missing, "missing_steps": missing_steps, "checklist_ok": checklist_ok, "current_step": payload.get("current_step")}
    except Exception as error:
        return {"name": "client_workflow_validation", "status": "fail", "message": str(error)}


def client_handoff_check(root: Path) -> dict[str, object]:
    required = [
        root / "CLIENT_HANDOFF_GUIDE.md",
        root / "BETA_READINESS_CHECKLIST.md",
        root / "scripts" / "create_demo_project.py",
        root / "scripts" / "package_client_handoff.py",
        root / "scripts" / "collect_client_feedback.py",
        root / "scripts" / "create_issue_report.py",
        root / "config" / "client_demo.json",
    ]
    missing = [relative_path(path, root) for path in required if not path.exists()]
    try:
        demo_config = json.loads((root / "config" / "client_demo.json").read_text(encoding="utf-8"))
    except Exception as error:
        return {"name": "client_handoff_validation", "status": "fail", "message": str(error), "missing": missing}
    flags_ok = bool(demo_config.get("demo_mode_enabled")) and bool(demo_config.get("show_simplified_workflow"))
    status = "pass" if not missing and flags_ok else "fail"
    return {"name": "client_handoff_validation", "status": status, "missing": missing, "flags_ok": flags_ok}


def trial_package_check(root: Path) -> dict[str, object]:
    required = [
        root / "CLIENT_QUICK_START.md",
        root / "TRIAL_LIMITATIONS.md",
        root / "TRIAL_DELIVERY_CHECKLIST.md",
        root / "CLIENT_TRIAL_QA_SUMMARY.md",
        root / "scripts" / "package_trial_release.py",
        root / "scripts" / "validate_trial_package.py",
        root / "scripts" / "build_trial_readiness_report.py",
        root / "scripts" / "run_client_trial_qa.py",
        root / "scripts" / "check_client_language.py",
    ]
    missing = [relative_path(path, root) for path in required if not path.exists()]
    try:
        quick_start = (root / "CLIENT_QUICK_START.md").read_text(encoding="utf-8")
        limitations = (root / "TRIAL_LIMITATIONS.md").read_text(encoding="utf-8")
        package_script = (root / "scripts" / "package_trial_release.py").read_text(encoding="utf-8")
    except Exception as error:
        return {"name": "trial_package_validation", "status": "fail", "message": str(error), "missing": missing}
    required_quick_start = ["Import Footage", "Import & Process", "Review", "Export", "Upload"]
    required_limitations = ["No cloud", "No social", "manual", "MP4", "MOV", "M4V"]
    missing_quick_start = [item for item in required_quick_start if item.lower() not in quick_start.lower()]
    missing_limitations = [item for item in required_limitations if item.lower() not in limitations.lower()]
    script_flags_ok = "--include-dmg" in package_script and "--dry-run" in package_script and "CLIENT_TRIAL_QA_SUMMARY.md" in package_script
    status = "pass" if not missing and not missing_quick_start and not missing_limitations and script_flags_ok else "fail"
    return {
        "name": "trial_package_validation",
        "status": status,
        "missing": missing,
        "missing_quick_start": missing_quick_start,
        "missing_limitations": missing_limitations,
        "script_flags_ok": script_flags_ok,
    }


def marketing_intelligence_check(root: Path) -> dict[str, object]:
    required = [
        root / "config" / "marketing_profile.example.json",
        root / "config" / "social_connectors.example.json",
        root / "analytics" / "marketing_brief.json",
        root / "analytics" / "audience_profile.json",
        root / "analytics" / "market_attack_plan.json",
        root / "analytics" / "content_strategy.json",
        root / "analytics" / "platform_strategy.json",
        root / "analytics" / "campaign_calendar.json",
        root / "analytics" / "marketing_recommendations.json",
        root / "out" / "marketing" / "marketing_brief.md",
        root / "out" / "marketing" / "market_attack_plan.md",
        root / "out" / "marketing" / "content_calendar.md",
        root / "out" / "marketing" / "platform_strategy.md",
        root / "out" / "marketing" / "clip_recommendations.json",
    ]
    missing = [relative_path(path, root) for path in required if not path.exists()]
    token_hits = []
    live_api_hits = []
    for path in required:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        if any(term in lowered for term in ("access_token", "client_secret", "refresh_token")):
            token_hits.append(relative_path(path, root))
        if "live_api_enabled\": true" in lowered:
            live_api_hits.append(relative_path(path, root))
    status = "pass" if not missing and not token_hits and not live_api_hits else "fail"
    return {
        "name": "marketing_intelligence_validation",
        "status": status,
        "missing": missing,
        "token_hits": token_hits,
        "live_api_hits": live_api_hits,
    }


def beta_checklist_check(root: Path) -> dict[str, object]:
    path = root / "BETA_READINESS_CHECKLIST.md"
    try:
        text = path.read_text(encoding="utf-8")
        required = ["install DMG", "Import", "Process", "Review", "Export", "Upload", "Diagnostics", "feedback"]
        missing = [item for item in required if item.lower() not in text.lower()]
        return {"name": "beta_checklist_validation", "status": "pass" if not missing else "fail", "missing": missing}
    except Exception as error:
        return {"name": "beta_checklist_validation", "status": "fail", "message": str(error)}


def upgrade_fixture_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path\n"
        "from tempfile import TemporaryDirectory\n"
        "import shutil\n"
        "from growth_engine.config import ensure_directories, load_config\n"
        "from growth_engine.json_store import save_json_file\n"
        "from growth_engine.migrations import build_upgrade_plan, pre_upgrade_backup_manifest, rollback_plan\n"
        "with TemporaryDirectory() as tmp:\n"
        "    root=Path(tmp)\n"
        "    config=load_config(root)\n"
        "    ensure_directories(config)\n"
        "    for rel in ('version_contract.json','state_contract.json','security_policy.json','retention_policy.json','error_taxonomy.json','release.json','project_manifest.example.json','client_demo.json','marketing_profile.example.json','social_connectors.example.json'):\n"
        "        shutil.copy(Path('config')/rel, root/'config'/rel)\n"
        "    save_json_file(root/'config'/'project_manifest.json', {'version':'V3.8','project_root':str(root),'local_only':True})\n"
        "    plan=build_upgrade_plan(config)\n"
        "    assert plan['status'] in ('pass','warn')\n"
        "    backup=pre_upgrade_backup_manifest(config)\n"
        "    rollback=rollback_plan(config, plan)\n"
        "    assert backup['source_media_preserved'] is True\n"
        "    assert rollback['reversible'] is True\n"
        "print('upgrade fixture ok')\n"
    )
    return command_result("upgrade_plan_fixture", ["python3", "-c", script], root, timeout=60)


def storage_fixture_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path\n"
        "from tempfile import TemporaryDirectory\n"
        "import shutil\n"
        "from growth_engine.config import ensure_directories, load_config\n"
        "from growth_engine.cache_manager import apply_cleanup_plan, archive_generated_artifacts, build_cleanup_plan, measure_storage\n"
        "with TemporaryDirectory() as tmp:\n"
        "    root=Path(tmp)\n"
        "    config=load_config(root)\n"
        "    ensure_directories(config)\n"
        "    (root/'config'/'retention_policy.json').write_text(Path('config/retention_policy.json').read_text(), encoding='utf-8')\n"
        "    (config.inbox_dir/'real.mp4').write_bytes(b'original')\n"
        "    cache=root/'out'/'media_cache'/'clip'/'thumb.jpg'\n"
        "    cache.parent.mkdir(parents=True, exist_ok=True)\n"
        "    cache.write_bytes(b'cache')\n"
        "    report=measure_storage(config)\n"
        "    plan=build_cleanup_plan(config, category='media_cache', dry_run=True)\n"
        "    applied=apply_cleanup_plan(config, confirm=True, category='media_cache', dry_run=False)\n"
        "    assert (config.inbox_dir/'real.mp4').exists()\n"
        "    assert (config.analytics_dir/'archive_manifest.json').exists()\n"
        "print('storage fixture ok')\n"
    )
    return command_result("storage_apply_archive_fixture", ["python3", "-c", script], root, timeout=60)


def security_fixture_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path\n"
        "from growth_engine.config import load_config\n"
        "from growth_engine.security import load_security_policy, validate_project_root, validate_import_file, require_confirmation\n"
        "config=load_config(Path('.'))\n"
        "policy=load_security_policy(config)\n"
        "assert policy['local_only'] is True\n"
        "assert validate_project_root(config, config.inbox_dir)['ok'] is False\n"
        "assert validate_project_root(config, Path('/'))['ok'] is False\n"
        "assert validate_import_file(config, Path('README.md'))['ok'] is False\n"
        "receipt=require_confirmation(config, 'backup_project', confirmed=True, summary='QA security fixture', affected_paths=['out/project_backups'])\n"
        "assert receipt['ok'] is True\n"
        "print('security fixture ok')\n"
    )
    return command_result("security_fixture_validation", ["python3", "-c", script], root, timeout=30)


def reconciliation_fixture_check(root: Path) -> dict[str, object]:
    script = (
        "from pathlib import Path\n"
        "from tempfile import TemporaryDirectory\n"
        "from growth_engine.config import ensure_directories, load_config\n"
        "from growth_engine.json_store import save_json_file\n"
        "from growth_engine.state_reconciler import reconcile_state\n"
        "with TemporaryDirectory() as tmp:\n"
        "    root=Path(tmp)\n"
        "    config=load_config(root)\n"
        "    ensure_directories(config)\n"
        "    (root/'config'/'state_contract.json').write_text((Path('config/state_contract.json')).read_text(), encoding='utf-8')\n"
        "    save_json_file(config.queue_path, {'entries':[{'clip_id':'fixture_clip','clip_path':'clips/missing_fixture.mp4'}]})\n"
        "    (config.analytics_dir/'events.jsonl').write_text('', encoding='utf-8')\n"
        "    result=reconcile_state(config, apply=True, limit=10)\n"
        "    assert result['report']['issue_count'] >= 1\n"
        "    assert (config.analytics_dir/'client_integrity.json').exists()\n"
        "    assert (config.analytics_dir/'quarantine_report.json').exists()\n"
        "print('fixture ok')\n"
    )
    return command_result("reconciliation_apply_fixture", ["python3", "-c", script], root, timeout=60)


def local_api_server_check(root: Path) -> dict[str, object]:
    port = 8876
    process = subprocess.Popen(
        ["python3", "scripts/run_local_api.py", "--port", str(port), "--write-status"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    results: dict[str, object] = {"name": "local_api_endpoint_check", "status": "fail", "endpoints": []}
    try:
        base = f"http://127.0.0.1:{port}"
        last_error = ""
        for _ in range(30):
            if process.poll() is not None:
                break
            try:
                with request.urlopen(f"{base}/health", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("ok") is True:
                    break
            except Exception as error:
                last_error = str(error)
                time.sleep(0.2)
        endpoints = []
        for path in ("/health", "/state/client", "/tasks/summary", "/metrics/client", "/audit/recent", "/health/score", "/state/integrity", "/state/reconciliation", "/security/status", "/storage/report", "/storage/client", "/cleanup/plan", "/upgrade/status", "/upgrade/plan", "/launch/preflight", "/contracts/data"):
            with request.urlopen(f"{base}{path}", timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            endpoints.append({"path": path, "ok": payload.get("ok"), "status": payload.get("status")})
        validate_body = json.dumps({"kind": "project", "path": str(root / "content_inbox")}).encode("utf-8")
        validate_request = request.Request(
            f"{base}/security/validate-path",
            data=validate_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(validate_request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        endpoints.append({"path": "/security/validate-path", "ok": payload.get("ok"), "status": payload.get("status")})
        post_body = json.dumps({"dry_run": True}).encode("utf-8")
        post_request = request.Request(
            f"{base}/tasks/enqueue/full-media-prep",
            data=post_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(post_request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        endpoints.append({"path": "/tasks/enqueue/full-media-prep", "ok": payload.get("ok"), "status": payload.get("status"), "dry_run": True})
        results.update({"status": "pass", "endpoints": endpoints})
        return results
    except Exception as error:
        stdout, stderr = process.communicate(timeout=2) if process.poll() is not None else ("", "")
        message = str(error)
        restricted = "Operation not permitted" in message or ("last_error" in locals() and "Operation not permitted" in last_error)
        results.update({
            "status": "warn" if restricted else "fail",
            "message": "Localhost socket check was blocked by the sandbox." if restricted else message,
            "stdout_tail": stdout[-1000:],
            "stderr_tail": stderr[-1000:],
        })
        if "last_error" in locals():
            results["last_error"] = last_error
        return results
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        try:
            from growth_engine.local_api import write_status

            write_status(load_config(root), {"state": "stopped", "host": "127.0.0.1", "port": port, "reason": "qa endpoint check complete"})
        except Exception:
            pass


def qa_stage(name: str, args: list[str], root: Path, timeout: int = 180) -> dict[str, object]:
    print(f"[qa] {name}", flush=True)
    return command_result(name, args, root, timeout=timeout)


def append_stage(results: list[dict[str, object]], result: dict[str, object], config) -> None:
    results.append(result)
    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "status": summarize_report(results),
        "root": str(config.root),
        "in_progress": True,
        "results": results,
    }
    save_json(config.analytics_dir / "qa_report.json", payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HigherKey full local QA")
    parser.add_argument("--root", default=".", help="Project root. Defaults to current directory.")
    parser.add_argument("--skip-smoke", action="store_true", help="Skip the heavier smoke test.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    config = load_config(root)
    results: list[dict[str, object]] = []

    print("[qa] diagnostics", flush=True)
    diagnostics = run_diagnostics(config)
    append_stage(results, {"name": "diagnostics", "status": diagnostics["status"], "summary": diagnostics.get("status")}, config)
    append_stage(results, qa_stage("py_compile", ["python3", "-m", "py_compile", *[str(path) for path in sorted(root.glob("growth_engine/*.py"))], *[str(path) for path in sorted(root.glob("scripts/*.py"))]], root, timeout=120), config)
    if not args.skip_smoke:
        append_stage(results, qa_stage("smoke_test", ["python3", "scripts/smoke_test.py"], root, timeout=240), config)
    append_stage(results, qa_stage("pipeline_once", ["python3", "scripts/run_pipeline.py"], root, timeout=180), config)
    append_stage(results, qa_stage("daemon_once", ["python3", "scripts/watch_daemon.py", "--once"], root, timeout=180), config)
    append_stage(results, qa_stage("orchestrator_once", ["python3", "scripts/run_orchestrator.py", "--once"], root, timeout=180), config)
    append_stage(results, qa_stage("media_cache_build", ["python3", "scripts/build_media_cache.py", "--force", "--limit", "3"], root, timeout=180), config)
    append_stage(results, qa_stage("color_school_quick", ["python3", "scripts/run_color_school.py", "--quick"], root, timeout=90), config)
    append_stage(results, qa_stage("audio_school_quick", ["python3", "scripts/run_audio_school.py", "--quick"], root, timeout=90), config)
    append_stage(results, qa_stage("project_manifest_check", ["python3", "scripts/init_project_manifest.py"], root, timeout=60), config)
    append_stage(results, qa_stage("runtime_backfill_quick", ["python3", "scripts/backfill_runtime_db.py", "--quick"], root, timeout=90), config)
    append_stage(results, qa_stage("runtime_snapshot_build", ["python3", "scripts/build_runtime_snapshot.py"], root, timeout=60), config)
    print("[qa] event_log_write", flush=True)
    append_stage(results, event_log_check(root), config)
    print("[qa] runtime_lock_test", flush=True)
    append_stage(results, runtime_lock_check(root), config)
    append_stage(results, qa_stage("maintenance_dry_run", ["python3", "scripts/run_maintenance.py", "--dry-run"], root, timeout=60), config)
    print("[qa] task_queue_validation", flush=True)
    append_stage(results, task_queue_check(root), config)
    append_stage(results, qa_stage("task_worker_dry_run", ["python3", "scripts/run_task_worker.py", "--once", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("task_snapshot_build", ["python3", "scripts/build_task_snapshot.py"], root, timeout=60), config)
    append_stage(results, qa_stage("client_workflow_build", ["python3", "scripts/build_client_workflow.py"], root, timeout=60), config)
    append_stage(results, qa_stage("create_demo_project_dry_run", ["python3", "scripts/create_demo_project.py", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("package_client_handoff_dry_run", ["python3", "scripts/package_client_handoff.py", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("package_trial_release", ["python3", "scripts/package_trial_release.py"], root, timeout=60), config)
    append_stage(results, qa_stage("validate_trial_package", ["python3", "scripts/validate_trial_package.py"], root, timeout=60), config)
    append_stage(results, qa_stage("collect_client_feedback_template", ["python3", "scripts/collect_client_feedback.py", "--template"], root, timeout=60), config)
    append_stage(results, qa_stage("create_issue_report_client_safe_dry_run", ["python3", "scripts/create_issue_report.py", "--dry-run", "--client-safe"], root, timeout=60), config)
    append_stage(results, qa_stage("client_language_scan", ["python3", "scripts/check_client_language.py"], root, timeout=60), config)
    append_stage(results, qa_stage("client_trial_qa", ["python3", "scripts/run_client_trial_qa.py"], root, timeout=60), config)
    append_stage(results, qa_stage("marketing_plan_build", ["python3", "scripts/build_marketing_plan.py"], root, timeout=60), config)
    append_stage(results, qa_stage("instagram_insights_import_dry_run", ["python3", "scripts/import_instagram_insights.py", "--dry-run"], root, timeout=60), config)
    print("[qa] marketing_intelligence_validation", flush=True)
    append_stage(results, marketing_intelligence_check(root), config)
    append_stage(results, qa_stage("trial_readiness_report", ["python3", "scripts/build_trial_readiness_report.py"], root, timeout=60), config)
    append_stage(results, qa_stage("schedule_tasks_dry_run", ["python3", "scripts/schedule_tasks.py", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("full_media_prep_chain_dry_run", ["python3", "scripts/enqueue_full_media_prep.py", "--dry-run"], root, timeout=60), config)
    print("[qa] worker_runtime_validation", flush=True)
    append_stage(results, worker_runtime_check(root), config)
    append_stage(results, qa_stage("worker_status", ["python3", "scripts/manage_worker.py", "status"], root, timeout=60), config)
    append_stage(results, qa_stage("worker_once", ["python3", "scripts/manage_worker.py", "once"], root, timeout=120), config)
    append_stage(results, qa_stage("worker_cleanup_stale", ["python3", "scripts/manage_worker.py", "cleanup-stale"], root, timeout=60), config)
    append_stage(results, qa_stage("local_api_once_health", ["python3", "scripts/run_local_api.py", "--once-health"], root, timeout=30), config)
    print("[qa] local_api_endpoint_check", flush=True)
    append_stage(results, local_api_server_check(root), config)
    append_stage(results, qa_stage("project_validate", ["python3", "scripts/validate_project.py"], root, timeout=60), config)
    append_stage(results, qa_stage("project_size_report", ["python3", "scripts/project_size_report.py"], root, timeout=60), config)
    append_stage(results, qa_stage("project_backup_dry_run", ["python3", "scripts/backup_project.py", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("demo_reset_dry_run", ["python3", "scripts/reset_demo_workspace.py", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("project_archive_dry_run", ["python3", "scripts/archive_project_artifacts.py", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("runtime_snapshot_lifecycle", ["python3", "scripts/build_runtime_snapshot.py"], root, timeout=60), config)
    append_stage(results, qa_stage("client_workflow_lifecycle", ["python3", "scripts/build_client_workflow.py"], root, timeout=60), config)
    append_stage(results, qa_stage("observability_report_build", ["python3", "scripts/build_observability_report.py"], root, timeout=60), config)
    append_stage(results, qa_stage("state_reconciliation_dry_run", ["python3", "scripts/reconcile_runtime_state.py", "--dry-run", "--limit", "25"], root, timeout=60), config)
    append_stage(results, qa_stage("state_reconciliation_json", ["python3", "scripts/reconcile_runtime_state.py", "--dry-run", "--json", "--limit", "10"], root, timeout=60), config)
    append_stage(results, qa_stage("security_check", ["python3", "scripts/run_security_check.py"], root, timeout=60), config)
    append_stage(results, qa_stage("storage_report", ["python3", "scripts/manage_storage.py", "report"], root, timeout=60), config)
    append_stage(results, qa_stage("cleanup_plan_dry_run", ["python3", "scripts/manage_storage.py", "plan", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("archive_dry_run", ["python3", "scripts/manage_storage.py", "archive", "--dry-run"], root, timeout=60), config)
    append_stage(results, qa_stage("vacuum_db_dry_run", ["python3", "scripts/manage_storage.py", "vacuum-db"], root, timeout=60), config)
    append_stage(results, qa_stage("upgrade_check", ["python3", "scripts/upgrade_project.py", "--check"], root, timeout=60), config)
    append_stage(results, qa_stage("upgrade_plan", ["python3", "scripts/upgrade_project.py", "--plan"], root, timeout=60), config)
    append_stage(results, qa_stage("data_contract_validation", ["python3", "scripts/validate_data_contract.py"], root, timeout=60), config)
    append_stage(results, qa_stage("launch_preflight", ["python3", "scripts/run_launch_preflight.py"], root, timeout=60), config)
    print("[qa] security_fixture_validation", flush=True)
    append_stage(results, security_fixture_check(root), config)
    print("[qa] audit_event_fixture", flush=True)
    append_stage(results, audit_check(root), config)
    print("[qa] error_taxonomy_load", flush=True)
    append_stage(results, error_taxonomy_check(root), config)
    print("[qa] state_contract_load", flush=True)
    append_stage(results, state_contract_check(root), config)
    print("[qa] retention_policy_load", flush=True)
    append_stage(results, retention_policy_check(root), config)
    print("[qa] version_contract_load", flush=True)
    append_stage(results, version_contract_check(root), config)
    print("[qa] client_workflow_validation", flush=True)
    append_stage(results, client_workflow_check(root), config)
    print("[qa] client_handoff_validation", flush=True)
    append_stage(results, client_handoff_check(root), config)
    print("[qa] beta_checklist_validation", flush=True)
    append_stage(results, beta_checklist_check(root), config)
    print("[qa] trial_package_validation", flush=True)
    append_stage(results, trial_package_check(root), config)
    print("[qa] upgrade_plan_fixture", flush=True)
    append_stage(results, upgrade_fixture_check(root), config)
    print("[qa] storage_apply_archive_fixture", flush=True)
    append_stage(results, storage_fixture_check(root), config)
    print("[qa] reconciliation_apply_fixture", flush=True)
    append_stage(results, reconciliation_fixture_check(root), config)
    print("[qa] dashboard_js_syntax", flush=True)
    append_stage(results, dashboard_js_check(root), config)
    print("[qa] packaged_path_verification", flush=True)
    append_stage(results, packaged_path_check(root), config)
    print("[qa] external_api_scan", flush=True)
    append_stage(results, external_api_scan(root), config)

    payload = {
        "version": 1,
        "updated_at": utc_now(),
        "local_only": True,
        "status": summarize_report(results),
        "root": str(root),
        "in_progress": False,
        "results": results,
    }
    save_json(config.analytics_dir / "qa_report.json", payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
