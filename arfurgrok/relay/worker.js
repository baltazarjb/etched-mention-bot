// @ArfurGrok webhook relay (Cloudflare Worker)
// =============================================
// twitterapi.io runs the filter rule `from:ArfurGrok` on an interval and POSTs any match
// here. It can't call GitHub itself (no way to add an Authorization header), so this
// turns the push into a repository_dispatch; the workflow then runs monitor.py, which
// does the formatting, dedup and Slack post exactly like a scheduled run.
//
// twitterapi.io gives the webhook 1 second and never retries, so answer at once and
// fire the dispatch in the background.
//
// Worker settings:
//   PING_SECRET  (variable) random string; the webhook URL is https://<worker>/<PING_SECRET>
//   GH_TOKEN     (secret)   fine-grained token, this repo only, Contents: read and write
const REPO = "baltazarjb/etched-mention-bot";
const EVENT = "arfurgrok-ping";

export default {
  async fetch(req, env, ctx) {
    const path = new URL(req.url).pathname;
    if (!env.PING_SECRET || req.method !== "POST" || path !== `/${env.PING_SECRET}`) {
      return new Response("not found", { status: 404 });
    }
    let body = {};
    try { body = await req.json(); } catch {}
    const ids = (Array.isArray(body.tweets) ? body.tweets : [])
      .map((t) => String((t && t.id) || ""))
      .filter((id) => /^\d+$/.test(id));
    // the dashboard's Test button sends event_type=test_webhook_url and no tweets
    if (ids.length) ctx.waitUntil(dispatch(env, ids.slice(0, 50).join(",")));
    return new Response("ok");
  },
};

async function dispatch(env, ids) {
  const r = await fetch(`https://api.github.com/repos/${REPO}/dispatches`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "arfurgrok-relay",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ event_type: EVENT, client_payload: { ids } }),
  });
  console.log(`dispatch ${ids} -> ${r.status}`, r.ok ? "" : await r.text());
}
