"use client";

import {useState} from "react";
import {apiFetch} from "@/lib/api";

export function VerifyEmailPanel({locale}: {locale: "en" | "zh"}) {
  const [token, setToken] = useState("");
  const [result, setResult] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const response = await apiFetch(`/v1/auth/verify-email?token=${encodeURIComponent(token)}`, undefined, {
      method: "POST",
    });
    const document = await response.json();
    setResult(response.ok
      ? (locale === "zh" ? "邮箱验证完成。" : "Email verification complete.")
      : JSON.stringify(document));
  }

  return <form className="panel form-grid" onSubmit={submit}>
    <label>{locale === "zh" ? "验证令牌" : "Verification token"}<input required value={token} onChange={(event) => setToken(event.target.value)} /></label>
    <button type="submit">{locale === "zh" ? "验证邮箱" : "Verify email"}</button>
    {result && <p>{result}</p>}
  </form>;
}
