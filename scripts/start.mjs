import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mkdirSync, writeFileSync, readFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import net from "node:net";
const root = fileURLToPath(new URL("../", import.meta.url));
let port = Number(process.env.RDX_PORT || "8765");
if (!Number.isInteger(port) || port < 1024 || port > 65535)
  throw new Error("Invalid RDX port");
const hash = createHash("sha256");
for (const name of readdirSync(`${root}rdx`)
  .filter((n) => n.endsWith(".py"))
  .sort())
  hash.update(name).update(readFileSync(`${root}rdx/${name}`));
const build = hash.digest("hex");
const openBrowser = (url) => {
  const browser = spawn("/usr/bin/open", [url], { stdio: "ignore" });
  browser.on("error", () => {});
};
let available = false;
for (let attempt = 0; attempt < 30 && !available; attempt++) {
  available = await new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once("error", (error) => {
      if (error.code === "EADDRINUSE") resolve(false);
      else reject(error);
    });
    probe.listen(port, "127.0.0.1", () => probe.close(() => resolve(true)));
  });
  if (!available) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/status`, {
        signal: AbortSignal.timeout(1000),
      });
      const status = await response.json();
      if (status.service === "rdx-studio" && status.build === build) {
        console.log(`RDX is already running at http://127.0.0.1:${port}`);
        if (process.env.RDX_OPEN_BROWSER === "1")
          openBrowser(`http://127.0.0.1:${port}`);
        process.exit(0);
      }
    } catch {}
    port++;
  }
}
if (!available) throw new Error("No free local port was found");
mkdirSync(`${root}data`, { recursive: true });
writeFileSync(`${root}data/bridge-connection.json`, JSON.stringify({ port }));
const child = spawn(
  `${root}.venv/bin/python`,
  [
    "-m",
    "uvicorn",
    "rdx.server:app",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  { cwd: root, stdio: "inherit" },
);
child.on("exit", (code) => process.exit(code ?? 1));
child.on("error", (error) => {
  console.error(error.message);
  process.exit(1);
});
console.log(`RDX studio: http://127.0.0.1:${port}`);
if (process.env.RDX_OPEN_BROWSER === "1") {
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/status`, {
        signal: AbortSignal.timeout(1000),
      });
      if (response.ok) {
        openBrowser(`http://127.0.0.1:${port}`);
        break;
      }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}
for (const signal of ["SIGINT", "SIGTERM"])
  process.on(signal, () => child.kill(signal));
