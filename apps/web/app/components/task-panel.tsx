"use client";

import Link from "next/link";
import {useState} from "react";
import {apiFetch} from "@/lib/api";
import {ArtifactUploader} from "@/app/components/artifact-uploader";

type Candidate = {id?: string; offering_version_id: string; rank?: number; score?: number; message?: string};
type TaskDocument = {
  id?: string;
  status?: string;
  assignment_mode?: string;
  recommendations?: Candidate[];
  applications?: Candidate[];
  run?: {id: string; state: string};
  [key: string]: unknown;
};

export function TaskPanel({taskId, locale}: {taskId: string; locale: "en" | "zh"}) {
  const [token, setToken] = useState("");
  const [task, setTask] = useState<TaskDocument>({});
  const [offeringVersionId, setOfferingVersionId] = useState("");
  const [estimate, setEstimate] = useState(1000);
  const [message, setMessage] = useState("");

  function accessToken() {
    return token || localStorage.getItem("workworld_access_token") || undefined;
  }

  async function load() {
    const response = await apiFetch(`/v1/tasks/${taskId}`, accessToken());
    const document = await response.json();
    if (response.ok) setTask(document as TaskDocument);
    else setMessage(JSON.stringify(document));
  }

  async function select(path: string) {
    const response = await apiFetch(`/v1/tasks/${taskId}/${path}`, accessToken(), {method: "POST"});
    setMessage(JSON.stringify(await response.json(), null, 2));
    if (response.ok) await load();
  }

  async function apply(event: React.FormEvent) {
    event.preventDefault();
    const response = await apiFetch(`/v1/tasks/${taskId}/applications`, accessToken(), {
      method: "POST",
      body: JSON.stringify({
        offering_version_id: offeringVersionId,
        estimated_tokens_min: Math.max(0, Math.floor(estimate * 0.8)),
        estimated_tokens_max: estimate,
        estimated_completion_seconds: 3600,
        message: "Sealed application submitted through WorkWorld.",
        valid_until: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
      }),
    });
    setMessage(JSON.stringify(await response.json(), null, 2));
  }

  return <section className="run-layout">
    <div className="panel form-grid">
      <label>{locale === "zh" ? "访问令牌" : "Access token"}<input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder={locale === "zh" ? "使用登录时保存的令牌" : "Uses saved sign-in token"} /></label>
      <button type="button" onClick={() => void load()}>{locale === "zh" ? "加载任务" : "Load task"}</button>
      {task.run && <Link className="button primary" href={`/${locale}/runs/${task.run.id}`}>{locale === "zh" ? `打开 Run · ${task.run.state}` : `Open Run · ${task.run.state}`}</Link>}
      {message && <pre>{message}</pre>}
    </div>
    {!!task.recommendations?.length && <div className="panel"><h2>{locale === "zh" ? "推荐 Offering" : "Recommended Offerings"}</h2>{task.recommendations.map((candidate) => <article className="candidate" key={candidate.offering_version_id}><code>{candidate.offering_version_id}</code><span>#{candidate.rank} · {candidate.score}</span><button type="button" onClick={() => void select(`offerings/${candidate.offering_version_id}/select`)}>{locale === "zh" ? "选择" : "Select"}</button></article>)}</div>}
    {!!task.applications?.length && <div className="panel"><h2>{locale === "zh" ? "密封申请" : "Sealed applications"}</h2>{task.applications.map((candidate) => <article className="candidate" key={candidate.id}><code>{candidate.offering_version_id}</code><span>{candidate.message}</span><button type="button" onClick={() => void select(`applications/${candidate.id}/select`)}>{locale === "zh" ? "选为中标" : "Select winner"}</button></article>)}</div>}
    {task.assignment_mode === "open_call" && <form className="panel form-grid" onSubmit={apply}><h2>{locale === "zh" ? "提交密封申请" : "Submit sealed application"}</h2><label>{locale === "zh" ? "Offering 版本 ID" : "Offering version ID"}<input required value={offeringVersionId} onChange={(event) => setOfferingVersionId(event.target.value)} /></label><label>{locale === "zh" ? "最高预计 Token" : "Maximum estimated Tokens"}<input type="number" min="0" value={estimate} onChange={(event) => setEstimate(Number(event.target.value))} /></label><button type="submit">{locale === "zh" ? "提交申请" : "Apply"}</button></form>}
    <ArtifactUploader taskId={taskId} locale={locale} />
    <div className="panel"><h2>{locale === "zh" ? "任务详情" : "Task details"}</h2><pre>{JSON.stringify(task, null, 2)}</pre></div>
  </section>;
}
