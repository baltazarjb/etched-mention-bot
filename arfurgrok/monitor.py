#!/usr/bin/env python3
"""
@ArfurGrok post feed
====================
Posts every new X post from @ArfurGrok (https://x.com/ArfurGrok) to Slack.
Designed to run on a schedule (GitHub Actions). Stateless except for state.json.

Unlike the mention monitors (fractile/, matx/, ../monitor.py) this is an ACCOUNT feed:
everything the account publishes is relevant by definition, so there is no
tiered classifier and no Claude judge. What it does share with them:

  - the same twitterapi.io data source and state.json / seen_ids bookkeeping
  - the same Slack Block Kit message shape (header link, quoted text, stats line)
  - the same Haiku translation step for non-English posts (the account posts in
    English, so this is a no-op in practice)

Sources (deduped by tweet id):
  /twitter/user/last_tweets?userId=…&includeReplies=true   the account timeline —
        originals, replies, quotes and native retweets, newest first
  /twitter/tweet/advanced_search  from:ArfurGrok since_time:…  second sweep, so a
        timeline hiccup can't drop a post; also fills in the since_time window

Every post is labelled by kind so the channel reads naturally:
  original       -> "X Post by @ArfurGrok"
  reply          -> "Reply by @ArfurGrok"  + "↩️ replying to @who" context
  quote          -> "X Post by @ArfurGrok" + the quoted post nested below
  native retweet -> "🔁 @ArfurGrok reposted @who" + the reposted text

Required env:
  TWAPI_KEY            twitterapi.io API key
  SLACK_BOT_TOKEN + SLACK_MAIN_CHANNEL   (or SLACK_WEBHOOK_URL)  where to post
Optional env:
  ANTHROPIC_API_KEY    enables translation of non-English posts (same model as the judges)

Run `python3 monitor.py --dry` to print what WOULD be posted without sending or saving.
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ------------------------------------------------------------------ config
TWAPI_KEY     = os.environ.get("TWAPI_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SLACK_MAIN    = os.environ.get("SLACK_WEBHOOK_URL", "")
SLACK_BOT_TOKEN    = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_MAIN_CHANNEL = os.environ.get("SLACK_MAIN_CHANNEL", "")

# The account. userId is what twitterapi.io recommends (stable across renames);
# the handle is kept for the search sweep, display and the fallback URL.
ACCOUNT_HANDLE = "ArfurGrok"
ACCOUNT_ID     = "2053001548335124480"

TIMELINE_BASE = "https://api.twitterapi.io/twitter/user/last_tweets"
SEARCH_BASE   = "https://api.twitterapi.io/twitter/tweet/advanced_search"
TRANSLATE_MODEL = "claude-haiku-4-5-20251001"
STATE_FILE  = os.path.join(os.path.dirname(__file__), "state.json")

FIRST_RUN_LOOKBACK_HOURS = 24   # the very first run seeds the channel with the last day
OVERLAP_SECONDS = 180           # re-scan a little of the previous window (seen_ids dedups)
TIMELINE_MAX_PAGES = 5          # 20 posts/page; the account posts a handful a day
SEARCH_MAX_PAGES   = 15
INCLUDE_RETWEETS = True         # native reposts ARE posts the account chose to share
INCLUDE_REPLIES  = True

# ------------------------------------------------------------------ http helpers
def _get_json(url, headers, retries=4):
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1)); continue
            raise
        except Exception:
            if attempt == retries - 1: raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("retries exhausted: " + url)

def _post_json(url, payload, headers=None, retries=4):
    body = json.dumps(payload).encode()
    hdr = {"Content-Type": "application/json"}
    if headers: hdr.update(headers)
    req = urllib.request.Request(url, data=body, headers=hdr, method="POST")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(1.5 * (attempt + 1)); continue
            raise
        except Exception:
            if attempt == retries - 1: raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("retries exhausted: POST " + url)

# ------------------------------------------------------------------ twitterapi.io
def _tweets_of(d):
    return d.get("tweets") or (d.get("data", {}) or {}).get("tweets") or []

def created_epoch(t):
    """createdAt is Twitter's classic 'Wed Sep 10 17:04:12 +0000 2026'. Returns 0 if unparseable."""
    s = t.get("createdAt") or ""
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return int(datetime.datetime.strptime(s.replace("Z", "+0000"), fmt).timestamp())
        except ValueError:
            continue
    return 0

def timeline(since_epoch, max_pages=TIMELINE_MAX_PAGES):
    """Newest-first account timeline; stop once a page is entirely older than since_epoch."""
    out, cursor, pages = [], "", 0
    while pages < max_pages:
        qs = urllib.parse.urlencode({"userId": ACCOUNT_ID, "cursor": cursor,
                                     "includeReplies": "true" if INCLUDE_REPLIES else "false"})
        d = _get_json(f"{TIMELINE_BASE}?{qs}", {"X-API-Key": TWAPI_KEY})
        tweets = _tweets_of(d)
        if not tweets: break
        out.extend(tweets)
        pages += 1
        # timelines can pin an old post to the top, so judge the page by its newest post
        newest = max((created_epoch(t) for t in tweets), default=0)
        if newest and newest < since_epoch: break
        if not d.get("has_next_page"): break
        cursor = d.get("next_cursor") or ""
        if not cursor: break
    return out

def search(since_epoch, max_pages=SEARCH_MAX_PAGES):
    out, cursor, pages = [], "", 0
    full_q = f"from:{ACCOUNT_HANDLE} since_time:{since_epoch}"
    while pages < max_pages:
        qs = urllib.parse.urlencode({"query": full_q, "queryType": "Latest", "cursor": cursor})
        d = _get_json(f"{SEARCH_BASE}?{qs}", {"X-API-Key": TWAPI_KEY})
        tweets = _tweets_of(d)
        if not tweets: break
        out.extend(tweets)
        pages += 1
        if not d.get("has_next_page"): break
        cursor = d.get("next_cursor") or ""
        if not cursor: break
    return out

def author_of(sub):
    if isinstance(sub, dict):
        a = sub.get("author")
        if isinstance(a, dict): return (a.get("userName") or "")
    return ""

def is_own(t):
    """Timeline pages only contain the account's posts, but the search sweep is a
    query and a defensive check costs nothing."""
    a = t.get("author") or {}
    return (str(a.get("id") or "") == ACCOUNT_ID
            or (a.get("userName") or "").lower() == ACCOUNT_HANDLE.lower())

def kind_of(t):
    """original | reply | quote | retweet"""
    if isinstance(t.get("retweeted_tweet"), dict) and t["retweeted_tweet"]:
        return "retweet"
    if (t.get("text") or "").startswith("RT @") and not t.get("quoted_tweet"):
        return "retweet"
    if t.get("isReply") or t.get("inReplyToUsername") or t.get("inReplyToId"):
        return "reply"
    if isinstance(t.get("quoted_tweet"), dict) and t["quoted_tweet"]:
        return "quote"
    return "original"

def wanted(t):
    k = kind_of(t)
    if k == "retweet" and not INCLUDE_RETWEETS: return False
    if k == "reply" and not INCLUDE_REPLIES: return False
    return True

def photos(t):
    """First photo URL attached to the post (or its reposted/quoted post), if any."""
    for sub in (t, t.get("retweeted_tweet"), t.get("quoted_tweet")):
        if not isinstance(sub, dict): continue
        ents = sub.get("extendedEntities") or sub.get("extended_entities") or {}
        for m in (ents.get("media") or []):
            if (m.get("type") or "") == "photo":
                u = m.get("media_url_https") or m.get("media_url")
                if u: return u
    return None

# ------------------------------------------------------------------ translation
# Twitter lang codes that mean "no real language" (media-only, undetermined, art)
NO_LANG = {"", "en", "und", "zxx", "qme", "qam", "qst", "qht", "art"}

def tweet_needs_translation(t):
    return (t.get("lang") or "").lower() not in NO_LANG

def translate(text):
    """Translate a non-English post to English via Haiku. Returns
    {"language": "Spanish", "translation": "..."} or None (already English / call failed)."""
    if not ANTHROPIC_KEY or not text:
        return None
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"is_english": {"type": "boolean"},
                             "language": {"type": "string"},
                             "translation": {"type": "string"}},
              "required": ["is_english", "language", "translation"]}
    system = ("You translate social-media posts to English for a media-monitoring bot. "
              "Report the source language by its English name (e.g. 'Spanish', 'Japanese') and "
              "translate the post faithfully and naturally, keeping @handles, #hashtags, URLs, "
              "ticker symbols and emoji as they are. If the post is already English or has no "
              "real text, set is_english=true and translation to an empty string.")
    payload = {"model": TRANSLATE_MODEL, "max_tokens": 1200, "system": system,
               "messages": [{"role": "user", "content": text[:2500]}],
               "output_config": {"format": {"type": "json_schema", "schema": schema}}}
    try:
        raw = _post_json("https://api.anthropic.com/v1/messages", payload,
                         headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"})
        data = json.loads(raw)
        out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        v = json.loads(out)
        if v.get("is_english") or not (v.get("translation") or "").strip():
            return None
        return {"language": (v.get("language") or "another language").strip(),
                "translation": v["translation"].strip()}
    except Exception as e:
        print(f"  [translate error] {e}", flush=True)
        return None

# ------------------------------------------------------------------ slack
def fmt_count(n):
    try: n = int(n or 0)
    except (TypeError, ValueError): return str(n)
    if n >= 1_000_000: return (f"{n/1_000_000:.1f}".rstrip("0").rstrip(".")) + "M"
    if n >= 1_000:     return (f"{n/1_000:.1f}".rstrip("0").rstrip(".")) + "k"
    return str(n)

def quote(text):
    """Slack-quote every line, not just the first."""
    return "\n>".join(text.splitlines())

def _clean(txt, limit=700):
    txt = (txt or "").strip()
    if len(txt) > limit: txt = txt[:limit - 3] + "..."
    return txt

def _url_of(t, handle):
    return t.get("url") or t.get("twitterUrl") or f"https://x.com/{handle}/status/{t.get('id')}"

def build_msg(t):
    """Same shape as the mention bots: bold header link, quoted text, stats context line.
    Returns (fallback_text, blocks)."""
    kind = kind_of(t)
    author = (t.get("author") or {})
    handle = author.get("userName") or ACCOUNT_HANDLE
    followers = author.get("followers") or author.get("followersCount") or 0
    url = _url_of(t, handle)

    txt = (t.get("text") or "").strip()
    sub_header, sub_text, ctx_note = None, None, None

    if kind == "retweet":
        rt = t.get("retweeted_tweet") or {}
        rt_handle = author_of(rt) or (re.match(r"RT @([A-Za-z0-9_]{1,15})", txt) or [None, "unknown"])[1]
        header = f"*<{url}|🔁 @{handle} reposted @{rt_handle}>*"
        # the RT's own text is "RT @x: …" — show the original post's full text instead
        txt = (rt.get("text") or re.sub(r"^RT @[A-Za-z0-9_]+:\s*", "", txt)).strip()
        # engagement belongs to the original post, not the repost
        stats_src = rt if rt else t
        fb = f"@{handle} reposted @{rt_handle}: {url}"
    else:
        label = "Reply by" if kind == "reply" else "X Post by"
        header = f"*<{url}|{label} @{handle}>*"
        stats_src = t
        fb = f"{label} @{handle}: {url}"
        if kind == "reply":
            to = t.get("inReplyToUsername") or ""
            ctx_note = f"↩️ replying to @{to}" if to else "↩️ reply"
        if kind == "quote":
            q = t.get("quoted_tweet") or {}
            sub_header = f"↪ quoting *<{_url_of(q, author_of(q) or 'i')}|@{author_of(q) or 'unknown'}>*"
            sub_text = _clean(q.get("text"), 400)

    tlabel = None
    if txt and tweet_needs_translation(t):
        tr = translate(txt)
        if tr:
            txt = tr["translation"]
            tlabel = f":globe_with_meridians: Translated from {tr['language']}"
    txt = _clean(txt)
    if not txt: txt = "_(no text — media or link only)_"

    likes = stats_src.get("likeCount", 0); rts = stats_src.get("retweetCount", 0)
    views = stats_src.get("viewCount", 0); replies = stats_src.get("replyCount", 0)
    stats = (f"❤️ {fmt_count(likes)} · 🔁 {fmt_count(rts)} · 💬 {fmt_count(replies)} · 👁 {fmt_count(views)}"
             f" · {fmt_count(followers)} followers")

    body = f"{header}\n>{quote(txt)}"
    if sub_header:
        body += f"\n{sub_header}"
        if sub_text: body += f"\n>{quote(sub_text)}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]
    pic = photos(t)
    if pic:
        blocks.append({"type": "image", "image_url": pic, "alt_text": f"image from @{handle}"})
    ctx = ([{"type": "mrkdwn", "text": ctx_note}] if ctx_note else []) \
        + ([{"type": "mrkdwn", "text": tlabel}] if tlabel else []) \
        + [{"type": "mrkdwn", "text": stats}]
    blocks.append({"type": "context", "elements": ctx})
    return fb, blocks

def slack_webhook(webhook, fallback, blocks):
    _post_json(webhook, {"text": fallback, "blocks": blocks, "unfurl_links": False})

def slack_api(token, channel, fallback, blocks):
    payload = {"channel": channel, "text": fallback, "blocks": blocks,
               "unfurl_links": False, "unfurl_media": False}
    raw = _post_json("https://slack.com/api/chat.postMessage", payload,
                     headers={"Authorization": f"Bearer {token}"})
    d = json.loads(raw)
    if not d.get("ok"):
        print(f"  [slack api error] {d.get('error')}", flush=True); return None
    return d.get("ts")

def send_main(fallback, blocks):
    """Deliver through an incoming webhook or directly through the Slack bot."""
    if SLACK_MAIN:
        return slack_webhook(SLACK_MAIN, fallback, blocks)
    if SLACK_BOT_TOKEN and SLACK_MAIN_CHANNEL:
        return slack_api(SLACK_BOT_TOKEN, SLACK_MAIN_CHANNEL, fallback, blocks)
    raise RuntimeError("set SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN + SLACK_MAIN_CHANNEL")

# ------------------------------------------------------------------ state
def load_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except Exception:
        return {"seen_ids": [], "last_run_epoch": 0}

def save_state(state):
    state["seen_ids"] = state["seen_ids"][-8000:]
    with open(STATE_FILE, "w") as f: json.dump(state, f, indent=1)

# ------------------------------------------------------------------ main
def main():
    if not TWAPI_KEY or not (SLACK_MAIN or (SLACK_BOT_TOKEN and SLACK_MAIN_CHANNEL)):
        print("FATAL: set TWAPI_KEY and either SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN + SLACK_MAIN_CHANNEL",
              file=sys.stderr); sys.exit(1)
    dry = "--dry" in sys.argv

    state = load_state()
    seen = set(state.get("seen_ids", []))
    now = int(time.time())
    first_run = not state.get("last_run_epoch")
    since = state.get("last_run_epoch", 0) or (now - FIRST_RUN_LOOKBACK_HOURS * 3600)
    since = max(0, since - OVERLAP_SECONDS)

    # 1) gather from both sources, dedup by id, keep only this account's new posts
    fetched, errors = {}, 0
    for name, fn in (("timeline", timeline), ("search", search)):
        try:
            got = fn(since)
            n_new = 0
            for t in got:
                tid = str(t.get("id") or "")
                if not tid or tid in seen or tid in fetched: continue
                if not is_own(t): continue
                if created_epoch(t) and created_epoch(t) < since: continue   # old post on a timeline page
                fetched[tid] = t; n_new += 1
            print(f"[{name}] {len(got)} fetched, {n_new} new", flush=True)
        except Exception as e:
            errors += 1
            print(f"[{name} error] {e}", flush=True)
    if errors == 2:
        print("FATAL: both sources failed; leaving state untouched so the next run retries", file=sys.stderr)
        sys.exit(1)

    to_post = [t for t in fetched.values() if wanted(t)]
    skipped = len(fetched) - len(to_post)
    print(f"[gather] {len(fetched)} new post(s) since {since}"
          f"{' (first run)' if first_run else ''}; posting {len(to_post)}, filtered {skipped}", flush=True)

    # 2) deliver, oldest first
    def keyf(t): return (created_epoch(t), t.get("id") or "")
    posted = 0
    for t in sorted(to_post, key=keyf):
        k = kind_of(t)
        if dry:
            print(f"  [{k:8}] {(t.get('text') or '')[:100]!r}  {_url_of(t, ACCOUNT_HANDLE)}", flush=True)
            continue
        try:
            fb, bl = build_msg(t); send_main(fb, bl); posted += 1
        except Exception as e:
            print(f"  [slack error] {e}", flush=True)

    # 3) persist (everything fetched counts as seen, including filtered kinds)
    seen.update(fetched.keys())
    state["seen_ids"] = list(seen)
    state["last_run_epoch"] = now
    if not dry: save_state(state)
    print(f"[done] {'would post' if dry else 'posted'}={len(to_post) if dry else posted}", flush=True)

if __name__ == "__main__":
    main()
