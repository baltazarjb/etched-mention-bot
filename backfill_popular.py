#!/usr/bin/env python3
"""
Backfill / audit the popular channel: what did the last N hours' mentions
actually score, and which would the channel surface?

Coverage goes well past the live monitor's keyword sweep:
  - QUOTE-TWEETS of @Etched's own recent posts (a viral quote of our
    announcement often never says "etched" in its own text)
  - QUOTES and REPLIES of the window's top real mentions (viral engagement
    with a mention usually doesn't repeat the brand word either)
  - bare-LINK posts the search matched: the linked article / X article is
    resolved and read before deciding, instead of being dropped
  - optional extra story queries via --q="..." (e.g. coverage of a raise that
    names the investor but not us) — the judge keeps precision

Every run prints a scored LEADERBOARD (top 40) so a human can audit the cut
line. Posting rules: score >= max(70, p95 of the window's real mentions), our
own posts never count, at most 2 posts per author, capped at 25 total, oldest
first. Anything not structurally certain goes through the Claude judge.

Touches NO state, so it can't affect the live tracker.

Usage: python backfill_popular.py [hours=48] [--dry] [--skip=id1,id2,...]
                                  [--q="extra query"] (repeatable)
"""

import sys, time, urllib.parse

import monitor as mon
import popular as pop

HOURS = next((float(a) for a in sys.argv[1:] if not a.startswith("-")), 48.0)
DRY = "--dry" in sys.argv
SKIP_IDS = set()
EXTRA_QUERIES = []
for a in sys.argv[1:]:
    if a.startswith("--skip="):
        SKIP_IDS.update(x.strip() for x in a[len("--skip="):].split(",") if x.strip())
    elif a.startswith("--q="):
        q = a[len("--q="):].strip()
        if q:
            EXTRA_QUERIES.append(q if "-filter:retweets" in q else q + " -filter:retweets")

FLOOR_FINAL = 70        # popular.py's 1h floor un-scaled to near-final engagement
MAX_POSTS = 25          # don't flood the channel even if the window went nuclear
MAX_PER_AUTHOR = 2      # a viral thread is one story, not three slots
QUOTE_SWEEP_OWN = 8     # our own posts whose quote-tweets get pulled
TRAVERSE_TOP = 12       # top real mentions whose quotes+replies get pulled
MAX_LINK_RESOLVES = 25  # over-bar link-only posts resolved per run

def own_handle(t):
    return ((t.get("author") or {}).get("userName") or "").lower()

def _paged(url_base, params, max_pages):
    out, cursor = [], ""
    for _ in range(max_pages):
        qs = urllib.parse.urlencode(dict(params, cursor=cursor))
        d = mon._get_json(f"{url_base}?{qs}", {"X-API-Key": mon.TWAPI_KEY})
        tws = d.get("tweets") or (d.get("replies") if isinstance(d.get("replies"), list) else None) or []
        out.extend(tws)
        if not d.get("has_next_page"):
            break
        cursor = d.get("next_cursor") or ""
        if not cursor:
            break
    return out

def quotes_of(tid, max_pages=3):
    return _paged("https://api.twitterapi.io/twitter/tweet/quotes", {"tweetId": tid}, max_pages)

def replies_of(tid, max_pages=2):
    return _paged("https://api.twitterapi.io/twitter/tweet/replies", {"tweetId": tid}, max_pages)

def judged_relevant(t, content=None):
    v = mon.judge(t, content)
    return bool(v and v.get("relevant") and float(v.get("confidence", 0) or 0) >= mon.CONF_ACCEPT)

def main():
    if not mon.TWAPI_KEY:
        print("FATAL: set TWAPI_KEY", file=sys.stderr)
        sys.exit(1)
    now = int(time.time())
    since = now - int(HOURS * 3600)

    # 1) keyword sweep (dedup by id)
    fetched = {}
    for q in mon.QUERIES + EXTRA_QUERIES:
        try:
            got = mon.search(q, since, max_pages=90)
            for t in got:
                tid = str(t.get("id"))
                if tid and tid not in fetched:
                    fetched[tid] = t
        except Exception as e:
            print(f"[search error] {q!r}: {e}", flush=True)
    print(f"[backfill] {len(fetched)} keyword candidates in the last {HOURS:.0f}h "
          f"({len(EXTRA_QUERIES)} extra queries)", flush=True)

    # 1b) structural sweep: quote-tweets of our own recent posts
    own = sorted((t for t in fetched.values() if own_handle(t) in mon.HANDLES),
                 key=pop.score_x, reverse=True)[:QUOTE_SWEEP_OWN]
    qt_new = 0
    for t in own:
        try:
            for q in quotes_of(str(t.get("id"))):
                qid = str(q.get("id"))
                if qid and qid not in fetched and own_handle(q) not in mon.HANDLES \
                        and pop.parse_created(q.get("createdAt") or "") >= since:
                    q["_tier"] = "Q"            # quotes our post -> a mention by construction
                    fetched[qid] = q
                    qt_new += 1
        except Exception as e:
            print(f"[quote sweep error] {t.get('id')}: {e}", flush=True)
    print(f"[backfill] +{qt_new} quote-tweets of our own posts ({len(own)} posts swept)", flush=True)

    # 2) tiers; the bar comes from THIS window's real mentions (own posts excluded)
    accepts, maybes, links = [], [], []
    for t in fetched.values():
        if own_handle(t) in mon.HANDLES:
            continue
        if t.get("_tier") == "Q":
            accepts.append(t)
            continue
        d, extra = mon.structural(t)
        if d == "accept":
            accepts.append(t)
        elif d == "maybe":
            maybes.append(t)
        elif d in ("fetch", "fetch_x"):
            t["_link"] = (extra[0] if extra else "")
            links.append(t)
    scores = [pop.score_x(t) for t in accepts]
    bar = float(FLOOR_FINAL)
    if len(scores) >= pop.MIN_BASELINE:
        bar = max(bar, float(pop.percentile(scores, pop.PCTL)))
    print(f"[backfill] accepts={len(accepts)} maybes={len(maybes)} links={len(links)} bar={bar:.0f}", flush=True)

    # 3) winners: accepts over the bar + judge-confirmed maybes over the bar
    winners = [t for t in accepts if pop.score_x(t) >= bar]
    judged = 0
    judged_in = set()
    for t in maybes:
        if pop.score_x(t) < bar:
            continue
        judged += 1
        if judged_relevant(t):
            winners.append(t)
            judged_in.add(str(t.get("id")))

    # 3b) over-bar link-only posts: read the link before deciding, never drop blind
    resolved = 0
    for t in sorted(links, key=pop.score_x, reverse=True):
        if pop.score_x(t) < bar or resolved >= MAX_LINK_RESOLVES:
            continue
        resolved += 1
        u = t.get("_link") or ""
        content = (mon.fetch_x_native_text(t, u) if (not u or mon._is_x_native(u))
                   else mon.fetch_url_text(u)[1])
        if content and (mon.ETCHED_WORD_RE.search(content) or mon.SOHU_WORD_RE.search(content)):
            judged += 1
            if judged_relevant(t, content):
                t["_tier"] = "L"
                winners.append(t)
                judged_in.add(str(t.get("id")))
    if resolved:
        print(f"[backfill] resolved {resolved} over-bar link posts", flush=True)

    # 3c) conversation sweep: quotes+replies of the top real mentions — viral
    #     engagement with a mention rarely repeats the brand word
    tops = sorted({str(t.get("id")): t for t in winners + accepts}.values(),
                  key=pop.score_x, reverse=True)[:TRAVERSE_TOP]
    kids_seen, kids_judged = 0, 0
    for parent in tops:
        pid = str(parent.get("id"))
        try:
            kids = quotes_of(pid, 2) + replies_of(pid, 2)
        except Exception as e:
            print(f"[conversation sweep error] {pid}: {e}", flush=True)
            continue
        for k in kids:
            kid = str(k.get("id"))
            if not kid or kid in fetched or own_handle(k) in mon.HANDLES:
                continue
            if pop.parse_created(k.get("createdAt") or "") < since:
                continue
            fetched[kid] = k
            kids_seen += 1
            if pop.score_x(k) < bar:
                continue
            if not k.get("quoted_tweet"):
                k["quoted_tweet"] = {"author": parent.get("author"), "text": parent.get("text")}
            kids_judged += 1
            if judged_relevant(k):
                k["_tier"] = "C"
                winners.append(k)
                judged_in.add(kid)
            maybes.append(k)         # either way, keep it visible on the leaderboard
    print(f"[backfill] conversation sweep: {kids_seen} children of top {len(tops)} "
          f"mentions, {kids_judged} judged", flush=True)

    winners.sort(key=pop.score_x, reverse=True)
    per_author, capped, dropped_author = {}, [], 0
    for t in winners:
        h = own_handle(t)
        if per_author.get(h, 0) >= MAX_PER_AUTHOR:
            dropped_author += 1
            continue
        per_author[h] = per_author.get(h, 0) + 1
        capped.append(t)
    winners = capped
    if dropped_author:
        print(f"[backfill] {dropped_author} dropped by the {MAX_PER_AUTHOR}/author cap", flush=True)
    if len(winners) > MAX_POSTS:
        print(f"[backfill] capping {len(winners)} winners -> top {MAX_POSTS} by score", flush=True)
        winners = winners[:MAX_POSTS]
    winner_ids = {str(t.get("id")) for t in winners}
    accept_ids = {str(t.get("id")) for t in accepts}

    # 4) the leaderboard — the audit trail for where the cut line landed
    pool = {str(t.get("id")): t for t in accepts + maybes + links}
    ranked = sorted(pool.values(), key=pop.score_x, reverse=True)[:40]
    print(f"\n{'':2} {'score':>6} {'❤':>6} {'RT':>5} {'👁':>7} {'foll':>7} {'age':>5}  tweet", flush=True)
    for t in ranked:
        tid = str(t.get("id"))
        a = t.get("author") or {}
        mark = "✓" if tid in winner_ids else (" " if pop.score_x(t) < bar else "·")
        tier = t.get("_tier") or ("A" if tid in accept_ids else ("L?" if t.get("_link") is not None else "B"))
        if tier == "B" and pop.score_x(t) >= bar and tid not in judged_in and tid not in winner_ids:
            tier = "b"      # judge said not-us (or judge unavailable)
        age_h = max(0.0, (now - pop.parse_created(t.get("createdAt") or "")) / 3600.0)
        txt = " ".join((t.get("text") or "").split())[:70]
        print(f"{mark:2} {pop.score_x(t):>6.0f} {pop._int(t.get('likeCount')):>6} "
              f"{pop._int(t.get('retweetCount')):>5} {pop._int(t.get('viewCount')):>7} "
              f"{pop._int(a.get('followers')):>7} {pop.fmt_age(age_h):>5} "
              f"[{tier}] @{a.get('userName')}: {txt}", flush=True)
    print("", flush=True)

    # 5) post, oldest first
    winners.sort(key=lambda t: pop.parse_created(t.get("createdAt") or ""))
    posted = 0
    for t in winners:
        tid = str(t.get("id"))
        a = t.get("author") or {}
        handle = a.get("userName") or "unknown"
        if tid in SKIP_IDS:
            print(f"  SKIP (already posted) @{handle}: {tid}", flush=True)
            continue
        rec = {"author": handle,
               "followers": pop._int(a.get("followers") or a.get("followersCount")),
               "url": t.get("url") or t.get("twitterUrl") or f"https://x.com/{handle}/status/{tid}"}
        age_h = max(0.0, (now - pop.parse_created(t.get("createdAt") or "")) / 3600.0)
        if DRY:
            print(f"  WOULD POST score={pop.score_x(t):.0f} @{handle}: {rec['url']}", flush=True)
            continue
        try:
            fb, blocks = pop.build_popular_msg(rec, t, age_h, note=f"backfill: last {HOURS:.0f}h")
            if pop.deliver(fb, blocks):
                posted += 1
            else:
                print("  [backfill] no destination configured; stopping", flush=True)
                break
        except Exception as e:
            print(f"  [backfill slack error] {e}", flush=True)
        time.sleep(1)
    print(f"[backfill] posted={posted} of {len(winners)} winners "
          f"(judged {judged} borderliners, bar {bar:.0f})", flush=True)

if __name__ == "__main__":
    main()
