ROLE: Act as a principal architect + delivery lead. Produce an enterprise-grade PROJECT PLAN
(not code) for "Project Management Accelerator" (PMA). Use tables; state assumptions.

PRODUCT: Web app where users repeatedly upload MS Project .mpp files for a program. Each upload
is an immutable, versioned SNAPSHOT with an "as-of" date. PMA parses it, computes KPIs, renders
an executive dashboard, tracks change across snapshots, and adds AI insights via Ollama.

DATA SOURCES (keep separate)
A. From .mpp (read-only): tasks, WBS/outline, milestones, start/finish, baseline, actuals,
   % complete, duration, work, cost, predecessors, constraints, deadlines, slack, critical
   flag, resources/assignments, calendars, notes, custom fields.
B. Governance data (not in .mpp): Risks, Decisions/Support requests, Attention items. Manual
   entry or AI-drafted -> human review -> approved; persist across snapshots.

MAPPING LAYER (define first)
- Per-program mapping wizard on first upload, reused afterwards. Track = outline level or
  custom field; Milestone = flag, outline level or custom field; numbering 01..n.
- Planned-to-date: baseline if present; else first snapshot frozen as baseline; else linear by
  duration. Variance (pts) = actual % - planned %. Handle re-baselining and changed structure.

AI DISCOVERY (run on every upload, before the dashboard is built)
- AI profiles the parsed file: which fields are populated, structure, data quality gaps.
- AI proposes the mapping (tracks, milestones) and EVERY KPI the data can support beyond the
  reference set; an admin approves, and the approved set is saved per program.
- AI only proposes and narrates. All numbers are computed by the deterministic KPI engine.

DASHBOARD - REFERENCE SPEC (reproduce all of it)
Header: client logo + name (EN/AR), title "<Program> - Executive Dashboard", subtitle, vendor
  logo; KPI strip: Tracks, Active, Avg Progress %, Milestones; chips: location, "As of <date>",
  role + sign out. Footer: Contact us + support email.
Nav: EXECUTIVE (Executive Overview) | PROGRAM (Delivery Tracks, Milestones, Timeline) |
  GOVERNANCE (Support & Decisions, Risk Register, Attention).
KPI cards, each with tag, big number, caption and mini progress bar:
  Program Completion % [On Track]; Active Tracks x/y ("n tracks pending activation");
  Total Milestones (scope caption); On Track count ("milestones progressing");
  Not Started count ("milestones pending"); Decisions Required [Action] ("n high-priority for
  Committee"); High Risks [Monitor] ("of n tracked - need mitigation"); Active Track Timeline
  in months (date range, "month x of y - z% elapsed"); Next Milestone (name, "starts <month>",
  click -> Milestones).
Delivery Tracks Overview: card per track (Track 01..n, name, status pill, %, bar), source label.
Active Track Progress: donut with % complete.
Milestone table: #, Milestone, Track, Timeline (start - end), Status pill (Completed / On Track
  / Delay / Critical Delay / Not Started), Health chip (COMPLETE / DUE IN nD / STARTS IN nD,
  colour by urgency), Progress bar + %, Variance chip (+/- pts, green/red/grey).
Gantt: monthly columns, bar per milestone with filled progress + % label, legend (On Track,
  Completed, Delay, Critical Delay, Not Started, Today, Milestone plan to date), red Today line.
Progress Trend: planned vs actual lines per reporting cycle; summary strip "Programme planned
  to date x% - Actual y% - z pts behind plan - weekly reporting cycle - n weeks reported -
  roll-up covers a of b tracks".
Key Support & Decisions cards: title, description, priority (High/Medium/Low), status
  (Pending/Approved/Rejected), owner, needed-by date; colour edge by priority.
Risk Register: severity badge, title, description, mitigation, action owner, due date.
Attention: overdue or at-risk items needing action.
Every number drills down to its underlying tasks.

EXTENDED KPI CATALOGUE (show when data supports it)
Schedule: SPI, schedule variance (days), slippage per milestone and cumulative, baseline
  execution index, milestone hit rate, forecast finish vs baseline, critical-path length and
  changes, total/free slack, near-critical tasks, tasks starting/finishing in next 30/60/90d,
  overdue tasks, late starts, missed deadlines, constraint count.
Progress: planned vs actual by track/phase, weekly velocity, S-curve, burn-up, % of duration
  elapsed vs % complete, stalled tasks (no progress across n snapshots).
Cost/effort (if present): BCWS, BCWP, ACWP, CPI, CV, EAC, ETC, VAC, work planned vs actual.
Resources (if present): allocation, over-allocation, unassigned tasks, workload by owner.
Plan quality: missing predecessors/successors, missing baseline, tasks without resources,
  long-duration tasks, hard constraints, negative slack, logic-health score.
Change: adds/removes/renames, date moves, progress delta, status transitions, scope growth %,
  re-baseline events, slippage trend and volatility.
Governance: open/overdue decisions, decision ageing, risks by severity, overdue mitigations.

CORE FEATURES
1. Ingestion: single/bulk upload, hash duplicate check, async queue, parse-error report.
2. Change tracking: match by Unique ID (fallback WBS + fuzzy name); diff vs previous snapshot
   and vs baseline; "What changed" view; milestone history; trends; snapshot selector/compare.
3. KPI engine: deterministic, versioned formulas, recalculated per snapshot.
4. AI insights: executive summary, change narrative, slippage root-cause, forecast, draft
   risks/decisions/attention items, Q&A over plan data. JSON in, schema-validated JSON out;
   cached per snapshot; app fully usable with AI off.
5. Export: PDF first; Excel and PPTX later.

UI: modern, professional, executive-grade; card layout, restrained palette with semantic status
colours, strong typography, responsive, WCAG AA, light/dark, EN/AR-ready.

DECISIONS THE PLAN MUST MAKE (options, trade-offs, recommendation)
- Parser: MPXJ is Java. JVM parser microservice vs Python + MPXJ via JPype. Cover
  password-protected and old-format files.
- AI hosting: Ollama Cloud vs self-hosted Ollama behind one provider interface, switchable per
  tenant. Self-hosted default for government/restricted data; redact before cloud calls; log.
- Stack (justify or replace): Vue 3 + TypeScript + ECharts; Python FastAPI; PostgreSQL; object
  storage; Redis queue; Docker; Azure; CI/CD.

PHASING (strict)
- MVP: upload -> mapping -> snapshot -> diff -> reference dashboard, manual governance data,
  login with 3 roles (Admin, PMO Editor, Super Viewer), PDF export.
- v1: AI discovery + insights, extended KPIs, SSO (OIDC), audit log, multi-program, Excel/PPTX.
- v2: multi-tenant, full AR/RTL, tenant branding, portfolio roll-up, alerts.

DELIVER THESE SECTIONS
1. Vision, scope, out-of-scope, assumptions
2. Personas and top user journeys
3. Architecture and data flow
4. Data model (Tenant, Program, MappingConfig, Track, Snapshot, Task, Milestone, TaskDiff,
   KPIDefinition, KPIValue, Risk, Decision, AttentionItem, Insight, User/Role)
5. Mapping rules + full KPI catalogue: formula, source fields, widget, phase
6. Snapshot diff algorithm and edge cases
7. AI design: discovery and insight prompts, guardrails, cost and latency controls
8. Security, compliance, NFR targets
9. Roadmap per phase: epics, team roles, effort, acceptance criteria
10. Testing/UAT, risks and mitigations, success metrics
11. Open questions for the client, ranked by impact