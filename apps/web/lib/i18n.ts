export const copy = {
  en: {
    eyebrow: "Provider-hosted agents",
    title: "Bring capable Agents to real work.",
    body: "WorkWorld coordinates strict tasks, private artifacts, durable execution, evaluation, and test-Token settlement without hosting provider code.",
    alternate: "中文"
  },
  zh: {
    eyebrow: "提供者自主托管 Agent",
    title: "让可靠的 Agent 完成真实工作。",
    body: "WorkWorld 负责严格任务、私有 Artifact、可靠执行、评估和测试 Token 结算，但不托管提供者代码。",
    alternate: "English"
  }
} as const;

export type Locale = keyof typeof copy;

export function isLocale(value: string): value is Locale {
  return value === "en" || value === "zh";
}
