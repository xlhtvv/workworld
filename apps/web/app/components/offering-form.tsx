"use client";

import {useEffect, useState} from "react";
import {apiFetch} from "@/lib/api";
import {ArtifactUploader} from "@/app/components/artifact-uploader";

type Schema = {id: string; version: string; name: {en: string; zh: string}};

export function OfferingForm({locale}: {locale: "en" | "zh"}) {
  const [schemas, setSchemas] = useState<Schema[]>([]);
  const [token, setToken] = useState("");
  const [agentId, setAgentId] = useState("");
  const [slug, setSlug] = useState("");
  const [schemaId, setSchemaId] = useState("text.summarize");
  const [nameEn, setNameEn] = useState("");
  const [nameZh, setNameZh] = useState("");
  const [descriptionEn, setDescriptionEn] = useState("");
  const [descriptionZh, setDescriptionZh] = useState("");
  const [capabilities, setCapabilities] = useState("");
  const [riskDisclosure, setRiskDisclosure] = useState("");
  const [outputLicense, setOutputLicense] = useState("task-publisher-use");
  const [slaSeconds, setSlaSeconds] = useState(3600);
  const [estimatedTokensMin, setEstimatedTokensMin] = useState(100);
  const [estimatedTokensMax, setEstimatedTokensMax] = useState(5000);
  const [estimatedSecondsMin, setEstimatedSecondsMin] = useState(5);
  const [estimatedSecondsMax, setEstimatedSecondsMax] = useState(3600);
  const [exampleArtifactIds, setExampleArtifactIds] = useState<string[]>([]);
  const [versionId, setVersionId] = useState("");
  const [result, setResult] = useState("");

  useEffect(() => {
    apiFetch("/v1/schemas").then(async (response) => {
      setSchemas(((await response.json()) as {schemas: Schema[]}).schemas);
    }).catch((error: unknown) => setResult(String(error)));
  }, []);

  function accessToken() {
    return token || localStorage.getItem("workworld_access_token") || undefined;
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const schema = schemas.find((item) => item.id === schemaId);
    if (!schema) return;
    const response = await apiFetch("/v1/offerings/versions", accessToken(), {
      method: "POST",
      body: JSON.stringify({
        offering_id: null, slug, agent_id: agentId, schema_id: schema.id,
        schema_version: schema.version, name_i18n: {en: nameEn, zh: nameZh},
        description_i18n: {en: descriptionEn, zh: descriptionZh},
        capabilities: capabilities.split(",").map((item) => item.trim()).filter(Boolean),
        example_artifact_ids: exampleArtifactIds,
        risk_disclosure: riskDisclosure,
        output_license: outputLicense, sla_seconds: slaSeconds, input_limits: {},
        estimated_tokens_min: estimatedTokensMin, estimated_tokens_max: estimatedTokensMax,
        estimated_seconds_min: estimatedSecondsMin,
        estimated_seconds_max: estimatedSecondsMax, auto_apply_policy: {},
      }),
    });
    const document = await response.json() as {version_id?: string};
    if (document.version_id) setVersionId(document.version_id);
    setResult(JSON.stringify(document, null, 2));
  }

  async function action(actionName: "certify" | "publish") {
    const response = await apiFetch(`/v1/offerings/versions/${versionId}/${actionName}`, accessToken(), {method: "POST"});
    setResult(JSON.stringify(await response.json(), null, 2));
  }

  return <>
    <ArtifactUploader locale={locale} direction="output" onComplete={(artifactId) => setExampleArtifactIds((current) => current.includes(artifactId) ? current : [...current, artifactId])} />
    <form className="panel form-grid" onSubmit={create}>
    <label>{locale === "zh" ? "访问令牌" : "Access token"}<input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder={locale === "zh" ? "使用登录时保存的令牌" : "Uses saved sign-in token"} /></label>
    <label>Agent ID<input required value={agentId} onChange={(event) => setAgentId(event.target.value)} /></label>
    <label>Slug<input required value={slug} onChange={(event) => setSlug(event.target.value)} /></label>
    <label>Schema<select value={schemaId} onChange={(event) => setSchemaId(event.target.value)}>{schemas.map((schema) => <option key={schema.id} value={schema.id}>{schema.name[locale]} · {schema.id}</option>)}</select></label>
    <label>{locale === "zh" ? "英文名称" : "English name"}<input required lang="en" value={nameEn} onChange={(event) => setNameEn(event.target.value)} /></label>
    <label>{locale === "zh" ? "中文名称" : "Chinese name"}<input required lang="zh" value={nameZh} onChange={(event) => setNameZh(event.target.value)} /></label>
    <label>{locale === "zh" ? "英文说明" : "English description"}<textarea required lang="en" value={descriptionEn} onChange={(event) => setDescriptionEn(event.target.value)} /></label>
    <label>{locale === "zh" ? "中文说明" : "Chinese description"}<textarea required lang="zh" value={descriptionZh} onChange={(event) => setDescriptionZh(event.target.value)} /></label>
    <label>{locale === "zh" ? "能力标签（逗号分隔）" : "Capabilities (comma separated)"}<input value={capabilities} onChange={(event) => setCapabilities(event.target.value)} /></label>
    <label>{locale === "zh" ? "风险说明" : "Risk disclosure"}<textarea required value={riskDisclosure} onChange={(event) => setRiskDisclosure(event.target.value)} /></label>
    <label>{locale === "zh" ? "输出许可证" : "Output license"}<input required value={outputLicense} onChange={(event) => setOutputLicense(event.target.value)} /></label>
    <label>{locale === "zh" ? "SLA 秒数" : "SLA seconds"}<input required type="number" min="1" value={slaSeconds} onChange={(event) => setSlaSeconds(Number(event.target.value))} /></label>
    <label>{locale === "zh" ? "预计 Token 最小值" : "Minimum estimated Tokens"}<input required type="number" min="0" value={estimatedTokensMin} onChange={(event) => setEstimatedTokensMin(Number(event.target.value))} /></label>
    <label>{locale === "zh" ? "预计 Token 最大值" : "Maximum estimated Tokens"}<input required type="number" min={estimatedTokensMin} value={estimatedTokensMax} onChange={(event) => setEstimatedTokensMax(Number(event.target.value))} /></label>
    <label>{locale === "zh" ? "预计耗时最小秒数" : "Minimum estimated seconds"}<input required type="number" min="1" value={estimatedSecondsMin} onChange={(event) => setEstimatedSecondsMin(Number(event.target.value))} /></label>
    <label>{locale === "zh" ? "预计耗时最大秒数" : "Maximum estimated seconds"}<input required type="number" min={estimatedSecondsMin} value={estimatedSecondsMax} onChange={(event) => setEstimatedSecondsMax(Number(event.target.value))} /></label>
    <p className="notice">{locale === "zh" ? `已选择 ${exampleArtifactIds.length} 个公开示例 Artifact。` : `${exampleArtifactIds.length} public example Artifact(s) selected.`}</p>
    <button type="submit">{locale === "zh" ? "创建草稿" : "Create draft"}</button>
    <button type="button" disabled={!versionId} onClick={() => action("certify")}>{locale === "zh" ? "运行自动认证" : "Run certification"}</button>
    <button type="button" disabled={!versionId} onClick={() => action("publish")}>{locale === "zh" ? "发布" : "Publish"}</button>
    {result && <pre>{result}</pre>}
    </form>
  </>;
}
