# Armarius — Frontend Design System

> Status: **v1 — "SCRIPTORIUM"** (2026-06-27). The visual + interaction layer for the mock-data app
> (DEV_PLAN FE-0). Governs every surface built in FE-1…FE-3. Owner-chosen direction: a warm,
> editorial **Scriptorium** — parchment, terracotta + manuscript gold, classical high-contrast serifs,
> and ornamental medieval details — matched to the owner's reference image. (An earlier cyberpunk
> direction was set aside after review.)

## 1. Concept

Armarius is a **scriptorium for agent collaboration**: a Patron masters a workshop of agents the way
a medieval scribe-master oversaw a manuscript atelier. Warm aged-paper surfaces, terracotta and
gold-leaf accents, high-contrast serifs, decorated initials and ornate frames — refined, editorial,
with a touch of warmth. **Not** flat SaaS, **not** dark/neon.

**The one thing to remember:** the page should feel like an *illuminated manuscript come to life* —
parchment texture, gilt edges, ink that settles into the page, initials that drop in.

## 2. Color tokens (CSS variables)

All defined in `frontend/src/index.css :root`. Legacy var names are **kept and repointed** so old
pages auto-reskin; new `--*` tokens are the canonical names.

### Surfaces (warm parchment)
| Token | Value | Use |
|---|---|---|
| `--paper` | `#F8F3E6` | page background (aged parchment) |
| `--paper-2` | `#F1E9D6` | deeper parchment |
| `--panel` | `#FBF7EC` | cream panel (elevated) |
| `--panel-2` | `#F6EFD9` | panel hover |
| `--line` | `#D4B896` | aged paper border |
| `--line-soft` | `#E4D6B8` | subtle divider |
| `--gilt` | `#C9A227` | manuscript gold (ornamental) |
| `--gilt-bright` | `#E0B540` | gold highlight |

### Text
| Token | Value |
|---|---|
| `--ink` | `#2B2722` (warm charcoal) |
| `--ink-soft` | `#6E6258` (muted ink) |
| `--ink-faint` | `#9A8E78` |

### Accents
| Token | Value | Role |
|---|---|---|
| `--terra` (`--gold`,`--gold-bright`) | `#C25A3A` / `#D9744E` | **primary accent** (terracotta) |
| `--manuscript-gold` | `#C9A227` | gilt highlight — frames, dividers, initials |
| `--ink-brown` | `#8B4513` | ornamental strokes |
| `--blue` | `#3A5876` | status: todo |
| `--green` | `#5E7A4A` | status/liveness: done / online |
| `--rust` | `#A8492C` | status: blocked / hung |
| `--violet` | `#7A5A8A` | status: in_review |
| `--slate` | `#857B6A` | status: backlog / muted |

**Status → color:** backlog `--slate` · todo `--blue` · in_progress `--terra` · in_review `--violet`
· blocked `--rust` · done `--green` · cancelled `--ink-faint` (+ `draft` = a dashed `--terra` chip).
**Liveness → color:** online `--green` · working `--terra` (pulse) · idle `--gilt` · offline
`--ink-faint` · hung `--rust`.

## 3. Typography

Distinctive, classical — the serif character is the identity.
| Role | Font | Where |
|---|---|---|
| **Display** | `Fraunces` (high-contrast serif, optical sizing, 600/700) | big headings, wordmark, numerals |
| **Body / UI** | `Spectral` (screen-optimized serif, editorial warmth) | all readable text + UI labels |
| **Ornamental initial** | `UnifrakturMaguntia` (blackletter) | decorated initials / wordmark flourish only |
| **Data / tokens** | `JetBrains Mono` | run trace, IDs, tokens, mono labels |

Loaded via Google Fonts in `index.html`. Classes: Tailwind `font-display` (Fraunces), `font-serif`
(Fraunces, legacy alias), `font-sans` (Spectral body), `font-mono` (JetBrains), `.font-initial`
(UnifrakturMaguntia).

## 4. Interaction / motion language

Each is a named, reusable effect. All respect `prefers-reduced-motion` (see §7). Warm and
manuscript-like — **no** glitch/scanline/neon.

| Name | Trigger | What happens | Impl |
|---|---|---|---|
| **quill-in** | page/section mount | fade in + ink-settle (soft blur → sharp), staggered like ink drying | `.quill-in` + `style={{animationDelay}}` |
| **scroll-unfurl** | modal/panel open | gentle scale(0.98→1) + fade, like unrolling a scroll | `.unfurl` + `@keyframes unfurl` |
| **gilt-hover** | hover on panels/cards/buttons | warm gold sheen sweeps across + lift 2px + soft shadow | `.gilt:hover` + `@keyframes sheen` |
| **wax-seal** | button `:active` | depress + soft inset shadow (wax pressed) | `.btn:active` |
| **pulse** | working agent / live run | terracotta glow ring pulses | `.pulse` + `@keyframes pulse-ring` |
| **drop-cap** | headers/lead paragraphs | large decorated initial (Fraunces/UnifrakturMaguntia) | `<DropCap>` component |

## 5. Component primitives (`src/ui.tsx` + `.panel/.btn/.chip/.input`)

- **`.panel`** — cream surface, aged `--line` border, soft warm shadow, optional **ornate frame**
  (`::before`/`::after` gilt corner accents). `.panel-flat` = no accents.
- **`.btn`** — outlined gilt; hover sweeps a warm sheen. **`.btn-primary`** — terracotta fill, gilt
  edge, `wax-seal` on press. **`.btn-danger`** — rust. Disabled dims.
- **`.chip`** — aged-border tag; color set inline per status/liveness.
- **`.input`** — cream field, aged border, terracotta focus ring (glow).
- **`.rule`** — gilt gradient divider.
- **`<Modal>`** — warm scrim (`rgba(60,45,25,0.45)` + blur), ornate panel, Fraunces title.
- **`<StatusBadge>` / `<LivenessDot>`** — earthy dot + label (labels i18n).
- **`<DropCap>`** — decorated initial (Fraunces by default; blackletter variant for flourishes).
- **`<Avatar>`** — gilt-ringed monogram; liveness dot overlaid.

## 6. Atmosphere (page background)

Layered on `body`, all subtle so content stays crisp:
1. `--paper` parchment base.
2. **Warm radial glows** — terracotta tint top-left, gold tint top-right (very low opacity).
3. **Parchment grain** — an inline SVG noise overlay at low opacity (`.grain`).
4. **Soft vignette** — subtle darkening at the edges.
Static — **no animated grid** (that was the discarded cyberpunk direction).

## 7. Accessibility

- **Reduced motion:** `@media (prefers-reduced-motion: reduce)` disables `quill-in`, `unfurl`,
  `sheen`, `pulse` (liveness stays a static colored dot).
- **Contrast:** warm charcoal `--ink` on parchment meets WCAG AA for body text; terracotta is used
  for accents and large text, always paired with a label.
- **Focus:** every interactive element has a visible terracotta focus ring (never `outline: none`
  without replacement). Keyboard nav works (FE-3 hardens).
- **No motion-only meaning:** liveness/status conveyed by color + label, not pulse alone.

## 8. Usage notes

- New surfaces (FE-2a–e) compose from these primitives only — no bespoke themes per page.
- The mock-data layer (FE-1) drives the *content*; this system drives the *look + feel*.
- The `/style` playground (FE-0) renders every token, primitive, and motion — the live spec.

## 9. Out of scope (later)
- Per-page illuminated illustrations / custom cursors beyond hover states.
- A dark "night-scriptorium" variant (Scriptorium is light/parchment by design).
