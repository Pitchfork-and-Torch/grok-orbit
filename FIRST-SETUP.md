# Grok Orbit first setup

Download is free. Watch your real fleet (or a labeled Sample well) immediately. Pay $19 later to unlock resume, COOK, ACP, and hand off.

## What they do

1. Download from https://orbit.jonbailey.xyz/download (no payment).
   The build is **not Authenticode-signed**. SmartScreen will say unknown publisher.
   Click More info, then Run anyway. Do not turn SmartScreen off.
2. Open Grok Orbit. Connect tools. Empty machines show a well marked Sample.
3. Observe Galaxy for free.
4. Unlock in the app (email, 6-digit code, $19 once) when you want to act.
5. Connect what is on this machine:
   - Grok CLI (detected from `~/.grok` / PATH)
   - Grok Bot desktop (detected under Local Programs)
   - grok.com (consent, then a Brave sync from the W view)
   - Optional Cursor Dashboard key
   - Optional OpenAI / Anthropic / Gemini / xAI keys
6. Enter Galaxy.

Keys stay under `%LOCALAPPDATA%\com.knock.grokorbit`. Session transcripts are not uploaded.

## Local development

A source checkout (`npm run tauri dev`) does not require a paid key.
Existing local data directories stay unlocked.

## License API

https://orbit.jonbailey.xyz/

Stripe product `grok-orbit-license`, price `price_1U4nrNLRSReqU8NalFEZD6PP` ($19).
