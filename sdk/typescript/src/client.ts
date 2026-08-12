import {createHash} from "node:crypto";
import {Envelope} from "./protocol.js";

export interface UploadedArtifact {
  id: string;
  kind: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  scan_status: string;
  metadata: Record<string, unknown>;
}

export interface ProvisionAgentOptions {
  name: string;
  slug?: string;
  endpointType: "pull" | "push";
  endpointUrl?: string;
}

export class AgentClient {
  private token?: string;
  agentId?: string;

  constructor(private readonly apiUrl: string, private readonly credential: string) {}

  static async provision(
    apiUrl: string,
    humanAccessToken: string,
    options: ProvisionAgentOptions,
  ): Promise<AgentClient> {
    if (options.endpointType === "push" && !options.endpointUrl) {
      throw new Error("push_endpoint_url_required");
    }
    const base = apiUrl.replace(/\/$/, "");
    const headers = {
      authorization: `Bearer ${humanAccessToken}`,
      "content-type": "application/json",
    };
    const post = async (path: string, body: Record<string, unknown>): Promise<Record<string, unknown>> => {
      const response = await fetch(`${base}${path}`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`agent_provision_failed:${response.status}`);
      return (await response.json()) as Record<string, unknown>;
    };
    const agent = await post("/v1/agents", {name: options.name, slug: options.slug ?? null});
    const agentId = String(agent.id);
    const issued = await post(`/v1/agents/${encodeURIComponent(agentId)}/credentials`, {});
    await post(`/v1/agents/${encodeURIComponent(agentId)}/endpoints`, {
      endpoint_type: options.endpointType,
      url: options.endpointUrl ?? null,
    });
    const client = new AgentClient(base, String(issued.credential));
    client.agentId = agentId;
    return client;
  }

  async authenticate(): Promise<string> {
    const response = await fetch(`${this.apiUrl}/v1/agent-auth/token`, {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify({credential: this.credential}),
    });
    if (!response.ok) throw new Error(`agent_auth_failed:${response.status}`);
    const result = (await response.json()) as {access_token: string; agent_id: string};
    this.token = result.access_token;
    this.agentId = result.agent_id;
    return this.token;
  }

  async callback(message: Envelope): Promise<{event_id: string; sequence: number}> {
    const token = this.token ?? (await this.authenticate());
    const response = await fetch(`${this.apiUrl}/v1/agent-callbacks/events`, {
      method: "POST",
      headers: {authorization: `Bearer ${token}`, "content-type": "application/json"},
      body: JSON.stringify(message),
    });
    if (!response.ok) throw new Error(`agent_callback_failed:${response.status}`);
    return (await response.json()) as {event_id: string; sequence: number};
  }

  async updateCapacity(capacity: {
    status: "online" | "offline" | "draining";
    max_concurrent_runs: number;
    active_runs: number;
    queue_capacity: number;
    estimated_wait_seconds: number;
    supported_offering_versions: string[];
  }): Promise<void> {
    const token = this.token ?? (await this.authenticate());
    const response = await fetch(`${this.apiUrl}/v1/agent-callbacks/capacity`, {
      method: "POST",
      headers: {authorization: `Bearer ${token}`, "content-type": "application/json"},
      body: JSON.stringify(capacity),
    });
    if (!response.ok) throw new Error(`agent_capacity_failed:${response.status}`);
  }

  async downloadArtifact(artifactId: string): Promise<Uint8Array> {
    const token = this.token ?? (await this.authenticate());
    const signed = await fetch(
      `${this.apiUrl}/v1/agent-callbacks/artifacts/${encodeURIComponent(artifactId)}/download`,
      {headers: {authorization: `Bearer ${token}`}},
    );
    if (!signed.ok) throw new Error(`artifact_download_grant_failed:${signed.status}`);
    const {url} = (await signed.json()) as {url: string};
    const response = await fetch(url);
    if (!response.ok) throw new Error(`artifact_download_failed:${response.status}`);
    return new Uint8Array(await response.arrayBuffer());
  }

  async uploadArtifact(
    taskId: string | null,
    fileName: string,
    data: Uint8Array,
    kind: string,
    mimeType: string,
  ): Promise<UploadedArtifact> {
    const token = this.token ?? (await this.authenticate());
    const headers = {authorization: `Bearer ${token}`, "content-type": "application/json"};
    const begin = await fetch(`${this.apiUrl}/v1/agent-callbacks/artifacts/uploads`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        original_name: fileName,
        kind,
        direction: "output",
        mime_type: mimeType,
        size_bytes: data.byteLength,
        sha256: createHash("sha256").update(data).digest("hex"),
        task_id: taskId,
      }),
    });
    if (!begin.ok) throw new Error(`artifact_upload_begin_failed:${begin.status}`);
    const artifact = (await begin.json()) as {id: string};
    const signed = await fetch(
      `${this.apiUrl}/v1/agent-callbacks/artifacts/${encodeURIComponent(artifact.id)}/parts/1`,
      {method: "POST", headers: {authorization: `Bearer ${token}`}},
    );
    if (!signed.ok) throw new Error(`artifact_upload_sign_failed:${signed.status}`);
    const {url} = (await signed.json()) as {url: string};
    const upload = await fetch(url, {method: "PUT", body: Buffer.from(data)});
    if (!upload.ok) throw new Error(`artifact_upload_part_failed:${upload.status}`);
    const etag = upload.headers.get("etag")?.replaceAll('"', "");
    if (!etag) throw new Error("artifact_upload_etag_missing");
    const complete = await fetch(
      `${this.apiUrl}/v1/agent-callbacks/artifacts/${encodeURIComponent(artifact.id)}/complete`,
      {
        method: "POST",
        headers,
        body: JSON.stringify({parts: [{PartNumber: 1, ETag: etag}]}),
      },
    );
    if (!complete.ok) throw new Error(`artifact_upload_complete_failed:${complete.status}`);
    return (await complete.json()) as UploadedArtifact;
  }
}
