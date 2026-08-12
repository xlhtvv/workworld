"use client";

import {useState} from "react";
import {apiFetch} from "@/lib/api";

const kinds = ["text", "json", "image", "document", "spreadsheet", "audio", "video", "archive", "repository_snapshot", "generic_file"];

export function ArtifactUploader({
  taskId,
  locale,
  direction = "input",
  onComplete,
}: {
  taskId?: string;
  locale: "en" | "zh";
  direction?: "input" | "output";
  onComplete?: (artifactId: string) => void;
}) {
  const [token, setToken] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("generic_file");
  const [mimeType, setMimeType] = useState("application/octet-stream");
  const [visibility, setVisibility] = useState<"public" | "applicants" | "winner">("winner");
  const [result, setResult] = useState("");

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!file) return;
    const accessToken = token || localStorage.getItem("workworld_access_token") || undefined;
    const bytes = await file.arrayBuffer();
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const sha256 = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
    const begin = await apiFetch("/v1/artifacts/uploads", accessToken, {
      method: "POST",
      body: JSON.stringify({
        original_name: file.name, kind, direction, mime_type: mimeType,
        size_bytes: file.size, sha256, task_id: taskId ?? null, visibility,
      }),
    });
    const artifact = await begin.json() as {id?: string; detail?: string};
    if (!begin.ok || !artifact.id) {
      setResult(JSON.stringify(artifact, null, 2));
      return;
    }
    const signed = await apiFetch(`/v1/artifacts/${artifact.id}/parts/1`, accessToken, {method: "POST"});
    const grant = await signed.json() as {url?: string; detail?: string};
    if (!signed.ok || !grant.url) {
      setResult(JSON.stringify(grant, null, 2));
      return;
    }
    const part = await fetch(grant.url, {method: "PUT", body: file});
    if (!part.ok) {
      setResult(locale === "zh" ? `分片上传失败：${part.status}` : `Multipart upload failed: ${part.status}`);
      return;
    }
    const completed = await apiFetch(`/v1/artifacts/${artifact.id}/complete`, accessToken, {
      method: "POST",
      body: JSON.stringify({parts: []}),
    });
    const document = await completed.json() as {id?: string; detail?: string};
    setResult(JSON.stringify(document, null, 2));
    if (completed.ok && document.id) onComplete?.(document.id);
  }

  return <form className="panel form-grid" onSubmit={upload}>
    <h2>{taskId ? (locale === "zh" ? "上传任务输入 Artifact" : "Upload task input Artifact") : (locale === "zh" ? "上传公开示例 Artifact" : "Upload public example Artifact")}</h2>
    <label>{locale === "zh" ? "访问令牌" : "Access token"}<input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder={locale === "zh" ? "使用登录时保存的令牌" : "Uses saved sign-in token"} /></label>
    <label>{locale === "zh" ? "种类" : "Kind"}<select value={kind} onChange={(event) => setKind(event.target.value)}>{kinds.map((value) => <option key={value}>{value}</option>)}</select></label>
    {taskId && direction === "input" && <label>{locale === "zh" ? "可见范围" : "Visibility"}<select value={visibility} onChange={(event) => setVisibility(event.target.value as "public" | "applicants" | "winner")}><option value="winner">{locale === "zh" ? "仅中选方" : "Winner only"}</option><option value="applicants">{locale === "zh" ? "申请方" : "Applicants"}</option><option value="public">{locale === "zh" ? "公开" : "Public"}</option></select></label>}
    <label>MIME type<input required value={mimeType} onChange={(event) => setMimeType(event.target.value)} /></label>
    <label>{locale === "zh" ? "文件" : "File"}<input type="file" required onChange={(event) => { const selected = event.target.files?.[0] ?? null; setFile(selected); if (selected?.type) setMimeType(selected.type); }} /></label>
    <button type="submit">{locale === "zh" ? "上传、扫描并提取元数据" : "Upload, scan, and measure"}</button>
    {result && <pre>{result}</pre>}
  </form>;
}
