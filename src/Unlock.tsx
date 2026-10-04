import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

const API_HOSTS = [
  "https://orbit.jonbailey.xyz",
  "https://grok-orbit-license.pitchfork-and-torch.workers.dev",
];

async function licenseHost(): Promise<string> {
  for (const host of API_HOSTS) {
    try {
      const r = await fetch(`${host}/health`, { method: "GET" });
      if (r.ok) return host;
    } catch {
      /* try next */
    }
  }
  return API_HOSTS[0];
}

export default function Unlock({ onDone, onClose }: { onDone: () => void; onClose?: () => void }) {
  const [api, setApi] = useState(API_HOSTS[0]);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [token, setToken] = useState("");
  const [key, setKey] = useState("");
  const [step, setStep] = useState<"email" | "code" | "pay" | "key">("email");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [note, setNote] = useState("Observe is free. $19 unlocks resume, COOK, ACP, and hand off.");

  useEffect(() => {
    void licenseHost().then(setApi);
  }, []);

  async function post(path: string, body: Record<string, unknown>) {
    const r = await fetch(`${api}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
    return data;
  }

  async function sendCode() {
    setBusy(true);
    setErr("");
    try {
      await post("/v1/register", { email: email.trim().toLowerCase() });
      setNote("Code sent. Keep this window open and type it here.");
      setStep("code");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function verify() {
    setBusy(true);
    setErr("");
    try {
      const data = await post("/v1/verify", { email: email.trim().toLowerCase(), code: code.trim() });
      setToken(String(data.verify_token || ""));
      setNote("Email verified. Pay $19 once.");
      setStep("pay");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function pay() {
    setBusy(true);
    setErr("");
    try {
      const data = await post("/v1/checkout", {
        email: email.trim().toLowerCase(),
        verify_token: token,
      });
      if (!data.url) throw new Error("Checkout did not return a URL.");
      await invoke("open_setup_url", { url: String(data.url) });
      setNote("Stripe is open. After you pay, this screen picks up the key.");
      for (let i = 0; i < 90; i++) {
        await new Promise((r) => window.setTimeout(r, 2000));
        try {
          const paid = await post("/v1/paid", {
            email: email.trim().toLowerCase(),
            verify_token: token,
          });
          if (paid.key) {
            setKey(String(paid.key));
            await activate(String(paid.key));
            return;
          }
        } catch {
          /* wait */
        }
      }
      setStep("key");
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function activate(raw?: string) {
    const useKey = (raw || key).trim();
    setBusy(true);
    setErr("");
    try {
      const mid = await invoke<string>("license_machine_id");
      const data = await post("/v1/activate", {
        key: useKey,
        machine_id: mid,
        email: email.trim().toLowerCase() || undefined,
      });
      await invoke("license_save", {
        raw: JSON.stringify({
          key: useKey,
          email: data.email || email.trim().toLowerCase(),
          machine_id: mid,
          source: "paid",
        }),
      });
      onDone();
    } catch (e) {
      setErr(String(e));
      setStep("key");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="setup-block">
      <p>{note}</p>
      {step === "email" && (
        <>
          <label htmlFor="unlock-email">Email</label>
          <input
            id="unlock-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
          <button className="setup-primary" disabled={busy || !email.includes("@")} onClick={() => void sendCode()}>
            {busy ? "Sending..." : "Email me a code"}
          </button>
        </>
      )}
      {step === "code" && (
        <>
          <label htmlFor="unlock-code">Six-digit code</label>
          <input id="unlock-code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" />
          <button className="setup-primary" disabled={busy || code.trim().length < 4} onClick={() => void verify()}>
            Verify
          </button>
        </>
      )}
      {step === "pay" && (
        <button className="setup-primary" disabled={busy} onClick={() => void pay()}>
          {busy ? "Opening Stripe..." : "Pay $19"}
        </button>
      )}
      {step === "key" && (
        <>
          <label htmlFor="unlock-key">License key</label>
          <input id="unlock-key" value={key} onChange={(e) => setKey(e.target.value)} placeholder="ORBIT-XXXX-XXXX-XXXX" spellCheck={false} />
          <button className="setup-primary" disabled={busy || key.trim().length < 8} onClick={() => void activate()}>
            Activate
          </button>
        </>
      )}
      {onClose ? (
        <button className="setup-ghost" onClick={onClose}>
          Keep observing free
        </button>
      ) : null}
      {err ? <p className="setup-err">{err}</p> : null}
    </div>
  );
}
