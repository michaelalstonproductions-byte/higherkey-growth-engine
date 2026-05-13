#!/usr/bin/env node
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const path = require("node:path");
const { spawn } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");

function run(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, options);
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (data) => { stdout += data.toString(); });
    child.stderr.on("data", (data) => { stderr += data.toString(); });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  const mainSource = fs.readFileSync(path.join(ROOT, "electron", "main.js"), "utf8");
  const dashboardSource = fs.readFileSync(path.join(ROOT, "dashboard", "review.html"), "utf8");
  assert(mainSource.includes("ipcMain.handle(\"pipeline:runOnce\", runPipelineOnce)"), "Electron pipeline bridge must use runPipelineOnce");
  assert(mainSource.includes("cwd: activeProjectRoot") || mainSource.includes("const cwd = activeProjectRoot"), "Electron Python runner must use activeProjectRoot as cwd");
  assert(dashboardSource.includes("Active Project"), "Dashboard must show active project path");
  assert(dashboardSource.includes("Select Project Folder"), "Dashboard must expose project folder selection");

  await fsp.mkdir(path.join(ROOT, "content_inbox"), { recursive: true });
  const result = await run("python3", [path.join(ROOT, "scripts", "run_pipeline.py")], {
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: ROOT }
  });
  assert(result.code === 0, `pipeline failed: ${result.stderr || result.stdout}`);
  const parsed = JSON.parse(result.stdout);
  assert(parsed.queue_entries > 0, `expected queue_entries > 0, got ${parsed.queue_entries}`);
  const queuePath = path.join(ROOT, "queue", "review_queue.json");
  const queue = JSON.parse(await fsp.readFile(queuePath, "utf8"));
  assert(Array.isArray(queue.entries) && queue.entries.length > 0, "review_queue.json has no entries");

  console.log(JSON.stringify({
    status: "pass",
    active_project_root: ROOT,
    content_inbox: path.join(ROOT, "content_inbox"),
    cwd: ROOT,
    queue_entries: parsed.queue_entries,
    processed: parsed.processed,
    skipped: parsed.skipped
  }, null, 2));
}

main().catch((error) => {
  console.error(JSON.stringify({ status: "fail", error: error.message || String(error) }, null, 2));
  process.exit(1);
});
