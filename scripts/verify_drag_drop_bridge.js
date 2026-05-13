#!/usr/bin/env node
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { ingestDroppedFilesToInbox } = require("../electron/ingest");

const ROOT = path.resolve(__dirname, "..");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sourceIncludes(relativePath, snippets) {
  const text = fs.readFileSync(path.join(ROOT, relativePath), "utf8");
  for (const snippet of snippets) {
    assert(text.includes(snippet), `${relativePath} is missing ${snippet}`);
  }
}

async function main() {
  sourceIncludes("electron/preload.js", ["getDroppedFilePaths", "webUtils.getPathForFile", "ingestDroppedFiles"]);
  sourceIncludes("electron/main.js", ["files:ingestDropped", "ingestDroppedFilesToInbox"]);
  sourceIncludes("dashboard/review.html", ["getDroppedFilePaths", "Dropped file received", "Open Content Inbox"]);

  const tempRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "hk-drag-drop-"));
  const inbox = path.join(tempRoot, "content_inbox");
  const fixtures = ["clip.mp4", "clip.mov", "clip.m4v", "notes.txt"];
  for (const fixture of fixtures) {
    await fsp.writeFile(path.join(tempRoot, fixture), `fixture ${fixture}\n`);
  }
  await fsp.writeFile(path.join(inbox, "clip.mp4"), "existing\n").catch(async () => {
    await fsp.mkdir(inbox, { recursive: true });
    await fsp.writeFile(path.join(inbox, "clip.mp4"), "existing\n");
  });

  const result = await ingestDroppedFilesToInbox(fixtures.map((name) => ({
    name,
    path: path.join(tempRoot, name)
  })).concat([{ name: "missing-path.mov", path: "" }]), inbox);

  assert(result.copied.length === 3, `expected 3 copied files, got ${result.copied.length}`);
  assert(result.skipped.length === 1, `expected 1 skipped file, got ${result.skipped.length}`);
  assert(result.errors.length === 1, `expected 1 missing-path error, got ${result.errors.length}`);
  assert(result.copied.some((item) => item.name === "clip-1.mp4"), "expected duplicate mp4 to receive a unique target name");
  for (const item of result.copied) {
    assert(fs.existsSync(item.target), `copied target is missing: ${item.target}`);
  }

  console.log(JSON.stringify({
    status: "pass",
    bridge: "renderer-preload-main",
    accepted_extensions: result.accepted_extensions,
    copied: result.copied.length,
    skipped: result.skipped.length,
    errors: result.errors.length,
    inbox
  }, null, 2));
}

main().catch((error) => {
  console.error(JSON.stringify({ status: "fail", error: error.message || String(error) }, null, 2));
  process.exit(1);
});
