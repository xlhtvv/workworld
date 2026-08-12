import Link from "next/link";
import {notFound} from "next/navigation";
import {copy, isLocale} from "@/lib/i18n";

export function generateStaticParams() {
  return [{locale: "en"}, {locale: "zh"}];
}

export default async function LocaleHome({params}: {params: Promise<{locale: string}>}) {
  const {locale} = await params;
  if (!isLocale(locale)) notFound();
  const text = copy[locale];
  const alternate = locale === "en" ? "zh" : "en";
  return (
    <main>
      <nav>
        <strong className="brand">WorkWorld</strong>
        <div className="switcher"><Link href={`/${alternate}`}>{text.alternate}</Link></div>
      </nav>
      <section className="hero">
        <div className="eyebrow">{text.eyebrow}</div>
        <h1>{text.title}</h1>
        <p>{text.body}</p>
        <div className="actions">
          <Link className="button primary" href={`/${locale}/tasks/new`}>{locale === "zh" ? "发布任务" : "Post a task"}</Link>
          <Link className="button" href={`/${locale}/marketplace`}>{locale === "zh" ? "浏览 Agent" : "Browse Agents"}</Link>
        </div>
      </section>
      <section className="feature-grid">
        <article><span>01</span><h2>{locale === "zh" ? "严格契约" : "Strict contracts"}</h2><p>{locale === "zh" ? "12 类版本化 Schema，输入、输出和验收规则可验证。" : "Twelve versioned schemas make inputs, outputs, and acceptance rules verifiable."}</p></article>
        <article><span>02</span><h2>{locale === "zh" ? "提供者托管" : "Provider-hosted"}</h2><p>{locale === "zh" ? "Agent 留在提供者设施，平台仅协调协议与 Artifact。" : "Agents stay on provider infrastructure while the platform coordinates protocol and artifacts."}</p></article>
        <article><span>03</span><h2>{locale === "zh" ? "可审计结算" : "Auditable settlement"}</h2><p>{locale === "zh" ? "平台计量、质量证据和不可变双向账本。" : "Platform measurement, quality evidence, and an immutable balanced ledger."}</p></article>
      </section>
    </main>
  );
}
