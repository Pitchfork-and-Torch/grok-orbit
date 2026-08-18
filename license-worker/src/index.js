const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    const url = new URL(request.url);
    try {
      if (url.pathname === "/health") {
        return json({
          ok: true,
          service: "grok-orbit-license",
          stripe: Boolean(env.STRIPE_SECRET_KEY && env.STRIPE_PRICE_ID),
          mail: Boolean(env.EMAIL_TOKEN && env.EMAIL_SEND_URL),
          notify: Boolean(env.NOTIFY_EMAIL),
        });
      }
      if (url.pathname === "/" && request.method === "GET") return landing(env);
      if (url.pathname === "/download" && request.method === "GET") return publicDownload(url, env);
      if (url.pathname === "/hero.jpg") return publicFile(env, "hero.jpg", "image/jpeg");
      if (url.pathname === "/og.jpg") return publicFile(env, "og.jpg", "image/jpeg");
      if (url.pathname === "/success" && request.method === "GET") return successPage(url, env);
      if (url.pathname === "/v1/register" && request.method === "POST") return register(request, env);
      if (url.pathname === "/v1/verify" && request.method === "POST") return verify(request, env);
      if (url.pathname === "/v1/checkout" && request.method === "POST") return checkout(request, env);
      if (url.pathname === "/v1/paid" && request.method === "POST") return paid(request, env);
      if (url.pathname === "/v1/activate" && request.method === "POST") return activate(request, env);
      if (url.pathname === "/v1/download" && request.method === "GET") return download(url, env);
      if (url.pathname === "/v1/stripe/webhook" && request.method === "POST") {
        return stripeWebhook(request, env);
      }
      return json({ error: "Not found" }, 404);
    } catch (err) {
      return json({ error: err instanceof Error ? err.message : String(err) }, 500);
    }
  },
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

async function publicDownload(url, env) {
  const portable = url.searchParams.get("file") === "portable";
  const names = portable
    ? ["grok-orbit.exe"]
    : ["GrokOrbit-setup.exe", "Grok Orbit_1.0.0_x64-setup.exe", "Grok Orbit_1.0.1_x64-setup.exe"];
  if (!env.DIST) return json({ error: "missing installer" }, 404);
  for (const name of names) {
    const obj = await env.DIST.get(name);
    if (obj) {
      return new Response(obj.body, {
        headers: {
          "Content-Type": "application/octet-stream",
          "Content-Disposition": `attachment; filename="${name.replace(/ /g, ".")}"`,
          "Cache-Control": "public, max-age=300",
        },
      });
    }
  }
  return json({ error: "Installer is not in the bucket yet." }, 404);
}

async function publicFile(env, name, type) {
  if (!env.DIST) return json({ error: "missing asset" }, 404);
  const obj = await env.DIST.get(name);
  if (!obj) return json({ error: "missing asset" }, 404);
  return new Response(obj.body, {
    headers: {
      "Content-Type": type,
      "Cache-Control": "public, max-age=86400",
    },
  });
}

function publicError(msg) {
  const s = String(msg || "");
  if (/api key|invalid api|Bearer/i.test(s)) return "Payments are being reset. Wait a few seconds and tap Pay again.";
  if (s.length > 160) return s.slice(0, 160);
  return s || "Something went wrong.";
}

function landing(env) {
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Grok Orbit - one panel for every local agent</title>
<meta name="description" content="Local Windows command center for Grok CLI, Grok Bot, grok.com, and other model keys. Download free. $19 unlocks Resume, COOK, Orbit ACP, hand off, and Cursor follow-up."/>
<link rel="canonical" href="https://orbit.jonbailey.xyz/"/>
<meta property="og:title" content="Grok Orbit"/>
<meta property="og:description" content="One local panel for Grok CLI, Grok Bot, grok.com, and other model keys. Download free. $19 unlocks Resume, COOK, Orbit ACP, hand off, and Cursor follow-up."/>
<meta property="og:image" content="https://orbit.jonbailey.xyz/og.jpg?v=1.0.2"/>
<meta property="og:image:width" content="1200"/>
<meta property="og:image:height" content="630"/>
<meta property="og:image:type" content="image/jpeg"/>
<meta property="og:url" content="https://orbit.jonbailey.xyz/"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:image" content="https://orbit.jonbailey.xyz/og.jpg?v=1.0.2"/>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
{"@type":"Question","name":"What is free, and what do I pay $19 for?","acceptedAnswer":{"@type":"Answer","text":"Download, install, Galaxy, Clearance, connecting Grok CLI / Grok Bot / grok.com / Cursor / other keys, opening folders, and copying a handoff pack are free. $19 is a one-time key that unlocks verbs that start work: Resume, COOK, Orbit ACP, Continue in Orbit ACP, and Cursor follow-up."}},
{"@type":"Question","name":"What does Resume do?","acceptedAnswer":{"@type":"Answer","text":"Resume opens a new Grok console on that session. It does not type into a Grok window you already have open. Pick a real CLI session, then Resume in Grok. Sample cards cannot resume."}},
{"@type":"Question","name":"What does COOK do?","acceptedAnswer":{"@type":"Answer","text":"COOK is a header button. You confirm once. Orbit then runs an in-app loop and starts new one-shot Grok consoles on named project wells that have a local clone, are not claimed by another desk, and have no live pager. Idle Cursor agents can get a capped follow-up. When a cook window closes, that turn finished. STOP COOK turns the loop off. COOK does not use Task Scheduler, does not inject into live pagers, and does not auto-approve tools."}},
{"@type":"Question","name":"What is Orbit ACP?","acceptedAnswer":{"@type":"Answer","text":"Orbit ACP is an agent session Orbit owns. You can start a new session in a project folder, attach an idle Grok session, send a prompt, and answer permission asks one by one. It never attaches a live TUI pager. It never runs with always-approve."}},
{"@type":"Question","name":"What is hand off?","acceptedAnswer":{"@type":"Answer","text":"Copy handoff is free. It copies a redacted pack (project, branch, last notes) to the clipboard. Continue in Orbit ACP is paid. It starts a new Orbit ACP in the linked project clone and feeds it that pack. Web chats with no local clone stay copy-only."}},
{"@type":"Question","name":"What is Cursor follow-up?","acceptedAnswer":{"@type":"Answer","text":"Cursor follow-up sends one extra run to an existing Cursor Cloud Agent after you confirm. Busy agents refuse; open them in the browser instead. This is only for cursor.com agents."}},
{"@type":"Question","name":"Will Orbit take over a Grok window I already have open?","acceptedAnswer":{"@type":"Answer","text":"No. Resume, COOK, ACP attach, and Continue in Orbit ACP all refuse a live Grok TUI. They open new work or they copy. They do not hijack the pager you are looking at."}},
{"@type":"Question","name":"Why does Sample refuse Resume?","acceptedAnswer":{"@type":"Answer","text":"Sample is a fake well so an empty install is not a blank board. It is not a real Grok session, so Resume has nothing to open."}},
{"@type":"Question","name":"How do I unlock?","acceptedAnswer":{"@type":"Answer","text":"Email on this page or in the app, type the 6-digit code in the same tab, pay $19 once on Stripe, then activate the key. Galaxy stays usable if you never pay."}},
{"@type":"Question","name":"Is the Windows installer signed?","acceptedAnswer":{"@type":"Answer","text":"No. The installer is not Authenticode-signed. SmartScreen will say the publisher is unknown. Click More info, then Run anyway. Leave SmartScreen on."}}
]}
</script>
<link rel="preconnect" href="https://api.fontshare.com"/>
<link href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&f[]=clash-display@500,600&display=swap" rel="stylesheet"/>
<style>
:root{
  color-scheme:dark;
  --void:#07080b;
  --void-2:#0c0f14;
  --panel:#10141a;
  --line:rgba(255,255,255,.08);
  --text:#e8eee6;
  --muted:#8d9689;
  --ion:#7dffa6;
  --ion-dim:rgba(125,255,166,.14);
  --warn:#e8b84a;
  --danger:#ff6b5a;
  --glass:rgba(12,16,22,.72);
  --focus:#7dffa6;
  --font-display:"Clash Display",Satoshi,system-ui,sans-serif;
  --font-sans:Satoshi,system-ui,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--void);color:var(--text);font-family:var(--font-sans);line-height:1.55}
body{min-height:100vh;background:
  radial-gradient(900px 420px at 78% 8%, rgba(125,255,166,.07), transparent 58%),
  radial-gradient(700px 380px at 0% 100%, rgba(108,182,255,.05), transparent 50%),
  var(--void)}
body::after{content:"";position:fixed;inset:0;pointer-events:none;opacity:.045;z-index:8;background-image:url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")}
img{max-width:100%;height:auto;display:block}
a{color:var(--ion)}
h1,h2{font-family:var(--font-display);font-weight:500;letter-spacing:-.02em;margin:0 0 10px}
h1{font-size:clamp(2.1rem,4.4vw,3.1rem);line-height:1.05}
h2{font-size:1.35rem}
.shell{width:min(1180px,calc(100% - 40px));margin:0 auto}
.top{display:flex;justify-content:space-between;align-items:center;padding:22px 0 18px}
.brand{font-family:var(--font-display);letter-spacing:.18em;text-transform:uppercase;font-size:12px;color:var(--ion)}
.top a.quiet{color:var(--muted);text-decoration:none;font-size:13px}
.top a.quiet:hover{color:var(--text)}
.top nav{display:flex;gap:16px;align-items:center;flex-wrap:wrap}
.skip{position:absolute;left:-999px;top:8px;z-index:20}
.skip:focus{left:12px;background:var(--ion);color:#071109;padding:8px 12px;border-radius:8px;font-weight:700;text-decoration:none}
.hero{position:relative;border-radius:22px;overflow:hidden;border:1px solid var(--line);
  box-shadow:0 30px 80px rgba(0,0,0,.38), inset 0 1px 0 rgba(255,255,255,.06)}
.hero-art{width:100%;aspect-ratio:1600/720;object-fit:cover;display:block}
.hero-scrim{position:absolute;inset:0;background:linear-gradient(90deg,rgba(7,8,11,.12) 42%,rgba(7,8,11,.18) 52%,rgba(7,8,11,.28) 100%)}
.hero-panel{position:absolute;top:50%;right:3.4%;transform:translateY(-50%);width:min(400px,46%);
  background:var(--glass);-webkit-backdrop-filter:blur(18px) saturate(1.25);backdrop-filter:blur(18px) saturate(1.25);
  border:1px solid rgba(255,255,255,.14);border-radius:18px;padding:22px 22px 18px;
  box-shadow:0 18px 50px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.16)}
.kicker{margin:0 0 8px;color:var(--ion);letter-spacing:.16em;text-transform:uppercase;font-size:11px}
.panel-title{margin:0 0 6px;font-size:1.55rem}
.lead{color:var(--muted);margin:0 0 14px}
.downloads{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 18px}
.downloads a{text-decoration:none}
button,.btn{appearance:none;border:0;border-radius:10px;padding:11px 14px;font:inherit;font-weight:700;cursor:pointer}
.btn-primary,button[type=submit],.downloads .btn-primary{background:var(--ion);color:#071109}
.btn-ghost,button.ghost{background:transparent;color:var(--text);border:1px solid rgba(255,255,255,.16);font-weight:500;margin:0}
button:disabled{opacity:.55;cursor:wait}
button:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.rule{height:1px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.12),transparent);margin:4px 0 14px;border:0}
.steps{display:flex;gap:6px;list-style:none;padding:0;margin:0 0 12px;flex-wrap:wrap}
.steps li{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:4px 8px}
.steps li.on{color:#071109;background:var(--ion);border-color:var(--ion)}
label{display:block;margin:10px 0 6px;font-size:12px;color:var(--muted)}
input{width:100%;padding:11px 12px;border-radius:10px;border:1px solid var(--line);background:rgba(8,10,14,.72);color:var(--text);font:inherit}
#code{letter-spacing:.28em;font-size:1.2rem}
.hint,.fine{font-size:12.5px;color:var(--muted);margin:8px 0 0}
.err{color:var(--danger);margin:10px 0 0}
.ok{color:var(--ion);margin:10px 0 0}
.hidden{display:none}
main{padding:36px 0 72px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:0 0 14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px 20px 18px;
  box-shadow:0 10px 28px rgba(0,0,0,.18)}
.card p:last-child{margin-bottom:0}
.notice{border-color:rgba(232,184,74,.35);background:linear-gradient(180deg,#16130c,#12110d)}
.notice h2{color:var(--warn)}
.list{margin:0;padding-left:1.15rem}
.list li{margin:8px 0}
.split{display:grid;grid-template-columns:1fr 1fr;gap:14px}
kbd{font:inherit;font-size:.85em;border:1px solid var(--line);border-radius:6px;padding:1px 6px;background:#0c1016}
.tools,.faq-block{margin:22px 0 0}
.tools > p.lead,.faq-block > p.lead{max-width:68ch}
.verbs{display:grid;gap:10px;margin:16px 0 0}
.verb{display:grid;grid-template-columns:minmax(148px,190px) 1fr;gap:6px 18px;background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:0 10px 28px rgba(0,0,0,.18)}
.verb h3{margin:0;font-family:var(--font-display);font-size:1.12rem;font-weight:500}
.verb .tag{margin:4px 0 0;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--ion)}
.verb p{margin:0;color:var(--muted)}
.faq-list{margin:16px 0 0}
.faq-list details{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin:0 0 8px}
.faq-list summary{cursor:pointer;padding:14px 16px;font-weight:700;list-style:none;min-height:44px}
.faq-list summary::-webkit-details-marker{display:none}
.faq-list summary::after{content:"+";float:right;color:var(--muted);font-weight:500}
.faq-list details[open] summary{border-bottom:1px solid var(--line)}
.faq-list details[open] summary::after{content:"-"}
.faq-list .ans{padding:12px 16px 16px;margin:0;color:var(--muted)}
.faq-list .ans p{margin:0 0 10px}
.faq-list .ans p:last-child{margin-bottom:0}
@media(max-width:920px){
  .hero-panel{position:relative;top:auto;right:auto;transform:none;width:auto;margin:0;border-radius:0 0 22px 22px}
  .hero-scrim{background:linear-gradient(180deg,transparent 40%,rgba(7,8,11,.55))}
  .grid,.split,.verb{grid-template-columns:1fr}
}
@media(prefers-reduced-transparency:reduce){
  .hero-panel{background:#12161c;backdrop-filter:none;-webkit-backdrop-filter:none}
}
@media(prefers-reduced-motion:reduce){
  *{transition:none!important;animation:none!important}
}
</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="shell top">
  <div class="brand">Orbit</div>
  <nav aria-label="On this page">
    <a class="quiet" href="#tools">Paid tools</a>
    <a class="quiet" href="#faq">FAQ</a>
    <a class="quiet" href="#how">How to set up</a>
  </nav>
</header>
<section class="shell hero" aria-label="Grok Orbit">
  <img class="hero-art" src="/hero.jpg?v=1.0.2" width="1600" height="720" alt="Grok Orbit: one panel for Grok CLI, Grok Bot, grok.com, and other model keys." fetchpriority="high"/>
  <div class="hero-scrim" aria-hidden="true"></div>
  <aside class="hero-panel" id="buy">
    <p class="kicker">Windows desktop</p>
    <h2 class="panel-title">Install free</h2>
    <p class="lead">No payment to download. Watch your fleet first. Unlock later to act.</p>
    <div class="downloads">
      <a class="btn btn-primary" href="/download">Download installer</a>
      <a class="btn btn-ghost" href="/download?file=portable">Portable exe</a>
    </div>
    <hr class="rule"/>
    <p class="kicker">Optional</p>
    <h2 class="panel-title" style="font-size:1.15rem">Unlock actions, $19</h2>
    <p class="fine">Galaxy stays free. Pay once to resume, COOK, run ACP, or hand off. <a href="#tools">What each tool does</a>.</p>
    <ol class="steps" aria-label="Unlock steps">
      <li id="dot-email" class="on">Email</li>
      <li id="dot-code">Code</li>
      <li id="dot-pay">Pay</li>
    </ol>
    <form id="f" novalidate>
      <div id="step-email">
        <label for="email">Email</label>
        <input id="email" type="email" autocomplete="email" required placeholder="you@example.com"/>
        <button type="submit" id="send">Email me a code</button>
        <p class="hint">This page stays open. Check mail, then type the code here.</p>
      </div>
      <div id="step-code" class="hidden">
        <label for="code">Six-digit code</label>
        <input id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="123456"/>
        <button type="submit" id="check">Verify code</button>
        <button type="button" class="ghost" id="resend">Resend</button>
        <p class="hint">Valid 30 minutes. Keep this tab open.</p>
      </div>
      <div id="step-pay" class="hidden">
        <p class="lead">Email verified. Pay $19 once for an action key.</p>
        <button type="submit" id="pay">Pay $19</button>
      </div>
    </form>
    <p class="err" id="err" hidden></p>
    <p class="ok" id="ok" hidden></p>
  </aside>
</section>
<main class="shell" id="main">
  <div class="grid">
    <article class="card">
      <p class="kicker">See</p>
      <h2>One situation bar</h2>
      <p class="fine">Live Grok CLI pagers, desk claims, and clearance in one glance. The official dashboard only sees the pager you are inside.</p>
    </article>
    <article class="card">
      <p class="kicker">Connect</p>
      <h2>Bot, web, keys</h2>
      <p class="fine">Grok Bot process status, consented grok.com chats, Cursor Cloud Agents, optional OpenAI / Anthropic / Gemini / xAI keys. Tokens stay on this PC.</p>
    </article>
    <article class="card">
      <p class="kicker">Act later</p>
      <h2>Pay only to move</h2>
      <p class="fine">Observe is free. $19 unlocks resume, COOK, ACP, hand off, and Cursor follow-up. Empty machines get a well marked Sample. <a href="#faq">FAQ</a>.</p>
    </article>
  </div>
  <div class="split">
    <section class="card notice">
      <h2>Windows will warn you</h2>
      <p>The installer is <strong>not Authenticode-signed</strong>. SmartScreen will say the publisher is unknown. That is expected, not a virus verdict.</p>
      <ol class="list">
        <li>Run the setup exe.</li>
        <li>If Windows says it protected your PC, click <strong>More info</strong>, then <strong>Run anyway</strong>.</li>
        <li>Leave SmartScreen on.</li>
      </ol>
    </section>
    <section class="card" id="how">
      <h2>How to set up</h2>
      <ol class="list">
        <li>Download from the hero. No payment.</li>
        <li>Install, then click through SmartScreen as at left.</li>
        <li>Open Orbit. Connect Grok CLI, Grok Bot, grok.com. Empty PCs show Sample.</li>
        <li>Watch Galaxy. Unlock in the app or this panel when you want to act. See <a href="#tools">paid tools</a>.</li>
        <li><kbd>g</kbd> Galaxy <kbd>c</kbd> Clearance <kbd>w</kbd> Web. Ctrl+Shift+O from the tray.</li>
      </ol>
    </section>
  </div>
  <section class="card tools" id="tools">
    <p class="kicker">Paid tools</p>
    <h2>What $19 actually does</h2>
    <p class="lead">Observe stays free. The key unlocks verbs that start work on your machine. None of them type into a Grok window you already have open.</p>
    <div class="verbs">
      <article class="verb">
        <div>
          <h3>Resume</h3>
          <p class="tag">New Grok console</p>
        </div>
        <p>Opens a new Grok console on the session you picked. It does not inject into a live TUI. Sample cards cannot resume because they are not a real session.</p>
      </article>
      <article class="verb">
        <div>
          <h3>COOK</h3>
          <p class="tag">In-app staff loop</p>
        </div>
        <p>Header button, confirm once. Orbit then starts new one-shot Grok consoles on named project wells that have a local clone, are not desk-claimed, and have no live pager. Idle Cursor agents can get a capped follow-up. A cook window that closes means that turn finished. STOP COOK turns the loop off. Already-open consoles stay up. No Task Scheduler. No auto-approve.</p>
      </article>
      <article class="verb">
        <div>
          <h3>Orbit ACP</h3>
          <p class="tag">Ask-mode agent</p>
        </div>
        <p>An agent session Orbit owns. Start one in a project folder, or attach an idle Grok session. Send a prompt. Answer permission asks one by one. Never attaches a live TUI. Never runs with always-approve.</p>
      </article>
      <article class="verb">
        <div>
          <h3>Hand off</h3>
          <p class="tag">Copy free, continue paid</p>
        </div>
        <p>Copy handoff is free. It copies a redacted pack (project, branch, last notes). Continue in Orbit ACP is paid. It starts a new Orbit ACP in the linked project clone and feeds it that pack. Web chats with no local clone stay copy-only.</p>
      </article>
      <article class="verb">
        <div>
          <h3>Cursor follow-up</h3>
          <p class="tag">One extra Cloud Agent run</p>
        </div>
        <p>After you confirm, Orbit posts one extra run to an existing Cursor Cloud Agent. Busy agents refuse; open them in the browser instead. This is only for cursor.com agents.</p>
      </article>
    </div>
  </section>
  <section class="card faq-block" id="faq">
    <p class="kicker">FAQ</p>
    <h2>Paid tools, answered</h2>
    <p class="lead">Short answers that match what the app actually does. Open a question for the rest.</p>
    <div class="faq-list">
      <details>
        <summary>What is free, and what do I pay $19 for?</summary>
        <div class="ans">
          <p>Download, install, Galaxy, Clearance, connecting Grok CLI / Grok Bot / grok.com / Cursor / other keys, opening folders, and copying a handoff pack are free.</p>
          <p>$19 is a one-time key that unlocks verbs that start work: Resume, COOK, Orbit ACP, Continue in Orbit ACP, and Cursor follow-up.</p>
        </div>
      </details>
      <details>
        <summary>What does Resume do?</summary>
        <div class="ans">
          <p>Resume opens a new Grok console on that session. It does not type into a Grok window you already have open. Pick a real CLI session, then Resume in Grok. Sample cards cannot resume.</p>
        </div>
      </details>
      <details>
        <summary>What does COOK do?</summary>
        <div class="ans">
          <p>COOK is a header button. You confirm once. Orbit then runs an in-app loop and starts new one-shot Grok consoles on named project wells that have a local clone, are not claimed by another desk, and have no live pager. Idle Cursor agents can get a capped follow-up. When a cook window closes, that turn finished. STOP COOK turns the loop off. COOK does not use Task Scheduler, does not inject into live pagers, and does not auto-approve tools.</p>
        </div>
      </details>
      <details>
        <summary>What is Orbit ACP?</summary>
        <div class="ans">
          <p>Orbit ACP is an agent session Orbit owns. You can start a new session in a project folder, attach an idle Grok session, send a prompt, and answer permission asks one by one. It never attaches a live TUI pager. It never runs with always-approve.</p>
        </div>
      </details>
      <details>
        <summary>What is hand off?</summary>
        <div class="ans">
          <p>Copy handoff is free. It copies a redacted pack (project, branch, last notes) to the clipboard. Continue in Orbit ACP is paid. It starts a new Orbit ACP in the linked project clone and feeds it that pack. Web chats with no local clone stay copy-only.</p>
        </div>
      </details>
      <details>
        <summary>What is Cursor follow-up?</summary>
        <div class="ans">
          <p>Cursor follow-up sends one extra run to an existing Cursor Cloud Agent after you confirm. Busy agents refuse; open them in the browser instead. This is only for cursor.com agents.</p>
        </div>
      </details>
      <details>
        <summary>Will Orbit take over a Grok window I already have open?</summary>
        <div class="ans">
          <p>No. Resume, COOK, ACP attach, and Continue in Orbit ACP all refuse a live Grok TUI. They open new work or they copy. They do not hijack the pager you are looking at.</p>
        </div>
      </details>
      <details>
        <summary>Why does Sample refuse Resume?</summary>
        <div class="ans">
          <p>Sample is a fake well so an empty install is not a blank board. It is not a real Grok session, so Resume has nothing to open.</p>
        </div>
      </details>
      <details>
        <summary>How do I unlock?</summary>
        <div class="ans">
          <p>Email on this page or in the app, type the 6-digit code in the same tab, pay $19 once on Stripe, then activate the key. Galaxy stays usable if you never pay.</p>
        </div>
      </details>
      <details>
        <summary>Is the Windows installer signed?</summary>
        <div class="ans">
          <p>No. The installer is not Authenticode-signed. SmartScreen will say the publisher is unknown. Click More info, then Run anyway. Leave SmartScreen on.</p>
        </div>
      </details>
    </div>
  </section>
</main>
<script>
const $=id=>document.getElementById(id);
const state={step:"email",email:"",token:""};
function show(step){
  state.step=step;
  ["email","code","pay"].forEach(s=>{
    $("step-"+s).classList.toggle("hidden", s!==step);
    $("dot-"+s).classList.toggle("on", s===step);
  });
}
function setErr(t){$("err").hidden=!t;$("err").textContent=t||"";$("ok").hidden=true;}
function setOk(t){$("ok").hidden=!t;$("ok").textContent=t||"";$("err").hidden=true;}
function busy(on){["send","check","resend","pay"].forEach(id=>{const b=$(id);if(b)b.disabled=!!on;});}
async function post(path,body){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const d=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(d.error||("Request failed ("+r.status+")"));
  return d;
}
async function sendCode(){
  const email=$("email").value.trim().toLowerCase();
  if(!email.includes("@")) throw new Error("Enter a valid email.");
  state.email=email;
  await post("/v1/register",{email});
  show("code");
  setOk("Code sent to "+email+". This tab stays put.");
  $("code").focus();
}
$("resend").onclick=async()=>{
  setErr("");
  busy(true);
  try{await sendCode();}catch(e){setErr(e.message);}
  finally{busy(false);}
};
$("f").onsubmit=async(e)=>{
  e.preventDefault();
  setErr("");
  busy(true);
  try{
    if(state.step==="email"){
      await sendCode();
    }else if(state.step==="code"){
      const code=$("code").value.replace(/\\s+/g,"");
      if(code.length<4) throw new Error("Enter the 6-digit code.");
      const vd=await post("/v1/verify",{email:state.email,code});
      state.token=vd.verify_token||"";
      show("pay");
      setOk("Email verified. Next is the $19 payment.");
    }else if(state.step==="pay"){
      const cd=await post("/v1/checkout",{email:state.email,verify_token:state.token});
      if(!cd.url) throw new Error("Checkout did not return a URL.");
      location.href=cd.url;
    }
  }catch(err){setErr(err.message);}
  finally{busy(false);}
};
</script>
</body>
</html>`;
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" } });
}

async function register(request, env) {
  const email = await readEmail(request);
  if (!email) return json({ error: "Valid email required" }, 400);
  const rec = (await env.KV.get(`mail:${email}`, "json")) || { hits: [] };
  const hourAgo = Date.now() - 3600_000;
  rec.hits = (rec.hits || []).filter((t) => t > hourAgo);
  if (rec.hits.length >= 5) return json({ error: "Too many codes. Try again later." }, 429);
  const code = String(Math.floor(100000 + Math.random() * 900000));
  rec.hits.push(Date.now());
  rec.code = code;
  rec.codeExp = Date.now() + 30 * 60_000;
  await env.KV.put(`mail:${email}`, JSON.stringify(rec), { expirationTtl: 86400 });
  await sendMail(
    env,
    email,
    "[ORBIT] Your verification code",
    `Your Grok Orbit verification code is ${code}. It expires in 30 minutes.\n\nKeep the Orbit tab open and type the code there. You do not need another device.\n\nIf you did not ask for this, ignore the email.`,
  );
  return json({ ok: true, sent: true });
}

async function verify(request, env) {
  const body = await request.json().catch(() => ({}));
  const email = String(body.email || "").trim().toLowerCase();
  const code = String(body.code || "").trim();
  if (!EMAIL_RE.test(email) || !code) return json({ error: "Email and code required" }, 400);
  const rec = await env.KV.get(`mail:${email}`, "json");
  if (!rec || !rec.code || rec.codeExp < Date.now()) {
    return json({ error: "Code expired. Request a new one." }, 400);
  }
  if (rec.code !== code) return json({ error: "That code is not correct." }, 400);
  rec.verified = true;
  rec.code = null;
  const token = crypto.randomUUID();
  rec.verifyToken = token;
  rec.verifyExp = Date.now() + 2 * 3600_000;
  await env.KV.put(`mail:${email}`, JSON.stringify(rec), { expirationTtl: 86400 * 7 });
  await env.KV.put(`vtok:${token}`, JSON.stringify({ email, exp: rec.verifyExp }), {
    expirationTtl: 7200,
  });
  return json({ ok: true, verify_token: token });
}

async function requireVerified(env, email, token) {
  const row = await env.KV.get(`vtok:${token}`, "json");
  if (!row || row.email !== email || row.exp < Date.now()) return false;
  return true;
}

async function checkout(request, env) {
  const body = await request.json().catch(() => ({}));
  const email = String(body.email || "").trim().toLowerCase();
  const token = String(body.verify_token || "");
  if (!EMAIL_RE.test(email) || !(await requireVerified(env, email, token))) {
    return json({ error: "Verify your email first." }, 403);
  }
  const existing = await env.KV.get(`email_lic:${email}`, "json");
  if (existing?.key) {
    return json({ url: `${new URL(request.url).origin}/success?key=${encodeURIComponent(existing.key)}` });
  }
  if (!env.STRIPE_SECRET_KEY || !env.STRIPE_PRICE_ID) {
    return json({ error: "Payments are not configured yet." }, 503);
  }
  const origin = new URL(request.url).origin;
  const params = new URLSearchParams({
    mode: "payment",
    "line_items[0][price]": env.STRIPE_PRICE_ID,
    "line_items[0][quantity]": "1",
    customer_email: email,
    success_url: `${origin}/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${origin}/`,
    client_reference_id: email,
    "metadata[product]": "grok-orbit",
    "metadata[email]": email,
  });
  const res = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.STRIPE_SECRET_KEY}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: params,
  });
  const data = await res.json();
  if (!res.ok) return json({ error: publicError(data.error?.message || "Stripe error") }, 502);
  await env.KV.put(
    `sess:${data.id}`,
    JSON.stringify({ email, token }),
    { expirationTtl: 86400 },
  );
  return json({ url: data.url });
}

async function issueKey(env, email, stripeId, amountCents) {
  const existing = await env.KV.get(`email_lic:${email}`, "json");
  if (existing?.key) return existing.key;
  const key = generateKey();
  const rec = {
    key,
    email,
    stripe: stripeId || "",
    created: new Date().toISOString(),
  };
  await env.KV.put(`lic:${await sha256(key)}`, JSON.stringify(rec));
  await env.KV.put(`email_lic:${email}`, JSON.stringify(rec));
  if (stripeId) await env.KV.put(`plain:${stripeId}`, key, { expirationTtl: 86400 * 2 });
  await sendMail(
    env,
    email,
    "[ORBIT] Your Grok Orbit license key",
    `Thanks for buying Grok Orbit.\n\nYour license key:\n\n${key}\n\nOpen the app, paste the key, then connect Grok CLI, Grok Bot, grok.com, and any other model keys.\n\nOne-time $19 license. This key is for you.`,
  );
  await notifySale(env, email, stripeId, amountCents);
  return key;
}

async function stripeWebhook(request, env) {
  if (!env.STRIPE_WEBHOOK_SECRET) return json({ error: "Webhook not configured" }, 503);
  const payload = await request.text();
  const sig = request.headers.get("stripe-signature");
  const secrets = [env.STRIPE_WEBHOOK_SECRET, env.STRIPE_WEBHOOK_SECRET_ALT].filter(Boolean);
  const ok = await Promise.any(
    secrets.map((s) => verifyStripeSignature(payload, sig, s).then((v) => (v ? true : Promise.reject()))),
  ).catch(() => false);
  if (!ok) return json({ error: "Invalid signature" }, 400);
  const event = JSON.parse(payload);
  if (event.type === "checkout.session.completed") {
    const obj = event.data.object || {};
    const details = obj.customer_details || {};
    const email = String(obj.customer_email || details.email || obj.metadata?.email || "").toLowerCase();
    const amountCents = Number(obj.amount_total);
    if (email) await issueKey(env, email, obj.id, amountCents);
  }
  return json({ received: true });
}

async function successPage(url, env) {
  let key = url.searchParams.get("key") || "";
  const sessionId = url.searchParams.get("session_id");
  if (!key && sessionId && env.STRIPE_SECRET_KEY) {
    key = (await env.KV.get(`plain:${sessionId}`)) || "";
    if (!key) {
      const res = await fetch(`https://api.stripe.com/v1/checkout/sessions/${sessionId}`, {
        headers: { Authorization: `Bearer ${env.STRIPE_SECRET_KEY}` },
      });
      if (res.ok) {
        const session = await res.json();
        const email = String(session.customer_email || session.metadata?.email || "").toLowerCase();
        if (email) key = await issueKey(env, email, session.id);
      }
    }
  }
  const html = `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Grok Orbit license</title>
<style>body{font-family:system-ui,sans-serif;background:#0a0c10;color:#e8eee6;max-width:560px;margin:0 auto;padding:32px}
code{display:block;background:#12161c;border:1px solid #232a32;padding:12px;border-radius:8px;color:#7dffa6;letter-spacing:.06em}
a{color:#7dffa6}</style></head>
<body>
<h1>You are in</h1>
${
  key
    ? `<p>Paste this key into Grok Orbit:</p><code>${key}</code>
<p><a href="/v1/download?key=${encodeURIComponent(key)}">Download Windows installer</a>
 &middot; <a href="/v1/download?key=${encodeURIComponent(key)}&file=portable">Portable exe</a></p>`
    : "<p>Payment is recorded. If the key is not here yet, check the email we just sent.</p>"
}
<p>Then connect Grok CLI, Grok Bot, grok.com, and any other model keys. One panel.</p>
<p>The installer is not code-signed. If Windows says it protected your PC, click More info, then Run anyway. Leave SmartScreen on.</p>
</body></html>`;
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

async function paid(request, env) {
  const body = await request.json().catch(() => ({}));
  const email = String(body.email || "").trim().toLowerCase();
  const token = String(body.verify_token || "");
  if (!(await requireVerified(env, email, token))) return json({ error: "Verify first." }, 403);
  const rec = await env.KV.get(`email_lic:${email}`, "json");
  if (!rec?.key) return json({ paid: false });
  return json({ paid: true, key: rec.key });
}

async function activate(request, env) {
  const body = await request.json().catch(() => ({}));
  const key = String(body.key || "")
    .trim()
    .toUpperCase();
  const machine = String(body.machine_id || "").slice(0, 80);
  if (!key.startsWith("ORBIT-")) return json({ error: "Invalid key" }, 400);
  const rec = await env.KV.get(`lic:${await sha256(key)}`, "json");
  if (!rec) return json({ error: "Unknown license key" }, 403);
  rec.machine_id = machine;
  rec.activated = new Date().toISOString();
  await env.KV.put(`lic:${await sha256(key)}`, JSON.stringify(rec));
  return json({ ok: true, email: rec.email, key });
}

async function download(url, env) {
  const key = String(url.searchParams.get("key") || "")
    .trim()
    .toUpperCase();
  const rec = key ? await env.KV.get(`lic:${await sha256(key)}`, "json") : null;
  if (!rec) return json({ error: "License required for download" }, 403);
  const name = url.searchParams.get("file") === "portable" ? "grok-orbit.exe" : "Grok Orbit_1.0.0_x64-setup.exe";
  if (env.DIST) {
    const obj = await env.DIST.get(name);
    if (obj) {
      return new Response(obj.body, {
        headers: {
          "Content-Type": "application/octet-stream",
          "Content-Disposition": `attachment; filename="${name}"`,
        },
      });
    }
  }
  if (env.DOWNLOAD_URL) return Response.redirect(env.DOWNLOAD_URL, 302);
  return json({ error: "Installer is not in the bucket yet." }, 404);
}

async function readEmail(request) {
  const body = await request.json().catch(() => ({}));
  const email = String(body.email || "").trim().toLowerCase();
  return EMAIL_RE.test(email) ? email : "";
}

function generateKey() {
  const seg = () => crypto.randomUUID().replace(/-/g, "").slice(0, 4).toUpperCase();
  return `ORBIT-${seg()}-${seg()}-${seg()}-${seg()}`;
}

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function sendMail(env, to, subject, text) {
  if (!env.EMAIL_TOKEN || !env.EMAIL_SEND_URL) return;
  const res = await fetch(env.EMAIL_SEND_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.EMAIL_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ to, subject, text }),
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(`email send failed: ${msg.slice(0, 180)}`);
  }
}

async function notifySale(env, email, stripeId, amountCents) {
  const to = String(env.NOTIFY_EMAIL || "").trim().toLowerCase();
  if (!EMAIL_RE.test(to)) return;
  if (stripeId) {
    const seen = await env.KV.get(`sold:${stripeId}`);
    if (seen) return;
  }
  const dollars =
    Number.isFinite(amountCents) && amountCents > 0
      ? `$${(amountCents / 100).toFixed(2)}`
      : "$19";
  const lines = [
    "[ORBIT] New Grok Orbit license purchase.",
    "",
    `Amount: ${dollars} one-time`,
    `Buyer: ${email}`,
  ];
  if (stripeId) lines.push(`Stripe session: ${stripeId}`);
  lines.push(`When: ${new Date().toISOString()}`);
  lines.push("");
  lines.push("Buyer already has their key by email. Reply to this mail if you want Grok to follow up.");
  try {
    await sendMail(env, to, `[ORBIT] Purchase ${dollars}`, lines.join("\n"));
    if (stripeId) {
      await env.KV.put(`sold:${stripeId}`, "1", { expirationTtl: 86400 * 90 });
    }
  } catch {
    /* do not fail key issue if operator mail fails */
  }
}

async function verifyStripeSignature(payload, header, secret) {
  const parts = Object.fromEntries(header.split(",").map((p) => p.split("=")));
  const ts = parts.t;
  const v1 = parts.v1;
  if (!ts || !v1) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signed = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${ts}.${payload}`));
  const expected = [...new Uint8Array(signed)].map((b) => b.toString(16).padStart(2, "0")).join("");
  return expected === v1;
}
