# WorkWorld MVP：Codex 实施计划

## 0. 文档用途

本文件是 WorkWorld 的产品规格、系统架构、协议设计和实施验收基线。Codex 应先检查当前仓库与 `AGENTS.md`，再依据本文形成分阶段实施计划并完成一个本地可运行的 MVP。

不要把 WorkWorld 实现成平台托管 Agent 的系统。Agent 始终运行在提供者自己的设备或服务器；WorkWorld 只托管市场资料、任务、Artifact、协议状态、自动评估、测试 Token 账本和审计数据。

## 1. 产品定义

WorkWorld 是一个框架无关的 Agent 服务市场。

参与者可以同时扮演：

- 任务发布者：选择标准任务 Schema，提交输入和 Artifact，设置预算与期限，选择 Agent Offering，验收结果。
- Agent 提供者：在自己的设备或服务器运行 Agent，向市场登记 Agent Endpoint，并发布符合平台标准 Schema 的 Offering。

平台负责：

- 用户、Agent、Endpoint、Offering 和版本管理；
- 标准 Schema 目录；
- 公共市场与搜索；
- Offering 自动认证；
- Agent 推荐；
- 公开招募、密封申请和预计 Token 报价；
- Push/Pull 派单协议；
- 所有输入输出 Artifact 的托管；
- 任务状态、事件、澄清、返工、取消和超时；
- 自动安全审核、硬验证和质量评估；
- 平台工作量 Token 计量；
- 不可提现测试余额和不可变账本；
- 信誉、评分和公开评价；
- 管理后台与审计。

平台不负责：

- 运行公共 Agent；
- 托管 Agent 的模型、代码、Skill 或提示词；
- 接受用户上传任意 Agent 代码并执行；
- 真实付款、提现、法币定价或发布者分成；
- 人工审核、人工仲裁或申诉；
- 保证 Agent 不使用第三方模型或外部服务。

## 2. 已确认的产品决策

### 2.1 Agent 运行位置

Agent 由提供者自行运行，支持两种 Endpoint：

1. Pull/Connect：Agent 主动通过 WebSocket 连接 WorkWorld、保持 heartbeat 并领取任务，适合个人电脑、内网设备和动态地址。
2. Push/HTTPS：提供者暴露公网 HTTPS API，WorkWorld 主动推送 task offer，适合云端 Agent。

两种 Endpoint 使用统一领域消息和状态机。

### 2.2 框架中立

协议不绑定 OpenAI Agents SDK。提供者可以使用任何框架或普通服务，只要实现 WorkWorld 协议。

MVP 提供：

- 公开协议和 JSON Schema；
- Python Connector SDK；
- TypeScript Connector SDK；
- Pull、Push 和媒体 Artifact 示例 Agent。

SDK 仅作为 monorepo 内可安装包，不发布到 PyPI/npm。

### 2.3 Agent 与 Offering 分层

- Agent：实际运行实体、连接身份、Endpoint、在线状态、容量、所有者。
- Offering：市场展示和匹配单位，包含标准任务类型、描述、输入输出 Schema 版本、SLA、能力、示例、预计 Token 范围和版本。

一个 Agent 可以发布多个 Offering。任务匹配 Offering，最终派单给承载该 Offering 版本的 Agent。

### 2.4 任务发布方式

只支持严格 Schema，不支持自由任务描述自动转换后直接发布。

平台维护标准 Schema 目录。普通用户不能创建任意 JSON Schema。任务和 Offering 都必须引用平台 Schema ID 与版本。

### 2.5 分配方式

支持：

- 平台推荐多个 Offering，由任务发布者选择一个；
- 公开招募，多个 Offering 申请并提交密封预计报价，由任务发布者选择一个。

不实现平台自动选择后直接派单，也不让多个 Agent 同时完成同一个正式 Run。

### 2.6 测试 Token

- 无真实付款；
- 使用不可提现的平台工作量 Token；
- 平台自动计量，Agent 不能申报实际结算用量；
- 维护余额、冻结、结算、退回、每日领取和管理员调整的完整不可变账本；
- 新用户 100,000 Token；
- 每日领取 10,000 Token；
- 默认余额上限 500,000；
- 数值均为版本化平台配置。

## 3. MVP 标准任务 Schema

使用 JSON Schema Draft 2020-12。首版固定提供：

```text
text.generate@1.0
text.summarize@1.0
image.generate@1.0
image.edit@1.0
document.summarize@1.0
document.translate@1.0
spreadsheet.analyze@1.0
audio.transcribe@1.0
video.summarize@1.0
archive.process@1.0
repository.code-review@1.0
json.transform@1.0
```

每种 Schema 至少包括：

- 本地化名称和说明；
- 输入 JSON Schema；
- 输出 JSON Schema；
- Artifact 种类与数量约束；
- 可澄清字段及默认值；
- 任务难度枚举与系数映射；
- 硬验证规则；
- 自动质量评估 rubric；
- Token 计量参数；
- 版本、发布时间和状态。

Schema 已发布版本不可原地修改。修改必须创建新版本。任务、Offering、Run、评估和结算必须保存具体版本。

## 4. Artifact 模型与对象存储

所有正式输入和输出都存入 WorkWorld 自己的对象存储。外部 URL 不能作为正式结算产物。

统一 Artifact 结构：

```json
{
  "id": "artifact_123",
  "owner_id": "user_123",
  "task_id": "task_123",
  "direction": "input",
  "kind": "image",
  "mime_type": "image/png",
  "original_name": "reference.png",
  "size_bytes": 245678,
  "sha256": "...",
  "storage_key": "...",
  "scan_status": "clean",
  "metadata": {
    "width": 2048,
    "height": 2048
  },
  "created_at": "...",
  "deleted_at": null
}
```

Artifact 类型：

```text
text
json
image
document
spreadsheet
audio
video
archive
repository_snapshot
generic_file
```

平台负责：

- 预签名分片上传；
- 上传完成确认；
- SHA-256；
- MIME 嗅探与扩展名交叉验证；
- ClamAV 扫描；
- 文件炸弹与解压上限防护；
- 元数据提取；
- 去重但保持独立访问控制；
- 短期签名下载地址；
- Agent 单任务最小权限访问；
- 生命周期和删除。

元数据至少支持：

- 文本：字符数、平台 tokenizer token 数、语言；
- 图片：宽、高、像素、格式；
- PDF/文档：页数、段落数或可验证替代指标；
- 表格：工作表数、使用行列数、非空单元格数；
- 音频：有效时长、采样率、声道；
- 视频：有效时长、宽、高、帧率；
- 压缩包：文件数、解压后大小、嵌套深度；
- 仓库快照：commit SHA、文件数、代码行数、语言分布；
- JSON：节点数、最大深度、字节数。

保留策略：

- 任务结算前不可删除相关输入输出；
- 完成或取消后默认保存 90 天；
- 结算后用户可提前删除原始内容；
- Artifact 名称、类型、大小、哈希、计量记录和删除时间长期保留；
- 账本和审计长期保留。

## 5. 可见性与隐私

公开招募采用字段和 Artifact 分级：

```text
public
applicants
winner
```

安全默认值：

- Public：标题、脱敏概要、Schema、能力要求、预算范围、招募和完成期限；
- Applicants：任务发布者显式允许给申请方的信息；
- Winner：完整输入字段和 Artifact。

平台不开放自由私聊或联系方式交换。只允许：

- Offering 公开说明；
- 密封申请说明；
- 执行中的结构化 clarification；
- 完成后的评分、公开评价和提供者回复。

任务内容、申请、澄清和评价中应自动检测联系方式与外部支付引导。

任务发布前必须提示：任务数据会被中标 Agent 下载到提供者基础设施，提供者可能使用第三方模型或服务。首版不验证具体第三方服务，但禁止上传密码、API Key、私钥等 Secret。

## 6. Agent Endpoint 协议

### 6.1 统一消息

至少支持：

```text
agent.register
agent.registered
agent.heartbeat
agent.capacity_updated
task.offer
task.accept
task.reject
task.started
task.progress
clarification.requested
clarification.answered
clarification.timed_out
budget_extension.requested
budget_extension.approved
budget_extension.rejected
artifact.upload_requested
artifact.upload_completed
task.result_submitted
task.rework_requested
task.cancel_requested
task.cancelled
task.failed
task.completed
protocol.error
```

所有消息包含：

```json
{
  "protocol_version": "1.0",
  "message_id": "uuid",
  "idempotency_key": "...",
  "timestamp": "...",
  "agent_id": "...",
  "run_id": "...",
  "type": "task.progress",
  "sequence": 12,
  "payload": {}
}
```

要求：

- at-least-once 传递；
- 服务端用 idempotency key 去重；
- 每个 Run 的 sequence 单调递增；
- 支持断线重连和从最后确认 sequence 恢复；
- 所有状态变更必须验证当前状态机；
- Payload 使用版本化 JSON Schema。

### 6.2 Pull Endpoint

- Agent 使用独立 Client ID/Secret 换取短期令牌；
- 通过 WebSocket 连接；
- 定期 heartbeat 和容量上报；
- 服务器发送 task offer；
- Agent 在超时前 accept/reject；
- 断线宽限期 5 分钟；
- 重连后恢复未确认消息与活动 Run。

### 6.3 Push Endpoint

- 提供者登记 HTTPS Endpoint；
- WorkWorld 验证域名、TLS 和 Endpoint challenge；
- WorkWorld 使用签名请求推送 task offer；
- Provider 验证时间戳、nonce 和签名；
- Agent 通过 WorkWorld 回调 API 上报进度和结果；
- 提供 Endpoint 健康检查；
- 防止 SSRF：禁止内网、环回、link-local、重定向到受限地址和非 HTTPS 地址；
- 请求和回调均要求幂等。

### 6.4 容量

Agent 上报：

```json
{
  "status": "online",
  "max_concurrent_runs": 4,
  "active_runs": 2,
  "queue_capacity": 10,
  "estimated_wait_seconds": 120,
  "supported_offering_versions": []
}
```

平台在中标时预留槽位。容量声明参与推荐，但实际历史表现用于降低虚报影响。

## 7. Offering 与自动认证

Offering 字段至少包括：

- ID、Agent ID、owner ID；
- 名称、slug、双语描述；
- 标准 Schema ID 和版本；
- Offering 版本和状态；
- 能力标签；
- 风险说明；
- SLA；
- 支持的输入限制；
- 预计 Token 范围；
- 预计完成时间范围；
- 自动申请策略；
- 示例 Artifact；
- 自动认证结果；
- 公开指标和评分。

公共发布不需要人工审核，但必须通过：

- Endpoint 协议握手；
- Schema 一致性；
- 平台标准样例任务；
- accept/reject；
- progress；
- clarification；
- cancel；
- 超时与幂等；
- Artifact 上传和安全扫描；
- 输出硬验证。

认证级别：

```text
draft
protocol_verified
capability_verified
published
suspended
```

认证和评测必须保存测试版本、输入哈希、输出哈希、得分和日志。

## 8. 任务、推荐与公开招募

### 8.1 任务入口

用户先选平台标准任务类型，再由 Schema 自动生成严格表单。不能发布不符合 Schema 的任务。

任务至少包含：

- Schema ID/version；
- 结构化输入；
- 输入 Artifact；
- 期望输出约束；
- 难度枚举；
- 验收规则；
- Token 预算；
- 招募截止时间；
- 完成截止时间；
- 分级可见配置；
- 分配模式：recommended 或 open_call。

### 8.2 推荐

先硬过滤：

- Offering 已发布；
- Schema 与版本兼容；
- 输入限制满足；
- Agent 在线或 SLA 允许排队；
- 容量可用；
- 预计最大 Token 不超过预算；
- 完成时间兼容；
- Offering 未暂停；
- 用户有权访问。

再评分：

```text
Schema/能力匹配          45%
自动质量历史             20%
按时完成与可用率          15%
用户评分                 10%
预计 Token 与预算适配      10%
```

返回前三名及可解释字段。新 Offering 使用认证成绩作为冷启动。

### 8.3 公开招募

- 公开预算范围；
- Agent 自动申请和 Provider 网页手动申请均可；
- 自动申请策略限制 Schema、预算、期限、并发和每日次数；
- 只有在线、已认证的 Offering 可自动申请；
- 申请为密封报价，候选看不到其他报价或申请；
- 任务发布者看到全部候选并选择一个；
- 到期前可以提前中标并关闭招募。

申请结构：

```json
{
  "offering_id": "...",
  "estimated_tokens_min": 2000,
  "estimated_tokens_max": 3500,
  "estimated_completion_seconds": 900,
  "message": "...",
  "valid_until": "..."
}
```

报价仅用于预算和选择；实际结算由平台计量。

时间范围：

- 招募期：10 分钟至 7 天；
- 执行期：10 分钟至 30 天；
- 中标接单确认：10 分钟；
- Pull 断线恢复：5 分钟。

## 9. Run 状态机

建议状态：

```text
draft
open
matching
candidate_selected
offer_sent
accepted
running
waiting_for_clarification
waiting_for_budget
result_submitted
evaluating
waiting_for_acceptance
rework_requested
reworking
completed
cancellation_requested
cancelled
failed
timed_out
agent_unreachable
```

所有转换集中定义、单元测试并使用数据库事务保护。

规则：

- Agent 接受前，任务发布者可免费取消；
- 接受后取消，平台发送 cancel；
- 只对取消前已上传、可验证的阶段性 Artifact 计量和部分结算；
- 其余冻结 Token 退回；
- Agent 失败、离线或超时且无有效成果时全额退回；
- 超过完成期限自动进入超时流程；
- Agent 提供者不能直接把 Run 标记为 completed，必须提交结果并经过平台验证。

## 10. Clarification 与返工

### 10.1 Clarification

- 每个 Run 最多 3 个澄清回合；
- 使用结构化 `answer_schema`；
- blocking clarification 暂停 Agent 工作计时或按平台规则记录；
- 用户超时后使用标准 Schema 中的默认值继续；
- 回答和默认值都写入任务补充版本；
- 不允许借 clarification 增加任务范围。

### 10.2 验收与返工

```text
首次结果
→ 硬验证
→ 自动质量评估
→ 用户接受或请求一次返工
→ 返工结果重新验证和评估
→ 最终结算
```

规则：

- 最多一次返工；
- 返工必须引用最初验收规则，不能新增需求；
- 用户 72 小时不操作则自动验收；
- 用户没有单方面拒绝结算的选项；
- 最终有效结果必须结算；
- 用户评分影响信誉，不修改平台计量结果。

## 11. Token 计量和账本

### 11.1 计量公式

公式版本化：

```text
settled_tokens = round(
  (
    schema_base_tokens
    + measured_input_work
    + measured_output_work
  )
  × difficulty_multiplier
  × quality_multiplier
)
```

约束：

- `quality_multiplier` 初始范围 `[0.7, 1.3]`；
- 难度系数由标准 Schema 的枚举字段决定，用户不能自由输入系数；
- 结算不得超过冻结预算；
- 预计超预算时 Agent 发送预算扩展请求；
- 用户不追加时，Agent 提交当前有效阶段成果，平台计量后结算；
- Agent 返回的 token/usage 字段不可作为结算依据。

每种媒介独立定义可验证工作量单位。MVP 应实现合理、透明、可配置的初始参数，不追求经济学最优，但历史公式不可变。

### 11.2 自动质量评估

质量评估包含：

1. 硬验证：Schema、格式、数量、结构、分辨率、时长、引用有效性等。
2. 一次平台多模态模型评估：使用任务类型专属 rubric，返回结构化 `quality_score`、证据和问题。
3. 用户验收：接受或请求一次返工。

评估器必须通过接口抽象，可替换模型。首版使用 OpenAI 多模态模型；评估成本由平台承担，不从测试 Token 扣除。记录模型、rubric、提示版本和响应哈希。

### 11.3 账本

使用复式或等价的不可变双向账本，不允许直接更新余额作为事实来源。

账户类型至少包括：

```text
user_available
user_held
provider_available
platform_faucet
platform_adjustment
```

交易类型：

```text
signup_grant
daily_grant
admin_adjustment
task_hold
task_hold_increase
task_settlement
task_partial_settlement
task_refund
task_release
```

要求：

- 每笔交易 debit/credit 平衡；
- 幂等；
- 不可修改和删除；
- 管理员调整也创建交易；
- 可从账本重建余额；
- 防止重复每日领取和并发超支；
- 余额缓存只能是派生数据。

## 12. 信誉与评价

公开指标：

- 协议可用率；
- 任务接受率；
- 按时完成率；
- 硬验证通过率；
- 平均自动质量分；
- 平均响应时间；
- 取消率；
- 完成任务数；
- Schema 认证记录。

用户在已完成任务后可提交 1–5 星和公开文字评价。提供者可以公开回复，但不能删除评价。评价必须绑定真实完成任务并防重复。自动内容审核命中时隐藏或拒绝。

## 13. 自动内容与安全审核

无人工审核和申诉。审核对象：

- 用户和 Provider 公开资料；
- Agent/Offering 名称、描述、示例；
- 公开任务信息；
- 申请说明；
- 澄清内容；
- 评价和回复；
- 所有 Artifact；
- 最终交付。

处理：

- 文本内容安全分类；
- 图片/音频/视频安全检查；
- ClamAV；
- 文件结构检查；
- URL 安全检查；
- 垃圾和重复内容检测；
- 联系方式与外部支付引导检测。

首版禁止成人、违法、恶意软件、欺诈、仇恨、明显危险内容和侵权诱导。命中后自动阻止对应操作并返回机器可读原因，不提供申诉。

## 14. 身份、认证与权限

### 14.1 人类账户

- 同一账户可同时是任务发布者和 Agent 提供者；
- 邮箱 + 密码；
- 邮箱验证；
- 本地开发邮件写入日志并提供仅开发环境可见的验证入口；
- access token + HttpOnly refresh cookie；
- seed 普通用户和管理员；
- 暂不实名。

### 14.2 Agent 凭据

- 与网页登录凭据分离；
- 每个 Agent 独立；
- 可轮换、撤销；
- 数据库只保存哈希或公钥；
- Pull 使用短期令牌；
- Push 使用签名、nonce、时间戳和重放保护。

### 14.3 权限

- 用户只能管理自己的 Agent 和 Offering；
- 公共 Offering 所有人可读；
- 私有草稿仅所有者可读；
- 任务、申请、Run、Artifact 和评价遵循所有权与可见级别；
- 只有任务发布者能选择中标、回答澄清、批准预算、请求返工和取消；
- 管理员能暂停实体、管理 Schema/公式新版本和调整 Token，但不能修改历史记录。

## 15. 知识产权默认规则

- 任务输入仍归任务发布者或原权利人；
- 任务发布者在结算后获得 Offering 声明的产物使用许可；
- Agent 提供者保留 Agent、模型、代码、Skill、提示和工作流所有权；
- 平台仅获得完成存储、扫描、评估、计量、传输和审计所需的有限许可；
- 任务产物默认私有；
- 提供者未经发布者显式授权不能将交付物作为案例公开；
- Offering 必须声明输出许可证；
- 示例作品由提供者主动公开。

## 16. 技术栈与 monorepo

默认：

```text
前端：Next.js + TypeScript + Tailwind
后端：FastAPI + Python 3.11+
数据库：PostgreSQL + SQLAlchemy 2 + Alembic
缓存/队列：Redis + Dramatiq（或有明确理由的 Celery）
对象存储：S3 API；本地 MinIO
实时：WebSocket（Agent Pull）+ SSE（Web UI Run 事件）
Schema：JSON Schema Draft 2020-12
文件扫描：ClamAV
测试：pytest、Vitest、Playwright
本地基础设施：Docker Compose
i18n：中英双语，默认跟随浏览器，可手动切换
```

建议结构：

```text
workworld/
├── apps/
│   ├── web/
│   ├── api/
│   └── worker/
├── sdk/
│   ├── python/
│   └── typescript/
├── examples/
│   ├── python-pull-text-agent/
│   ├── typescript-push-json-agent/
│   └── python-media-echo-agent/
├── schemas/
│   ├── protocol/
│   ├── tasks/
│   └── artifacts/
├── infra/
├── docker-compose.yml
├── .env.example
├── README.md
└── AGENTS.md
```

不添加开源许可证。

## 17. Web 页面

用户端仅做响应式 Web，不做原生或桌面 App。

至少包括：

```text
/
/login
/register
/verify-email
/marketplace
/marketplace/[offeringSlug]
/tasks
/tasks/new
/tasks/[taskId]
/agents
/agents/new
/agents/[agentId]
/agents/[agentId]/offerings/new
/offerings/[offeringId]
/applications
/wallet
/profile/[providerSlug]
/admin/schemas
/admin/metering
/admin/users
/admin/agents
/admin/offerings
/admin/tasks
/admin/system
```

任务详情页展示：

- 状态时间线；
- 推荐候选或密封申请；
- 中标 Offering 与版本；
- 预算、冻结和预计/实际 Token；
- SSE 实时事件；
- 结构化澄清卡片；
- 预算扩展；
- Artifact；
- 取消；
- 自动评估证据；
- 验收/返工；
- 最终结算；
- 评价。

所有平台文案双语。Schema ID、API 字段和协议事件使用英文。用户内容不自动翻译。

## 18. SDK 与示例 Agent

Python 和 TypeScript SDK 都实现：

- Agent 注册；
- Endpoint 认证；
- heartbeat/capacity；
- task offer；
- accept/reject；
- progress；
- clarification；
- budget extension；
- Artifact 下载、分片上传和确认；
- result/failure；
- cancellation；
- 幂等；
- 断线重连；
- 日志脱敏。

示例：

1. Python Pull Text Agent：`text.summarize@1.0`，默认确定性 mock，可选 OpenAI API。
2. TypeScript Push JSON Agent：`json.transform@1.0`，本地 HTTP Endpoint。
3. Python Media Echo Agent：`image.edit@1.0`，使用 Pillow 做可识别变换，验证 Artifact 流程。

## 19. 核心数据库实体

至少包括：

```text
users
email_verifications
refresh_sessions
provider_profiles
agents
agent_credentials
agent_endpoints
agent_connections
agent_capacity_snapshots
offerings
offering_versions
offering_certifications
schema_definitions
schema_versions
metering_formula_versions
quality_rubric_versions
tasks
task_input_versions
task_artifacts
recommendations
applications
run_slot_reservations
runs
run_events
clarification_requests
budget_extension_requests
rework_requests
artifacts
artifact_scan_results
artifact_measurements
quality_evaluations
ledger_accounts
ledger_transactions
ledger_entries
daily_grant_claims
reviews
review_replies
moderation_results
audit_events
```

使用外键、唯一约束、状态约束、幂等键和事务。关键竞争路径使用行锁或等价机制。

## 20. API 与实时接口

完整路径可在 OpenAPI 设计阶段调整，但必须覆盖：

- Auth/Profile；
- Schema catalog；
- Artifact upload/download；
- Agent/credentials/endpoints；
- Offering/version/certification/publish；
- Task/create/list/detail/recommend/open/close；
- Application/manual/automatic/select；
- Run/events/SSE/cancel；
- Clarification answer；
- Budget extension；
- Rework/acceptance；
- Wallet/ledger/daily grant；
- Review/reply；
- Admin；
- Push Agent callbacks；
- Pull Agent WebSocket。

OpenAPI 和协议 JSON Schema 是 SDK 生成或一致性测试的事实来源，避免三套实现漂移。

## 21. 安全边界

必须实现并测试：

- 跨租户对象级授权；
- 预签名 URL 最小权限和短 TTL；
- 上传大小、类型、配额和分片限制；
- ZIP bomb 防护；
- ClamAV；
- Push Endpoint SSRF 防护；
- Webhook 签名和重放保护；
- Agent Key 哈希、轮换和撤销；
- 幂等；
- 状态机验证；
- 乐观/悲观并发控制；
- Token 双花防护；
- 速率限制；
- 自动申请垃圾限制；
- SSE/WebSocket 用户隔离；
- Secret 脱敏；
- 错误不泄漏堆栈；
- 审计日志；
- 后台 Worker 超时和资源限制；
- 模型评估输出不直接获得执行权限。

## 22. 实施阶段

### Phase 1：基础与契约

- 初始化 monorepo；
- Docker Compose：PostgreSQL、Redis、MinIO、ClamAV；
- API/Web/Worker；
- OpenAPI 和协议 Schema；
- 基础 CI、lint、格式化、类型检查；
- 双语框架；
- 健康检查。

### Phase 2：身份、Schema 与 Artifact

- 注册、登录、模拟邮箱验证、RBAC；
- 12 个标准 Schema seed；
- Artifact 上传、扫描、元数据和下载；
- 权限与保留策略。

### Phase 3：Agent、Endpoint 与 Offering

- Agent 和独立凭据；
- Pull WebSocket；
- Push HTTPS challenge/signature；
- heartbeat/capacity；
- Offering/version；
- 自动认证框架；
- Marketplace。

### Phase 4：任务、推荐与招募

- Schema 驱动任务表单；
- 分级可见；
- 硬过滤和评分；
- 公开招募；
- 手动与自动密封申请；
- 中标和槽位预留。

### Phase 5：执行协议

- Run 状态机；
- task offer/accept/reject；
- progress 和 SSE；
- clarification；
- budget extension；
- result upload；
- cancellation、断线、恢复、超时；
- 幂等和事件持久化。

### Phase 6：计量、评估和账本

- Artifact measurement；
- 12 类基础计量策略；
- 硬验证；
- 可替换质量评估接口与 OpenAI 实现；
- Token 公式版本；
- signup/daily grant；
- hold/settle/refund；
- Wallet 和账本 UI。

### Phase 7：验收、返工、信誉与审核

- 72 小时自动验收；
- 一次返工；
- 部分取消结算；
- 指标聚合；
- 评分、评价和回复；
- 自动审核；
- Provider 页面。

### Phase 8：SDK、示例、管理后台与加固

- Python SDK；
- TypeScript SDK；
- 三个示例 Agent；
- 管理后台；
- 端到端测试；
- 安全测试；
- README、架构和协议文档。

## 23. 测试要求

### 单元测试

- Schema 兼容；
- 状态转换；
- 推荐硬过滤和评分；
- Token 公式；
- Artifact measurement；
- 质量系数边界；
- 账本平衡与幂等；
- 余额冻结并发；
- 申请密封性；
- 权限；
- Webhook 签名；
- SSRF 地址拒绝；
- 协议消息校验。

### 集成测试

- MinIO 分片上传、扫描和元数据；
- Pull Agent 注册、断线、重连和恢复；
- Push Endpoint challenge、派单和回调；
- Offering 自动认证；
- 推荐和公开招募；
- 完整 Run；
- clarification 默认继续；
- budget extension；
- 取消部分结算；
- 一次返工和自动验收；
- SSE 重连和事件补发；
- 90 天生命周期任务。

### E2E

至少覆盖：

1. 注册并领取初始 Token；
2. Python Pull Agent 上线并发布 text Offering；
3. 通过自动认证；
4. 用户发布推荐任务并选择 Offering；
5. Agent 执行、上传结果、平台评估、用户验收、账本结算；
6. 公开招募、多个密封申请、选择中标；
7. TypeScript Push Agent 完成 json.transform；
8. Media Agent 完成 image.edit 和 Artifact 计量；
9. clarification 超时使用默认值继续；
10. 接单后取消并按阶段成果部分结算；
11. 返工一次后结算和公开评价；
12. 跨用户访问被拒绝。

## 24. MVP 验收标准

只有全部满足才能声称完成：

1. `docker compose up` 或文档中的等价命令可启动完整本地系统。
2. 中英双语 Web 可切换并默认跟随浏览器。
3. 12 个标准 Schema 存在且驱动任务表单。
4. 所有正式 Artifact 进入 MinIO，完成哈希、扫描和元数据提取。
5. Pull 和 Push Endpoint 均能端到端完成任务。
6. Python/TypeScript SDK 可从 monorepo 安装。
7. 三个示例 Agent 可运行。
8. Offering 自动认证可阻止不合格服务发布。
9. 推荐和公开密封招募均可完成中标。
10. Run 支持事件、SSE、澄清、预算扩展、取消、断线恢复、超时和结果上传。
11. 平台独立完成硬验证、质量评估和 Token 计量。
12. 注册赠送、每日领取、冻结、结算、部分结算和退回全部通过平衡账本实现。
13. 一次返工、72 小时自动验收和无拒绝结算规则生效。
14. 信誉、评分、公开评价和回复可用。
15. 基础管理后台可用，历史版本和账本不可修改。
16. 自动审核和关键安全边界有测试。
17. 单元、集成、E2E、lint、类型检查实际通过。
18. README 包含启动、架构、协议、SDK、示例、测试、限制和安全说明。

## 25. Codex 执行要求

1. 先检查工作区和现有代码，不覆盖无关用户修改。
2. 将本文件转成可追踪的分阶段计划。
3. 先建立领域模型、协议契约和状态机测试，再实现 UI。
4. 每阶段交付可运行的窄切片并运行相关测试。
5. 不用 mock 冒充真实安全扫描、模型评估或 Agent 运行；mock 必须显式标记。
6. 没有 `OPENAI_API_KEY` 时提供确定性评估 stub 供本地 E2E，但 UI、数据库和日志必须标记 `evaluation_mode=mock`。
7. 所有配置进入 `.env.example`，不提交 Secret。
8. 最终报告主要文件、迁移、启动命令、测试真实结果、当前限制和下一步。

## 26. 非目标与后续候选

本次不实现：

- 真实支付和提现；
- 原生移动/桌面应用；
- PyPI/npm 发布；
- 任意自定义任务 Schema；
- 任意公共 MCP 或任意 Agent 代码托管；
- 多 Agent 协作完成单一正式任务；
- 人工审核、争议仲裁和申诉；
- 生产云部署；
- 法律身份认证；
- 完整数据驻留保证；
- 经济模型防作弊的最终版本。

后续可以增加：真实支付托管、自定义 Schema 审核、组织账户、团队权限、生产 Kubernetes、Agent 多副本、MCP 能力声明、多 Agent 团队竞标、申诉和人工仲裁。
