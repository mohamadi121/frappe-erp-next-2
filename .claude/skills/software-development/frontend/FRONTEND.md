# Frontend (sub-skill of software-development)

Two sources: **VibeFarsi** (https://github.com/TronIsHere/vibafarsiui, site vibefarsi.ir, MIT) for Persian/RTL product UI, and **Vengeance UI** (https://www.vengenceui.com, repo Ashutoshx7/VengeanceUI, MIT) for animated English/LTR marketing pages.

Graphify-first applies: before touching UI code, `graphify query/path` to find the component, its consumers and the design tokens. Verify UI in a real browser (Playwright CLI, see `../qa/QA.md`); UI tests are always Playwright.

## Which one to use
| Project | Use |
|---|---|
| Persian / Iranian product (dashboards, shops, forms, admin, anything user-facing in Farsi) | **VibeFarsi**, always. Don't ship shadcn/Radix defaults, Inter, Latin digits or `ml-`/`text-left` there. |
| English/LTR marketing or landing page that wants motion (hero, bento, tooltips, marquee, text effects) | **Vengeance UI** components, copy-pasted via shadcn CLI. |
| Persian landing page that wants motion | VibeFarsi's `animations`/`backgrounds`/`blocks` first (no extra deps, RTL-correct). Take a Vengeance component only if nothing equivalent exists, and re-check it for RTL (logical classes, flipped icons/motion direction, Persian font). |

## VibeFarsi
Stack: React + Tailwind v4 + `lucide-react`; copy-paste registry, **not an npm UI kit** (own the files; no component-library dependency). Works with Next.js and Vite.

Setup (once per project): `npx vibefarsi@latest init` writes `lang="fa" dir="rtl"`, Vazirmatn (or `--font iransans`), theme tokens in `globals.css`, `lib/utils.ts` (Persian digits, `formatToman`, `cn`), `lib/jalali.ts`, and the agent rules block in `AGENTS.md` (+ `@AGENTS.md` in `CLAUDE.md`). Add parts: `npx vibefarsi add button calendar price` (dependencies resolve themselves); `npx vibefarsi list`; use `--dry-run` first on an existing project, `--overwrite` only deliberately.

Catalog: 68 components (inputs for phone, OTP, IBAN/Sheba, card, national ID, postal code, plate; price in toman; Jalali date picker/calendar; data table; etc.), 8 blocks, 15 charts (dependency-free), 10 calendar views, 39 animations, 44 backgrounds, 24 templates, 6 themes (graphite default/dark, turquoise, saffron, pomegranate, lapis, paper/light).

MCP (optional, token-efficient lookup instead of reading the repo): `claude mcp add --transport http vibefarsi https://vibefarsi.ir/mcp`; tools `get_design_rules` (topics: rtl, typography, numbers, forms, tokens, motion, a11y, iran, craft), `search_registry`, `get_component`, `get_theme`, `scaffold_page`. Page workflow: `get_design_rules` -> `scaffold_page` -> `get_component`.

### Non-negotiable rules (summary; full text in the vendored files)
- **RTL by default**: `<html lang="fa" dir="rtl">` once; logical CSS only (`ms/me`, `ps/pe`, `start/end`, `text-start`, `border-s`, `gap-*` not `space-x-*`); never `flex-row-reverse` to fix order; directional icons flip (`ArrowLeft` = next). Keep phone/email/OTP/IBAN/card/URL fields `dir="ltr"` on the control only.
- **Typography**: Persian font (Vazirmatn/IRANSans), `letter-spacing: 0`, body ~16-16.5px at line-height 1.8 (long reading 1.9, headings ~1.2, never <1.15), CSS `line-clamp` instead of `slice`.
- **Numbers**: show Persian digits (`fa()`), `٬` thousands, `formatToman` with unit after the number; forms/URLs/JSON keep Latin digits; Jalali dates with week starting Saturday via `lib/jalali.ts`; never mix toman and rial silently (rial = toman x 10).
- **Forms**: label above field with `htmlFor`; errors under field with `aria-invalid`; controls >=16px on iOS; Iranian validators (national ID checksum, IBAN, card Luhn, postal code) before inventing your own.
- **Tokens only**: colours/radius/shadows/motion from theme variables; no hex, no arbitrary values (`p-[13px]`); one accent per section; default Graphite, call `get_theme` before inventing a palette.
- **Craft** (`ui-craft-rules.md`): 4px grid with even sizes, touch targets >=44px, <=6 font sizes, lucide icons only (stroke matches text weight), `aspect-ratio`/min-height so there is zero layout shift, skeletons not spinners, 150-300ms motion on transform/opacity with `prefers-reduced-motion`, check at 360-390px, real copy (no lorem ipsum), dev panel only outside production. When told "make it prettier", name the concrete technique, then apply it.
- **A11y**: visible focus ring, Persian `aria-label` on icon buttons, dialogs trap/restore focus, contrast on both dark and light themes.
- **Copy**: Persian UI text must be specific and natural (no "Oops"); read `persian-ui-copy` before writing any Persian string.

### Vendored reference (MIT, copied unmodified from TronIsHere/vibafarsiui, license in `frontend/vibefarsi/LICENSE`)
Read the one you need (they are not auto-registered as skills):
| File | Read when |
|---|---|
| `frontend/vibefarsi/persian-rtl-ui/SKILL.md` | any Persian/RTL UI work (has the full checklist) |
| `frontend/vibefarsi/ui-craft-rules.md` | polishing/reviewing any UI; has the done-checklist and the agent block |
| `frontend/vibefarsi/agents-md-persian.md` | setting up CLAUDE.md/AGENTS.md in a Persian project |
| `frontend/vibefarsi/persian-typography.md` | fonts, line-height, bidi, truncation |
| `frontend/vibefarsi/persian-ui-copy/SKILL.md` | writing interface strings |
| `frontend/vibefarsi/persian-conversational/`, `persian-formal/` | casual vs official Persian text |
| `frontend/vibefarsi/iran-validation/SKILL.md` | national ID, IBAN, card, phone, postal code |
| `frontend/vibefarsi/jalali-calendar/SKILL.md`, `jalali.ts` | Jalali dates, holidays, conversions. **Warning:** `jalali.ts` `toJalali` reads the host's local date (`getFullYear/getMonth/getDate`), so on a UTC server it is a day early from 20:30 UTC; convert the instant to Asia/Tehran Y/M/D first. |
| `frontend/vibefarsi/persian-seo/SKILL.md` | Persian SEO/metadata |
| `frontend/vibefarsi/zarinpal-payment.md`, `kavenegar-otp.md`, `parspack-s3-upload.md` | Iranian payment gateway, SMS OTP, object storage (backend integration guides; treat secrets and callbacks per the backend security rules). **Warning:** `zarinpal-payment.md` spreads the client's `...body` after server-set fields (lines 279, 328), so a client can set `status`, `userId`, `amount` or `authority` (mass assignment); copy allowed fields explicitly and put server fields last. |
Component source is not vendored; fetch with `npx vibefarsi add <name>` or the MCP.

## Vengeance UI
Animated React components for landing pages: ~46 components in families (Buttons, Text & Motion, Layout & Cards/bento, Tooltip & Marquee, Navbar & Docs, Backgrounds, Loaders) plus 100+ blocks. Docs are at vengenceui.com/docs (install-nextjs, install-tailwind, theming, add-utilities, cli).

- Install: shadcn-based. `npx shadcn@latest init` (New York, Zinc, CSS variables), then `npx shadcn@latest add @vengeanceui/<component>` or the raw URL form `npx shadcn@latest add https://raw.githubusercontent.com/Ashutoshx7/VengeanceUI/main/public/r/<component>.json`. Tailwind v4 + Next.js.
- Utilities: `cn()` from `clsx` + `tailwind-merge`; many components need `framer-motion` (each component page lists its exact deps).
- Theme: optional `vengeance-theme.json` adds `--vng-*` tokens (primary, radius, transition speed) wired to shadcn tokens; set light values in `:root`, dark in `.dark`.
- Use it for visual flair on hero/marketing sections only. Keep one motion idea per section, honor `prefers-reduced-motion`, and check performance and CLS (heavy 3D/particle/shader components can hurt LCP on mobile); lazy-load below-the-fold effects.
- Not Persian/RTL-aware: the docs do not mention RTL. In RTL projects fix direction, fonts and digits after copying.
- Heads-up: the docs site displays a "Community Token CA" (a crypto-token contract address). Unrelated to the MIT-licensed code, but never run wallet/token actions from it; only fetch component JSON from the GitHub repo URL above.
- Since you own the copied files, review them like any third-party code (dependencies, `dangerouslySetInnerHTML`, network calls) before shipping.

## Generic frontend defaults (any project)
- Semantic HTML first; accessible names so Playwright `getByRole` works; add `data-testid` only where no role/label exists.
- Escape/encode untrusted content; no `dangerouslySetInnerHTML` without sanitising; keep secrets out of client bundles.
- Performance: budget bundle size, lazy-load heavy routes/effects, images with dimensions and modern formats, avoid layout shift.
- Match the repo's existing framework, styling and component conventions before introducing anything new.
