"use client";

import {useEffect, useRef, useState} from "react";
import {apiFetch} from "@/lib/api";

type EventDocument = {id: string; sequence: number; type: string; payload: Record<string, unknown>};
type Clarification = {
  id: string;
  question: string;
  status: string;
  default_answer?: unknown;
};
type BudgetRequest = {
  id: string;
  requested_tokens: number;
  reason: string;
  status: string;
};
type RunDetail = Record<string, unknown> & {
  state?: string;
  clarifications?: Clarification[];
  budget_requests?: BudgetRequest[];
};

export function RunPanel({runId, locale}: {runId: string; locale: "en" | "zh"}) {
  const [token, setToken] = useState("");
  const [detail, setDetail] = useState<RunDetail>({});
  const [events, setEvents] = useState<EventDocument[]>([]);
  const [message, setMessage] = useState("");
  const [reworkReason, setReworkReason] = useState("");
  const [ruleRefs, setRuleRefs] = useState("");
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, string>>({});
  const [rating, setRating] = useState(5);
  const [reviewBody, setReviewBody] = useState("");
  const stream = useRef<AbortController | null>(null);

  useEffect(() => () => stream.current?.abort(), []);

  function accessToken() {
    return token || localStorage.getItem("workworld_access_token") || undefined;
  }

  async function load() {
    stream.current?.abort();
    const authorization = accessToken();
    const response = await apiFetch(`/v1/runs/${runId}`, authorization);
    const document = await response.json();
    if (!response.ok) {
      setMessage(JSON.stringify(document));
      return;
    }
    setDetail(document as RunDetail);
    const prior = await apiFetch(`/v1/runs/${runId}/events`, authorization);
    const history = await prior.json() as EventDocument[];
    setEvents(history);
    const controller = new AbortController();
    stream.current = controller;
    const live = await apiFetch(`/v1/runs/${runId}/events/stream`, authorization, {
      signal: controller.signal,
      headers: history.length ? {"Last-Event-ID": String(history.at(-1)?.sequence ?? 0)} : {},
    });
    if (!live.ok || !live.body) {
      setMessage(locale === "zh" ? `SSE 连接失败：${live.status}` : `SSE failed: ${live.status}`);
      return;
    }
    const reader = live.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, {stream: true});
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const data = block.split("\n").find((line) => line.startsWith("data: "));
          if (!data) continue;
          const event = JSON.parse(data.slice(6)) as EventDocument;
          setEvents((current) => current.some((item) => item.id === event.id)
            ? current : [...current, event]);
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) setMessage(String(error));
    }
  }

  async function action(path: string, body?: object) {
    const response = await apiFetch(`/v1/runs/${runId}/${path}`, accessToken(), {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    setMessage(JSON.stringify(await response.json(), null, 2));
    if (response.ok) void load();
  }

  async function answerClarification(clarification: Clarification) {
    const raw = clarificationAnswers[clarification.id] ?? JSON.stringify(clarification.default_answer ?? {});
    try {
      await action(`clarifications/${clarification.id}/answer`, {answer: JSON.parse(raw)});
    } catch (error) {
      setMessage(error instanceof Error ? error.message : (locale === "zh" ? "澄清 JSON 无效" : "Invalid clarification JSON"));
    }
  }

  return <section className="run-layout">
    <div className="panel form-grid">
      <label>{locale === "zh" ? "访问令牌" : "Access token"}<input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder={locale === "zh" ? "使用登录时保存的令牌" : "Uses saved sign-in token"} /></label>
      <button type="button" onClick={() => void load()}>{locale === "zh" ? "连接实时事件" : "Connect live events"}</button>
      <button type="button" onClick={() => void action("cancel")}>{locale === "zh" ? "取消任务" : "Cancel"}</button>
      <button type="button" onClick={() => void action("accept")}>{locale === "zh" ? "验收结果" : "Accept result"}</button>
      <label>{locale === "zh" ? "返工原因" : "Rework reason"}<textarea value={reworkReason} onChange={(event) => setReworkReason(event.target.value)} /></label>
      <label>{locale === "zh" ? "验收规则键（逗号分隔）" : "Acceptance rule keys (comma separated)"}<input value={ruleRefs} onChange={(event) => setRuleRefs(event.target.value)} /></label>
      <button type="button" onClick={() => void action("rework", {reason: reworkReason, acceptance_rule_refs: ruleRefs.split(",").map((item) => item.trim()).filter(Boolean)})}>{locale === "zh" ? "请求一次返工" : "Request rework"}</button>
      {message && <pre>{message}</pre>}
    </div>
    {!!detail.clarifications?.length && <div className="panel form-grid">
      <h2>{locale === "zh" ? "澄清请求" : "Clarification requests"}</h2>
      {detail.clarifications.map((clarification) => <div className="candidate" key={clarification.id}>
        <strong>{clarification.question}</strong>
        <span>{clarification.status}</span>
        {clarification.status === "pending" && <>
          <label>
            {locale === "zh" ? "JSON 答复" : "JSON answer"}
            <textarea
              value={clarificationAnswers[clarification.id] ?? JSON.stringify(clarification.default_answer ?? {}, null, 2)}
              onChange={(event) => setClarificationAnswers({...clarificationAnswers, [clarification.id]: event.target.value})}
            />
          </label>
          <button type="button" onClick={() => void answerClarification(clarification)}>
            {locale === "zh" ? "提交澄清" : "Submit clarification"}
          </button>
        </>}
      </div>)}
    </div>}
    {!!detail.budget_requests?.length && <div className="panel">
      <h2>{locale === "zh" ? "预算扩展请求" : "Budget extension requests"}</h2>
      {detail.budget_requests.map((request) => <article className="candidate" key={request.id}>
        <strong>{request.requested_tokens} Token</strong>
        <span>{request.reason} · {request.status}</span>
        {request.status === "pending" && <>
          <button type="button" onClick={() => void action(`budget-requests/${request.id}/decision`, {approve: true})}>
            {locale === "zh" ? "批准" : "Approve"}
          </button>
          <button type="button" onClick={() => void action(`budget-requests/${request.id}/decision`, {approve: false})}>
            {locale === "zh" ? "拒绝" : "Decline"}
          </button>
        </>}
      </article>)}
    </div>}
    {detail.state === "completed" && <form className="panel form-grid" onSubmit={(event) => {
      event.preventDefault();
      void action("review", {rating, body: reviewBody});
    }}>
      <h2>{locale === "zh" ? "公开评价" : "Public review"}</h2>
      <label>
        {locale === "zh" ? "评分" : "Rating"}
        <select value={rating} onChange={(event) => setRating(Number(event.target.value))}>
          {[5, 4, 3, 2, 1].map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <label>
        {locale === "zh" ? "评价内容" : "Review"}
        <textarea required value={reviewBody} onChange={(event) => setReviewBody(event.target.value)} />
      </label>
      <button type="submit">{locale === "zh" ? "发布评价" : "Publish review"}</button>
    </form>}
    <div className="panel"><h2>{locale === "zh" ? "运行详情" : "Run details"}</h2><pre>{JSON.stringify(detail, null, 2)}</pre></div>
    <div className="panel"><h2>{locale === "zh" ? "实时事件" : "Live events"}</h2><ol className="timeline">{events.map((event) => <li key={event.id}><strong>{event.sequence} · {event.type}</strong><pre>{JSON.stringify(event.payload, null, 2)}</pre></li>)}</ol></div>
  </section>;
}
