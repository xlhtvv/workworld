"use client";

import {useState} from "react";
import {apiFetch} from "@/lib/api";

export function AuthPanel({mode, locale}: {mode: "login" | "register"; locale: "en" | "zh"}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [result, setResult] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const response = await apiFetch(`/v1/auth/${mode}`, undefined, {
      method: "POST", body: JSON.stringify({email, password}),
    });
    const document = await response.json() as {access_token?: string; detail?: string};
    if (document.access_token) localStorage.setItem("workworld_access_token", document.access_token);
    setResult(document.access_token
      ? (locale === "zh" ? "访问令牌已保存在当前浏览器中。" : "Access token saved in this browser.")
      : JSON.stringify(document));
  }
  return <form className="panel form-grid" onSubmit={submit}>
    <label>{locale === "zh" ? "邮箱" : "Email"}<input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
    <label>{locale === "zh" ? "密码" : "Password"}<input type="password" minLength={mode === "register" ? 12 : undefined} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
    <button type="submit">{mode === "login" ? (locale === "zh" ? "登录" : "Sign in") : (locale === "zh" ? "创建账户" : "Create account")}</button>
    {result && <p>{result}</p>}
  </form>;
}
