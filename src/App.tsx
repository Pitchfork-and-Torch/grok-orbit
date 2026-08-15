import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type { AcpState, Attention, CookShip, CookState, GitPulse, HandoffPack, Project, SearchHit, Session, SessionDetail, Snapshot } from "./types";
import "./styles.css";

type View = "galaxy" | "clearance" | "feed" | "web";

type Cmd = { id: string; label: string; hint: string; group: string; kbd?: string };

function bootStarId(): string | null {
  try {
    return new URLSearchParams(window.location.search).get("star");
  } catch {
    return null;
  }
}

function bootIsStar(): boolean {
  if (bootStarId()) return true;
  try {
    return getCurrentWindow().label === "star";
  } catch {
    return false;
  }
}

export default function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("galaxy");
  const [selected, setSelected] = useState<string | null>(() => bootStarId());
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const [toastKind, setToastKind] = useState<"ok" | "error">("ok");
  const [helpOpen, setHelpOpen] = useState(false);
  const [gitPulse, setGitPulse] = useState<GitPulse | null>(null);
  const paletteRef = useRef<HTMLInputElement | null>(null);
  const [acp, setAcp] = useState<AcpState | null>(null);
  const [draft, setDraft] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [starMode, setStarMode] = useState(() => bootIsStar());
  const [openFinished, setOpenFinished] = useState<Record<string, boolean>>({});
  const [cursorRefreshing, setCursorRefreshing] = useState(false);
  const [followDraft, setFollowDraft] = useState("");
  const [followConfirm, setFollowConfirm] = useState(false);
  const [relayOpen, setRelayOpen] = useState(false);
  const [cookConfirm, setCookConfirm] = useState(false);
  const [cookBoard, setCookBoard] = useState<CookState | null>(null);
  const awaitingCursor = useRef(false);
  const seenCookDetail = useRef<string | null>(null);
  const seenCursorProbe = useRef<string | null>(null);
  const cursorWaitTimer = useRef<number | null>(null);

  const refresh = useCallback(async (full = false) => {
    try {
      const [next, acpNext, cookNext] = await Promise.all([
        invoke<Snapshot>("get_snapshot", { full }),
        invoke<AcpState>("acp_state"),
        invoke<CookState>("cook_status").catch(() => null),
      ]);
      setSnap(next);
      setAcp(acpNext);
      if (cookNext) setCookBoard(cookNext);
      setError(null);
      if (!selected && next.sessions[0]) {
        setSelected(next.sessions[0].id);
      }
    } catch (e) {
      setError(String(e));
    }
  }, [selected]);

  const flashToast = useCallback((msg: string, ms = 2400, kind: "ok" | "error" = "ok") => {
    setToastKind(kind);
    setToast(msg);
    if (kind === "error") return;
    window.setTimeout(() => setToast(null), ms);
  }, []);

  const exitStar = useCallback((next?: View) => {
    setStarMode(false);
    if (next) setView(next);
    else setView("galaxy");
  }, []);

  useEffect(() => {
    void refresh();
    const star = bootIsStar();
    const t = star
      ? undefined
      : window.setInterval(() => void refresh(false), 2000);
    let unlisten: (() => void) | undefined;
    void listen<{ title?: string }>("orbit-attention", (ev) => {
      if (ev.payload?.title) flashToast(ev.payload.title, 3600);
    }).then((fn) => {
      unlisten = fn;
    });
    return () => {
      if (t) window.clearInterval(t);
      unlisten?.();
      if (cursorWaitTimer.current) window.clearTimeout(cursorWaitTimer.current);
    };
  }, [flashToast, refresh]);

  useEffect(() => {
    const fromUrl = bootStarId();
    let unlisten: (() => void) | undefined;
    void (async () => {
      let label = "";
      try {
        label = getCurrentWindow().label;
      } catch {
        label = "";
      }
      const isStar = label === "star" || Boolean(fromUrl);
      if (isStar) setStarMode(true);
      let stored: string | null = null;
      if (isStar) {
        try {
          stored = await invoke<string | null>("star_session");
        } catch {
          stored = null;
        }
      }
      const id = fromUrl || stored;
      if (id) setSelected(id);
      try {
        const fn = await listen<string>("orbit-star", (ev) => {
          setStarMode(true);
          if (ev.payload) setSelected(ev.payload);
        });
        unlisten = fn;
      } catch {
        /* window still paints */
      }
    })();
    return () => {
      unlisten?.();
    };
  }, []);

  useEffect(() => {
    if (!palette) {
      setHits([]);
      return;
    }
    const q = query.trim();
    if (q.length < 2) {
      setHits([]);
      return;
    }
    const t = window.setTimeout(() => {
      invoke<SearchHit[]>("search_sessions_cmd", { query: q })
        .then(setHits)
        .catch(() => setHits([]));
    }, 120);
    return () => window.clearTimeout(t);
  }, [query, palette]);

  const refreshCursorApi = useCallback(async () => {
    if (awaitingCursor.current) {
      flashToast("Cursor refresh already running");
      return;
    }
    seenCursorProbe.current = snap?.surfaces.cursor_web_probed_at || "";
    awaitingCursor.current = true;
    setCursorRefreshing(true);
    if (cursorWaitTimer.current) window.clearTimeout(cursorWaitTimer.current);
    cursorWaitTimer.current = window.setTimeout(() => {
      if (awaitingCursor.current) {
        awaitingCursor.current = false;
        setCursorRefreshing(false);
        flashToast("Cursor refresh timed out (cache unchanged)", 3200);
      }
    }, 50000);
    try {
      const msg = await invoke<string>("web_sync_cursor_api");
      flashToast(typeof msg === "string" ? msg : "Cursor official API refresh started");
    } catch (e) {
      awaitingCursor.current = false;
      setCursorRefreshing(false);
      if (cursorWaitTimer.current) window.clearTimeout(cursorWaitTimer.current);
      const text = String(e);
      flashToast(text.includes("already running") ? "Cursor refresh already running" : text, 3200);
    }
  }, [flashToast, snap]);

  useEffect(() => {
    const probed = snap?.surfaces.cursor_web_probed_at || "";
    if (!awaitingCursor.current) {
      if (probed) seenCursorProbe.current = probed;
      return;
    }
    if (!probed || probed === seenCursorProbe.current) return;
    awaitingCursor.current = false;
    setCursorRefreshing(false);
    if (cursorWaitTimer.current) window.clearTimeout(cursorWaitTimer.current);
    seenCursorProbe.current = probed;
    const cursorSessions = (snap?.sessions || []).filter(
      (s) => s.source === "cursor_web" || s.id.startsWith("web:cursor:"),
    );
    const running = cursorSessions.filter((s) => s.agent_name === "running").length;
    flashToast(`Refresh done: ${cursorSessions.length} agents, ${running} running`, 4200);
  }, [flashToast, snap]);

  const copyHandoff = useCallback(async (id: string) => {
    try {
      const pack = await invoke<HandoffPack>("get_handoff", { id });
      await navigator.clipboard.writeText(pack.text);
      flashToast(pack.inject_ok ? "Handoff copied" : `Handoff copied (${pack.reason || "no inject"})`);
    } catch (e) {
      flashToast(String(e), 3200);
    }
  }, [flashToast]);

  const continueHandoff = useCallback(
    async (id: string) => {
      try {
        const newId = await invoke<string>("handoff_to_acp", { id });
        setSelected(newId);
        flashToast(`New Orbit ACP ${newId}`);
        void refresh();
      } catch (e) {
        flashToast(String(e), 4200, "error");
      }
    },
    [refresh],
  );

  useEffect(() => {
    if (!starMode || !selected) {
      setGitPulse(null);
      return;
    }
    invoke<GitPulse>("star_git_status", { id: selected })
      .then(setGitPulse)
      .catch(() => setGitPulse(null));
  }, [starMode, selected]);

  useEffect(() => {
    if (!selected) {
      setDetail(null);
      return;
    }
    invoke<SessionDetail>("get_session_detail", { id: selected })
      .then(setDetail)
      .catch((e) => setError(String(e)));
  }, [selected, snap?.generated_at]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const inField = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((v) => !v);
        setQuery("");
        setCursor(0);
        return;
      }
      if (e.key === "Escape") {
        if (helpOpen) {
          setHelpOpen(false);
          return;
        }
        if (relayOpen) {
          setRelayOpen(false);
          return;
        }
        if (palette) {
          setPalette(false);
          return;
        }
        if (starMode && !bootIsStar()) {
          exitStar("galaxy");
          return;
        }
        return;
      }
      if (inField) return;
      if (e.key === "r") void refresh(true);
      if (e.key === "C" && e.shiftKey) {
        e.preventDefault();
        void toggleCook();
      }
      if (e.key === "j" || e.key === "k") {
        const list = visibleSessions(snap, view);
        if (!list.length) return;
        const idx = Math.max(0, list.findIndex((s) => s.id === selected));
        const next = e.key === "j" ? Math.min(list.length - 1, idx + 1) : Math.max(0, idx - 1);
        setSelected(list[next].id);
      }
      if (e.key === "Enter" && selected) {
        e.preventDefault();
        if (view === "clearance") {
          const row = (snap?.attention || []).find((a) => a.session_id === selected);
          const verb = row ? clearanceVerb(row) : null;
          if (verb) {
            void runClearanceVerb(selected, verb.dest);
            return;
          }
        }
        setStarMode(true);
      }
      if (e.key === "o" && selected) void act("open_session_cwd", selected, "Opened folder");
      if (e.key === "h" && selected) void copyHandoff(selected);
      if (e.key === "y" && selected) {
        setStarMode(true);
        setRelayOpen(true);
      }
      if (e.key === "b" && selected) void actNamed("focus_session", { id: selected }, "Brought to front");
      if (e.key.toLowerCase() === "p" && selected) {
        if (e.shiftKey) {
          void actNamed("open_star_window", { id: selected }, "Star on other monitor");
        } else {
          setStarMode(true);
        }
      }
      if (e.key === "g") exitStar("galaxy");
      if (e.key === "c") exitStar("clearance");
      if (e.key === "f") exitStar("feed");
      if (e.key === "w") exitStar("web");
      if (e.key === "?") {
        e.preventDefault();
        setHelpOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [palette, refresh, selected, snap, view, copyHandoff, starMode, exitStar, relayOpen, helpOpen, cookConfirm]);

  const commands = useMemo(() => commandList(snap, selected), [snap, selected]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const cmds = q
      ? commands.filter(
          (c) =>
            c.label.toLowerCase().includes(q) ||
            c.hint.toLowerCase().includes(q) ||
            c.group.toLowerCase().includes(q),
        )
      : commands;
    const searchRows: Cmd[] = hits.map((h) => ({
      id: `sel:${h.id}`,
      label: h.title || h.id,
      hint: h.live ? `live · ${h.snippet}` : h.snippet || h.cwd,
      group: "Find",
    }));
    return q.length >= 2 ? [...searchRows, ...cmds] : cmds;
  }, [commands, query, hits]);

  async function act(cmd: string, id?: string, ok?: string) {
    return actNamed(cmd, id ? { id } : {}, ok);
  }

  async function actNamed(cmd: string, payload: Record<string, string>, ok?: string) {
    try {
      const msg = await invoke<string | void>(cmd, payload);
      flashToast(ok || (typeof msg === "string" ? msg : "Done"));
      void refresh();
    } catch (e) {
      flashToast(String(e), 4200, "error");
    }
  }

  const attachedInfo = acp?.attached.find((s) => s.id === selected);
  const attached = Boolean(attachedInfo);
  const busy = Boolean(attachedInfo?.busy);
  const acpEvents = (acp?.events || []).filter((e) => e.session_id === selected);

  async function sendFollowup() {
    if (!selected || !followDraft.trim()) return;
    if (!followConfirm) {
      setFollowConfirm(true);
      return;
    }
    const text = followDraft.trim();
    try {
      const raw = await invoke<string>("cursor_followup", { id: selected, text });
      let msg = "Follow-up sent";
      try {
        const parsed = JSON.parse(raw) as { run_id?: string; status?: string; error?: string; hint?: string };
        if (parsed.error === "agent_busy") {
          flashToast("Agent busy. Open in browser instead.", 3600);
          setFollowConfirm(false);
          return;
        }
        if (parsed.error) {
          flashToast(parsed.error, 3600);
          setFollowConfirm(false);
          return;
        }
        msg = parsed.run_id ? `Follow-up ${parsed.run_id}${parsed.status ? ` ${parsed.status}` : ""}` : msg;
      } catch {
        if (raw.trim()) msg = raw.trim().slice(0, 160);
      }
      setFollowDraft("");
      setFollowConfirm(false);
      flashToast(msg, 4200);
    } catch (e) {
      const textErr = String(e);
      flashToast(textErr.includes("agent_busy") ? "Agent busy. Open in browser instead." : textErr, 3600);
      setFollowConfirm(false);
    }
  }

  async function sendPrompt() {
    if (!selected || !draft.trim()) return;
    const text = draft;
    setDraft("");
    await actNamed("acp_prompt", { id: selected, text }, "Turn started");
  }

  async function newOrbitSession() {
    let cwd = "";
    if (selected) {
      try {
        cwd = await invoke<string>("session_clone_path", { id: selected });
      } catch {
        cwd = "";
      }
    }
    if (!looksLikePath(cwd) && looksLikePath(detail?.session.cwd)) {
      cwd = detail?.session.cwd || "";
    }
    if (!looksLikePath(cwd)) {
      const path = (snap?.projects || []).find((p) => (p.paths || []).some((x) => looksLikePath(x)))?.paths?.[0] || "";
      cwd = path;
    }
    if (!looksLikePath(cwd)) {
      flashToast("No clone path for new session", 3200, "error");
      return;
    }
    try {
      const id = await invoke<string>("acp_new_session", { cwd });
      setSelected(id);
      flashToast(`New Orbit session ${id}`);
      void refresh();
    } catch (e) {
      flashToast(String(e), 4200, "error");
    }
  }

  async function runRelay(dest: string) {
    if (!selected) return;
    setRelayOpen(false);
    if (dest === "clipboard") return void copyHandoff(selected);
    if (dest === "acp") return void continueHandoff(selected);
    if (dest === "followup") {
      if (!followDraft.trim()) {
        setFollowDraft("Continue this work from Orbit Relay.\n");
      }
      setFollowConfirm(true);
      flashToast("Confirm follow-up to send");
      return;
    }
    if (dest === "open_pr") {
      return void actNamed("open_session_pr", { id: selected }, "Opened pull request");
    }
    if (dest === "open_url") {
      return void actNamed("open_session_url", { id: selected }, "Opened in browser");
    }
    if (dest === "focus") {
      try {
        const text = await invoke<string>("relay_focus_copy", { id: selected });
        await navigator.clipboard.writeText(text);
        flashToast("Pack copied. Paste in that pager. Orbit will not inject.", 4200);
      } catch (e) {
        flashToast(String(e), 3200);
      }
      return;
    }
    if (dest === "announce") {
      const title = detail?.session.title || selected;
      try {
        const msg = await invoke<string>("desk_announce", { note: `relay ${title}`.slice(0, 180) });
        flashToast(typeof msg === "string" ? msg : "Announced");
        void refresh();
      } catch (e) {
        flashToast(String(e), 3200);
      }
    }
  }

  async function runClearanceVerb(sessionId: string, dest: string) {
    if (dest === "focus") {
      return void actNamed("focus_session", { id: sessionId }, "Brought to front");
    }
    if (dest === "open_pr") {
      return void actNamed("open_session_pr", { id: sessionId }, "Opened pull request");
    }
    if (dest === "open_url") {
      return void actNamed("open_session_url", { id: sessionId }, "Opened in browser");
    }
    if (dest === "open_cwd") {
      return void act("open_session_cwd", sessionId, "Opened folder");
    }
  }

  async function toggleCook() {
    const armed = Boolean(snap?.surfaces.cook_armed);
    if (armed) {
      setCookConfirm(false);
      try {
        const msg = await invoke<string>("cook_disarm");
        flashToast(typeof msg === "string" ? msg : "COOK stopped");
        void refresh(true);
      } catch (e) {
        flashToast(String(e), 4200, "error");
      }
      return;
    }
    if (!cookConfirm) {
      setCookConfirm(true);
      flashToast("Confirm COOK: new Grok consoles on free wells. Desk-occupied and live pagers skipped. STOP to halt.");
      return;
    }
    setCookConfirm(false);
    try {
      const msg = await invoke<string>("cook_arm");
      flashToast(typeof msg === "string" ? msg : "COOK armed", 4200);
      void refresh(true);
    } catch (e) {
      flashToast(String(e), 4200, "error");
    }
  }

  async function runCommand(id: string) {
    setPalette(false);
    if (id === "refresh") return void refresh(true);
    if (id === "refresh-cursor-api") return void refreshCursorApi();
    if (id === "star" && selected) {
      setStarMode(true);
      return;
    }
    if (id === "star-monitor" && selected) {
      return void actNamed("open_star_window", { id: selected }, "Star on other monitor");
    }
    if (id === "clearance") return exitStar("clearance");
    if (id === "galaxy") return exitStar("galaxy");
    if (id === "feed") return exitStar("feed");
    if (id === "web") return exitStar("web");
    if (id === "copy-handoff" && selected) return void copyHandoff(selected);
    if (id === "continue-handoff" && selected) return void continueHandoff(selected);
    if (id === "relay" && selected) {
      setStarMode(true);
      setRelayOpen(true);
      return;
    }
    if (id === "new-acp") return void newOrbitSession();
    if (id === "cook") return void toggleCook();
    if (id.startsWith("sel:")) return setSelected(id.slice(4));
    if (id.startsWith("act:") && selected) {
      const [, cmd, label] = id.split(":");
      return act(cmd, selected, label);
    }
  }

  const sessions = visibleSessions(snap, view);
  const attnCount = (snap?.attention.length || 0) + (acp?.permissions.length || 0);
  const cursorN = (snap?.sessions || []).filter((s) => s.id.startsWith("web:cursor:")).length;
  const cursorClock = clockFromIso(snap?.surfaces.cursor_web_probed_at);

  const hop = nextHop(snap, acp);
  const clauses = situationClauses(error || snap?.situation || "");
  const leadClause = clauses[0] || "";
  const extraClauses = leadClause.toLowerCase().startsWith("next") ? clauses.slice(1, 4) : clauses.slice(0, 3);
  const showHop = hop && !leadClause.toLowerCase().startsWith("next");

  useEffect(() => {
    const detail = snap?.surfaces.cook_detail || "";
    if (!snap?.surfaces.cook_armed || !detail) return;
    if (seenCookDetail.current === null) {
      seenCookDetail.current = detail;
      return;
    }
    if (detail !== seenCookDetail.current) {
      seenCookDetail.current = detail;
      flashToast(`COOK ${detail}`, 3600);
    }
  }, [flashToast, snap?.surfaces.cook_armed, snap?.surfaces.cook_detail]);

  return (
    <div className={`app ${starMode ? "star-mode" : ""} ${snap?.surfaces.cook_armed ? "cook-on" : ""}`}>
      <a className="skip" href="#orbit-main">
        Skip to fleet
      </a>
      {!starMode && (
      <aside className="rail" aria-label="Orbit views">
        <div className="mark">ORBIT</div>
        <nav className="rail-nav">
          <button
            className={view === "galaxy" ? "active" : ""}
            aria-current={view === "galaxy" ? "page" : undefined}
            title="Galaxy (g)"
            onClick={() => setView("galaxy")}
          >
            G
          </button>
          <button
            className={view === "clearance" ? "active" : ""}
            aria-current={view === "clearance" ? "page" : undefined}
            title="Clearance (c)"
            onClick={() => setView("clearance")}
          >
            C
            {attnCount > 0 ? <span className="rail-count">{attnCount}</span> : null}
          </button>
          <button
            className={view === "feed" ? "active" : ""}
            aria-current={view === "feed" ? "page" : undefined}
            title="Feed (f)"
            onClick={() => setView("feed")}
          >
            F
          </button>
          <button
            className={view === "web" ? "active" : ""}
            aria-current={view === "web" ? "page" : undefined}
            title="Web (w)"
            onClick={() => setView("web")}
          >
            W
          </button>
        </nav>
      </aside>
      )}

      <header className="sit">
        <div className="sit-lead">
          <p className="sit-kicker">{snap?.surfaces.cook_armed ? "Cooking" : "Situation"}</p>
          {leadClause ? <p className="sit-clause next">{leadClause}</p> : <p>Collecting fleet...</p>}
          {showHop ? <p className="sit-next">{hop}</p> : null}
          {extraClauses.length > 0 && (
            <div className="sit-clauses">
              {extraClauses.map((c) => (
                <p key={c} className="sit-clause">
                  {c}
                </p>
              ))}
            </div>
          )}
          {cookConfirm && !snap?.surfaces.cook_armed && (
            <p className="warn-line">Confirm COOK: new Grok consoles on free wells. Occupied and live pagers skip. STOP to halt.</p>
          )}
          {starMode && !bootIsStar() && (
            <button className="back-galaxy" onClick={() => exitStar("galaxy")}>
              Galaxy
            </button>
          )}
        </div>
        <div className="sit-ops">
          <div className="cook-cluster">
            <button
              className={`cook-btn ${snap?.surfaces.cook_armed ? "armed" : ""} ${cookConfirm ? "confirm" : ""}`}
              title={snap?.surfaces.cook_detail || "Deploy staff to named wells until STOP"}
              aria-pressed={Boolean(snap?.surfaces.cook_armed)}
              onClick={() => void toggleCook()}
            >
              {snap?.surfaces.cook_armed ? "STOP COOK" : cookConfirm ? "Confirm COOK" : "COOK"}
            </button>
            {(cookBoard?.last_detail || cookBoard?.last_summary || snap?.surfaces.cook_summary || snap?.surfaces.cook_detail) ? (
              <span className="cook-meta" title={cookBoard?.last_summary || snap?.surfaces.cook_summary || ""}>
                {cookBoard?.last_detail || cookBoard?.last_summary || snap?.surfaces.cook_summary || snap?.surfaces.cook_detail}
              </span>
            ) : null}
          </div>
          <div className="chips">
          {quietAdapters(snap).map((a) => (
            <span key={a.name} className={`chip ${a.status}`} title={a.detail}>
              <span className="dot" />
              {a.name}
            </span>
          ))}
          <span className={`chip ${snap?.surfaces.grok_bot ? "ok" : "offline"}`}>
            <span className="dot" />
            bot {snap?.surfaces.steward_pack || ""}{" "}
            {snap?.surfaces.local_exec_alive ? "exec" : "no-exec"}
          </span>
          <span
            className={`chip ${snap?.surfaces.cursor ? "ok" : "idle"}`}
            title={
              snap?.surfaces.cursor
                ? "Cursor.exe is running"
                : "Cursor desktop is not installed. cursor.com is the live list."
            }
          >
            <span className="dot" />
            desktop {snap?.surfaces.cursor ? "on" : "off"}
          </span>
          <span className={`chip ${webChip(snap?.surfaces.grok_web)}`} title={snap?.surfaces.grok_web_detail || ""}>
            <span className="dot" />
            grok.com {snap?.surfaces.grok_web || "?"}
          </span>
          <span
            className={`chip ${webChip(snap?.surfaces.cursor_web)}`}
            title={snap?.surfaces.cursor_web_detail || ""}
          >
            <span className="dot" />
            cursor.com {snap?.surfaces.cursor_web || "?"}
            {cursorN ? ` ${cursorN}` : ""}
            {cursorClock ? ` @ ${cursorClock}` : ""}
          </span>
          <span className={`chip ${acp?.initialized ? "ok" : acp?.last_error ? "degraded" : ""}`}>
            <span className="dot" />
            acp {acp?.initialized ? `${acp.attached.length} att` : "idle"} {acp?.grok_permission_mode || ""}
          </span>
          <span className={`chip ${snap?.surfaces.cook_armed ? "ok" : "idle"}`} title={snap?.surfaces.cook_detail || ""}>
            <span className="dot" />
            cook {snap?.surfaces.cook_armed ? "on" : "off"}
          </span>
          <span className="chip" title={snap?.snap_profile || ""}>
            {snap ? `${snap.elapsed_ms} ms` : "..."}
          </span>
          </div>
        </div>
      </header>

      <main className="main" id="orbit-main">
        <section className="galaxy">
          <div className="toolbar">
            <h2>
              {view === "clearance"
                ? "Clearance"
                : view === "feed"
                  ? "Feed"
                  : view === "web"
                    ? "Web"
                    : "Galaxy"}
            </h2>
            <div>
              <button className="ghost" onClick={() => setPalette(true)}>
                Ctrl+K
              </button>
              <button className="ghost" onClick={() => void refresh(true)}>
                Refresh
              </button>
            </div>
          </div>
          {snap && view === "galaxy" && (
            <div className="cook-board" aria-live="polite">
              <div className="cook-board-top">
                <strong>{(cookBoard?.armed ?? snap.surfaces.cook_armed) ? "COOK is on" : "COOK is off"}</strong>
                <span>
                  {(cookBoard?.staff_now || snap.surfaces.cook_staff || 0) > 0
                    ? `${cookBoard?.staff_now || snap.surfaces.cook_staff} windows open`
                    : "no cook windows open"}
                </span>
              </div>
              <p>
                {cookBoard?.last_summary
                  || snap.surfaces.cook_summary
                  || "COOK sends one-shot Grok turns. The window prints the work, then closes. That means the turn ended, not that it failed."}
              </p>
              {nextWaveLine(cookBoard) ? (
                <p className="cook-line cook-next">Next wave: {nextWaveLine(cookBoard)}</p>
              ) : null}
              {shipLines(cookBoard).length > 0 ? (
                <ul className="cook-ships">
                  {shipLines(cookBoard).map((row) => (
                    <li key={row.id}>
                      <strong>{row.name}</strong> {row.shipped}
                      {row.next ? <span className="cook-leftover"> next: {row.next}</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
              {(cookBoard?.last_board || []).length > 0 ? (
                <ul className="cook-roster">
                  {(cookBoard?.last_board || []).map((row) => (
                    <li key={row.id} className={`cook-row is-${row.state || "idle"}`}>
                      <span className="cook-name">{row.name || row.id}</span>
                      <span className="cook-state">{row.state || "idle"}</span>
                      <span className="cook-note">{row.note || row.shipped || ""}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <>
                  {(cookBoard?.last_sent || []).length > 0 && (
                    <p className="cook-line">Sent: {(cookBoard?.last_sent || []).join(", ")}</p>
                  )}
                  {(cookBoard?.last_waiting || []).length > 0 && (
                    <p className="cook-line">Waiting: {(cookBoard?.last_waiting || []).join(", ")}</p>
                  )}
                </>
              )}
            </div>
          )}
          {!snap && (
            <div className="empty-state" aria-busy="true">
              <h3>Collecting fleet</h3>
              <p>Reading live pagers, desk, and cached Cursor rows.</p>
              <div className="skel" />
            </div>
          )}
          {snap && view === "galaxy" &&
            snap.projects.map((p) => {
              const pack = projectCards(sessions, p, Boolean(openFinished[p.id]));
              return (
              <div key={p.id} className={`project health-${p.health || "ok"}`}>
                <div className="project-head">
                  <span>
                    {p.name}
                    {p.remotes && p.remotes[0] ? <span className="proj-remote"> {p.remotes[0]}</span> : null}
                  </span>
                  <span>
                    {p.running_count ? `${p.running_count} running / ` : ""}
                    {p.live_count} live / {p.session_ids.length}
                    {wellFlags(snap, p) ? ` ${wellFlags(snap, p)}` : ""}
                  </span>
                </div>
                <div className="cards">
                  {pack.shown.map((s) => (
                      <SessionCard
                        key={s.id}
                        session={s}
                        selected={selected === s.id}
                        prMates={pack.mates[s.id] || 0}
                        onSelect={() => setSelected(s.id)}
                      />
                    ))}
                  {pack.extra > 0 && (
                    <button
                      className="card more-finished"
                      onClick={() => setOpenFinished((prev) => ({ ...prev, [p.id]: !prev[p.id] }))}
                    >
                      {openFinished[p.id]
                        ? "Show less"
                        : p.id === "loose" || p.id === "grok.com"
                          ? `${pack.extra} more`
                          : `${pack.extra} more finished`}
                    </button>
                  )}
                </div>
              </div>
              );
            })}
          {snap && view === "web" && (
            <div className="cards">
              <div className="card">
                <div className="card-top">
                  <span className="card-title">Grok web</span>
                  <span className="badge">
                    {sessions.filter((s) => s.id.startsWith("web:grok:")).length || snap.surfaces.grok_web || "unknown"}
                  </span>
                </div>
                <div className="meta">
                  Galaxy lists grok.com chats from the last Brave sync. Refresh bounces Brave once.
                  Cookie values are not stored. Nothing is kept always-on-top.
                </div>
                <div className="perm">
                  <button
                    className="allow"
                    onClick={() => void actNamed("web_open_daily", { surface: "grok_web" }, "Opened grok.com in daily Brave")}
                  >
                    Open grok.com in daily Brave
                  </button>
                  <button
                    onClick={() =>
                      void actNamed(
                        "web_sync_brave",
                        {},
                        "Brave grok.com + cursor.com sync started (Brave will bounce)",
                      )
                    }
                  >
                    Refresh Brave lists
                  </button>
                </div>
              </div>
              <div className="card">
                <div className="card-top">
                  <span className="card-title">Cursor web</span>
                  <span className="badge">
                    {sessions.filter((s) => s.id.startsWith("web:cursor:")).length || snap.surfaces.cursor_web || "unknown"}
                  </span>
                </div>
                <div className="meta">
                  Cloud Agents from the official API when a Dashboard key is installed.
                  Brave scrape is fallback only. Cookies are never sent to api.cursor.com.
                </div>
                <div className="perm">
                  <button
                    className="allow"
                    onClick={() => void actNamed("web_open_daily", { surface: "cursor_web" }, "Opened cursor.com in daily Brave")}
                  >
                    Open cursor.com/agents in daily Brave
                  </button>
                  <button
                    className="allow"
                    disabled={cursorRefreshing}
                    onClick={() => void refreshCursorApi()}
                  >
                    {cursorRefreshing ? "Refreshing..." : "Refresh via API"}
                  </button>
                  <button
                    onClick={() =>
                      void actNamed(
                        "web_sync_brave",
                        {},
                        "Brave grok.com + cursor.com sync started (Brave will bounce)",
                      )
                    }
                  >
                    Refresh Brave lists
                  </button>
                  <button
                    onClick={() =>
                      void invoke("set_cursor_pulse", { on: snap.surfaces.cursor_pulse === false }).then((msg) => {
                        flashToast(typeof msg === "string" ? msg : "Pulse updated");
                        void refresh();
                      })
                    }
                  >
                    {snap.surfaces.cursor_pulse === false ? "Enable 60s pulse" : "Disable 60s pulse"}
                  </button>
                </div>
              </div>
              {sessions
                .filter((s) => s.id.startsWith("web:"))
                .map((s) => (
                  <SessionCard
                    key={s.id}
                    session={s}
                    selected={selected === s.id}
                    onSelect={() => setSelected(s.id)}
                  />
                ))}
              {sessions.filter((s) => s.id.startsWith("web:")).length === 0 && (
                <div className="empty">
                  No cached grok.com or cursor.com rows. Use Refresh Brave lists (bounces Brave once).
                </div>
              )}
            </div>
          )}
          {snap && view === "feed" && (
            <div className="cards">
              {(snap.activity || []).length === 0 && (
                <div className="empty-state">
                  <h3>Feed is quiet</h3>
                  <p>Tails appear when live pagers or recent disk sessions write updates.</p>
                  <button className="primary" onClick={() => void refresh(true)}>
                    Refresh
                  </button>
                </div>
              )}
              {(snap.activity || []).map((a) => (
                <button key={a.id} className={`card ${a.live ? "live" : ""}`} onClick={() => setSelected(a.session_id)}>
                  <div className="card-top">
                    <span className="card-title">{a.title}</span>
                    <span className="badge">{a.kind}</span>
                  </div>
                  <div className="meta">{a.live ? "live" : "disk"}</div>
                  <div className="event t">{a.text}</div>
                </button>
              ))}
            </div>
          )}
          {snap && view === "clearance" && (
            <div className="cards">
              {(acp?.permissions.length || 0) === 0 && snap.attention.length === 0 && (
                <div className="empty-state">
                  <h3>Clearance empty</h3>
                  <p>No stale pagers, running Cursor agents, open PRs, or desk claims need you.</p>
                  <button className="ghost" onClick={() => setView("galaxy")}>
                    Back to Galaxy
                  </button>
                </div>
              )}
              {(acp?.permissions || []).map((p) => (
                <div key={p.request_id} className="card live">
                  <div className="card-top">
                    <span className="card-title">{p.title}</span>
                    <span className="badge">{p.kind}</span>
                  </div>
                  <div className="meta">{p.session_id}</div>
                  <div className="perm">
                    {p.options.map((o) => (
                      <button
                        key={o.option_id}
                        className={o.kind.startsWith("allow") ? "allow" : "reject"}
                        onClick={() =>
                          void actNamed("acp_respond", { requestId: p.request_id, optionId: o.option_id }, o.name)
                        }
                      >
                        {o.name}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              {snap.attention.map((a) => {
                const verb = clearanceVerb(a);
                return (
                <div
                  key={a.id}
                  className={`card ${a.session_id && a.session_id === selected ? "selected" : ""}`}
                  onClick={() => a.session_id && setSelected(a.session_id)}
                >
                  <div className="card-top">
                    <span className="card-title">{a.title}</span>
                    <span className="badge">{a.kind}</span>
                  </div>
                  <div className="meta">{a.severity}</div>
                  {verb && a.session_id ? (
                    <div className="perm">
                      <button
                        className="allow"
                        onClick={(e) => {
                          e.stopPropagation();
                          void runClearanceVerb(a.session_id as string, verb.dest);
                        }}
                      >
                        {verb.label}
                      </button>
                    </div>
                  ) : null}
                </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="detail">
          {!detail && (
            <div className="empty-state">
              <h3>No star selected</h3>
              <p>Pick a card, or press j / k. p opens Star. y opens Relay.</p>
            </div>
          )}
          {detail && (
            <>
              <h2>{detail.session.title}</h2>
              <div className="meta">
                <span className="badge">
                  {detail.session.live ? "live" : detail.session.agent_name || detail.session.state}
                </span>
                <span>{detail.session.source}</span>
              </div>
              <div className="actions">
                {detail.session.id.startsWith("web:") ? (
                  <button
                    className="primary"
                    onClick={() => void actNamed("open_session_url", { id: detail.session.id }, "Opened in browser")}
                  >
                    Open in browser
                  </button>
                ) : detail.session.live ? (
                  <button
                    className="primary"
                    onClick={() => void actNamed("focus_session", { id: detail.session.id }, "Brought to front")}
                  >
                    Bring to front
                  </button>
                ) : (
                  <button className="primary" onClick={() => void act("resume_session", detail.session.id, "Resume launched")}>
                    Resume in Grok
                  </button>
                )}
                {detail.session.pr_url ? (
                  <button
                    className="allow"
                    onClick={() => void actNamed("open_session_pr", { id: detail.session.id }, "Opened pull request")}
                  >
                    Open PR {prLabel(detail.session.pr_url)}
                  </button>
                ) : null}
                <button onClick={() => void copyHandoff(detail.session.id)}>Copy handoff</button>
                {!detail.session.live && (
                  <button onClick={() => void continueHandoff(detail.session.id)}>Continue in Orbit ACP</button>
                )}
                {!starMode && (
                  <button className="primary" onClick={() => setStarMode(true)}>
                    Star
                  </button>
                )}
                {starMode && !bootIsStar() && (
                  <button className="primary" onClick={() => exitStar("galaxy")}>
                    Galaxy
                  </button>
                )}
                <button onClick={() => setRelayOpen((v) => !v)}>Relay</button>
                <button
                  onClick={() =>
                    void actNamed("open_star_window", { id: detail.session.id }, "Star on other monitor")
                  }
                >
                  Other monitor
                </button>
                {!detail.session.live && !detail.session.id.startsWith("web:") && (
                  <button
                    onClick={() =>
                      void actNamed(
                        "acp_attach",
                        { id: detail.session.id, cwd: detail.session.cwd },
                        "Attached in Orbit",
                      )
                    }
                  >
                    Attach in Orbit
                  </button>
                )}
                <button onClick={() => void act("open_session_cwd", detail.session.id, "Opened cwd")}>
                  Open folder
                </button>
                <button onClick={() => void act("reveal_session_dir", detail.session.id, "Opened session dir")}>
                  Session files
                </button>
                <button
                  onClick={() => {
                    void navigator.clipboard.writeText(detail.session.id);
                    flashToast("Copied id", 1800);
                  }}
                >
                  Copy id
                </button>
              </div>
              {detail.session.source === "cursor_web" && (
                <div className="composer">
                  {detail.session.agent_name === "running" ? (
                    <p className="warn-line">Agent is running. Follow-up refused. Open in browser instead.</p>
                  ) : (
                    <>
                      <textarea
                        value={followDraft}
                        placeholder="Follow-up this Cloud Agent (confirm once)"
                        onChange={(e) => {
                          setFollowDraft(e.target.value);
                          setFollowConfirm(false);
                        }}
                        onKeyDown={(e) => {
                          if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                            e.preventDefault();
                            void sendFollowup();
                          }
                        }}
                      />
                      <div>
                        <button
                          className="primary"
                          disabled={!followDraft.trim()}
                          onClick={() => void sendFollowup()}
                        >
                          {followConfirm ? "Confirm follow-up" : "Send follow-up"}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
              {starMode && gitPulse && (
                <>
                  <h2>Git</h2>
                  <div className="meta">
                    <span>{gitPulse.branch || "branch?"}</span>
                    <span>{gitPulse.dirty === 0 ? "clean" : `${gitPulse.dirty} dirty`}</span>
                  </div>
                  {gitPulse.lines.length === 0 ? (
                    <div className="empty-state">
                      <h3>Working tree clean</h3>
                      <p>{gitPulse.cwd}</p>
                    </div>
                  ) : (
                    gitPulse.lines.map((line) => (
                      <div key={line} className="event">
                        <div className="t">{line}</div>
                      </div>
                    ))
                  )}
                </>
              )}
              <div className="kv">
                <span>cwd</span>
                <b>{detail.session.cwd || "-"}</b>
                <span>model</span>
                <b>{detail.session.model || "-"}</b>
                <span>agent</span>
                <b>{detail.session.agent_name || "-"}</b>
                <span>pid</span>
                <b>{detail.session.pid ?? "-"}</b>
                <span>updated</span>
                <b>{detail.session.updated_at || "-"}</b>
                {detail.session.url && (
                  <>
                    <span>url</span>
                    <b>{detail.session.url}</b>
                  </>
                )}
                {detail.session.remote && (
                  <>
                    <span>remote</span>
                    <b>{detail.session.remote}</b>
                  </>
                )}
                {detail.session.branch && (
                  <>
                    <span>branch</span>
                    <b>{detail.session.branch}</b>
                  </>
                )}
                {detail.session.pr_url && (
                  <>
                    <span>pr</span>
                    <b>
                      {detail.session.pr_state && detail.session.pr_state !== "unknown"
                        ? `${detail.session.pr_state} `
                        : ""}
                      {detail.session.pr_url}
                    </b>
                  </>
                )}
                {typeof detail.session.pr_file_count === "number" && (
                  <>
                    <span>files</span>
                    <b>{detail.session.pr_file_count}</b>
                  </>
                )}
              </div>
              {(detail.session.pr_files || []).length > 0 && (
                <>
                  <h2>PR files</h2>
                  {(detail.session.pr_files || []).map((path) => (
                    <div key={path} className="event">
                      <div className="t">{path}</div>
                    </div>
                  ))}
                </>
              )}
              {relayOpen && (
                <div className="composer">
                  <p className="warn-line">Relay this brief. Confirm-once. Orbit will not inject into a live TUI.</p>
                  <div className="perm">
                    <button className="allow" onClick={() => void runRelay("clipboard")}>
                      Clipboard
                    </button>
                    <button onClick={() => void runRelay("acp")}>New Orbit ACP</button>
                    {wellLiveSibling(snap, detail.session) ? (
                      <button className="allow" onClick={() => void runRelay("focus")}>
                        Focus live pager
                      </button>
                    ) : null}
                    {detail.session.source === "cursor_web" && detail.session.agent_name !== "running" ? (
                      <button onClick={() => void runRelay("followup")}>Cursor follow-up</button>
                    ) : null}
                    {detail.session.pr_url ? (
                      <button onClick={() => void runRelay("open_pr")}>Open PR</button>
                    ) : null}
                    {detail.session.url ? (
                      <button onClick={() => void runRelay("open_url")}>Open chat</button>
                    ) : null}
                    {isNamedWell(detail.session.project_id) ? (
                      <button onClick={() => void runRelay("announce")}>Desk announce</button>
                    ) : null}
                  </div>
                </div>
              )}
              {wellMembers(snap, detail.session).length > 0 && (
                <>
                  <h2>On this well</h2>
                  {wellDesk(snap, detail.session.project_id) ? (
                    <div className="meta">{wellDesk(snap, detail.session.project_id)?.title}</div>
                  ) : null}
                  {wellMembers(snap, detail.session).map((s) => (
                    <button
                      key={`well-${s.id}`}
                      className="card"
                      onClick={() => setSelected(s.id)}
                    >
                      <div className="card-top">
                        <span className="card-title">{s.title}</span>
                        <span className="badge">{memberKindLabel(s)}</span>
                      </div>
                    </button>
                  ))}
                </>
              )}
              {prSiblings(snap, detail.session).length > 0 && (
                <>
                  <h2>Also on this PR</h2>
                  {prSiblings(snap, detail.session).map((s) => (
                    <button
                      key={s.id}
                      className="card"
                      onClick={() => setSelected(s.id)}
                    >
                      <div className="card-top">
                        <span className="card-title">{s.title}</span>
                        <span className="badge">{s.agent_name || s.state}</span>
                      </div>
                    </button>
                  ))}
                </>
              )}
              {detail.session.live && (
                <p className="warn-line">
                  Live TUI pager. Orbit will not inject. Bring the native window to the front, or attach after it goes idle.
                </p>
              )}
              {attached && (
                <div className="composer">
                  <textarea
                    value={draft}
                    placeholder={busy ? "Turn in flight..." : "Prompt this session from Orbit"}
                    disabled={busy}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
                        e.preventDefault();
                        void sendPrompt();
                      }
                    }}
                  />
                  <div>
                    <button className="primary" disabled={busy || !draft.trim()} onClick={() => void sendPrompt()}>
                      Send
                    </button>
                    <button onClick={() => void actNamed("acp_cancel", { id: detail.session.id }, "Cancelled")}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
              {acpEvents.length > 0 && (
                <>
                  <h2>Orbit ACP</h2>
                  {acpEvents.map((ev, i) => (
                    <div key={`a${i}`} className="event">
                      <div className="k">{ev.kind}</div>
                      <div className="t">{ev.text}</div>
                    </div>
                  ))}
                </>
              )}
              {detail.plan_excerpt && (
                <>
                  <h2>Plan</h2>
                  <pre className="event t">{detail.plan_excerpt}</pre>
                </>
              )}
              <h2>Updates</h2>
              {detail.events.length === 0 && <div className="empty">No tailed updates.</div>}
              {detail.events.map((ev, i) => (
                <div key={i} className="event">
                  <div className="k">{ev.kind}</div>
                  <div className="t">{ev.text}</div>
                </div>
              ))}
            </>
          )}
        </section>
      </main>

      {palette && (
        <div className="palette-back" onClick={() => setPalette(false)}>
          <div
            className="palette"
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              ref={paletteRef}
              autoFocus
              placeholder="Search sessions or run a command"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setCursor(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setCursor((c) => Math.min(filtered.length - 1, c + 1));
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setCursor((c) => Math.max(0, c - 1));
                }
                if (e.key === "Home") {
                  e.preventDefault();
                  setCursor(0);
                }
                if (e.key === "End") {
                  e.preventDefault();
                  setCursor(Math.max(0, filtered.length - 1));
                }
                if (e.key === "Enter" && filtered[cursor]) {
                  void runCommand(filtered[cursor].id);
                }
              }}
            />
            <div className="palette-list" role="listbox" aria-label="Results">
              {filtered.map((c, i) => {
                const prev = i > 0 ? filtered[i - 1] : null;
                const head = !prev || prev.group !== c.group;
                return (
                  <div key={c.id}>
                    {head ? <div className="palette-group">{c.group}</div> : null}
                    <button
                      role="option"
                      aria-selected={i === cursor}
                      className={i === cursor ? "active" : ""}
                      onMouseEnter={() => setCursor(i)}
                      onClick={() => void runCommand(c.id)}
                    >
                      <span>
                        {c.label}
                        <div className="hint">{c.hint}</div>
                      </span>
                      {c.kbd ? <span className="kbd">{c.kbd}</span> : null}
                    </button>
                  </div>
                );
              })}
              {filtered.length === 0 && (
                <div className="empty-state">
                  <h3>No matches for {query}</h3>
                  <p>Try a session title, well name, or command like relay.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {helpOpen && (
        <div className="help-back" onClick={() => setHelpOpen(false)}>
          <div className="help" role="dialog" aria-modal="true" aria-label="Orbit keys" onClick={(e) => e.stopPropagation()}>
            <h2>Orbit keys</h2>
            <dl>
              <dt>g c f w</dt>
              <dd>Galaxy, Clearance, Feed, Web</dd>
              <dt>j / k</dt>
              <dd>Move selection</dd>
              <dt>Enter</dt>
              <dd>Star, or run Clearance verb</dd>
              <dt>p / y</dt>
              <dd>Star / Relay</dd>
              <dt>h / b / o</dt>
              <dd>Handoff, bring to front, open folder</dd>
              <dt>r</dt>
              <dd>Full refresh</dd>
              <dt>Shift+C</dt>
              <dd>COOK / STOP COOK</dd>
              <dt>Ctrl+K</dt>
              <dd>Command palette</dd>
              <dt>Esc</dt>
              <dd>Close overlay or leave Star</dd>
            </dl>
          </div>
        </div>
      )}

      {toast && (
        <div className={`toast ${toastKind === "error" ? "error" : ""}`} role="status" aria-live={toastKind === "error" ? "assertive" : "polite"}>
          {toast}
          {toastKind === "error" ? (
            <button className="ghost" onClick={() => setToast(null)}>
              Dismiss
            </button>
          ) : null}
        </div>
      )}

      {!starMode && (
        <footer className="kbd-dock" aria-label="Keyboard shortcuts">
          <span>g galaxy</span>
          <span>c clearance</span>
          <span>Enter act</span>
          <span>Shift+C cook</span>
          <span>p star</span>
          <span>y relay</span>
          <span>h pack</span>
          <span>Ctrl+K</span>
          <span>? keys</span>
        </footer>
      )}
    </div>
  );
}

function SessionCard({
  session,
  selected,
  prMates = 0,
  onSelect,
}: {
  session: Session;
  selected: boolean;
  prMates?: number;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (selected) {
      ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [selected]);
  return (
    <button
      ref={ref}
      className={`card ${session.live ? "live" : ""} ${session.agent_name === "running" ? "running" : ""} ${selected ? "selected" : ""}`}
      aria-current={selected ? "true" : undefined}
      title={session.title}
      onClick={onSelect}
    >
      <div className="card-top">
        <span className="card-title">{session.title}</span>
        <span className="badge">{cardBadge(session)}</span>
      </div>
      <div className="meta">
        <span>{session.model || "model?"}</span>
        <span>{session.agent_name || ""}</span>
        <span>{session.pid ? `pid ${session.pid}` : ""}</span>
        <span>{sessionAge(session)}</span>
        <span>{prMates > 1 ? `+${prMates - 1} more` : ""}</span>
      </div>
    </button>
  );
}

function sessionWhen(session: Session): string | null {
  return session.last_active_at || session.updated_at || session.created_at || null;
}

function formatAgeSeconds(sec: number): string {
  const n = Math.max(0, Math.floor(sec));
  if (n < 60) return `${n}s`;
  if (n < 3600) return `${Math.floor(n / 60)}m`;
  if (n < 86400) return `${Math.floor(n / 3600)}h`;
  return `${Math.floor(n / 86400)}d`;
}

function sessionAge(session: Session): string {
  const raw = sessionWhen(session);
  if (!raw) return "";
  const ms = Date.parse(raw);
  if (!Number.isFinite(ms)) return "";
  const label = formatAgeSeconds((Date.now() - ms) / 1000);
  if (session.live && Date.now() - ms > 30 * 60 * 1000) return `stale ${label}`;
  return label;
}

function prIsOpen(session: Session): boolean {
  const st = (session.pr_state || "unknown").toLowerCase();
  return st === "open" || st === "unknown" || st === "";
}

function prIsDone(session: Session): boolean {
  const st = (session.pr_state || "").toLowerCase();
  return st === "merged" || st === "closed";
}

function cardBadge(session: Session): string {
  if (session.live) return "live";
  if (session.agent_name === "running") return "running";
  if (session.pr_url) {
    const st = session.pr_state && session.pr_state !== "unknown" ? ` ${session.pr_state}` : "";
    return `pr ${prLabel(session.pr_url)}${st}`;
  }
  if (session.source === "cursor_web") return session.agent_name || "cursor.com";
  if (session.source === "grok_web") return "grok.com";
  return session.state;
}

function nextWaveLine(board: CookState | null): string {
  const named = (board?.last_next || []).filter(Boolean);
  if (named.length) return named.join(", ");
  const waiting = (board?.last_board || [])
    .filter((row) => row.state === "waiting" || row.state === "empty")
    .map((row) => row.name || row.id)
    .filter(Boolean)
    .slice(0, 4);
  return waiting.join(", ");
}

function shipLines(board: CookState | null): CookShip[] {
  const ships = (board?.last_ships || []).filter((row) => row.shipped);
  if (ships.length) return ships.slice(0, 6);
  return (board?.last_board || [])
    .filter((row) => Boolean(row.shipped))
    .map((row) => ({
      id: row.id,
      name: row.name || row.id,
      shipped: row.shipped || "",
      next: row.next,
    }))
    .slice(0, 6);
}

function projectCards(sessions: Session[], project: Project, showAllFinished: boolean) {
  const members = sessions.filter((s) => (s.project_id || s.cwd) === project.id);
  const leftover = project.id === "loose" || project.id === "grok.com";
  const { winners, mates } = pickPrWinners(members);
  const finished = members.filter(
    (s) =>
      s.source === "cursor_web" &&
      (prIsDone(s) ||
        (s.agent_name === "finished" && (!s.pr_url || !winners.has(s.id) || prIsDone(s)))),
  );
  const hot = members.filter(
    (s) =>
      s.live ||
      s.agent_name === "running" ||
      s.agent_name === "error" ||
      (Boolean(s.pr_url) && winners.has(s.id) && prIsOpen(s)),
  );
  const rest = members.filter((s) => !hot.includes(s) && !finished.includes(s));
  if (leftover) {
    const pool = [...rest, ...finished].sort((a, b) => sessionRank(a) - sessionRank(b));
    const cap = showAllFinished ? pool : pool.slice(0, 3);
    return { shown: [...hot, ...cap], extra: Math.max(0, pool.length - 3), mates };
  }
  const cap = showAllFinished ? finished : finished.slice(0, 3);
  const shown = [...hot, ...rest, ...cap].sort((a, b) => sessionRank(a) - sessionRank(b));
  return { shown, extra: Math.max(0, finished.length - 3), mates };
}

function normalizePr(url: string): string {
  return url
    .trim()
    .toLowerCase()
    .replace("https://www.github.com/", "https://github.com/")
    .replace("https://www.gitlab.com/", "https://gitlab.com/")
    .replace(/[?#].*$/, "")
    .replace(/\/$/, "");
}

function pickPrWinners(members: Session[]): { winners: Set<string>; mates: Record<string, number> } {
  const groups = new Map<string, Session[]>();
  for (const s of members) {
    if (!s.pr_url) continue;
    const key = normalizePr(s.pr_url);
    const rows = groups.get(key) || [];
    rows.push(s);
    groups.set(key, rows);
  }
  const winners = new Set<string>();
  const mates: Record<string, number> = {};
  for (const rows of groups.values()) {
    const sorted = [...rows].sort(
      (a, b) => sessionRank(a) - sessionRank(b) || a.title.localeCompare(b.title) || a.id.localeCompare(b.id),
    );
    winners.add(sorted[0].id);
    mates[sorted[0].id] = sorted.length;
  }
  return { winners, mates };
}

function sessionRank(session: Session): number {
  if (session.live) return 0;
  if (session.agent_name === "running") return 1;
  if (session.agent_name === "error" || session.state === "needs_input") return 2;
  if (session.pr_url) return 2;
  return 3;
}

function looksLikePath(cwd?: string | null): boolean {
  if (!cwd) return false;
  if (cwd === "cursor.com" || cwd === "grok.com" || cwd === "loose") return false;
  return /[\\/]/.test(cwd) || /^[A-Za-z]:/.test(cwd);
}

function isNamedWell(id?: string | null): boolean {
  return Boolean(id) && id !== "loose" && id !== "grok.com" && id !== "cursor.com";
}

function memberKindLabel(session: Session): string {
  if (session.live) return "live pager";
  if (session.source === "cursor_web" || session.id.startsWith("web:cursor:")) {
    if (session.pr_state === "draft") return "Cursor draft";
    if (session.pr_state === "open") return "Cursor PR";
    return "Cursor";
  }
  if (session.source === "grok_web" || session.id.startsWith("web:grok:")) return "grok.com";
  return session.agent_name || session.state;
}

function wellMembers(snap: Snapshot | null, session: Session): Session[] {
  if (!snap || !isNamedWell(session.project_id)) return [];
  return snap.sessions
    .filter((s) => s.id !== session.id && s.project_id === session.project_id)
    .sort((a, b) => sessionRank(a) - sessionRank(b))
    .slice(0, 8);
}

function wellDesk(snap: Snapshot | null, projectId?: string | null) {
  if (!snap || !isNamedWell(projectId)) return null;
  const needle = `claim ${projectId}`.toLowerCase();
  return snap.attention.find((a) => a.kind === "desk_claim" && a.title.toLowerCase().includes(needle)) || null;
}

function wellLiveSibling(snap: Snapshot | null, session: Session): Session | null {
  if (!snap || !isNamedWell(session.project_id)) return null;
  return (
    snap.sessions.find(
      (s) => s.live && s.id !== session.id && s.project_id === session.project_id,
    ) || null
  );
}

function wellFlags(snap: Snapshot, project: Project): string {
  if (!isNamedWell(project.id)) return "";
  const bits: string[] = [];
  if (snap.sessions.some((s) => s.project_id === project.id && s.live)) bits.push("+ pager");
  if (wellDesk(snap, project.id)) bits.push("+ desk");
  return bits.join(" ");
}

function clearanceVerb(a: Attention): { label: string; dest: string } | null {
  if (a.kind === "stale") return { label: "Bring to front", dest: "focus" };
  if (a.kind === "running") return { label: "Open in browser", dest: "open_url" };
  if (a.kind === "pr_ready") return { label: "Open PR", dest: "open_pr" };
  if (a.kind === "desk_claim") return { label: "Open folder", dest: "open_cwd" };
  return null;
}

function prSiblings(snap: Snapshot | null, session: Session): Session[] {
  if (!snap || !session.pr_url) return [];
  const key = normalizePr(session.pr_url);
  return snap.sessions
    .filter((s) => s.id !== session.id && s.pr_url && normalizePr(s.pr_url) === key)
    .sort((a, b) => a.title.localeCompare(b.title));
}

function prLabel(url?: string | null): string {
  if (!url) return "";
  const pull = url.match(/\/pull\/(\d+)/);
  if (pull) return `#${pull[1]}`;
  const mr = url.match(/\/merge_requests\/(\d+)/);
  if (mr) return `!${mr[1]}`;
  return "PR";
}

function clockFromIso(iso?: string | null): string {
  if (!iso) return "";
  const t = iso.split("T")[1] || "";
  return t.slice(0, 5);
}

function webChip(status?: string): string {
  if (status === "ok") return "ok";
  if (status === "degraded" || status === "stale") return "degraded";
  if (status === "needs_consent" || status === "unauth" || status === "offline") return "offline";
  return "";
}

function visibleSessions(snap: Snapshot | null, view: View): Session[] {
  if (!snap) return [];
  let rows = snap.sessions;
  if (view === "web") {
    rows = rows.filter((s) => s.id.startsWith("web:"));
  } else if (view === "clearance") {
    const ids = new Set(snap.attention.map((a) => a.session_id).filter(Boolean));
    rows = rows.filter((s) => ids.has(s.id));
  }
  return [...rows].sort((a, b) => sessionRank(a) - sessionRank(b));
}

function quietAdapters(snap: Snapshot | null) {
  return (snap?.adapters || []).filter((a) => a.status !== "ok" || a.name === "web" || a.name === "desk");
}

function situationClauses(text: string): string[] {
  return text
    .split(/\.\s+/)
    .map((s) => s.replace(/\.$/, "").trim())
    .filter((s) => s.length > 0)
    .slice(0, 6);
}

function nextHop(snap: Snapshot | null, acp: AcpState | null): string {
  if (!snap) return "";
  if (acp?.permissions?.length) return `approve ${acp.permissions[0].title}`;
  const stale = snap.attention.find((a) => a.kind === "stale");
  if (stale) return stale.title;
  const run = snap.attention.find((a) => a.kind === "running");
  if (run) return run.title;
  const pr = snap.attention.find((a) => a.kind === "pr_ready");
  if (pr) return pr.title;
  const desk = snap.attention.find((a) => a.kind === "desk_claim");
  if (desk) return desk.title;
  return "";
}

function commandList(snap: Snapshot | null, selected: string | null): Cmd[] {
  const cmds: Cmd[] = [
    { id: "galaxy", label: "Go to Galaxy", hint: "named wells", group: "Navigate", kbd: "g" },
    { id: "clearance", label: "Go to Clearance", hint: "true queue", group: "Navigate", kbd: "c" },
    { id: "feed", label: "Go to Feed", hint: "activity tails", group: "Navigate", kbd: "f" },
    { id: "web", label: "Go to Web adapters", hint: "grok.com / cursor.com", group: "Navigate", kbd: "w" },
    { id: "cook", label: "COOK / STOP COOK", hint: "deploy staff to all named wells", group: "Act", kbd: "Shift+C" },
    { id: "refresh", label: "Refresh snapshot", hint: "full collect", group: "Act", kbd: "r" },
    { id: "refresh-cursor-api", label: "Refresh Cursor via API", hint: "official, no Brave bounce", group: "Act" },
    { id: "star", label: "Star this session", hint: "same window", group: "Act", kbd: "p" },
    { id: "star-monitor", label: "Star on other monitor", hint: "off invoke thread", group: "Act" },
    { id: "copy-handoff", label: "Copy handoff pack", hint: "never injects", group: "Act", kbd: "h" },
    { id: "relay", label: "Relay this brief", hint: "hop to another surface", group: "Act", kbd: "y" },
    { id: "continue-handoff", label: "Continue in new Orbit ACP", hint: "clone path, no live inject", group: "Act" },
    { id: "new-acp", label: "New Orbit ACP session", hint: "ask mode, not yolo", group: "Act" },
  ];
  const picked = (snap?.sessions || []).find((s) => s.id === selected);
  if (picked && !picked.live && !picked.id.startsWith("web:")) {
    cmds.push({
      id: "act:resume_session:Resume launched",
      label: "Resume selected in Grok",
      hint: "new window; refuses live TUI",
      group: "Act",
    });
  }
  if (selected) {
    cmds.push(
      { id: "act:open_session_cwd:Opened cwd", label: "Open selected folder", hint: "explorer", group: "Act", kbd: "o" },
      { id: "act:reveal_session_dir:Opened session dir", label: "Reveal session files", hint: "disk", group: "Act" },
    );
  }
  for (const s of (snap?.sessions || []).filter((x) => x.live).slice(0, 6)) {
    cmds.push({
      id: `sel:${s.id}`,
      label: s.title || s.id,
      hint: "live pager",
      group: "Live",
    });
  }
  return cmds;
}
