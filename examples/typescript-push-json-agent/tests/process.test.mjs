import assert from "node:assert/strict";
import {createHmac} from "node:crypto";
import {execFileSync, spawn} from "node:child_process";
import {mkdtempSync, rmSync} from "node:fs";
import {createServer as createHTTPServer} from "node:http";
import {request as httpsRequest} from "node:https";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {createServer as createTCPServer} from "node:net";
import test from "node:test";

function listen(server) {
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve(server.address().port));
  });
}

function close(server) {
  return new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

async function freePort() {
  const server = createTCPServer();
  const port = await listen(server);
  await close(server);
  return port;
}

function postHTTPS(port, document, headers = {}) {
  const body = Buffer.from(JSON.stringify(document));
  return new Promise((resolve, reject) => {
    const request = httpsRequest({
      hostname: "127.0.0.1",
      port,
      method: "POST",
      path: "/workworld",
      rejectUnauthorized: false,
      headers: {"content-type": "application/json", "content-length": body.length, ...headers},
    }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => resolve({
        status: response.statusCode,
        body: Buffer.concat(chunks).toString("utf8"),
      }));
    });
    request.on("error", reject);
    request.end(body);
  });
}

async function waitFor(predicate, failure, timeoutMs = 8_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(failure());
}

test("Push JSON example runs as a TLS process and completes a real callback sequence", {timeout: 20_000}, async () => {
  const directory = mkdtempSync(join(tmpdir(), "workworld-push-example-"));
  const keyPath = join(directory, "key.pem");
  const certPath = join(directory, "cert.pem");
  execFileSync("openssl", [
    "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
    "-subj", "/CN=localhost", "-keyout", keyPath, "-out", certPath,
  ], {stdio: "ignore"});

  const callbacks = [];
  let authenticatedCredential = "";
  const api = createHTTPServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
    if (request.url === "/v1/agent-auth/token") {
      authenticatedCredential = body.credential;
      response.writeHead(200, {"content-type": "application/json"});
      response.end(JSON.stringify({access_token: "agent-token", agent_id: "agent_push"}));
      return;
    }
    if (request.url === "/v1/agent-callbacks/events") {
      assert.equal(request.headers.authorization, "Bearer agent-token");
      callbacks.push(body);
      response.writeHead(202, {"content-type": "application/json"});
      response.end(JSON.stringify({event_id: `event_${callbacks.length}`, sequence: body.sequence}));
      return;
    }
    response.writeHead(404).end();
  });

  const apiPort = await listen(api);
  const agentPort = await freePort();
  const child = spawn(process.execPath, ["--enable-source-maps", "dist/server.js"], {
    cwd: new URL("..", import.meta.url),
    env: {
      ...process.env,
      WORKWORLD_PUSH_SECRET: "push-process-secret",
      WORKWORLD_AGENT_CREDENTIAL: "wwa_process.credential",
      WORKWORLD_API_URL: `http://127.0.0.1:${apiPort}`,
      TLS_CERT_FILE: certPath,
      TLS_KEY_FILE: keyPath,
      PORT: String(agentPort),
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let childOutput = "";
  child.stdout.on("data", (chunk) => { childOutput += chunk; });
  child.stderr.on("data", (chunk) => { childOutput += chunk; });

  try {
    let ready = false;
    const deadline = Date.now() + 8_000;
    while (!ready && Date.now() < deadline) {
      try {
        const response = await postHTTPS(agentPort, {challenge: "ready"});
        ready = response.status === 200 && JSON.parse(response.body).challenge === "ready";
      } catch {
        await new Promise((resolve) => setTimeout(resolve, 25));
      }
    }
    assert.equal(ready, true, `agent did not become ready: ${childOutput}`);

    const offer = {
      protocol_version: "1.0",
      event_id: "event_offer",
      idempotency_key: "run_push:task.offer:1",
      sent_at: new Date().toISOString(),
      agent_id: "agent_push",
      run_id: "run_push",
      type: "task.offer",
      sequence: 1,
      payload: {
        input: {
          document: {keep: true, nested: {old: "remove"}},
          operations: [
            {op: "set", path: "nested.value", value: 42},
            {op: "remove", path: "nested.old"},
          ],
        },
      },
    };
    const body = Buffer.from(JSON.stringify(offer));
    const timestamp = Math.floor(Date.now() / 1000);
    const nonce = "process-nonce";
    const signature = createHmac("sha256", "push-process-secret")
      .update(`${timestamp}.${nonce}.`)
      .update(body)
      .digest("hex");
    const response = await postHTTPS(agentPort, offer, {
      "x-workworld-timestamp": String(timestamp),
      "x-workworld-nonce": nonce,
      "x-workworld-signature": signature,
    });
    assert.equal(response.status, 202, response.body);
    await waitFor(() => callbacks.length === 3, () => `callbacks=${callbacks.length}; ${childOutput}`);
    assert.equal(authenticatedCredential, "wwa_process.credential");
    assert.deepEqual(callbacks.map((item) => item.type), [
      "task.accept", "task.started", "task.result_submitted",
    ]);
    assert.deepEqual(callbacks.at(-1).payload.output.document, {
      keep: true,
      nested: {value: 42},
    });
  } finally {
    if (child.exitCode === null) {
      const exited = new Promise((resolve) => child.once("exit", resolve));
      child.kill("SIGTERM");
      await exited;
    }
    await close(api);
    rmSync(directory, {recursive: true, force: true});
  }
});
