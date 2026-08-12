"use client";

import {useCallback, useState} from "react";
import {apiFetch} from "@/lib/api";

type Row = Record<string, unknown>;

function rowId(row: Row): string {
  return typeof row.id === "string" ? row.id : "";
}

export function AdminPanel({
  section,
  endpoint,
  locale,
}: {
  section: string;
  endpoint: string;
  locale: "en" | "zh";
}) {
  const [token, setToken] = useState("");
  const [data, setData] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [adjustment, setAdjustment] = useState({userId: "", amount: "", reason: ""});

  const accessToken = useCallback(
    () => token || localStorage.getItem("workworld_access_token") || undefined,
    [token],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await apiFetch(endpoint, accessToken());
      const document: unknown = await response.json();
      setData(document);
      setMessage(response.ok ? "" : JSON.stringify(document));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : (locale === "zh" ? "请求失败" : "Request failed"));
    } finally {
      setLoading(false);
    }
  }, [accessToken, endpoint, locale]);

  async function post(path: string, body?: object) {
    setLoading(true);
    const response = await apiFetch(path, accessToken(), {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    const document: unknown = await response.json();
    setMessage(JSON.stringify(document, null, 2));
    setLoading(false);
    if (response.ok) await load();
  }

  async function adjust(event: React.FormEvent) {
    event.preventDefault();
    await post("/v1/admin/ledger/adjustments", {
      user_id: adjustment.userId,
      amount: Number(adjustment.amount),
      reason: adjustment.reason,
      idempotency_key: `admin-ui:${crypto.randomUUID()}`,
    });
  }

  const rows = Array.isArray(data) ? (data as Row[]) : [];
  const suspendPath = (id: string) =>
    section === "users"
      ? `/v1/admin/users/${encodeURIComponent(id)}/suspend`
      : section === "agents"
        ? `/v1/admin/agents/${encodeURIComponent(id)}/suspend`
        : `/v1/admin/offerings/${encodeURIComponent(id)}/suspend`;
  const canSuspend = ["users", "agents", "offerings"].includes(section);

  return (
    <section className="run-layout">
      <div className="panel form-grid">
        <label>
          {locale === "zh" ? "访问令牌" : "Access token"}
          <input
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder={locale === "zh" ? "使用已保存的管理员令牌" : "Uses saved administrator token"}
          />
        </label>
        <button type="button" disabled={loading} onClick={() => void load()}>
          {loading ? (locale === "zh" ? "加载中…" : "Loading…") : locale === "zh" ? "刷新" : "Refresh"}
        </button>
        <p className="notice">
          {locale === "zh"
            ? "停用操作不会删除历史记录；账本调整会创建新的平衡交易。"
            : "Suspension never deletes history. Ledger adjustments create new balanced transactions."}
        </p>
        {message && <pre>{message}</pre>}
      </div>

      {section === "ledger" && (
        <form className="panel form-grid" onSubmit={adjust}>
          <h2>{locale === "zh" ? "账本调整" : "Ledger adjustment"}</h2>
          <label>
            User ID
            <input
              required
              value={adjustment.userId}
              onChange={(event) => setAdjustment({...adjustment, userId: event.target.value})}
            />
          </label>
          <label>
            {locale === "zh" ? "数量（可为负）" : "Amount (may be negative)"}
            <input
              required
              type="number"
              value={adjustment.amount}
              onChange={(event) => setAdjustment({...adjustment, amount: event.target.value})}
            />
          </label>
          <label>
            {locale === "zh" ? "原因" : "Reason"}
            <textarea
              required
              value={adjustment.reason}
              onChange={(event) => setAdjustment({...adjustment, reason: event.target.value})}
            />
          </label>
          <button type="submit" disabled={loading}>
            {locale === "zh" ? "创建调整交易" : "Create adjustment transaction"}
          </button>
        </form>
      )}

      {rows.length > 0 ? (
        <div className="panel admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                {Object.keys(rows[0]).map((key) => <th key={key}>{key}</th>)}
                {canSuspend && <th>{locale === "zh" ? "操作" : "Action"}</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={rowId(row)}>
                  {Object.entries(row).map(([key, value]) => (
                    <td key={key}>{typeof value === "object" ? JSON.stringify(value) : String(value)}</td>
                  ))}
                  {canSuspend && (
                    <td>
                      <button
                        type="button"
                        disabled={loading || row.suspended === true || row.status === "suspended"}
                        onClick={() => void post(suspendPath(rowId(row)))}
                      >
                        {locale === "zh" ? "停用" : "Suspend"}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : section !== "ledger" ? (
        <div className="panel"><pre>{JSON.stringify(data, null, 2)}</pre></div>
      ) : null}
    </section>
  );
}
