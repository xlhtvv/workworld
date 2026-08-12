import {createHmac, timingSafeEqual} from "node:crypto";
import {IncomingMessage} from "node:http";

const MAX_BODY = 2 * 1024 * 1024;

export class NonceStore {
  private readonly seen = new Map<string, number>();

  use(nonce: string, expiresAt: number): boolean {
    const now = Date.now();
    for (const [key, expiry] of this.seen) if (expiry <= now) this.seen.delete(key);
    if (this.seen.has(nonce)) return false;
    this.seen.set(nonce, expiresAt);
    return true;
  }
}

export async function verifyPushRequest(
  request: IncomingMessage,
  secret: string,
  nonces: NonceStore,
): Promise<unknown> {
  const timestampText = request.headers["x-workworld-timestamp"];
  const nonce = request.headers["x-workworld-nonce"];
  const signature = request.headers["x-workworld-signature"];
  if (typeof timestampText !== "string" || typeof nonce !== "string" || typeof signature !== "string") {
    throw new Error("webhook_headers_missing");
  }
  const timestamp = Number(timestampText);
  if (!Number.isSafeInteger(timestamp) || Math.abs(Date.now() / 1000 - timestamp) > 300) {
    throw new Error("webhook_timestamp_out_of_range");
  }
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const value = Buffer.from(chunk as Uint8Array);
    size += value.length;
    if (size > MAX_BODY) throw new Error("webhook_body_too_large");
    chunks.push(value);
  }
  const body = Buffer.concat(chunks);
  const expected = createHmac("sha256", secret)
    .update(`${timestamp}.${nonce}.`)
    .update(body)
    .digest();
  const supplied = Buffer.from(signature, "hex");
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
    throw new Error("webhook_signature_invalid");
  }
  if (!nonces.use(nonce, Date.now() + 300_000)) throw new Error("webhook_nonce_replayed");
  return JSON.parse(body.toString("utf8"));
}
