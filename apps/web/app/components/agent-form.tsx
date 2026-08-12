"use client";

import {useState} from "react";
import {apiFetch} from "@/lib/api";

export function AgentForm({locale}: {locale: "en" | "zh"}) {
  const [token, setToken] = useState("");
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [endpointType, setEndpointType] = useState<"pull" | "push">("pull");
  const [url, setUrl] = useState("");
  const [result, setResult] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const accessToken = token || localStorage.getItem("workworld_access_token") || undefined;
    const created = await apiFetch("/v1/agents", accessToken, {
      method: "POST",
      body: JSON.stringify({name, slug: slug || null}),
    });
    const agent = await created.json() as {id?: string; detail?: string};
    if (!created.ok || !agent.id) {
      setResult(JSON.stringify(agent, null, 2));
      return;
    }
    const credentialResponse = await apiFetch(`/v1/agents/${agent.id}/credentials`, accessToken, {
      method: "POST",
    });
    const credential = await credentialResponse.json();
    const endpointResponse = await apiFetch(`/v1/agents/${agent.id}/endpoints`, accessToken, {
      method: "POST",
      body: JSON.stringify({endpoint_type: endpointType, url: endpointType === "push" ? url : null}),
    });
    const endpoint = await endpointResponse.json();
    setResult(JSON.stringify({agent, credential, endpoint}, null, 2));
  }

  return <form className="panel form-grid" onSubmit={submit}>
    <label>{locale === "zh" ? "访问令牌" : "Access token"}<input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder={locale === "zh" ? "使用登录时保存的令牌" : "Uses saved sign-in token"} /></label>
    <label>{locale === "zh" ? "名称" : "Name"}<input required value={name} onChange={(event) => setName(event.target.value)} /></label>
    <label>Slug<input value={slug} onChange={(event) => setSlug(event.target.value)} /></label>
    <label>{locale === "zh" ? "连接端点" : "Endpoint"}<select value={endpointType} onChange={(event) => setEndpointType(event.target.value as "pull" | "push")}><option value="pull">Pull / WebSocket</option><option value="push">Push / HTTPS</option></select></label>
    {endpointType === "push" && <label>HTTPS URL<input type="url" required value={url} onChange={(event) => setUrl(event.target.value)} /></label>}
    <p className="notice">{locale === "zh" ? "Agent 凭证只显示一次，请立即保存。Push URL 会执行 TLS、DNS 和 SSRF 验证。" : "The Agent credential is shown once. Save it immediately. Push URLs undergo TLS, DNS, and SSRF verification."}</p>
    <button type="submit">{locale === "zh" ? "注册 Agent" : "Register Agent"}</button>
    {result && <pre>{result}</pre>}
  </form>;
}
