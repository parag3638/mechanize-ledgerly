# DESIGN.md — Frontend UI system

> Read this before any frontend change. It is the source of truth for look, tokens and component usage.
> If a request conflicts with this file, follow the request and flag the conflict in one line.

**Feel:** nocturnal finance terminal. Matte-black canvas, luminous white type, colour only where it carries meaning, depth from light (halos, hairlines) instead of boxes.
**References:** Odyssey (odyssey.paragsingh.in) for structure, Fey by T. Costa for finish.
**Stack:** Next.js App Router, Tailwind v4, shadcn/ui, lucide icons, Recharts (via shadcn Chart).

---

## 0. Prerequisites

Agent: run every check, install what's missing, then report a one-line status per row before touching UI.

| # | Item | Check | Install |
|---|------|-------|---------|
| 1 | Node 20+ | `node -v` | `nvm install --lts` |
| 2 | Next.js + Tailwind v4 | `grep -E '"next"\|"tailwindcss"' package.json` | New project: `npx shadcn@latest init -t next` |
| 3 | shadcn initialised | `test -f components.json && npx shadcn@latest info` | `npx shadcn@latest init` |
| 4 | shadcn skill | `npx skills list \| grep -i shadcn` | `npx skills add shadcn/ui` |
| 5 | shadcn MCP | `/mcp` shows `shadcn` Connected | `npx shadcn@latest mcp init --client claude`, restart |
| 6 | frontend-design plugin | `/plugin` → Installed | `/plugin marketplace add anthropics/claude-plugins-official` then `/plugin install frontend-design@claude-plugins-official` |
| 7 | Playwright MCP (used by tester) | `/mcp` shows `playwright` | `claude mcp add playwright -- npx @playwright/mcp@latest` |
| 8 | Check script | `pnpm check` runs | `pnpm add -D @biomejs/biome vitest`, then add `"check": "biome check . && tsc --noEmit && vitest run"` to `package.json` |
| 9 | App font | `--font-app` set in `app/layout.tsx` | See §3 |

Notes
- Other agents (Cursor, VS Code, Codex): use the MCP config from ui.shadcn.com/docs/mcp.
- Pick one base library at init (`base` or `radix`). Never mix.
- Precedence: this file > frontend-design plugin > shadcn defaults.

Baseline components (add once):

```bash
npx shadcn@latest add button card badge input input-group kbd table tabs toggle-group \
  dialog sheet alert-dialog dropdown-menu command tooltip hover-card skeleton empty \
  spinner field select item scroll-area carousel chart toast
```

Everything else: add on demand via MCP or `npx shadcn@latest search <query>`.

---

## 1. Principles

1. **Black is the canvas, white is the voice.** Hierarchy comes from type weight and grey levels, not containers.
2. **Colour is a signal.** Chromatic colour only for price direction, status, the active/focused element and one brand accent. Never decorative fills.
3. **Depth by light.** A soft black halo or a 1px white-alpha hairline. Never stacked grey drop shadows.
4. **Pills for controls, soft cards for content.** Interactive = `rounded-full`. Containers = `rounded-2xl`.
5. **Dense, calm, exact.** Compact padding, tabular numbers, right-aligned figures, no shouting weights.
6. **One memorable thing per screen.** Everything around it stays quiet.

---

## 2. Tokens — `app/globals.css`

Keep the imports and the `@theme inline` mappings that `shadcn init` generated. Delete init's `:root` and `.dark` colour blocks and paste this. Dark is the default; `<html>` keeps `class="dark"` so shadcn's `dark:` variants apply.

```css
/* ---- additions to init's @theme inline ---- */
@theme inline {
  --font-sans: var(--font-app), ui-sans-serif, system-ui, sans-serif;
  --color-brand: var(--brand);
  --color-brand-foreground: var(--brand-foreground);
  --color-gain: var(--gain);
  --color-loss: var(--loss);
  --color-warning: var(--warning);
}

/* ---- type roles + depth ---- */
@theme {
  --text-display: clamp(2.5rem, 2rem + 2.5vw, 3.5rem);
  --text-display--line-height: 1;
  --text-display--letter-spacing: -0.05em;
  --text-display--font-weight: 600;

  --text-title: 1.5rem;
  --text-title--line-height: 1.2;
  --text-title--letter-spacing: -0.035em;
  --text-title--font-weight: 600;

  --text-heading: 1.125rem;
  --text-heading--line-height: 1.3;
  --text-heading--letter-spacing: -0.01em;
  --text-heading--font-weight: 500;

  --text-body: 0.875rem;
  --text-body--line-height: 1.5;

  --text-label: 0.75rem;
  --text-label--line-height: 1.3;
  --text-label--font-weight: 500;

  --text-caption: 0.6875rem;
  --text-caption--line-height: 1.4;

  --shadow-halo: 0 0 44px 0 oklch(0 0 0 / 0.8);
  --shadow-glow: 0 1px 0 0 oklch(0 0 0 / 0.85), 0 0 14px 0 oklch(1 0 0 / 0.25);
}

/* ---- palette (dark default) ---- */
:root {
  --radius: 0.625rem;

  --background: oklch(0.150 0 0);              /* #0b0b0b canvas */
  --foreground: oklch(0.985 0 0);              /* #fafafa */
  --card: oklch(0.187 0 0);                    /* #131313 */
  --card-foreground: var(--foreground);
  --popover: oklch(0.213 0 0);                 /* #191919 */
  --popover-foreground: var(--foreground);
  --primary: oklch(0.985 0 0);                 /* white pill CTA */
  --primary-foreground: oklch(0.150 0 0);
  --secondary: oklch(0.213 0 0);
  --secondary-foreground: var(--foreground);
  --muted: oklch(0.213 0 0);
  --muted-foreground: oklch(0.645 0.016 244.8); /* #868f97, 6:1 on canvas */
  --accent: oklch(1 0 0 / 6%);                 /* hover / selected wash */
  --accent-foreground: var(--foreground);
  --destructive: var(--loss);
  --border: oklch(1 0 0 / 8%);
  --input: oklch(1 0 0 / 12%);
  --ring: var(--brand);

  --brand: oklch(0.691 0.159 251.8);           /* signal #479ffa */
  --brand-foreground: oklch(0.150 0 0);
  --gain: oklch(0.726 0.119 166.5);            /* #4ebe96 */
  --loss: oklch(0.677 0.176 18.1);             /* #f0616d */
  --warning: oklch(0.820 0.141 78.8);          /* #f5b84b */

  --chart-1: var(--brand);
  --chart-2: var(--gain);
  --chart-3: oklch(0.793 0.131 49.5);          /* ember */
  --chart-4: oklch(0.867 0.067 254.8);         /* frost */
  --chart-5: var(--muted-foreground);

  --sidebar: var(--background);
  --sidebar-foreground: var(--foreground);
  --sidebar-primary: var(--brand);
  --sidebar-primary-foreground: var(--brand-foreground);
  --sidebar-accent: var(--accent);
  --sidebar-accent-foreground: var(--foreground);
  --sidebar-border: var(--border);
  --sidebar-ring: var(--ring);
}

/* ---- theme colour presets: set data-accent on <html> ---- */
[data-accent="ember"]  { --brand: oklch(0.793 0.131 49.5); }
[data-accent="frost"]  { --brand: oklch(0.867 0.067 254.8); }
[data-accent="volt"]   { --brand: oklch(0.938 0.197 121.6); }
[data-accent="growth"] { --brand: oklch(0.726 0.119 166.5); }

/* ---- utilities ---- */
@utility page {
  width: 100%;
  max-width: 75rem;
  margin-inline: auto;
  padding-inline: 1rem;
  @media (width >= 48rem) { padding-inline: 1.5rem; }
}

@utility glass {
  background-color: color-mix(in oklch, var(--background) 72%, transparent);
  border: 1px solid var(--border);
  backdrop-filter: blur(16px) saturate(140%);
}

@layer base {
  * { @apply border-border outline-ring/50; }
  body {
    @apply bg-background text-foreground font-sans text-body antialiased;
    font-variant-numeric: tabular-nums;
  }
  ::selection { background: color-mix(in oklch, var(--brand) 30%, transparent); }
}
```

### Changing the theme colour
- Set `data-accent` on `<html>`: `signal` (default), `ember`, `frost`, `volt`, `growth`.
- New theme = one new `[data-accent]` block. Never recolour inside component files.
- Avoid `growth` as brand in trading screens; it collides with `gain`.

---

## 3. Typography

One family. No second face, no monospace outside code blocks.

| Option | Source | When |
|--------|--------|------|
| Calibre | Klim (licensed) | If licence available — exact Fey voice |
| Satoshi | Fontshare (free), `next/font/local` | Default choice |
| Inter Tight | `next/font/google` | Zero-setup fallback |

```tsx
// app/layout.tsx
import localFont from "next/font/local"
const app = localFont({ src: "./fonts/Satoshi-Variable.woff2", variable: "--font-app", display: "swap" })
// fallback: const app = Inter_Tight({ subsets: ["latin"], variable: "--font-app" })

<html lang="en" className={`dark ${app.variable}`} data-accent="signal">
```

| Class | Spec | Use |
|-------|------|-----|
| `text-display` | 40–56 / 600 / −0.05em | Hero, portfolio value |
| `text-title` | 24 / 600 / −0.035em | Page titles |
| `text-heading` | 18 / 500 / −0.01em | Card and section titles |
| `text-body` | 14 / 400 / 1.5 | Default |
| `text-label` | 12 / 500 | Nav, table headers, field labels |
| `text-caption` | 11 / 400 + `text-muted-foreground` | Timestamps, footnotes |

Rules: weights 400–600 (700 only if the font needs it at display size). Sentence case everywhere. Tracking tightens as size grows; never positive on headings. Prose under 80ch. Tune `--text-display--letter-spacing` per font (Calibre takes −0.08em; Satoshi/Inter Tight look right near −0.05em).

---

## 4. Surfaces and depth

| Level | Class | Use |
|-------|-------|-----|
| 0 Canvas | `bg-background` | Page |
| 1 Card | `bg-card border` | Panels, tables, stat cards |
| 2 Raised | `bg-popover` | Menus, dialogs, nested wells |
| Glass | `glass` | Top bar, floating bars, overlays on charts |

- `shadow-halo`: hero and feature cards only.
- `shadow-glow`: primary button only.
- Overlay backdrop: shadcn default (`bg-black/80`-ish) is fine.

---

## 5. Colour usage

- **Direction:** `text-gain` / `text-loss`, always with a sign (+/−) or ▲/▼ icon. Never colour alone.
- **Brand:** active nav indicator, focus ring, inline links, selected toggle, `chart-1`. Max one brand element per card.
- **Primary button is white**, not brand. No filled chromatic buttons.
- **Badges are tinted, not solid:** `bg-gain/12 text-gain`, `bg-loss/12 text-loss`, `bg-warning/12 text-warning`, `bg-brand/12 text-brand`, neutral = `secondary`.

---

## 6. Layout

- **Shell:** sticky `glass` top bar (`h-14 border-b`) → `<main className="page">` → sections with `gap-12` (48px) or `gap-16` (64px).
- **Top bar:** logo, nav pills (Home, Stocks, Research, Portfolio), spacer, search (InputGroup + `Kbd` "/"), mode badge (Paper/Live), avatar.
- **Grid:** 12 columns at `lg`. Dashboards use an 8/4 main/rail split; rail stacks below main under `lg`.
- **Spacing:** card padding `p-5` (dense `p-4`); inside cards `gap-3`/`gap-4`; between cards `gap-4`/`gap-6`.
- **Alignment:** left by default; numeric columns right; empty states centred.
- **Responsive:** mobile first. Wide tables sit in `ScrollArea` on mobile.

---

## 7. Components — shadcn first

### Rules
1. Before writing any UI piece, search the registry (MCP, `npx shadcn@latest search`, `npx shadcn@latest docs <name>`). If it exists, use it.
2. `components/ui/*` is shadcn source. Edit it only for global look changes, and log them in §7.3.
3. A composition used twice becomes a block in `components/blocks/*`. Feature code lives in `components/<feature>/*`.
4. Variants via `cva` in the component file. One-off tweaks via `className` + `cn()`.
5. Tokens only. No hex/rgb/oklch literals in TSX. No `[arbitrary]` values; if a value is missing, add a token.
6. Number formatting lives in `lib/format.ts` (currency, percent, compact, signed). No inline `toFixed`.

### 7.1 Need → component

| Need | Use |
|------|-----|
| Top nav items | `Button variant="ghost" size="sm"`; active = `text-foreground` + brand dot/underline |
| Global search ("/" or ⌘K) | `CommandDialog` + `Kbd` |
| Search field in top bar | `InputGroup` + `Kbd` |
| Timeframes (1D…ALL), Gainers/Losers | `ToggleGroup type="single" size="sm"` |
| Switching page sections | `Tabs` |
| Stocks, orders, positions | `Table`; sortable/filterable → shadcn data-table pattern (TanStack) |
| Rows with logo + meta (trades, bots) | `Item` |
| KPI / summary | `Card` → `StatCard` block |
| Status (Active, Paper, Filled) | `Badge` (tinted) |
| New order / New bot | `Dialog` for short forms, `Sheet` for long ones |
| Form fields | `Field` / `FieldGroup` + `Input` / `Select` / `Switch` |
| Row actions | `DropdownMenu` |
| Ticker preview | `HoverCard` |
| Icon-only hints | `Tooltip` |
| Tips / onboarding | `Carousel` |
| Charts | `Chart` with `--chart-*` tokens |
| Loading | `Skeleton` shaped like the content; `Spinner` inside buttons. Never "Loading…" text |
| Nothing to show | `Empty` with one action |
| After an action | `Toast` |
| Destructive confirm | `AlertDialog` |

### 7.2 Blocks (create once, reuse everywhere)
`PageHeader` (title, description, actions), `Section` (title, action, children), `StatCard` (label, value, delta), `Delta` (signed %, colour + arrow), `TickerCell` (logo, symbol, name), `Money` (formatted, tabular).

### 7.3 Global overrides in `components/ui` (apply once, then log)
- **Button:** all sizes `rounded-full`. `default` = `bg-primary text-primary-foreground shadow-glow hover:bg-primary/90`. `outline` = transparent with `border-input`, `hover:bg-accent`.
- **Card:** `rounded-2xl bg-card border p-5`.
- **Badge:** `rounded-full text-label`; add `gain`, `loss`, `warning`, `brand` tinted variants.
- **Table:** header `text-label text-muted-foreground`; rows `h-11 hover:bg-accent`; numeric cells `text-right tabular-nums`.
- **Popover / DropdownMenu / Dialog:** `bg-popover rounded-xl border shadow-halo`.
- **Tabs / ToggleGroup:** pill track `bg-secondary rounded-full p-0.5`; active item `bg-accent text-foreground`.

**Override log** (agent appends: date, component, change)
- _none yet_

---

## 8. Motion

- 150–200ms, ease-out. Animate what the user triggered: open, expand, confirm.
- At most one orchestrated moment per page (e.g. the portfolio value settling in on load).
- No fade-up on every section, no hover lift on cards.
- Live prices: brief `bg-gain/10` or `bg-loss/10` flash (~600ms) on change.
- Respect reduced motion (`motion-safe:` / `motion-reduce:`).

---

## 9. Copy

- Sentence case, plain verbs. Buttons name the action ("Place order", "Create bot"); the toast mirrors it ("Order placed").
- Errors: what happened and how to fix it. No apologies.
- Empty states invite one action.
- Link text names the destination ("All stocks"). No arrow glyphs.

---

## 10. Don'ts

- All-caps eyebrows above headings, middle-dot meta strings, `→` appended to links, monospace data labels.
- Colouring one word of a headline.
- Gradients or glows as decoration.
- Every block in an identical shadowed card; one radius on everything.
- `01 / 02 / 03` markers unless the content is a real sequence.
- More than one chromatic accent per card.
- Hardcoded colours, arbitrary values, duplicate components, new font families.

---

## 11. Workflow for every UI task

Roles: `architect` plans, you build, `tester` verifies (`.claude/agents/`).

1. Read this file. Confirm §0 is green.
2. Bigger than one small edit? Get a plan from `architect` and follow its steps in order.
3. State the single change you're making.
4. Search the registry → use or compose existing → only then write new code.
5. Implement that one change. Run `pnpm check`.
6. Hand to `tester`: what changed, where, and the step's acceptance criteria. Fix what it reports until PASS. Don't edit tests; if one looks wrong, say why.
7. Stop for review with the tester's report and screenshots.
8. `components/ui` changed → append to the §7.3 log. Any other deviation from this file → one line in `DECISIONS.md`.

**Done means:** `pnpm check` passes and `tester` reports PASS — §10 respected, contrast AA, keyboard focus visible, works at 390, 768 and 1440, reduced motion respected.
