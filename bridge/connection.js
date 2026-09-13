const max = require("max-api");
const http = require("node:http");
const fs = require("node:fs/promises");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
let polling = false;
let awaitingResult = null;

async function request(endpoint, body) {
  const config = JSON.parse(
    await fs.readFile(path.join(root, "data/bridge-connection.json"), "utf8"),
  );
  const token = (
    await fs.readFile(path.join(root, "data/bridge-token"), "utf8")
  ).trim();
  return new Promise((resolve, reject) => {
    const contents = JSON.stringify(body);
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port: config.port,
        path: `/api/bridge/${endpoint}`,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": Buffer.byteLength(contents),
          "X-RDX-Token": token,
        },
        timeout: 5000,
      },
      (res) => {
        let output = "";
        res.on("data", (chunk) => {
          output += chunk;
        });
        res.on("end", () => {
          try {
            const parsed = JSON.parse(output);
            if (res.statusCode !== 200)
              throw new Error(parsed.detail || "Bridge request failed");
            resolve(parsed);
          } catch (error) {
            reject(error);
          }
        });
      },
    );
    req.on("timeout", () => req.destroy(new Error("RDX connection timed out")));
    req.on("error", reject);
    req.end(contents);
  });
}

max.addHandler("state", async (raw) => {
  if (polling) return;
  polling = true;
  try {
    if (awaitingResult) {
      await request("result", awaitingResult);
      awaitingResult = null;
    }
    const response = await request("poll", JSON.parse(raw));
    if (response.command) {
      const job = response.command;
      if (!/^[a-f0-9]{12}$/.test(job.id) || (job.kind !== "append_project" && job.kind !== "insert_device"))
        throw new Error("Unsupported transfer");
      const directory = path.join(root, "data/bridge-commands");
      await fs.mkdir(directory, { recursive: true });
      const filename = path.join(directory, `${job.id}.json`);
      // Large note lists travel through a file, not Max's message-size limit.
      await fs.writeFile(filename, JSON.stringify(job));
      await max.outlet("command", filename);
    } else await max.outlet("connection", "RDX connected locally");
  } catch (error) {
    await max.outlet("connection", `Disconnected: ${error.message}`);
  } finally {
    polling = false;
  }
});

max.addHandler("result", async (raw) => {
  awaitingResult = JSON.parse(raw);
  try {
    await request("result", awaitingResult);
    awaitingResult = null;
  } catch (error) {
    await max.outlet("connection", `Confirmation pending: ${error.message}`);
  }
});
