# Desktop apps, system tooling and network clients (sub-skill of software-development)

Distilled from the user's own `sushtun-expert` skill (sushTun: PySide6 + Xray-core TUN VPN client, Windows/Linux/macOS, PyInstaller). Only the generalisable rules are here; repo paths, the user's laptop/servers, release state and Xray internals stay in that skill. If the work is on sushTun, load `sushtun-expert` first.

Applies to: cross-platform desktop apps (Qt/Electron/Tauri), apps that wrap or supervise an external process, anything needing elevated privileges or changing OS state (routes, DNS, firewall, services), and VPN/proxy/network tools. Security companion: `../backend/security-audit/DESKTOP-MOBILE-AND-LOCAL-IPC.md`.

## Architecture
- Keep the core free of the UI toolkit (Qt-free, plain stdlib where practical); the UI layer translates strings. Core stays testable headless (`QT_QPA_PLATFORM=offscreen` for UI tests).
- Per-OS code behind small modules with a shared common layer (e.g. Windows / POSIX-Linux / macOS), not `if platform` scattered through logic.
- Defaults are no-ops: an untouched install behaves exactly like the base template; every setting/overlay is opt-in. Config merge: treat dict settings as schemas (unknown keys dropped), replace lists wholesale, so store user-defined maps as lists.
- Optional features must never break the main path: a bad optional entry (port, forward, DNS, rule) is dropped with a WARNING, not raised.

## Supervising an external process
- Sanitize everything before rendering config for it: many tools exit instantly on any unparseable config and the user just sees "can't connect".
- Validate with the real tool (its own `-test`/dry-run mode on a throwaway config) before trusting a guess about what it accepts; don't encode assumptions about limits you haven't checked.
- Update data files it consumes (e.g. geo lists) only after validating them against the current rules.
- Frozen/bundled builds put bundled libs on `LD_LIBRARY_PATH`; child tools (`resolvectl`, `ip`) can crash silently on the bundled libs. Run children with a cleaned environment helper.
- Detect conflicting software (another VPN/TUN owning the default route) and refuse up front with a clear message.

## Privileged operations and OS state
- Elevation by platform: UAC relaunch (Windows), `pkexec` (Linux), `osascript` (macOS). Know that running any binary unprivileged may pop a prompt on the user's screen; use `fakeroot` or scratch copies for headless checks.
- Anything that mutates OS state (DNS, routes, firewall, hotspot) needs guaranteed cleanup: teardown on every failure path, stale-state recovery after a crash (restore DNS/routes on next start), and boot-time tasks for leftovers. Persist what *you* changed and restore only that (e.g. stop tethering only if the app started it).
- A process running as root that writes into user-owned paths must go through a safe helper (no-follow, ownership checks) because of symlink attacks.
- Keep state files describing what is live (`profile_uid`, etc.); UI selection may differ from live state. Changing the selection while connected must not silently relabel the live connection; prompt to reconnect.

## Diagnosing "connected but X doesn't work"
1. Client or server? Run a 2x2 matrix (our core / reference client's core, x our profile / theirs) through a local SOCKS/HTTP inbound. Same result in all cells means the server side (fail2ban, firewall, relay).
2. Don't trust ping/telnet/traceroute through a TUN: a userspace TUN answers TCP handshakes locally and may drop or fake ICMP. Prove reachability with application bytes (SSH banner, real TLS response, `curl --noproxy '*'`).
3. Read the core log + `ip route`/`ip rule`/`resolvectl status` (Windows/macOS equivalents). Developer shells often export `http(s)_proxy`/`ALL_PROXY`; bypass them when testing.
4. Chaining relays can loop back through the same relay; the exit country is not the address's country (measure it, e.g. via a trace endpoint).
5. DNS in censored networks is filtered (sinkhole answers); leaks show up as sinkhole IPs.
6. Import tolerance: strip BOM (Notepad), accept alternative formats, accept numbers given as strings.

## i18n
- Core strings in English; one `tr()` for every user-visible literal; the second language is a dict keyed by the exact English text. Every new literal needs both entries (test for missing keys if cheap).
- RTL/bidi: Latin values (IPs, codes, URLs) LTR inside RTL text.
- Release notes bilingual in the changelog (English, then a marked Persian section in the user's own colloquial voice: draft it, let the user edit).

## Test, CI and release
- Bug fix: failing test first, per `../SKILL.md` §3.
- Reproduce CI in a clean worktree (`git worktree add --detach <scratch> <ref>`) before pushing: untracked local binaries and data files make local runs pass where CI fails. Never build in or switch branches of the user's main checkout.
- No local macOS? Use CI: add `workflow_dispatch` and a macOS job, push a temp branch, `gh workflow run`, `gh run watch`, delete the branch.
- Release only when the user says so: bump version, changelog section, full tests + linter, CI green on all OSes, fast-forward main, annotated tag, push main + tag. A tag-triggered workflow builds all artifacts (single-file binaries per OS, Windows installer, `.deb`, macOS `.dmg`) plus `SHA256SUMS`; verify the asset list with `gh release view`.
- Auto-update paths (e.g. `.deb` self-update) need integrity checks (checksums/signatures) and tests.
- README screenshots: render the real UI offscreen with fictional data via a script, so they are reproducible and leak nothing.
- Never `--no-verify`. Conventional commits (`feat(scope):`, `fix(ui):`, `chore: release X`).
