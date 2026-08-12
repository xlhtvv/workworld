"use client";

import {useState} from "react";
import {apiFetch} from "@/lib/api";

export function WalletPanel({locale}: {locale: "en" | "zh"}) {
  const [token, setToken] = useState("");
  const [wallet, setWallet] = useState<Record<string, unknown>>({});
  const [message, setMessage] = useState("");

  function accessToken() {
    return token || localStorage.getItem("workworld_access_token") || undefined;
  }

  async function load() {
    const response = await apiFetch("/v1/wallet", accessToken());
    const document = await response.json();
    if (response.ok) setWallet(document as Record<string, unknown>);
    else setMessage(JSON.stringify(document));
  }

  async function claim() {
    const response = await apiFetch("/v1/wallet/daily-grant", accessToken(), {method: "POST"});
    setMessage(JSON.stringify(await response.json(), null, 2));
    if (response.ok) await load();
  }

  return <section className="run-layout">
    <div className="panel form-grid">
      <label>{locale === "zh" ? "访问令牌" : "Access token"}<input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder={locale === "zh" ? "使用登录时保存的令牌" : "Uses saved sign-in token"} /></label>
      <button type="button" onClick={() => void load()}>{locale === "zh" ? "刷新余额" : "Refresh balances"}</button>
      <button type="button" onClick={() => void claim()}>{locale === "zh" ? "领取每日 10,000 Token" : "Claim daily 10,000 Tokens"}</button>
      <p className="notice">{locale === "zh" ? "测试 Token 不可提现、不可转让且没有法币价值。所有余额均从不可变平衡账本重建。" : "Test Tokens cannot be withdrawn or transferred and have no fiat value. Every balance is reconstructed from the immutable balanced ledger."}</p>
      {message && <pre>{message}</pre>}
    </div>
    <div className="panel"><h2>{locale === "zh" ? "账本余额" : "Ledger balances"}</h2><pre>{JSON.stringify(wallet, null, 2)}</pre></div>
  </section>;
}
