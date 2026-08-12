import assert from "node:assert/strict";
import {createHmac} from "node:crypto";
import {Readable} from "node:stream";
import {createServer} from "node:http";
import {readFileSync} from "node:fs";
import test from "node:test";

import {
  envelope,
  NonceStore,
  redactSecrets,
  verifyPushRequest,
  AgentClient,
  PROTOCOL_EVENT_TYPES,
} from "../dist/index.js";

test("runtime protocol event types match the versioned JSON Schema", () => {
  const schema = JSON.parse(readFileSync(new URL("../../../schemas/protocol/envelope.schema.json", import.meta.url)));
  assert.deepEqual([...PROTOCOL_EVENT_TYPES].sort(), [...schema.properties.type.enum].sort());
});

function request(body, secret, timestamp, nonce) {
  const stream = Readable.from([body]);
  stream.headers = {
    "x-workworld-timestamp": String(timestamp),
    "x-workworld-nonce": nonce,
    "x-workworld-signature": createHmac("sha256", secret)
      .update(`${timestamp}.${nonce}.`)
      .update(body)
      .digest("hex"),
  };
  return stream;
}

test("envelope creates a stable idempotency key", () => {
  const value = envelope("agent_1", "run_1", "task.progress", 3, {percent: 50});
  assert.equal(value.idempotency_key, "run_1:task.progress:3");
  assert.throws(() => envelope("agent_1", "run_1", "task.progress", 0, {}));
});

test("push verification rejects replay and body tampering", async () => {
  const secret = "test-push-secret";
  const timestamp = Math.floor(Date.now() / 1000);
  const body = Buffer.from(JSON.stringify({type: "task.offer", run_id: "run_1"}));
  const nonces = new NonceStore();
  const result = await verifyPushRequest(request(body, secret, timestamp, "nonce-1"), secret, nonces);
  assert.equal(result.run_id, "run_1");
  await assert.rejects(
    verifyPushRequest(request(body, secret, timestamp, "nonce-1"), secret, nonces),
    /webhook_nonce_replayed/,
  );
  const tampered = request(body, secret, timestamp, "nonce-2");
  await assert.rejects(verifyPushRequest(tampered, `${secret}-wrong`, nonces), /signature_invalid/);
});

test("redaction removes credentials and bearer tokens", () => {
  const output = redactSecrets("credential=wwa_agent.secret Authorization: Bearer token-value");
  assert.equal(output, "credential=wwa_agent.[REDACTED] Authorization: Bearer [REDACTED]");
  assert.doesNotMatch(output, /secret|token-value/);
});

test("provision performs the real three-request registration flow", async () => {
  const requests = [];
  const server = createServer(async (incoming, response) => {
    const chunks = [];
    for await (const chunk of incoming) chunks.push(chunk);
    requests.push({
      path: incoming.url,
      authorization: incoming.headers.authorization,
      body: JSON.parse(Buffer.concat(chunks).toString("utf8")),
    });
    const result = incoming.url === "/v1/agents"
      ? {id: "agent_1"}
      : incoming.url.endsWith("/credentials")
        ? {credential: "wwa_000000000000.secret"}
        : {id: "endpoint_1"};
    response.writeHead(201, {"content-type": "application/json"});
    response.end(JSON.stringify(result));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  try {
    const address = server.address();
    assert.equal(typeof address, "object");
    const client = await AgentClient.provision(`http://127.0.0.1:${address.port}`, "human-token", {
      name: "Pull Agent",
      endpointType: "pull",
    });
    assert.equal(client.agentId, "agent_1");
  } finally {
    await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  }
  assert.deepEqual(requests.map((item) => item.path), [
    "/v1/agents",
    "/v1/agents/agent_1/credentials",
    "/v1/agents/agent_1/endpoints",
  ]);
  assert.ok(requests.every((item) => item.authorization === "Bearer human-token"));
  assert.deepEqual(requests.at(-1).body, {endpoint_type: "pull", url: null});
});
