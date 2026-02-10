import { defineConfig } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const baseURL = process.env.E2E_BASE_URL || "http://127.0.0.1:18080";
const cacheRoot = process.env.HOME
  ? path.join(process.env.HOME, "Library", "Caches", "ms-playwright")
  : "";

function detectHeadlessShellPath(): string | undefined {
  if (!cacheRoot || !fs.existsSync(cacheRoot)) {
    return undefined;
  }
  const versionDirs = fs
    .readdirSync(cacheRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith("chromium_headless_shell-"))
    .map((entry) => entry.name)
    .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));

  const relativeCandidates = [
    "chrome-headless-shell-mac-arm64/chrome-headless-shell",
    "chrome-headless-shell-mac-x64/chrome-headless-shell",
  ];

  for (const versionDir of versionDirs) {
    for (const relativePath of relativeCandidates) {
      const resolved = path.join(cacheRoot, versionDir, relativePath);
      if (fs.existsSync(resolved)) {
        return resolved;
      }
    }
  }
  return undefined;
}

const executablePath = process.env.PLAYWRIGHT_EXECUTABLE_PATH || detectHeadlessShellPath();

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  retries: 0,
  reporter: "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
    launchOptions: {
      executablePath,
    },
  },
});
