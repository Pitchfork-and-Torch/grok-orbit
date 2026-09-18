import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import Unlock from "./Unlock";
import "./setup.css";

type LicenseStatus = {
  licensed: boolean;
  unlocked: boolean;
  observe: boolean;
  setup_complete: boolean;
  source: string;
};

type Surface = {
  id: string;
  label: string;
  status: string;
  detail: string;
  hint: string;
};

type Probe = {
  grok_home: string;
  python: boolean;
  scripts: boolean;
  surfaces: Surface[];
};

export default function Setup({ onDone }: { onDone: () => void }) {
  const [probe, setProbe] = useState<Probe | null>(null);
  const [status, setStatus] = useState<LicenseStatus | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [showUnlock, setShowUnlock] = useState(false);
  const [openai, setOpenai] = useState("");
  const [anthropic, setAnthropic] = useState("");
  const [gemini, setGemini] = useState("");
  const [xai, setXai] = useState("");
  const [cursor, setCursor] = useState("");

  const load = useCallback(async () => {
    const [lic, surf] = await Promise.all([
      invoke<LicenseStatus>("license_status"),
      invoke<Probe>("setup_probe"),
    ]);
    setStatus(lic);
    setProbe(surf);
    return lic;
  }, []);

  useEffect(() => {
    void load().catch((e) => setErr(String(e)));
  }, [load]);

  async function grantWeb() {
    setBusy(true);
    setErr("");
    try {
      await invoke<string>("web_grant_consent");
      await load();
      setNote("grok.com consent granted. Sync from the W view after you enter.");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveKeys() {
    setBusy(true);
    setErr("");
    try {
      await invoke("setup_save_connectors", {
        raw: JSON.stringify({ openai, anthropic, gemini, xai, cursor }),
      });
      await load();
      setNote("Keys saved on this PC only.");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    setBusy(true);
    setErr("");
    try {
      await invoke("setup_complete");
      onDone();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="setup-shell">
      <div className="setup-card">
        <p className="setup-kicker">Grok Orbit</p>
        <h1>Watch first. Pay only to act.</h1>
        <p>
          Galaxy is free. If this PC has no Grok yet, you will see a well marked <strong>Sample</strong>.
          Connect your tools. Unlock later ($19) to resume, COOK, ACP, and hand off.
        </p>
        <ul className="setup-surfaces">
          {(probe?.surfaces || []).map((s) => (
            <li key={s.id} className={`surf is-${s.status}`}>
              <div>
                <strong>{s.label}</strong>
                <span className="surf-st">{s.status}</span>
              </div>
              <p>{s.detail}</p>
              <p className="setup-muted">{s.hint}</p>
            </li>
          ))}
        </ul>
        <div className="setup-actions">
          <button className="setup-ghost" disabled={busy} onClick={() => void grantWeb()}>
            Grant grok.com consent
          </button>
          <button className="setup-ghost" disabled={busy} onClick={() => void load()}>
            Refresh detections
          </button>
        </div>
        <details className="setup-more">
          <summary>Other model API keys (optional)</summary>
          <label>Cursor Dashboard key</label>
          <input value={cursor} onChange={(e) => setCursor(e.target.value)} spellCheck={false} />
          <label>OpenAI</label>
          <input value={openai} onChange={(e) => setOpenai(e.target.value)} spellCheck={false} />
          <label>Anthropic</label>
          <input value={anthropic} onChange={(e) => setAnthropic(e.target.value)} spellCheck={false} />
          <label>Gemini</label>
          <input value={gemini} onChange={(e) => setGemini(e.target.value)} spellCheck={false} />
          <label>xAI API</label>
          <input value={xai} onChange={(e) => setXai(e.target.value)} spellCheck={false} />
          <button className="setup-ghost" disabled={busy} onClick={() => void saveKeys()}>
            Save keys on this PC
          </button>
        </details>
        <div className="setup-actions">
          <button className="setup-primary" disabled={busy} onClick={() => void finish()}>
            Enter Galaxy
          </button>
          {!status?.unlocked ? (
            <button className="setup-ghost" onClick={() => setShowUnlock((v) => !v)}>
              Unlock actions ($19)
            </button>
          ) : (
            <span className="setup-muted">Actions unlocked</span>
          )}
        </div>
        {showUnlock && !status?.unlocked ? (
          <Unlock
            onDone={() => {
              setShowUnlock(false);
              void load();
            }}
            onClose={() => setShowUnlock(false)}
          />
        ) : null}
        {note ? <p className="setup-note">{note}</p> : null}
        {err ? <p className="setup-err">{err}</p> : null}
      </div>
    </div>
  );
}
