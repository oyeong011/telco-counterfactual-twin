# Telco Counterfactual Twin Console Design System

## 0. Research Log

- Embedded refs: shortlisted Sentry, IBM Carbon, and ClickHouse. Picked operational `taste-skill.md` plus Sentry Layer B because Task 9 is a developer-operations console that needs dense evidence, warm dark IDE material, restrained technical labels, and high trust without becoming an enterprise template or analytics-marketing page.
- Lazyweb: 6 searches, 16 screens visually inspected from the Task 9 research packet. Borrowed the three-zone operations grammar: persistent nav, contextual run or incident rail, detail canvas, and evidence or activity panel. Sources included Better Stack, incident.io, Juniper, Netmaker, MLflow, Langfuse, Adaline, Fieldguide, Wrike, FireHydrant, Grafana Labs, Statsig, Together, and Eppo.
- Imagen drafts: primary reference `/Users/oy/Library/Mobile Documents/iCloud~md~obsidian/Documents/obsidian/obsidian/.omo/evidence/task-9-design-research/concept-a-workbench.png`; secondary RunDetail reference `/Users/oy/Library/Mobile Documents/iCloud~md~obsidian/Documents/obsidian/obsidian/.omo/evidence/task-9-design-research/concept-b-run-detail.png`. Concept A governs the ScenarioWorkbench workbench density and topology-plus-evidence composition. Concept B governs RunDetail side navigation, ledger panel, and proposed patch inspection.
- UI-UX DB sanity check: product lookup supported ops dark data-dense dashboard styling; typography lookup supported a Fira-like technical sans and mono pairing, adapted here to Rubik Variable plus IBM Plex Mono; chart lookup required network graph plus adjacency-list table fallback and line charts with dashed-vs-solid series plus a data table; UX lookup required WCAG contrast, color-not-only status, and resilient mobile table handling.
- Repo and plan evidence: React 19.2.8 plus Vite 8.2.2 in `frontend/package.json`; `frontend/src/README.md` states no console UI exists yet; accepted plan Todo 9 requires ScenarioWorkbench, RunDetail, EvidenceBoard, BenchmarkLab, About, API/SSE, visual QA over loading, empty, error, stale, rejected, approved, and demo states; ADR 0002 forbids mutation authority; ADR 0005 binds public claims to runtime identity.

## 1. Atmosphere & Identity

The console feels like a forensic network operations bench under incident pressure: compact, evidence-first, and calmly skeptical. Its signature is the aubergine proof surface: warm dark panels separated by tonal shifts and single-pixel rules, with every metric, topology edge, approval state, and action carrying a visible evidence trail. The interface should feel senior and controlled, not cinematic, not marketing-led, and never decorative. Design read: senior network operators and technical recruiters inspecting a deterministic, non-executing counterfactual twin; variance 4, motion 2, density 8.

## 2. Color

### Palette

| Role | Token | Light | Dark | Usage |
| --- | --- | --- | --- | --- |
| Surface/root | `--surface-root` | `#f6f1f4` | `#171019` | Full app background, never pure white or black |
| Surface/nav | `--surface-nav` | `#ebe2e8` | `#120c15` | Persistent sidenav and shell chrome |
| Surface/panel | `--surface-panel` | `#fff9fc` | `#201724` | Primary panels, tables, route modules |
| Surface/raised | `--surface-raised` | `#fffbfd` | `#2a2030` | Popovers, active rail item, modal surface |
| Surface/inset | `--surface-inset` | `#ece4ea` | `#18111c` | Code blocks, typed diffs, skeleton beds |
| Text/primary | `--text-primary` | `#211824` | `#f7eff8` | Body, headings, table values |
| Text/secondary | `--text-secondary` | `#5d5062` | `#c3b4c8` | Captions, labels, metadata |
| Text/muted | `--text-muted` | `#827587` | `#8d7e94` | Disabled text, low-emphasis timestamps |
| Border/subtle | `--border-subtle` | `#ded1dc` | `#372b3d` | Interior dividers |
| Border/strong | `--border-strong` | `#bcaabc` | `#5a4861` | Focusable containers and selected rows |
| Accent/primary | `--accent-primary` | `#65408a` | `#b890e6` | Primary interactive controls, focus outline |
| Accent/primary-hover | `--accent-primary-hover` | `#563477` | `#c7a7ef` | Hover and active interactive states |
| Accent/proof | `--accent-proof` | `#527a23` | `#a4d65e` | Replay verified, approved, deterministic proof |
| Accent/warning | `--accent-warning` | `#9a5b17` | `#e2a04d` | Stale telemetry, needs review, medium risk |
| Accent/danger | `--accent-danger` | `#ad3f36` | `#f07a68` | Invalid patch, outage, rejected, critical |
| Accent/info | `--accent-info` | `#375c9d` | `#87a6e8` | Neutral selected context, links, model info |
| Chart/baseline | `--chart-baseline` | `#6a5c71` | `#b8a7c1` | Baseline series, dashed stroke |
| Chart/candidate | `--chart-candidate` | `#65408a` | `#c09af0` | Candidate series, solid stroke |
| Chart/delta-positive | `--chart-delta-positive` | `#527a23` | `#a4d65e` | Improvement values, success markers |
| Chart/delta-negative | `--chart-delta-negative` | `#ad3f36` | `#f07a68` | Degradation values, failure markers |

### Rules

- The palette is original warm aubergine. It is Sentry-informed in atmosphere only and does not copy Sentry brand hex values.
- Use CSS custom properties as the only color source. Component code may not introduce raw hex, RGB, OKLCH, HSL, or named colors outside this file.
- Functional color must always be paired with label text or iconography. Red or green alone never communicates state.
- Accent/proof is rare and semantic: replay verified, deterministic benchmark, approved proof, or successful policy constraint. It is not decoration.
- Demo mode must use visible copy and a status chip, not a unique color family.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Tracking | Usage |
| --- | --- | --- | --- | --- | --- |
| Display | `32px / 2rem` | 620 | 1.15 | 0 | Route title on desktop only |
| H1 | `24px / 1.5rem` | 620 | 1.2 | 0 | Page object title, selected run name |
| H2 | `18px / 1.125rem` | 580 | 1.25 | 0 | Panel title, route section title |
| H3 | `15px / 0.9375rem` | 560 | 1.35 | 0 | Table group headers, card titles |
| Body | `14px / 0.875rem` | 400 | 1.5 | 0 | Default interface copy |
| Body/sm | `13px / 0.8125rem` | 400 | 1.45 | 0 | Secondary table cells and rail metadata |
| Caption | `12px / 0.75rem` | 500 | 1.35 | 0 | Badges, timestamps, inline labels |
| Micro | `11px / 0.6875rem` | 560 | 1.3 | 0.01em | Very compact metadata, never paragraphs |
| Code | `13px / 0.8125rem` | 400 | 1.55 | 0 | YAML patch, IDs, hashes, monospace rows |

### Font Stack

- Primary: `Rubik Variable`, `Rubik`, sans-serif.
- Mono: `IBM Plex Mono`, monospace.
- Maximum families: 2. Do not add a display, serif, icon font, or fallback brand font.

### Rules

- Rubik carries navigation, headings, body copy, and controls because it matches the Sentry-inspired developer-tool reference while staying legible at console density.
- IBM Plex Mono carries hashes, timestamps, patch diffs, metric numbers, topology labels, and command-like data. Use tabular figures where supported.
- Body text may not drop below 13px. Critical labels, errors, and approval decisions must be at least 14px.
- Do not use generic default UI fonts as the primary design choice. Browser defaults may exist only as late fallbacks after Rubik.
- Letter spacing is normally 0. Micro labels may use 0.01em only where compact all-caps metadata needs separation.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a 4px base.

| Token | Value | Usage |
| --- | --- | --- |
| `--space-1` | `4px` | Icon gap, hairline offset |
| `--space-2` | `8px` | Compact inline groups, table cell x-padding |
| `--space-3` | `12px` | Control padding, panel internal gap |
| `--space-4` | `16px` | Standard panel padding |
| `--space-5` | `20px` | Header groups, dense route gaps |
| `--space-6` | `24px` | Major panel separation |
| `--space-8` | `32px` | Wide desktop route gutters |
| `--space-10` | `40px` | About page section separation |

### Grid And Shell

- Breakpoints: narrow `375px`, tablet `768px`, desktop `1280px`, wide `1536px`.
- Desktop shell: fixed-sidenav-shell with 80px icon-and-label primary nav, optional 272px contextual rail, main detail canvas, and optional 320px evidence rail. The app root is bounded by `100dvb`.
- Main content max width: none for operational routes. The canvas uses available width because topology, tables, and timelines are the product.
- Scroll ownership: the root shell does not document-scroll. Primary nav and command bar stay fixed. Each route body owns vertical scroll with `min-block-size: 0; overflow: auto`. ContextRail, EvidenceRail, table bodies, timeline bodies, and patch diff panes may scroll only when their responsibility is named in the route anatomy.
- Mobile: primary nav collapses to a top command bar plus route switcher. ContextRail becomes a drill-down drawer. EvidenceRail becomes a bottom sheet or full-screen detail route. Tables convert to card rows or horizontally scroll inside their own labelled table region.

### Route Anatomy

- ScenarioWorkbench: fixed AppShell and CommandBar; ContextRail lists scenario families and runs; main two-column workbench with TopologyCanvas above TypedPatchDiff on the left, MetricDeltaTable and EventTimeline on the right, plus EvidenceRail pinned on desktop. Mobile order is object header, status chips, topology summary, metric deltas, patch diff, timeline, evidence sheet.
- RunDetail: ContextRail owns the run navigator; main header exposes run ID, fault family, seed, freshness, topology snapshot, duration, and deterministic status; detail stack shows abbreviated topology path, event timeline, baseline-vs-candidate line chart, TypedPatchDiff, and ApprovalEvidence in the right rail. Mobile keeps the run list as a drawer and puts evidence after the chart.
- EvidenceBoard: evidence packages, replay hashes, lineage hashes, approval proofs, build identity, and export receipts are the primary table. EvidenceRail shows selected package details. Mobile uses list-detail drill-down with a persistent back affordance.
- BenchmarkLab: benchmark matrix, deterministic seeds, model or rules baseline status, acceptance thresholds, and chart/table comparison. Charts are secondary to the MetricDeltaTable because exact values matter.
- About: compact explanatory route for no-mutation boundary, synthetic-data boundary, build identity fields, and verification commitments. It uses content-limiter for prose and no app marketing hero.

### State Coverage

Every route must render demo, loading, empty, error, stale, rejected, and approved states. State labels must be visible in the object header and in the affected row or panel. A blank screen is never an acceptable state.

## 5. Components

### AppShell

- Structure: `skip link`, fixed primary navigation, bounded route frame, main landmark, optional side rail slots.
- Variants: desktop fixed-sidenav-shell, tablet condensed rail, mobile top-shell with drawer navigation.
- Spacing: `--space-2` nav item gap, `--space-3` compact chrome padding, `--space-4` route frame padding.
- States: default stable chrome; hover row tone shift; active route selected with raised surface and label; focus visible 2px accent outline; disabled nav item muted and not focusable unless explanatory tooltip is reachable; loading keeps nav interactive and shows route skeleton in main; empty passes through to route body; error shows CommandBar status plus ErrorState in main; stale adds global freshness StatusChip; rejected and approved expose route-level status in the object header; demo shows persistent Demo StatusChip.
- Accessibility: skip link targets main; nav uses `aria-current="page"`; icon-only collapsed items require `aria-label`; tab order follows visual order.
- Motion: no automatic nav animation. Drawer open/close uses 160ms transform and opacity, disabled under reduced motion.
- Layout: fixed-sidenav-shell. AppShell bounds viewport height and never owns body document scroll.

### CommandBar

- Structure: route title, environment/freshness chips, search or filter controls, primary evidence action, secondary export/copy actions.
- Variants: default route command bar, simulation-progress command bar, mobile compact command bar.
- Spacing: `--space-2` inline control gap, `--space-3` padding, `--space-4` between groups.
- States: default; hover and active on controls; focus outline on every button/input; disabled actions explain why in `aria-describedby`; loading shows inline progress text and prevents duplicate submit; empty disables filters that need data; error includes request ID when available; stale shows last capture age; rejected shows reason and next eligible action; approved exposes approval proof hash; demo states sample data boundary.
- Accessibility: one primary action per route; buttons have clear names; status changes announce through polite live region.
- Motion: state chip changes crossfade in 120ms. No looping activity except real progress.
- Layout: cluster inside fixed shell row; wraps into two rows on mobile without horizontal overflow.

### ContextRail

- Structure: rail header, search/filter controls, grouped selectable list, optional details footer.
- Variants: scenario list, run navigator, evidence package list, benchmark set list.
- Spacing: `--space-2` row gap, `--space-3` rail padding.
- States: default; hover row tonal shift; active row with raised surface and left border; focus ring around full row; disabled row remains readable with disabled reason; loading uses Skeleton rows; empty keeps controls and one empty row; error provides retry; stale rows show freshness chip; rejected rows show explicit rejected chip and reason; approved rows show proof chip; demo rail includes demo source label.
- Accessibility: listbox or nav semantics must match behavior; selection is keyboard reachable; long IDs truncate with title and copy action.
- Motion: none beyond focus and row state transitions.
- Layout: list-detail rail. Desktop rail scrolls independently; mobile rail becomes drawer.

### StatusChip

- Structure: short label, optional icon from the chosen icon family, optional metadata.
- Variants: neutral, proof, warning, danger, info, demo, stale, rejected, approved.
- Spacing: `--space-1` icon gap, `--space-2` horizontal padding.
- States: default readable; hover only when clickable; active for selected filter; focus visible; disabled muted with text still 4.5:1 where possible; loading uses text such as "Checking"; empty is not used; error maps to danger with specific text; stale maps to warning with age; rejected maps to danger with reason; approved maps to proof with proof availability; demo maps to info plus "Synthetic demo".
- Accessibility: color is never sole indicator; each chip includes visible state text.
- Motion: instant state changes or 100ms opacity crossfade only.
- Layout: cluster item with fixed min touch area when interactive.

### DataTable

- Structure: caption or heading, optional toolbar, table with sticky header, sortable columns, row actions, empty/error row.
- Variants: metric deltas, evidence packages, benchmark results, policy constraints, adjacency list.
- Spacing: `--space-2` cell x-padding, `--space-3` header row padding.
- States: default; row hover; active selected row; focusable rows/actions; disabled row actions with reason; loading skeleton rows; empty one-row message; error inline table error with retry; stale row flag and age column; rejected row retained with reason column; approved row with proof hash/action; demo caption states synthetic sample.
- Accessibility: semantic `table`; sortable headers use `aria-sort`; dense cells preserve readable names; mobile table has labelled horizontal scroll or card-row alternative.
- Motion: none for sorting; selected-row detail changes crossfade in 120ms.
- Layout: scroll-body-shell for table body when height-bounded; mobile card rows where precision is not harmed.

### TopologyCanvas

- Structure: toolbar, topology canvas, legend, selected node panel, and accessible adjacency-list fallback using DataTable.
- Variants: full topology, abbreviated run path, impacted-only, diff view.
- Spacing: `--space-3` toolbar and legend gaps, `--space-4` canvas padding.
- States: default graph; hover highlights node and connected edges; active selected node locks detail; focus keyboard traversal through node list and canvas controls; disabled layer controls explain unavailable data; loading reserves canvas dimensions with Skeleton; empty shows no topology snapshot message plus required source; error shows recoverable graph failure and adjacency fallback; stale marks snapshot age; rejected highlights policy-failed nodes or edges by pattern plus text; approved highlights proof-bound path by text and stroke style; demo labels synthetic topology.
- Accessibility: canvas or SVG is not the only representation. Provide adjacency list table with columns Source, Target, Link Type, Status, Impact, Evidence ID. Keyboard users can move through nodes in logical topology order.
- Motion: topology changes use 180ms opacity and transform only; no force-directed drifting in the default ops screen; reduced motion freezes all transitions.
- Layout: frame plus overlay-stack for controls. Canvas scrolls or zooms only inside its labelled region.

### EventTimeline

- Structure: ordered list with timestamp, event type, impacted elements, severity, evidence link, and optional detail disclosure.
- Variants: compact route timeline, full evidence timeline, simulation progress trace.
- Spacing: `--space-2` row gap, `--space-3` row padding.
- States: default; hover row tone; active selected event; focus disclosure/action; disabled event actions with reason; loading skeleton timeline rows; empty no events row; error retry plus request ID; stale source age; rejected event with reason; approved event with proof marker; demo states simulated event source.
- Accessibility: semantic ordered list or table depending density; timestamps remain text; severity includes label and icon.
- Motion: new events enter with 120ms opacity and translate-y only when live streaming; reduced motion inserts instantly.
- Layout: vertical stack with internal scroll only when placed in fixed panel.

### MetricDeltaTable And Line Chart

- Structure: metric filter controls, exact delta table, optional line chart, legend, and downloadable data link.
- Variants: compact deltas, route comparison, benchmark matrix, chart-detail mode.
- Spacing: `--space-2` table cells, `--space-3` controls, `--space-4` between table and chart.
- States: default; hover rows and chart points; active selected metric; focus on controls and series toggles; disabled metric explains missing source; loading reserves chart/table geometry; empty no comparison available; error calculation failure with retry; stale warns last candidate or baseline age; rejected shows policy or approval rejection reason; approved shows bound proof and evidence hash; demo states sample seed.
- Accessibility: baseline is dashed and candidate is solid. Deltas include sign, unit, direction text, and impact label. A table equivalent is always available and is primary for exact values.
- Motion: chart series changes crossfade 160ms; no animated counting for metrics.
- Layout: stack on mobile, switcher on tablet, split panel on desktop.

### TypedPatchDiff

- Structure: file/path header, schema version, diff body, validation summary, policy impact, copy/download action.
- Variants: YAML patch, generated typed patch, rejected patch, approved patch.
- Spacing: `--space-2` code line padding, `--space-3` header padding.
- States: default; hover line actions; active selected hunk; focus keyboard line navigation and copy; disabled copy/export with reason; loading skeleton code rows; empty no patch proposed; error invalid patch/schema; stale patch generated from stale observation; rejected diff keeps redacted reason and failed constraints; approved diff includes approval proof; demo sample patch clearly marked.
- Accessibility: code block uses line numbers as text; additions/removals are labeled with words and signs, not color alone.
- Motion: none except focus and selection transitions.
- Layout: scroll-body-shell with `overflow-wrap: anywhere` for hashes and long paths.

### EvidenceRail

- Structure: evidence object header, replay status, hashes, generated-at, source artifacts, approval state, blast radius, and actions.
- Variants: workbench rail, run-detail rail, evidence package rail, mobile bottom sheet.
- Spacing: `--space-3` section padding, `--space-4` between evidence groups.
- States: default; hover on evidence links/actions; active selected artifact; focus trap when rendered as modal sheet; disabled downloads explain missing package; loading skeleton evidence groups; empty no evidence selected; error unavailable evidence package; stale source warning; rejected approval or replay mismatch; approved verified proof; demo sample evidence label.
- Accessibility: rail has `aside` landmark with accessible name; bottom sheet restores focus to trigger on close; copy buttons announce copied state.
- Motion: sheet enters from inline end or block end in 180ms; reduced motion removes travel.
- Layout: sticky-aside on desktop, modal bottom sheet on mobile.

### ApprovalEvidence

- Structure: approval state header, reviewer steps, policy constraints, proof hash, signed request metadata, approve/reject affordances when allowed.
- Variants: pending, approved, rejected, stale-ineligible, demo.
- Spacing: `--space-2` step rows, `--space-3` groups.
- States: default pending; hover on actions; active action pressed; focus visible; disabled approve when proof or freshness missing; loading request/decision in progress; empty no approval requested; error structured request failure; stale blocks approval with age and policy reason; rejected keeps reason, reviewer, and timestamp; approved exposes signed proof metadata; demo cannot be mistaken for real authorization.
- Accessibility: reviewer steps are ordered and named; approve/reject controls have distinct labels; destructive or irreversible wording is not used because approval is evidence-only.
- Motion: state transition crossfade 160ms with live-region announcement.
- Layout: stack in EvidenceRail or dedicated panel.

### ErrorState

- Structure: state title, exact code, human-readable detail, request or evidence ID, retry or safe navigation action.
- Variants: API outage, invalid patch, stale telemetry, rejected approval, no execution surface, build identity mismatch, demo unavailable.
- Spacing: `--space-4` container padding, `--space-2` action gap.
- States: default error; hover/focus/active actions; disabled retry when unsafe; loading after retry; empty not applicable; stale specialized warning; rejected specialized failure; approved not used; demo specialized copy.
- Accessibility: `role="alert"` only for newly appearing blocking errors; otherwise `status`; text explains recovery path without relying on icon or color.
- Motion: none.
- Layout: stack that fits inside any panel without forcing horizontal scroll.

### Skeleton

- Structure: reserved blocks matching final table, timeline, graph, chart, diff, or rail geometry.
- Variants: table rows, timeline rows, chart frame, topology frame, code lines, evidence rail.
- Spacing: inherits target component spacing.
- States: default loading; reduced-motion static; error replaced by ErrorState; empty replaced by empty state; stale/rejected/approved/demo not represented by skeleton.
- Accessibility: hidden from screen readers when paired with live loading text; never the only indication of loading.
- Motion: subtle 1.2s opacity shimmer only when `prefers-reduced-motion: no-preference`; no lateral shimmer that implies fake progress.
- Layout: reserves final dimensions to prevent layout shift.

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
| --- | --- | --- | --- |
| Micro | `100ms` | `ease-out` | Button press, row hover, focus ring reveal |
| Standard | `140-180ms` | `cubic-bezier(0.2, 0, 0, 1)` | Drawer, sheet, route panel change |
| Progress | event driven | linear only for determinate progress | Simulation trace progress tied to real status |

### Rules

- Motion intensity is 2. The console should feel stable during incidents.
- Animate only transform and opacity. Do not animate width, height, top, left, grid, or layout-affecting properties.
- Motion must communicate state transition, focus, relationship, or progress. Decorative glow, glass shimmer, background animation, and looping ornament are rejected.
- `prefers-reduced-motion: reduce` disables non-essential transitions and shimmer.
- Keyboard and pointer interactions must have equivalent state feedback. Hover-only affordances are not sufficient.
- Long-running simulation progress uses textual steps and deterministic timestamps rather than decorative spinners.

## 7. Depth & Surface

### Strategy

Depth strategy: mixed tonal shift plus 1px border.

| Level | Treatment | Usage |
| --- | --- | --- |
| Root | `--surface-root` | App background |
| Sunken | `--surface-inset` plus `1px solid --border-subtle` | Patch diff, code, skeleton beds |
| Panel | `--surface-panel` plus `1px solid --border-subtle` | Tables, topology, timelines |
| Raised | `--surface-raised` plus `1px solid --border-strong` | Active rail item, popover, mobile sheet |
| Focus | `2px solid --accent-primary` plus 2px offset | Keyboard focus only |

### Rules

- No decorative glow, no glassmorphism, no blur-as-style, no bokeh, no gradient orbs.
- Shadows are avoided by default. When elevation must detach a modal or sheet, use a tokenized shadow that is subtle, dark, and secondary to the border.
- Border radius scale: 4px for controls and table rows, 6px for panels, 8px maximum for modals or sheets. Cards are not nested inside cards.
- Density is created with typography, spacing, and dividers, not cramped unreadable text.

## 8. Accessibility Constraints & Accepted Debt

### Constraints

- WCAG target: 2.2 AA minimum. Body text contrast must be at least 4.5:1; large text and graphical UI elements at least 3:1; focus indicators at least 3:1 against adjacent colors.
- Touch targets: 44px minimum hit area for interactive controls, including icon buttons in dense rails.
- Visible focus: every interactive element has a visible keyboard focus state using `--accent-primary`, not browser-default removal.
- Color-not-only: status must include text and icon or pattern. Charts use line style, symbol shape, label, and table values in addition to color.
- Reduced motion: all non-essential motion is disabled under `prefers-reduced-motion`.
- Theme system: light and dark mappings are defined together. Default may follow system preference, but every route must pass in both themes.
- Low vision and zoom: every route must remain operable at 200 percent browser zoom with no loss of primary content or controls.
- Keyboard operator: full happy and failure flows must be completable without pointer interaction.
- Screen reader: route landmarks, table semantics, live regions, drawer focus management, and canvas fallbacks are required.
- Cognitive accessibility: object identity, current state, next safe action, and evidence provenance must stay visible or one drill-down away. Do not require users to remember hidden run IDs or prior decisions.

### Inclusive Personas

| Persona | Context | Must succeed |
| --- | --- | --- |
| Incident-pressure keyboard operator | Uses keyboard while responding to a degraded synthetic network scenario | Select scenario, run simulation, compare metrics, open evidence, and request approval without pointer-only controls |
| Color-vision deficient reviewer | Cannot rely on red/green status contrast | Understand improved vs degraded metrics, approved vs rejected states, and stale warnings through labels, icons, stroke styles, and table text |
| Low-vision 200 percent zoom user | Browser zoom at 200 percent, possible high contrast preference | Navigate each route, read tables and patches, open rail details, and recover from errors without hidden controls or horizontal page scroll |
| First-time reviewer with limited working memory | Knows the portfolio story but not the product model | Identify what is synthetic, what evidence was generated, why a change is safe or unsafe, and why approval is not execution |

### Accepted Debt

| Item | Location | Why accepted | Owner / Exit |
| --- | --- | --- | --- |
| None | All routes | Zero accepted design or accessibility debt at contract creation | New debt must be added here with owner approval before implementation can claim completion |

### Verification Requirements

- Primitive showcase before product screens: every Section 5 primitive must be rendered in default, hover, active, focus, disabled, loading, empty, error, stale, rejected, approved, and demo states where the state applies.
- Route visual QA: ScenarioWorkbench, RunDetail, EvidenceBoard, BenchmarkLab, and About at desktop and mobile viewports, including loading, empty, error, stale, rejected, approved, and demo.
- Accessibility checks: axe zero serious or critical, keyboard traversal, screen reader labels for canvas fallback and rails, color contrast checks in light and dark themes, 44px target audit, and 200 percent zoom audit.
- Data contract checks: no fake/chat/screenshot data; build identity and evidence hashes visible where plan requires; mutation authority absent from labels and actions.
- Final implementation gate: pass the accepted Task 9 command sequence from the plan, including `pnpm --dir frontend typecheck`, tests, build, Playwright, and `assert_visual_qa_manifest.py` with the required states and reviewers.
