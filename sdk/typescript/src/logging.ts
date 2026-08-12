const AGENT_CREDENTIAL = /(?:wwa_[^.\s]+\.)[^\s]+/g;
const BEARER_TOKEN = /Bearer\s+[^\s]+/gi;

export function redactSecrets(value: string): string {
  return value
    .replace(AGENT_CREDENTIAL, (credential) => `${credential.split(".", 1)[0]}.[REDACTED]`)
    .replace(BEARER_TOKEN, "Bearer [REDACTED]");
}
