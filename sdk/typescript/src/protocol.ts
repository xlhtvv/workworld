import {randomUUID} from "node:crypto";

export const PROTOCOL_EVENT_TYPES = [
  "agent.register",
  "agent.registered",
  "agent.heartbeat",
  "agent.capacity_updated",
  "task.offer",
  "task.accept",
  "task.reject",
  "task.started",
  "task.progress",
  "clarification.requested",
  "clarification.answered",
  "clarification.timed_out",
  "budget_extension.requested",
  "budget_extension.approved",
  "budget_extension.rejected",
  "artifact.upload_requested",
  "artifact.upload_completed",
  "task.result_submitted",
  "task.rework_requested",
  "task.cancel_requested",
  "task.cancelled",
  "task.failed",
  "task.completed",
  "protocol.error",
] as const;

export type ProtocolEventType = typeof PROTOCOL_EVENT_TYPES[number];

export type AgentEventType = Exclude<
  ProtocolEventType,
  | "agent.registered"
  | "task.offer"
  | "clarification.answered"
  | "clarification.timed_out"
  | "budget_extension.approved"
  | "budget_extension.rejected"
  | "task.rework_requested"
  | "task.cancel_requested"
  | "task.completed"
  | "protocol.error"
>;

export interface Envelope<T extends string = string> {
  protocol_version: "1.0";
  message_id: string;
  idempotency_key: string;
  timestamp: string;
  agent_id: string;
  run_id: string;
  type: T;
  sequence: number;
  payload: Record<string, unknown>;
}

export function envelope<T extends AgentEventType>(
  agentId: string,
  runId: string,
  type: T,
  sequence: number,
  payload: Record<string, unknown>,
  idempotencyKey = `${runId}:${type}:${sequence}`,
): Envelope<T> {
  if (!Number.isSafeInteger(sequence) || sequence < 1) throw new Error("sequence_must_be_positive");
  return {
    protocol_version: "1.0",
    message_id: randomUUID(),
    idempotency_key: idempotencyKey,
    timestamp: new Date().toISOString(),
    agent_id: agentId,
    run_id: runId,
    type,
    sequence,
    payload,
  };
}
