# Grok Orbit (folder law)

Local-first command center for Grok Build, Grok Bot, Grok web, and Cursor. MIT.

**This is not `~/orbitstack`.** orbitstack is LeoAware / VELA congestion control. Do not mix trees, crates, or docs.

## Canonical tree

`%USERPROFILE%\grok-orbit` only.

## Visibility

Public GitHub (`Pitchfork-and-Torch/grok-orbit`). License/download API lives at `orbit.jonbailey.xyz` (functional, not a marketing site).

## License + first setup (v1.0.1)

- Download is free. Galaxy observe is free. $19 unlocks resume, COOK, ACP, hand off, and Cursor follow-up. Public FAQ: orbit.jonbailey.xyz/#faq.
- Empty machines get a well marked Sample. Real sessions replace it.
- Keys look like `ORBIT-XXXX-XXXX-XXXX-XXXX`. Issued by `license-worker/`.
- New paid checkout emails the operator via Worker secret `NOTIFY_EMAIL` (from local agent-email config; never commit the address). Buyer still gets their own key mail. Deduped per Stripe session.
- Existing local data homes and `tauri dev` stay unlocked.
- First-run card: connect surfaces. Unlock is optional.
- Never write `auth.json`. Never store connector keys in the repo. Never print keys.

## Phase 1 rails

- Read local Grok state (`active_sessions.json`, `session_search.sqlite`, `summary.json`).
- Never write Grok session files.
- Never read `auth.json`, `mcp_credentials.json`, or `~/.grokbot/*token*`.
- Never `grok -p -r` into a **live** pager. Resume = new console window.
- Do not walk all of `~/.grok/sessions` for Galaxy. Use the sqlite index + live summaries.
- Compose with `knock-desk`. Do not invent a second claim protocol.
- SessionStart hooks stay empty. Orbit is not a Grok startup hook.
- Phase 2 ACP: attach idle sessions with `session/resume` (not load/replay). Prompt and answer `session/request_permission` in ask mode. Never `--always-approve`. Never attach a live TUI pager.

## How to run

```powershell
cd $env:USERPROFILE\grok-orbit
npm install
npm run tauri dev
```

Headless snapshot (no UI):

```powershell
py -3 .\scripts\snapshot.py
```

## Design

Read `DESIGN.md` before changing architecture. Phase 4/5 MCP is in: `scripts/orbit_mcp.py` registered as `[mcp_servers.grok-orbit]` (stdio, enabled). Tools: snapshot (includes activity + web surface), search (FTS snippets), session_detail, resume (refuses live TUI), focus (HWND resolve / bring to front, no inject), orbit_web_status (cache only, never launches a browser). Star window pops detail to the other monitor.

Web adapters: isolated profiles under `%LOCALAPPDATA%\com.knock.grokorbit\web\profiles\<browser>\`. Daily Brave listing: operator grant `brave_grok.py grant` then `brave_grok.py sync` (one CDP bounce). grok.com/x.ai cookies list Grok chats. cursor.com agents page is scraped in that same bounce. Cookie values never stored. Never send Brave cookies to `api.cursor.com` (official Cloud Agents API is key-only via `ORBIT_CURSOR_API_KEY` or `web/cursor_api_key.txt`). Do not leave port 9222 open. Isolated Brave cannot stay separate while daily Brave is running.

Galaxy Phase 7: sessions group into named wells (VELA, LeoAware, INSTAR, Ghost, Orbit, ...) via `scripts/projects.py` / `src-tauri/src/projects.rs`. Finished Cursor agents collapse. Do not group by raw cwd.

Phase 8 Pulse slice 1: UI polls a cached snapshot unless files change or 15s elapsed. `git remote` is memoized. Leftover wells (`loose`, `grok.com`) collapse. Manual Refresh / `r` forces a full collect.

Phase 8 Pulse slice 2: Cursor official refresh enriches latest-run status in parallel (6 workers), writes `cursor_web.done.json`, and is one-in-flight. W "Refresh via API" toasts `Refresh done: N agents, M running` when `cursor_web_probed_at` changes. Second click says already running. Hidden spawn (`CREATE_NO_WINDOW`). Never print the key.

Phase 8 Pulse slices 3-4: Tray tooltip names waiting work (`N waiting | title`). Window title gets `(N)` when hot. Unseen high-severity attention (running, error, pr_ready, acp_perm) toasts once (`orbit.db` attention_seen). 60s hidden Cursor pulse is on by default; W view can disable (`cursor_pulse` in consent.json). Star follow-up is confirm-once POST `/v1/agents/{id}/runs`. Busy agents refuse (open in browser). Not on MCP.

Phase 9 Flare slice 1: Cached Cursor `pr_url` is Clearance `pr_ready`, stays hot in Galaxy (not collapsed with finished), and Star has Open PR. Only `https://github.com/.../pull/N` or GitLab merge-request URLs. Never print keys.

Phase 9 Flare slice 2: Duplicate agents that share a pull URL collapse to one Clearance row and one Galaxy card. Situation counts unique PRs. Extra agents show as `+N more` on the winner card.

Star: `p` is in-app (same window, no second WebView). Leave Star with the Galaxy button, Esc, or `g` (also `c`/`f`/`w`). Shift+p / Other monitor is the detached window, created after invoke returns. Detached Star does not 2s-poll.

Phase 10 Clock slice 1: Galaxy cards show age (`3m`, `2h`). Live pagers quiet more than 30 minutes show `stale`. Cursor rows use agent/run timestamps, not the probe clock.

Phase 10 Clock slice 2: stale live pagers are Clearance `stale` (tray-hot). Situation leads with `N live pager(s) quiet >30m`.

Phase 11 Lens: full collect writes `snap_profile` (set `ORBIT_SNAP_PROFILE=1` for stderr). Activity tails memoize by path+mtime. 60s Cursor pulse skips enrich when `id+status+updated_at` matches `cursor_web.pulse.json`. `gh pr view --json state,isDraft,title,files` caches 5 min in `pr_state.json` (never printed). Clearance and tray only keep open/unknown PRs. Drafts stay Galaxy-only. Merged/closed finish. Star shows Updates/plan and PR file paths. No `gh` on the 2s poll. No MCP follow-up or gh writes.

Phase 12 Relay: Star lists other surfaces on the same named well. `y` opens the Relay picker (clipboard, new ACP, focus+copy to a sibling live pager, Cursor follow-up, open PR/chat). Packs include PR state/files and well members. Focus+copy never injects. New ACP uses the clone path, not a project slug. MCP adds `orbit_next`, `orbit_well`, `orbit_relay_pack` (read/pack only; no claim, no follow-up). Clearance rows have one verb.

UX (Night Range): Clash Display + Satoshi. Semantic tokens + designed `:focus-visible` rings. Situation lead is the Next clause; extra facts wrap. COOK lives in its own cluster (Shift+C). Adapter chips hide healthy noise. Selected cards scroll into view. Empty git is "working tree clean". Ctrl+K is grouped. Errors persist until dismiss. `?` key map. Do not import Inter. Do not `outline: none` without a ring.

Phase 13 Apex: Situation rust/python starts with `Next:`. MCP `orbit_next` uses `build_next()` (live + desk + cursor cache + PR overlay only). Enter opens Star, or on Clearance runs the row verb. Star fetches git porcelain for the clone/cwd, memo 10s, never on the 2s Galaxy poll. Hidden git spawn.

COOK: header COOK button (confirm-once) arms an in-app loop. Each tick (5 min) `scripts/cook.py tick` starts new `grok -p` consoles on named wells that have a clone, are not desk-occupied, and have no live pager. Idle Cursor agents get a cook follow-up (cap 4 grok / 2 cursor per tick). Galaxy shows a roster: cooking / sent (window closed = turn done) / waiting (usually the 4-Grok cap). STOP COOK disarms; already-running consoles stay up. No Task Scheduler. No Bot tokens. No live inject. No `--always-approve`. Not on MCP.

Tide: the next tick rotates last-sent Grok wells to the back so waiting wells cook. Galaxy prints `Next wave:`. Occupied, live pagers, and already-cooking windows still skip.

Harvest: staff write `.orbit/cook-receipt.json` (ok, shipped, next, files, tests) and do not commit `.orbit/`. Galaxy lists last ships. A fresh ok receipt skips that well for 45 minutes. Empty turns (window closed, no receipt) stay at the front. Armed loop harvests every 20s; next wave is 90s after windows close, 300s while they stay open. Prompts carry mission excerpt, last ship, leftover, and git dirty. Cook status overlays named-clone receipts in-process (no git remote, no extra Python). Still no Task Scheduler, no MCP arm, no live inject.

Never leave Orbit, Edge, Brave, Grok Bot, or the Grok TUI Always-on-Top. Clear with `Clear-AlwaysOnTop.ps1 -All`. Pin only the operator-chosen window via `Pin-SelectedWindow.ps1`.

Handoff: `get_handoff` builds a redacted pack. Never inject into a live TUI. `handoff_to_acp` starts a new Orbit ACP session in the linked project clone when one exists. Web sessions without a clone are copy-only. MCP `orbit_handoff` is pack-only.

Unattended gate (no GUI): `py -3 .\scripts\orbit_auto_test.py`

ACP smoke: `py -3 .\scripts\acp_roundtrip.py`

Bot/VM portable (Python only): `py -3 .\scripts\portable_acp_mock_test.py`

## Type

Fontshare Clash Display + Satoshi via `public/fonts/fontshare`. Do not introduce Inter.
