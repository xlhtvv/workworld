"use client";

import {useEffect, useMemo, useState} from "react";
import {apiFetch} from "@/lib/api";
import {ArtifactUploader} from "@/app/components/artifact-uploader";

type Property = {type?: string; enum?: string[]; default?: unknown; minimum?: number; maximum?: number};
type Schema = {
  id: string; version: string; name: {en: string; zh: string};
  input_schema: {required?: string[]; properties: Record<string, Property>};
};

function localDate(minutes: number) {
  const date = new Date(Date.now() + minutes * 60_000);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function TaskComposer({locale}: {locale: "en" | "zh"}) {
  const [schemas, setSchemas] = useState<Schema[]>([]);
  const [schemaId, setSchemaId] = useState("text.summarize");
  const [input, setInput] = useState<Record<string, unknown>>({difficulty: "simple"});
  const [token, setToken] = useState("");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [budget, setBudget] = useState(1000);
  const [mode, setMode] = useState<"recommended" | "open_call">("recommended");
  const [completion, setCompletion] = useState(localDate(120));
  const [recruitment, setRecruitment] = useState(localDate(30));
  const [disclosureAcknowledged, setDisclosureAcknowledged] = useState(false);
  const [result, setResult] = useState("");
  const [createdTaskId, setCreatedTaskId] = useState("");

  useEffect(() => {
    apiFetch("/v1/schemas").then(async (response) => {
      const catalog = await response.json() as {schemas: Schema[]};
      setSchemas(catalog.schemas);
    }).catch((error: unknown) => setResult(String(error)));
  }, []);
  const selected = useMemo(() => schemas.find((item) => item.id === schemaId), [schemas, schemaId]);

  function changeSchema(value: string) {
    setSchemaId(value);
    const schema = schemas.find((item) => item.id === value);
    const defaults: Record<string, unknown> = {};
    for (const [name, property] of Object.entries(schema?.input_schema.properties ?? {})) {
      if (property.default !== undefined) defaults[name] = property.default;
      else if (property.enum) defaults[name] = property.enum[0];
    }
    setInput(defaults);
  }

  function field(name: string, property: Property) {
    const value = input[name];
    if (property.enum) return <select value={String(value ?? "")} onChange={(e) => setInput({...input, [name]: e.target.value})}>{property.enum.map((item) => <option key={item}>{item}</option>)}</select>;
    if (property.type === "boolean") return <input type="checkbox" checked={Boolean(value)} onChange={(e) => setInput({...input, [name]: e.target.checked})} />;
    if (property.type === "integer" || property.type === "number") return <input type="number" min={property.minimum} max={property.maximum} value={Number(value ?? 0)} onChange={(e) => setInput({...input, [name]: Number(e.target.value)})} />;
    if (property.type === "array" || property.type === "object") return <textarea value={typeof value === "string" ? value : JSON.stringify(value ?? (property.type === "array" ? [] : {}), null, 2)} onChange={(e) => setInput({...input, [name]: e.target.value})} />;
    return <textarea value={String(value ?? "")} onChange={(e) => setInput({...input, [name]: e.target.value})} />;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    try {
      const normalized = {...input};
      for (const [name, property] of Object.entries(selected.input_schema.properties)) {
        if ((property.type === "array" || property.type === "object") && typeof normalized[name] === "string") {
          normalized[name] = JSON.parse(normalized[name] as string);
        }
      }
      const accessToken = token || localStorage.getItem("workworld_access_token") || undefined;
      const response = await apiFetch("/v1/tasks", accessToken, {
        method: "POST",
        body: JSON.stringify({
          schema_id: selected.id, schema_version: selected.version, title,
          public_summary: summary, input_json: normalized, field_visibility: {},
          difficulty: String(normalized.difficulty), acceptance_rules: {}, budget_tokens: budget,
          recruitment_deadline: mode === "open_call" ? new Date(recruitment).toISOString() : null,
          completion_deadline: new Date(completion).toISOString(), assignment_mode: mode,
          data_disclosure_acknowledged: disclosureAcknowledged,
        }),
      });
      const document = await response.json() as {id?: string};
      if (response.ok && document.id) setCreatedTaskId(document.id);
      setResult(JSON.stringify(document, null, 2));
    } catch (error) {
      setResult(error instanceof Error ? error.message : (locale === "zh" ? "输入无效" : "Invalid input"));
    }
  }

  return (
    <>
    <form className="panel form-grid" onSubmit={submit}>
      <label>{locale === "zh" ? "访问令牌" : "Access token"}<input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={locale === "zh" ? "使用登录时保存的令牌" : "Uses the token saved at sign-in"} /></label>
      <label>{locale === "zh" ? "任务类型" : "Task type"}<select value={schemaId} onChange={(e) => changeSchema(e.target.value)}>{schemas.map((schema) => <option key={schema.id} value={schema.id}>{schema.name[locale]} · {schema.id}</option>)}</select></label>
      <label>{locale === "zh" ? "标题" : "Title"}<input required value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>{locale === "zh" ? "公开摘要" : "Public summary"}<textarea required value={summary} onChange={(e) => setSummary(e.target.value)} /></label>
      {Object.entries(selected?.input_schema.properties ?? {}).map(([name, property]) => <label key={name}>{name}{selected?.input_schema.required?.includes(name) ? " *" : ""}{field(name, property)}</label>)}
      <label>{locale === "zh" ? "Token 预算" : "Token budget"}<input type="number" min="1" value={budget} onChange={(e) => setBudget(Number(e.target.value))} /></label>
      <label>{locale === "zh" ? "分配方式" : "Assignment"}<select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}><option value="recommended">recommended</option><option value="open_call">open_call</option></select></label>
      {mode === "open_call" && <label>{locale === "zh" ? "招募截止时间" : "Recruitment deadline"}<input type="datetime-local" value={recruitment} onChange={(e) => setRecruitment(e.target.value)} /></label>}
      <label>{locale === "zh" ? "完成截止时间" : "Completion deadline"}<input type="datetime-local" value={completion} onChange={(e) => setCompletion(e.target.value)} /></label>
      <label className="notice"><input type="checkbox" required checked={disclosureAcknowledged} onChange={(event) => setDisclosureAcknowledged(event.target.checked)} />{locale === "zh" ? "我确认任务数据会下载到中标 Agent 的基础设施，提供者可能使用第三方服务；我未上传密码、API Key 或私钥。" : "I acknowledge that the winning Agent downloads task data to provider infrastructure and may use third-party services; I have not uploaded passwords, API keys, or private keys."}</label>
      <button type="submit">{locale === "zh" ? "创建任务" : "Create task"}</button>
      {result && <pre>{result}</pre>}
    </form>
    {createdTaskId && <ArtifactUploader taskId={createdTaskId} locale={locale} />}
    </>
  );
}
