# Grok Orbit

Local-first desktop command center for Grok CLI, Grok Bot, grok.com, and other model keys.

Users install the Windows package, verify email, pay $19 once, connect the tools on their machine, and watch the fleet in one panel. It does not replace `grok dashboard` inside a pager. It sees the windows that dashboard cannot.

MIT. Not orbitstack (that tree is LeoAware / VELA). GitHub: `Pitchfork-and-Torch/grok-orbit`.

## First setup (end users)

See `FIRST-SETUP.md`. License API: https://orbit.jonbailey.xyz/

## Run from source

```powershell
cd grok-orbit
npm install
npm run tauri dev
```

```powershell
py -3 .\scripts\snapshot.py
```

Packaged Windows installer:

```powershell
npm run tauri build
```

## Docs

- `FIRST-SETUP.md` - email, $19 key, connect surfaces
- `DESIGN.md` - architecture
- `AGENTS.md` - folder law
