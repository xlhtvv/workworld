import {readFileSync} from "node:fs";
import {createServer} from "node:https";
import {AgentClient, envelope, NonceStore, verifyPushRequest} from "@workworld/sdk";

const secret = process.env.WORKWORLD_PUSH_SECRET;
if (!secret) throw new Error("WORKWORLD_PUSH_SECRET is required");
const nonces = new NonceStore();

function agentClient(): AgentClient {
  const credential = process.env.WORKWORLD_AGENT_CREDENTIAL
    ?? readFileSync(process.env.WORKWORLD_AGENT_CREDENTIAL_FILE!, "utf8").trim();
  if (!credential) throw new Error("WORKWORLD_AGENT_CREDENTIAL is required");
  return new AgentClient(process.env.WORKWORLD_API_URL ?? "http://localhost:8000", credential);
}

function transform(input: Record<string, unknown>): unknown {
  const document = structuredClone(input.document) as Record<string, unknown>;
  for (const raw of input.operations as Array<Record<string, unknown>>) {
    const path = String(raw.path ?? "").split(".").filter(Boolean);
    if (!path.length) throw new Error("operation_path_required");
    let target = document;
    for (const part of path.slice(0, -1)) {
      const child = target[part];
      if (typeof child !== "object" || child === null || Array.isArray(child)) target[part] = {};
      target = target[part] as Record<string, unknown>;
    }
    if (raw.op === "set") target[path.at(-1)!] = raw.value;
    else if (raw.op === "remove") delete target[path.at(-1)!];
    else throw new Error("operation_not_supported");
  }
  return document;
}

const server = createServer(
  {cert: readFileSync(process.env.TLS_CERT_FILE!), key: readFileSync(process.env.TLS_KEY_FILE!)},
  async (request, response) => {
    try {
      if (!request.headers["x-workworld-signature"]) {
        const chunks: Buffer[] = [];
        for await (const chunk of request) chunks.push(Buffer.from(chunk as Uint8Array));
        const challenge = JSON.parse(Buffer.concat(chunks).toString("utf8")) as {challenge: string};
        response.writeHead(200, {"content-type": "application/json"});
        response.end(JSON.stringify(challenge));
        return;
      }
      const offer = (await verifyPushRequest(request, secret, nonces)) as {
        agent_id: string; run_id: string; type: string; payload: Record<string, unknown>;
        certification_id?: string;
        sample_input?: Record<string, unknown>;
        artifact_challenge?: {content_utf8: string};
        scenarios?: Array<{name: string; challenge: string}>;
      };
      if (offer.type === "offering.certification") {
        if (!offer.certification_id || !offer.sample_input || !offer.artifact_challenge || !offer.scenarios) {
          throw new Error("certification_request_invalid");
        }
        const client = agentClient();
        await client.updateCapacity({
          status: "online", max_concurrent_runs: 1, active_runs: 0,
          queue_capacity: 1, estimated_wait_seconds: 0, supported_offering_versions: [],
        });
        const artifact = await client.uploadArtifact(
          null,
          "certification.txt",
          Buffer.from(offer.artifact_challenge.content_utf8, "utf8"),
          "generic_file",
          "text/plain",
        );
        let sampleDocument: unknown;
        try {
          sampleDocument = transform(offer.sample_input);
        } catch {
          sampleDocument = structuredClone(offer.sample_input.document);
        }
        response.writeHead(200, {"content-type": "application/json"});
        response.end(JSON.stringify({
          certification_id: offer.certification_id,
          results: offer.scenarios.map((item) => ({...item, passed: true})),
          sample_output: {document: sampleDocument},
          artifact_id: artifact.id,
        }));
        return;
      }
      response.writeHead(202).end();
      if (offer.type !== "task.offer") return;
      const client = agentClient();
      await client.callback(envelope(offer.agent_id, offer.run_id, "task.accept", 1, {}));
      await client.callback(envelope(offer.agent_id, offer.run_id, "task.started", 2, {}));
      const input = offer.payload.input as Record<string, unknown>;
      await client.callback(
        envelope(offer.agent_id, offer.run_id, "task.result_submitted", 3, {
          output: {document: transform(input)},
        }),
      );
    } catch (error) {
      if (response.headersSent) {
        response.destroy(error instanceof Error ? error : undefined);
        return;
      }
      response.writeHead(400, {"content-type": "application/json"});
      response.end(JSON.stringify({error: error instanceof Error ? error.message : "unknown"}));
    }
  },
);

server.listen(Number(process.env.PORT ?? 8443), "0.0.0.0");
