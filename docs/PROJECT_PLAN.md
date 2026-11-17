# Project Management Accelerator: Project Plan & Architecture

Status: implemented (MVP + v1 + v2 scope) · Version 1.0 · 2026-11-10

This document answers the eleven sections the brief requires and records every decision as built.
Paths in brackets point to the implementation.

---

## 0. Decisions the plan must make

| Decision | Options | Trade-offs | **Decision** |
|---|---|---|---|
| **Parser** | (a) Java microservice wrapping MPXJ behind REST; (b) Python + MPXJ via JPype in-process | (a) language isolation and independent scaling, but a second runtime, service, API contract and network hop. (b) one codebase and image; MPXJ's Java objects are converted to plain Python immediately; needs a JRE in the image and care with JVM lifecycle | **(b) Python + MPXJ via JPype** (`mpxj` PyPI package, MPXJ 16). The JVM is started once on the main thread of each process; RQ uses `SimpleWorker` (no fork after the JVM starts) [`backend/app/parser/mpp_parser.py`, `backend/app/worker.py`]. Revisit (a) only if parse volume needs separate scaling. |
| Password-protected / old formats | | | MPXJ reads MPP8/9/12/14 (Project 98 → current), MPT, MPX and MSPDI XML. Protected files: the uploader supplies the password (`MPPReader.setReadPassword`); otherwise a structured parse-error report (`password_protected`, `wrong_password`, `unsupported_format`, `corrupt_file`, `no_tasks`, `empty_file`) with a remediation hint. *Reprocess* re-parses with a password. |
| **AI hosting** | Ollama Cloud vs self-hosted Ollama | Cloud: no GPU estate, but data leaves the network. Self-hosted: data stays inside; needs GPU/CPU capacity | **One provider interface** (`LLMProvider`) with self-hosted and cloud implementations of the same Ollama `/api/chat` protocol, **switchable per tenant** (`Tenant.ai_mode = off / self_hosted / cloud`). Self-hosted is the recommended default for government/restricted data. Cloud calls are **redacted** (people, emails, phones, IBANs, IDs → reversible tokens) and **every call is logged** (`AIRequestLog`) [`backend/app/ai/`]. |
| **Stack** | Brief: Vue 3 + TS + ECharts; FastAPI; PostgreSQL; object storage; Redis queue; Docker; Azure; CI/CD | | **Kept as proposed.** Vue 3 + strict TypeScript + ECharts (SVG renderer, a11y); FastAPI + SQLAlchemy 2 + Alembic; PostgreSQL 16 (SQLite supported for single-node/dev); S3/MinIO **or Azure Blob** or local disk; Redis + RQ (inline thread pool for single-node); Docker Compose; Azure target (Container Apps + Azure Database for PostgreSQL + Azure Cache for Redis + Blob); GitHub Actions CI [`.github/workflows/ci.yml`]. |

---

## 1. Vision, scope, out-of-scope, assumptions

**Vision.** Executives see a trustworthy, current, explainable picture of a programme from the MS Project
plans the PMO already maintains, with every number traceable to tasks and every change between reporting cycles visible.

**In scope:** ingestion (single/bulk, duplicate detection, async, error reports) · per-program mapping wizard ·
immutable versioned snapshots · deterministic, versioned KPI engine (reference set + extended catalogue) ·
reference executive dashboard with drill-down · change tracking (diff vs previous / baseline / any snapshot,
milestone history, trends) · governance data (risks, decisions/support, attention) with AI-draft review ·
AI discovery and insights (summary, change narrative, root cause, forecast, drafts, Q&A) · PDF/Excel/PPTX export ·
3 roles, OIDC SSO, audit log · multi-program, multi-tenant, branding, portfolio roll-up, alerts · EN/AR + RTL, light/dark.

**Out of scope:** editing schedules (PMA is read-only on source A); writing back to MS Project/Project Online;
resource levelling or re-scheduling (PMA reports MS Project's computed values); timesheets; native mobile apps;
Primavera-specific KPIs (P6 files parse through MPXJ but are not a supported input).

**Assumptions**

| # | Assumption |
|---|---|
| A1 | Uploaded plans are saved by MS Project, so Unique IDs are stable between versions. Rebuilt plans are handled by WBS + fuzzy-name matching. |
| A2 | As-of date = user-supplied value, else the project **status date**, else upload date (with a warning). |
| A3 | Percent complete is MS Project *% Complete* (duration-based). Roll-ups are weighted by baseline duration, else duration. Summary rows never double-count. |
| A4 | Planned-to-date is linear between planned start and finish (calendar days). |
| A5 | A track is *active* once any leaf task has started (actual start or % > 0). Completed tracks count as active. |
| A6 | Governance data (risks, decisions, attention) belongs to the programme, not a snapshot, and is evaluated live. |
| A7 | Status thresholds default to −5 pts (Delay) and −15 pts (Critical Delay) and are configurable per programme. |
| A8 | One reporting cycle = `reporting_cycle_days` (default 7). The trend uses the latest snapshot in each cycle. |

---

## 2. Personas and top user journeys

| Persona | Role in PMA | Needs |
|---|---|---|
| Steering-committee executive | Super Viewer | One-screen status, what needs a decision, what changed, a PDF/PPTX for the meeting |
| Programme director | Super Viewer / Editor | Track and milestone health, slippage root cause, forecast |
| PMO analyst | PMO Editor | Weekly upload, curate risks/decisions, review AI drafts, answer "why" questions |
| PMO lead / admin | Admin | Mapping, KPI set, thresholds, users, branding, AI policy, alerts, audit |
| Platform operator | Platform admin | Tenants, deployment, AI provider capacity |

**Top journeys**
1. *First upload:* create programme → upload `.mpp` → AI/heuristic discovery → mapping wizard (profile → tracks → milestones → planned method → KPI set) → approve → dashboard.
2. *Weekly cycle:* upload new snapshot → auto-mapped → dashboard, What Changed, alerts, AI summary refresh.
3. *Committee pack:* open overview → review decisions/risks/attention → export PDF/PPTX.
4. *Investigation:* click any number → underlying tasks → milestone history → AI root cause / Q&A.
5. *Back-fill:* bulk upload historical files with per-file as-of dates → out-of-order processing recomputes later snapshots.

---

## 3. Architecture and data flow

```
 Browser (Vue 3 SPA, EN/AR, light/dark)
     │ HTTPS
 nginx (static SPA, /api reverse proxy, CSP, 110 MB uploads)
     │
 FastAPI API ──────────────┬───────────── PostgreSQL (snapshots, tasks, KPIs, governance, audit)
  auth/RBAC/tenancy        │
  upload → sha256 dedupe ──┼──► Object storage (S3/MinIO | Azure Blob | local) – original files
  enqueue ────────────────►│    Redis (RQ queue)
                           ▼
                     RQ worker(s) [JVM + MPXJ]
   parse → store raw (immutable) → profile → AI discovery ─► Ollama (self-hosted | cloud, redacted)
   → mapping (approved? else wait for wizard) → planned-to-date → diff (prev & baseline)
   → KPI engine (versioned) → alerts (in-app/email/webhook) → AI summary + change narrative (cached)
```

Module map: `app/parser` (MPXJ), `app/services/{profiling,mapping,schedule_math,diff,context,pipeline,dashboard,alerts,export}`,
`app/kpi/engine.py`, `app/ai/{provider,redact,prompts,schemas,service}`, `app/api/*` (routers), `frontend/src`.

---

## 4. Data model

| Entity | Key fields | Notes |
|---|---|---|
| **Tenant** | name/name_ar, slug, branding{logos, colour, support email, contact url, location}, ai_mode, ai_model, ai_redact | Isolation boundary for every query |
| **User/Role** | email, role ∈ {admin, pmo_editor, super_viewer}, is_platform_admin, password_hash \| oidc_subject, token_version | `token_version` revokes sessions |
| **Program** | names EN/AR, client EN/AR, subtitle, location, reporting_cycle_days, thresholds, branding overrides | |
| **MappingConfig** | version, status (proposed/approved/superseded), track_rule, milestone_rule, planned_method, track_names, excluded_track_keys, approved_kpis, proposed_kpis, proposed_by (ai/heuristic/user) | Versioned; approval recomputes history |
| **Track** | number (01..n, stable), key (`uid:<summary UID>` or `cf:<field>:<value>`), name/name_ar, source_label | Matched by key, then by name |
| **Snapshot** | version_no, as_of_date + source, filename, sha256, storage_key, status, error_report, warnings, project_props, calendars, custom_field_defs, profile, has_baseline, planned_method_used, rebaselined, kpi_engine_version | Unique (program, hash) |
| **Task** | full MPXJ field set (dates, baselines, actuals, %, durations, work, cost, BCWS/BCWP/ACWP, constraints, deadline, slack, critical, predecessors/successors, resources, calendar, notes, custom fields) + derived track_id, is_mapped_milestone, planned_percent | Raw fields immutable |
| Resource / Assignment | units, work, cost, over-allocation, peak units | |
| **Milestone** | per snapshot: number, track, dates, baseline, %, planned %, variance, status, health chip, slippage | Enables milestone history |
| **TaskDiff** | compare_to (previous/baseline), match_method + score, change_type, field changes, start/finish/progress deltas, status transition | |
| **KPIDefinition** | code, version, formula, source fields, widget, phase | Seeded from the registry |
| **KPIValue** | snapshot, code, kpi_version, available/reason, value, display, details, drill_uids | |
| **Risk / Decision / AttentionItem** | programme-scoped; severity/priority, status, owner, dates, mitigation; source (manual/ai/engine); review_status (draft/approved/rejected) | Persist across snapshots |
| **Insight** | snapshot, kind, input_hash (cache key), content (validated JSON), guardrail_flags, provider/model, prompt_version, latency | |
| AuditLog, AIRequestLog, AlertRule, Alert | | v1/v2 |

---

## 5. Mapping rules + full KPI catalogue

**Mapping.** Track = outline level L (each summary at L, descendants inherit) **or** custom-field value
(inherited down the outline). Milestone = MS Project milestone flag **or** outline level **or** custom field
(= value, or truthy for flags). Numbered 01..n by track then start. **Planned-to-date:** baseline if present
(auto when ≥ 50 % of leaves are baselined), else the first snapshot frozen as baseline, else linear by duration.
The fallback applies per task. **Variance (pts) = actual % − planned %.** **Re-baselining:** flagged when ≥ 10 % of
matched tasks change baseline finish, or baselines appear. Variance then measures against the new baseline,
and the event is counted. **Structure change:** tracks are matched by key, then by name. New tracks are
appended, vanished tracks keep their number. A warning is raised when the approved rules no longer fit the file
or discovery's proposal changes between uploads.

**Status** = Completed (≥ 100 %) · Not Started (0 % and nothing planned yet) · On Track (variance ≥ delay threshold)
· Delay (≥ critical threshold) · Critical Delay. **Health chip** = COMPLETE / STARTS IN nD / DUE IN nD / OVERDUE nD,
with urgency colour (≤ 7–14 d high, ≤ 30 d medium).

KPI catalogue (69 KPIs, all in [`backend/app/kpi/engine.py`] with code, formula version, source fields, widget, phase;
unavailable KPIs report *why*; every value carries the drill-down task UIDs):

| Category | KPIs (formula summary) | Widget | Phase |
|---|---|---|---|
| Reference | Program completion (Σw·%/Σw), planned to date, variance pts, tracks, active tracks x/y, total/on-track/not-started/completed/delayed/critical milestones, active track timeline (months, month x of y, % elapsed), next milestone, decisions required (+high priority), high risks (of n tracked) | KPI cards, strip, donut, trend | MVP |
| Schedule | SPI (BCWP/BCWS or duration EV/PV), schedule variance days, forecast finish vs baseline, milestone slippage (each + cumulative), BEI, milestone hit rate, critical-path length + changes, total/free slack, near-critical, tasks starting/finishing in 30/60/90 d, overdue tasks, late starts, missed deadlines, constraint count | gauge, cards, tables | v1 |
| Progress | Planned vs actual by track, weekly velocity (+ weeks to complete), S-curve, burn-up, % duration elapsed vs % complete, stalled tasks (no change across n snapshots) | bar, line | v1 |
| Cost/effort | BCWS, BCWP, ACWP, CPI, CV, SV, EAC (BAC/CPI), ETC, VAC, BAC, work planned vs actual. Uses file EV fields when present, else computes | cards, gauge | v1 |
| Resources | Allocation, over-allocation, unassigned tasks, workload by owner | table, bar | v1 |
| Plan quality | Missing predecessors/successors, missing baseline, tasks without resources, long-duration (> 44 d), hard constraints, negative slack, logic-health score (12 DCMA-14-style checks) | cards, gauge | v1 |
| Change | Adds/removes/renames/date moves/status transitions, progress delta, scope growth % (tasks & duration), re-baseline events, slippage trend & volatility (σ of finish moves) | table, line | v1 |
| Governance (live) | Open/overdue decisions, decision ageing (buckets), risks by severity, overdue mitigations | cards, bar | v1 |

The admin approves the extended KPI set per programme in the wizard. AI discovery proposes the supportable set
and ideas beyond the catalogue. It never computes values.

---

## 6. Snapshot diff algorithm and edge cases

1. **Unique ID match.** A pair is rejected as UID reuse when name similarity < 50 and the WBS differs. If < 40 % of
   UID pairs are sane, UIDs are treated as unreliable for that file.
2. **WBS/outline-number match** with name similarity ≥ 60.
3. **Fuzzy name match** (token-sort ratio ≥ 85 on punctuation-normalised names, +5 for the same parent), greedy one-to-one.
4. Unmatched → **added** / **removed**. For pairs: renamed, date moved (start/finish Δ days), progress Δ, status
   transition, duration, baseline, logic, resources, parent move, (de)activation, milestone/critical flag toggles.

| Edge case | Handling |
|---|---|
| Out-of-order upload (back-fill) | Previous = nearest earlier as-of. Every later snapshot is recomputed (diff, history, frozen baseline). |
| Same as-of twice | Ordered by version number |
| Identical file | Rejected by SHA-256 with a reference to the existing version |
| Plan rebuilt / UIDs renumbered | WBS → fuzzy fallback. Tracks matched by name. |
| Re-baseline | Detected and flagged on the snapshot and in What Changed. KPIs use the new baseline. |
| No baseline at all | Frozen first snapshot acts as the baseline for planned % and the "vs baseline" diff |
| Summary rows | Diffed (renames matter) but excluded from roll-ups |
| Mapping changed | All snapshots recomputed in as-of order. Raw data is never altered. |
| Snapshot deleted | Programme recomputed |

Compare any two snapshots on demand: `GET /snapshots/{id}/diff?compare_to=<id|previous|baseline>`.

---

## 7. AI design

* **Discovery (every upload, before the dashboard):** input = profile (field coverage, outline structure,
  custom fields, quality gaps) + KPI catalogue. Output = `DiscoveryOut` (mapping proposal, supportable KPI codes
  with rationale, extra KPI ideas, gaps). The proposal is validated against the file (levels and fields must
  exist) and falls back to the deterministic heuristic.
* **Insights:** executive summary, change narrative, slippage root cause (cites evidence task UIDs), forecast,
  draft governance (risks/decisions/attention → saved as **drafts** → human approve/reject), Q&A (keyword-ranked
  relevant tasks + facts, cites task UIDs).
* **Guardrails:** facts are JSON from the KPI engine, not raw files. Ollama structured outputs are constrained by
  the JSON schema and validated with Pydantic, with one retry and an error otherwise. The system prompt treats
  plan text as data (prompt-injection resistant). A **numeric grounding check** flags any number in the narrative
  that does not appear in the facts. Cited task UIDs and KPI codes are validated against the snapshot and registry.
  Drafts never publish without review, and drafts duplicating an existing item (fuzzy title match) are dropped.
  Q&A retrieval pulls the open tasks of any track named in the question; cited UIDs are recovered from the answer
  text and validated.
* **Cost & latency:** cache per (snapshot, kind, SHA-256 of input + prompt version + model). Facts are trimmed
  to `PMA_AI_MAX_INPUT_CHARS`. Daily per-tenant call limit, timeouts, low temperature, `num_predict` cap.
  Summary + change narrative are pre-generated asynchronously after each snapshot. The AI call log records
  tokens, latency, cache hits and redactions.
* **AI off:** every feature except AI pages works. AI endpoints return 503 with a clear message.

---

## 8. Security, compliance, NFR targets

| Area | Implementation |
|---|---|
| AuthN | Local accounts (bcrypt-12, strength policy, login throttling) + **OIDC SSO** (auth code + PKCE, nonce, JWKS validation, role mapping from IdP claims). Short-lived HS256 JWT. Logout and password changes revoke tokens. |
| AuthZ | 3 roles enforced server-side on every endpoint. Tenant isolation in every query. Platform-admin-only tenant management. |
| Data | Originals in private object storage (SSE on S3). No secrets in code. AI redaction for cloud. Files are parsed in a temp file that is deleted afterwards. |
| Web | CSP, HSTS (prod), X-Frame-Options DENY, nosniff, no-store on API, SVG logo script check, upload type/size limits |
| Audit | Every login, upload, parse failure, mapping change, governance CRUD/review, export, AI call and admin change |
| Accessibility | WCAG 2.1 AA: contrast-checked tokens (light/dark), keyboard navigation, focus rings, skip link, ARIA labels on charts, progress bars and dialogs, focus-trapped modals, reduced motion |

NFR targets: dashboard API p95 < 800 ms for 5k-task plans; parse + compute < 60 s for 10k tasks; 50 concurrent
viewers per API replica; 99.5 % availability (Azure Container Apps, 2+ replicas); RPO 24 h / RTO 4 h
(PostgreSQL PITR + blob soft delete); uploads ≤ 100 MB.

---

## 9. Roadmap per phase

| Phase | Epics (delivered) | Acceptance criteria |
|---|---|---|
| **MVP** | Upload → mapping wizard → snapshot → diff → reference dashboard; manual governance; login with Admin / PMO Editor / Super Viewer; PDF export | A real `.mpp` produces every reference widget. Numbers reconcile with MS Project roll-ups (±0.1 pt). Duplicates rejected. Parse errors reported. Role matrix enforced. PDF contains header, KPIs, tracks, milestones, Gantt, trend, governance. |
| **v1** | AI discovery + insights; extended KPI catalogue; OIDC SSO; audit log; multi-program; Excel/PPTX | App fully usable with AI off. AI output schema-valid, cached, grounded, logged. SSO login maps roles. Every write audited. |
| **v2** | Multi-tenant; full AR/RTL; tenant branding; portfolio roll-up; alerts | Tenant data isolated. UI mirrors in Arabic. Logos/colours in UI and exports. Portfolio aggregates. Alerts fire on threshold breach via in-app/email/webhook. |

Team (reference, 16-week build): delivery lead, solution architect, 2 backend (Python), 1 frontend (Vue/TS),
1 data/KPI analyst (PMO SME), 0.5 ML engineer (prompts/evals), 0.5 DevOps, 1 QA, 0.5 UX/accessibility.
Effort: MVP ≈ 8 weeks, v1 ≈ 5 weeks, v2 ≈ 3 weeks.

---

## 10. Testing/UAT, risks and mitigations, success metrics

**Testing (in repo).** `tests/test_e2e.py`: full API journey over real MPXJ parsing (upload, duplicate, corrupt
file, mapping proposal/preview/approve, bulk upload, dashboard spec, KPIs, drill-down, diff types, compare,
milestone history, governance live KPIs, PDF/XLSX/PPTX, AI-off, RBAC, portfolio, alerts). `tests/test_units.py`:
matching edge cases, schedule maths, status/health, redaction, grounding. `tests/ui_smoke.py`: Playwright
through every screen, including Arabic/RTL, dark mode and phone width. CI runs migrations, tests and the strict
TS build. UAT: run real client `.mpp` files and reconcile programme %, milestone dates and slippage against MS Project.

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Client plans lack baselines / logic | High | Medium | Frozen-first-snapshot baseline, quality KPIs, discovery gaps report |
| Inconsistent structure across files | Medium | High | Stable track keys + name fallback, drift warnings, re-approval recompute |
| Encrypted/old files | Medium | Medium | Password re-processing, actionable error reports |
| AI hallucination | Medium | High | Facts-only prompts, schema validation, grounding flags, human review of drafts |
| Data residency | Medium | High | Self-hosted default, per-tenant switch, redaction, logs |
| JVM memory on huge files | Low | Medium | `PMA_JVM_MAX_HEAP`, worker isolation, job timeout |

**Success metrics:** report preparation time −70 %; snapshot to dashboard < 2 min; ≥ 90 % of weekly packs exported
from PMA; AI drafts accepted ≥ 50 %; zero unreconciled KPI disputes after UAT; WCAG AA audit pass.

---

## 11. Open questions for the client (ranked by impact)

1. Is any programme data classified such that **cloud AI must be disabled** by policy (vs redacted)? Which GPU capacity is available for self-hosted Ollama?
2. Which **identity provider** (Entra ID?), and which groups map to Admin / PMO Editor / Super Viewer?
3. Do plans carry **baselines** consistently, and which baseline (0–10) is authoritative?
4. Is the **track/milestone structure** fixed by outline level or by a custom field/outline code? Are there enterprise custom fields?
5. **Working-day calendars:** must planned-to-date use the project calendar (e.g. Fri/Sat weekend) instead of calendar days?
6. **Status thresholds** and tag wording for Delay / Critical Delay. Do overdue milestones always count as critical?
7. **Azure landing zone:** subscription, region (data residency), private networking, backup/retention policy.
8. **Arabic content:** is AR translation of track/milestone names required in the source, or entered in PMA?
9. **Export branding:** templates for PPTX/PDF (corporate master slides)?
10. **Alert channels:** email relay, Teams/Slack webhooks, and who receives what.
