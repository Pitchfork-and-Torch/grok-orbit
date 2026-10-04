# Grok Orbit

**Local-first desktop command center for Grok CLI, Grok Bot, grok.com, and other model keys.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.0.1-informational)](package.json)
[![Windows](https://img.shields.io/badge/windows-x64-0078D6)](https://orbit.jonbailey.xyz/download)
[![Live](https://img.shields.io/badge/license%20api-orbit.jonbailey.xyz-111111)](https://orbit.jonbailey.xyz/)

Install the Windows package, watch the fleet in one panel, then unlock acting tools when you want them. Orbit does not replace `grok dashboard` inside a pager. It sees the windows that dashboard cannot.

Download is free. Observe immediately. Pay **$19 once** later to unlock resume, COOK, ACP, and hand-off.

Not [OrbitStack](https://github.com/Pitchfork-and-Torch/orbitstack) (that tree is LeoAware / VELA).

**License API + download:** [orbit.jonbailey.xyz](https://orbit.jonbailey.xyz/)

## First setup

See [FIRST-SETUP.md](FIRST-SETUP.md).

1. Download from https://orbit.jonbailey.xyz/download (no payment).
2. The build is not Authenticode-signed. SmartScreen will say unknown publisher. More info, then Run anyway. Do not turn SmartScreen off.
3. Open Grok Orbit. Empty machines show a well marked Sample.
4. Observe Galaxy for free.
5. Unlock in the app (email, 6-digit code, $19 once) when you want to act.

Keys stay on this machine. Session transcripts are not uploaded.

## Run from source

```powershell
git clone https://github.com/Pitchfork-and-Torch/grok-orbit.git
cd grok-orbit
npm install
npm run tauri dev
```

Snapshot helper:

```powershell
py -3 .\scripts\snapshot.py
```

Packaged Windows installer:

```powershell
npm run tauri build
```

A source checkout does not require a paid key.

## Docs

- [FIRST-SETUP.md](FIRST-SETUP.md) - download, email, unlock
- [DESIGN.md](DESIGN.md) - architecture
- [AGENTS.md](AGENTS.md) - folder law

## Related

| Tool | Role |
|------|------|
| [cell](https://github.com/Pitchfork-and-Torch/cell) | Real PSTN number from the CLI |
| [HavenID](https://github.com/Pitchfork-and-Torch/HavenID) | Self-hosted identity + screening number |
| [GrokForge](https://github.com/Pitchfork-and-Torch/GrokForge) | Public-goods marketplace |

## License

MIT. See [LICENSE](LICENSE). Issues on this repo only.
