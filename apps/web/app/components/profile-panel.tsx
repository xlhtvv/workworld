"use client";

import {useCallback, useEffect, useState} from "react";
import {apiFetch} from "@/lib/api";

type Review = {id: string; rating: number; body: string; reply?: string | null};
type Profile = {
  provider_id?: string;
  display_name?: string;
  bio?: string;
  reputation?: Record<string, unknown>;
  reviews?: Review[];
  agents?: unknown[];
  offerings?: unknown[];
};

export function ProfilePanel({identifier, locale}: {identifier: string; locale: "en" | "zh"}) {
  const [profile, setProfile] = useState<Profile>({});
  const [token, setToken] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [bio, setBio] = useState("");
  const [reviewId, setReviewId] = useState("");
  const [replyBody, setReplyBody] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    const response = await apiFetch(`/v1/profile/${encodeURIComponent(identifier)}`);
    const document = await response.json() as Profile & {detail?: string};
    if (!response.ok) {
      setMessage(JSON.stringify(document));
      return;
    }
    setProfile(document);
    setDisplayName(document.display_name ?? "");
    setBio(document.bio ?? "");
  }, [identifier]);

  useEffect(() => {
    let cancelled = false;
    void apiFetch(`/v1/profile/${encodeURIComponent(identifier)}`).then(async (response) => {
      const document = await response.json() as Profile & {detail?: string};
      if (cancelled) return;
      if (!response.ok) {
        setMessage(JSON.stringify(document));
        return;
      }
      setProfile(document);
      setDisplayName(document.display_name ?? "");
      setBio(document.bio ?? "");
    }).catch((error: unknown) => {
      if (!cancelled) setMessage(error instanceof Error ? error.message : (locale === "zh" ? "请求失败" : "Request failed"));
    });
    return () => { cancelled = true; };
  }, [identifier, locale]);

  function accessToken() {
    return token || localStorage.getItem("workworld_access_token") || undefined;
  }

  async function submit(path: string, method: "POST" | "PUT", body: object) {
    const response = await apiFetch(path, accessToken(), {method, body: JSON.stringify(body)});
    const document: unknown = await response.json();
    setMessage(JSON.stringify(document, null, 2));
    if (response.ok) await load();
  }

  return <section className="run-layout">
    <div className="panel">
      <h2>{profile.display_name ?? identifier}</h2>
      <p>{profile.bio}</p>
      <h3>{locale === "zh" ? "信誉" : "Reputation"}</h3>
      <pre>{JSON.stringify(profile.reputation, null, 2)}</pre>
      <h3>{locale === "zh" ? "公开评价" : "Public reviews"}</h3>
      {profile.reviews?.map((review) => <article className="candidate" key={review.id}>
        <strong>{review.rating}/5</strong>
        <span>{review.body}</span>
        {review.reply && <p>{locale === "zh" ? "提供者回复：" : "Provider reply: "}{review.reply}</p>}
      </article>)}
    </div>
    <form className="panel form-grid" onSubmit={(event) => {
      event.preventDefault();
      void submit("/v1/profile", "PUT", {display_name: displayName, bio});
    }}>
      <h2>{locale === "zh" ? "维护提供者资料" : "Maintain provider profile"}</h2>
      <label>{locale === "zh" ? "访问令牌" : "Access token"}<input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder={locale === "zh" ? "使用已保存的提供者令牌" : "Uses saved provider token"} /></label>
      <label>{locale === "zh" ? "显示名称" : "Display name"}<input required value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
      <label>{locale === "zh" ? "简介" : "Bio"}<textarea required value={bio} onChange={(event) => setBio(event.target.value)} /></label>
      <button type="submit">{locale === "zh" ? "保存资料" : "Save profile"}</button>
    </form>
    <form className="panel form-grid" onSubmit={(event) => {
      event.preventDefault();
      void submit(`/v1/reviews/${encodeURIComponent(reviewId)}/reply`, "POST", {body: replyBody});
    }}>
      <h2>{locale === "zh" ? "回复评价" : "Reply to a review"}</h2>
      <label>Review ID<input required value={reviewId} onChange={(event) => setReviewId(event.target.value)} /></label>
      <label>{locale === "zh" ? "回复" : "Reply"}<textarea required value={replyBody} onChange={(event) => setReplyBody(event.target.value)} /></label>
      <button type="submit">{locale === "zh" ? "发布回复" : "Publish reply"}</button>
    </form>
    {message && <div className="panel"><pre>{message}</pre></div>}
  </section>;
}
