"use client";

import {useState} from "react";
import {apiFetch} from "@/lib/api";

export function ResourcePanel({endpoint, publicAccess = false, locale}: {endpoint: string; publicAccess?: boolean; locale: "en" | "zh"}) {
  const [token, setToken] = useState("");
  const [result, setResult] = useState("—");
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const savedToken = token || localStorage.getItem("workworld_access_token") || undefined;
      const response = await apiFetch(endpoint, publicAccess ? undefined : savedToken);
      const document = await response.json();
      setResult(JSON.stringify(document, null, 2));
    } catch (error) {
      setResult(error instanceof Error ? error.message : (locale === "zh" ? "请求失败" : "Request failed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="panel api-panel">
      {!publicAccess && (
        <label>
          {locale === "zh" ? "访问令牌" : "Access token"}
          <input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="ey…" />
        </label>
      )}
      <button onClick={load} disabled={loading}>{loading ? (locale === "zh" ? "加载中…" : "Loading…") : (locale === "zh" ? "加载实时数据" : "Load live data")}</button>
      <pre>{result}</pre>
    </section>
  );
}
