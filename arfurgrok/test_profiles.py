#!/usr/bin/env python3
"""Fast, offline checks for the @ArfurGrok feed: kind detection, filtering, message shape."""
import json
import monitor as m

A = {"id": m.ACCOUNT_ID, "userName": "ArfurGrok", "followers": 6856}
OTHER = {"id": "42", "userName": "someone_else", "followers": 10}

def post(text, **kw):
    t = {"id": "1", "text": text, "author": A, "createdAt": "Wed Sep 10 17:04:12 +0000 2026",
         "likeCount": 1500, "retweetCount": 120, "replyCount": 33, "viewCount": 250000, "lang": "en"}
    t.update(kw); return t

orig  = post("Excited to announce I have joined Etched, Anthropic, OpenAI and Nvidia this morning.")
reply = post("@UbertiGavin yes", isReply=True, inReplyToUsername="UbertiGavin")
quo   = post("this but unironically",
             quoted_tweet={"id": "9", "text": "we are hiring", "author": OTHER, "url": "https://x.com/someone_else/status/9"})
rt    = post("RT @someone_else: the original words",
             retweeted_tweet={"id": "7", "text": "the original words, in full", "author": OTHER,
                              "likeCount": 9, "retweetCount": 2, "replyCount": 1, "viewCount": 100})
pic   = post("look", extendedEntities={"media": [{"type": "photo", "media_url_https": "https://pbs.twimg.com/media/x.jpg"}]})

for label, t, expected in [("original", orig, "original"), ("reply", reply, "reply"),
                           ("quote", quo, "quote"), ("retweet", rt, "retweet")]:
    assert m.kind_of(t) == expected, f"{label}: got {m.kind_of(t)}"

assert m.is_own(orig) and not m.is_own(post("x", author=OTHER))
assert m.created_epoch(orig) == 1789059852, m.created_epoch(orig)
assert m.created_epoch({"createdAt": "garbage"}) == 0

# messages: shape shared with the mention bots (section + context), plus an image block for photos
fb, bl = m.build_msg(orig)
assert bl[0]["type"] == "section" and bl[-1]["type"] == "context"
assert "X Post by @ArfurGrok" in bl[0]["text"]["text"] and "https://x.com/ArfurGrok/status/1" in fb
assert "❤️ 1.5k · 🔁 120 · 💬 33 · 👁 250k · 6.9k followers" in bl[-1]["elements"][-1]["text"]

fb, bl = m.build_msg(reply)
assert "Reply by @ArfurGrok" in bl[0]["text"]["text"]
assert bl[-1]["elements"][0]["text"] == "↩️ replying to @UbertiGavin"

fb, bl = m.build_msg(quo)
body = bl[0]["text"]["text"]
assert "quoting *<https://x.com/someone_else/status/9|@someone_else>*" in body and ">we are hiring" in body

fb, bl = m.build_msg(rt)
body = bl[0]["text"]["text"]
assert "🔁 @ArfurGrok reposted @someone_else" in body and ">the original words, in full" in body
assert "❤️ 9 · 🔁 2" in bl[-1]["elements"][-1]["text"], "repost stats must be the original's"

fb, bl = m.build_msg(pic)
assert [b["type"] for b in bl] == ["section", "image", "context"]

# filtering knobs
m.INCLUDE_RETWEETS = False
assert not m.wanted(rt) and m.wanted(orig)
m.INCLUDE_RETWEETS = True

json.dumps(bl)   # must be serialisable for chat.postMessage

# run wiring: which endpoints a run calls, with the network and Slack faked out
import os, sys, time
def at(epoch): return time.strftime("%a %b %d %H:%M:%S +0000 %Y", time.gmtime(epoch))
now = int(time.time())
calls, sent = [], []
def fake_get(url, headers, retries=4):
    calls.append(url.split("?")[0].rsplit("/", 1)[-1])
    if "/twitter/tweets" in url:   # a pushed post from before the window, not yet in search
        return {"tweets": [post("pushed", id="500", createdAt=at(now - 7200))]}
    if "last_tweets" in url:       # one new post, then 19 old ones: page 2 must not be fetched
        return {"tweets": [post("new", id="400", createdAt=at(now - 60))]
                          + [post("old", id=str(i), createdAt=at(now - 86400)) for i in range(19)],
                "has_next_page": True, "next_cursor": "c"}
    return {"tweets": []}
m._get_json = fake_get
m.send_main = lambda fb, bl: sent.append(fb)
m.save_state = lambda s: None
m.load_state = lambda: {"seen_ids": [], "last_run_epoch": now - 600}
m.TWAPI_KEY, m.SLACK_BOT_TOKEN, m.SLACK_MAIN_CHANNEL = "k", "x", "c"

sys.argv = ["monitor.py"]; m.main()
assert calls == ["last_tweets", "advanced_search"], calls
assert len(sent) == 1 and "/status/400" in sent[0], sent

calls.clear(); sent.clear()
os.environ["PUSHED_IDS"] = "500,not-an-id"
sys.argv = ["monitor.py", "--search-only"]; m.main()
assert calls == ["tweets", "advanced_search"], calls
assert len(sent) == 1 and "/status/500" in sent[0], "pushed post must post even if older than the window"
del os.environ["PUSHED_IDS"]

print("ArfurGrok profile checks passed")
