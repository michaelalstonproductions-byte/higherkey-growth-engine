const fsp = require("node:fs/promises");
const path = require("node:path");

const ACCEPTED_DROP_EXTENSIONS = new Set([".mp4", ".mov", ".m4v"]);

async function uniqueInboxTarget(inbox, fileName) {
  const parsed = path.parse(fileName);
  let target = path.join(inbox, fileName);
  let index = 1;
  while (true) {
    try {
      await fsp.access(target);
      target = path.join(inbox, `${parsed.name}-${index}${parsed.ext}`);
      index += 1;
    } catch {
      return target;
    }
  }
}

async function ingestDroppedFilesToInbox(filePaths, inbox) {
  await fsp.mkdir(inbox, { recursive: true });
  const copied = [];
  const skipped = [];
  const errors = [];
  for (const item of Array.isArray(filePaths) ? filePaths : []) {
    const filePath = typeof item === "string" ? item : item?.path;
    const name = typeof item === "string" ? path.basename(item) : (item?.name || path.basename(filePath || ""));
    if (!filePath) {
      errors.push({ name, reason: "Dropped file path was not available from Electron." });
      continue;
    }
    const ext = path.extname(filePath).toLowerCase();
    if (!ACCEPTED_DROP_EXTENSIONS.has(ext)) {
      skipped.push({ path: filePath, name, reason: `Unsupported extension ${ext || "(none)"}` });
      continue;
    }
    try {
      const stat = await fsp.stat(filePath);
      if (!stat.isFile()) {
        skipped.push({ path: filePath, name, reason: "Dropped item is not a file" });
        continue;
      }
      const target = await uniqueInboxTarget(inbox, path.basename(filePath));
      await fsp.copyFile(filePath, target);
      copied.push({ source: filePath, target, name: path.basename(target) });
    } catch (error) {
      errors.push({ path: filePath, name, reason: error.message || String(error) });
    }
  }
  return { accepted_extensions: [...ACCEPTED_DROP_EXTENSIONS].sort(), copied, skipped, errors, inbox };
}

module.exports = { ACCEPTED_DROP_EXTENSIONS, ingestDroppedFilesToInbox, uniqueInboxTarget };
