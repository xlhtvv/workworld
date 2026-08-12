import Link from "next/link";
import {notFound} from "next/navigation";
import {ResourcePanel} from "@/app/components/resource-panel";
import {TaskComposer} from "@/app/components/task-composer";
import {TaskPanel} from "@/app/components/task-panel";
import {AuthPanel} from "@/app/components/auth-panel";
import {AgentForm} from "@/app/components/agent-form";
import {OfferingForm} from "@/app/components/offering-form";
import {RunPanel} from "@/app/components/run-panel";
import {VerifyEmailPanel} from "@/app/components/verify-email-panel";
import {WalletPanel} from "@/app/components/wallet-panel";
import {AdminPanel} from "@/app/components/admin-panel";
import {ProfilePanel} from "@/app/components/profile-panel";
import {isLocale} from "@/lib/i18n";

const pages: Record<string, {en: string; zh: string; endpoint?: string; publicAccess?: boolean}> = {
  marketplace: {en: "Agent marketplace", zh: "Agent 市场", endpoint: "/v1/marketplace", publicAccess: true},
  dashboard: {en: "Workspace overview", zh: "工作台", endpoint: "/v1/tasks"},
  login: {en: "Sign in", zh: "登录"},
  register: {en: "Create an account", zh: "创建账户"},
  "verify-email": {en: "Verify email", zh: "验证邮箱"},
  tasks: {en: "My tasks", zh: "我的任务", endpoint: "/v1/tasks"},
  "tasks/new": {en: "Create a schema-driven task", zh: "按 Schema 创建任务"},
  applications: {en: "Sealed applications", zh: "密封申请", endpoint: "/v1/applications"},
  wallet: {en: "Test Token wallet", zh: "测试 Token 钱包", endpoint: "/v1/wallet"},
  agents: {en: "My Agents", zh: "我的 Agents", endpoint: "/v1/agents"},
  "agents/new": {en: "Register an Agent", zh: "注册 Agent"},
  offerings: {en: "Offering versions", zh: "Offering 版本", endpoint: "/v1/marketplace", publicAccess: true},
  "offerings/new": {en: "Create an Offering", zh: "创建 Offering"},
  "admin/users": {en: "Admin · Users", zh: "管理 · 用户", endpoint: "/v1/admin/users"},
  "admin/schemas": {en: "Admin · Schemas", zh: "管理 · Schema", endpoint: "/v1/schemas", publicAccess: true},
  "admin/metering": {en: "Admin · Metering", zh: "管理 · 计量", endpoint: "/v1/admin/metering"},
  "admin/agents": {en: "Admin · Agents", zh: "管理 · Agents", endpoint: "/v1/admin/agents"},
  "admin/offerings": {en: "Admin · Offerings", zh: "管理 · Offerings", endpoint: "/v1/admin/offerings"},
  "admin/tasks": {en: "Admin · Tasks", zh: "管理 · 任务", endpoint: "/v1/admin/tasks"},
  "admin/audit": {en: "Admin · Audit", zh: "管理 · 审计", endpoint: "/v1/admin/audit"},
  "admin/ledger": {en: "Admin · Ledger", zh: "管理 · 账本", endpoint: "/v1/admin/users"},
  "admin/system": {en: "Admin · System", zh: "管理 · 系统", endpoint: "/v1/admin/system"},
};

export default async function ProductPage({params}: {params: Promise<{locale: string; slug: string[]}>}) {
  const {locale, slug} = await params;
  if (!isLocale(locale)) notFound();
  const key = slug.join("/");
  const dynamic = key.startsWith("tasks/") && key !== "tasks/new"
    ? {en: "Task detail", zh: "任务详情", endpoint: `/v1/tasks/${slug[1]}`}
    : key.startsWith("runs/")
      ? {en: "Run timeline", zh: "Run 时间线", endpoint: `/v1/runs/${slug[1]}`}
      : key.startsWith("providers/")
        ? {en: "Provider reputation", zh: "提供者信誉", endpoint: `/v1/providers/${slug[1]}/reputation`, publicAccess: true}
        : key.startsWith("profile/")
          ? {en: "Provider profile", zh: "提供者主页", endpoint: `/v1/profile/${slug[1]}`, publicAccess: true}
          : key.startsWith("marketplace/")
            ? {en: "Offering detail", zh: "Offering 详情", endpoint: `/v1/marketplace/${slug[1]}`, publicAccess: true}
            : key.startsWith("agents/") && slug.length === 2
              ? {en: "Agent detail", zh: "Agent 详情", endpoint: `/v1/agents/${slug[1]}`}
              : key.startsWith("agents/") && slug[2] === "offerings" && slug[3] === "new"
                ? {en: "Create an Offering", zh: "创建 Offering"}
                : key.startsWith("offerings/")
                  ? {en: "Offering detail", zh: "Offering 详情", endpoint: `/v1/marketplace/${slug[1]}`, publicAccess: true}
                  : undefined;
  const page = pages[key] ?? dynamic;
  if (!page) notFound();
  const isNewTask = key === "tasks/new";
  const isNewAgent = key === "agents/new";
  const isNewOffering = key === "offerings/new" || (slug[0] === "agents" && slug[2] === "offerings" && slug[3] === "new");
  const isRun = key.startsWith("runs/") && Boolean(slug[1]);
  const isTask = key.startsWith("tasks/") && key !== "tasks/new" && Boolean(slug[1]);
  const isWallet = key === "wallet";
  const isProfile = key.startsWith("profile/") && Boolean(slug[1]);
  const isEmailVerification = key === "verify-email";
  const authMode = key === "login" || key === "register" ? key : undefined;
  const isAdmin = key.startsWith("admin/") && Boolean(page.endpoint);
  return (
    <main>
      <nav className="product-nav">
        <Link className="brand" href={`/${locale}`}>WorkWorld</Link>
        <div className="nav-links">
          <Link href={`/${locale}/marketplace`}>{locale === "zh" ? "市场" : "Marketplace"}</Link>
          <Link href={`/${locale}/tasks`}>{locale === "zh" ? "任务" : "Tasks"}</Link>
          <Link href={`/${locale}/agents`}>Agents</Link>
          <Link href={`/${locale}/wallet`}>{locale === "zh" ? "钱包" : "Wallet"}</Link>
          <Link href={`/${locale === "en" ? "zh" : "en"}/${key}`}>{locale === "en" ? "中文" : "English"}</Link>
        </div>
      </nav>
      <header className="page-head">
        <span className="eyebrow">{key.startsWith("admin") ? (locale === "zh" ? "运营管理" : "Operations") : (locale === "zh" ? "工作空间" : "Workspace")}</span>
        <h1>{page[locale]}</h1>
        <p>{locale === "zh" ? "此页面直接连接 WorkWorld API；私有数据需要 Access Token。" : "This surface connects directly to the WorkWorld API. Private data requires an access token."}</p>
      </header>
      {isAdmin && <nav className="admin-nav">
        {["users", "agents", "offerings", "tasks", "metering", "audit", "ledger", "system"].map((item) => <Link key={item} href={`/${locale}/admin/${item}`}>{locale === "zh" ? ({users: "用户", agents: "Agents", offerings: "Offerings", tasks: "任务", metering: "计量", audit: "审计", ledger: "账本", system: "系统"} as Record<string, string>)[item] : item}</Link>)}
      </nav>}
      {authMode ? <AuthPanel mode={authMode} locale={locale} /> : isEmailVerification ? <VerifyEmailPanel locale={locale} /> : isNewTask ? <TaskComposer locale={locale} /> : isNewAgent ? <AgentForm locale={locale} /> : isNewOffering ? <OfferingForm locale={locale} /> : isRun ? <RunPanel runId={slug[1]} locale={locale} /> : isTask ? <TaskPanel taskId={slug[1]} locale={locale} /> : isWallet ? <WalletPanel locale={locale} /> : isProfile ? <ProfilePanel identifier={slug[1]} locale={locale} /> : isAdmin && page.endpoint ? <AdminPanel section={slug[1]} endpoint={page.endpoint} locale={locale} /> : page.endpoint ? <ResourcePanel endpoint={page.endpoint} publicAccess={page.publicAccess} locale={locale} /> : <section className="panel"><p>{locale === "zh" ? "使用 API 创建并发布版本化资源。" : "Use the API-backed workflow to create and publish versioned resources."}</p></section>}
    </main>
  );
}
