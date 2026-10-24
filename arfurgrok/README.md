# @ArfurGrok post feed

Posts every new X post from [@ArfurGrok](https://x.com/ArfurGrok) ("anon simultaneously at every
tech company") to `#hiring-lab-departures`. Runs on GitHub Actions
(`.github/workflows/arfurgrok-monitor.yml`), started by a webhook within a few minutes of a post.

## How a run starts

```
twitterapi.io filter rule "from:ArfurGrok" (checks every 300 s)
  -> POST https://arfurgrok-relay.<account>.workers.dev/<PING_SECRET>   (relay/worker.js)
  -> GitHub repository_dispatch "arfurgrok-ping" with the post ids
  -> workflow runs monitor.py --search-only with PUSHED_IDS
```

- The rule lives at twitterapi.io/tweet-filter-rules; the webhook URL is the account-wide
  setting on that page. Each check bills the 15-credit minimum even when nothing matches
  (300 s = 288 checks/day ≈ 4.3k credits/day ≈ $1.30/month). Change the interval there.
- twitterapi.io gives the webhook 1 second and never retries, so the worker answers at once.
- The cron (every 2 hours) is only a backstop for a missed push. Don't tighten it: GitHub
  dropped ~94% of the old 15-minute schedule (it fired about 6 times a day), and each
  scheduled run calls the timeline, which bills ~20 posts (300 credits) every time.
- Webhook runs skip the timeline and fetch the pushed ids directly plus a search sweep
  (~30 credits a run).

Relay setup (Cloudflare dashboard → Workers): paste `relay/worker.js`, set the variable
`PING_SECRET` to a random string and the secret `GH_TOKEN` to a fine-grained GitHub token
limited to this repo with **Contents: read and write** (that is what `repository_dispatch` needs).

## What it posts

Everything the account publishes, labelled by kind:

| Kind | Header | Extra |
|---|---|---|
| original post | `X Post by @ArfurGrok` | first attached photo, if any |
| reply | `Reply by @ArfurGrok` | `↩️ replying to @who` context |
| quote post | `X Post by @ArfurGrok` | the quoted post nested underneath |
| repost | `🔁 @ArfurGrok reposted @who` | the reposted text; stats are the original's |

The message shape (bold header link, quoted text, `❤️ · 🔁 · 💬 · 👁 · followers` line) matches the
mention channels. Non-English posts are translated with the same Haiku call the other bots use.

There is no relevance judge: it is an account feed, so every post is relevant by definition.
`INCLUDE_RETWEETS` / `INCLUDE_REPLIES` at the top of `monitor.py` turn those kinds off.

## How it fetches

Two twitterapi.io sources, deduplicated by tweet id and against `state.json`:

- `/twitter/user/last_tweets?userId=2053001548335124480&includeReplies=true` — the account
  timeline (originals, replies, quotes and native reposts). Keyed by user id, so a handle
  rename can't break it.
- `/twitter/tweet/advanced_search` with `from:ArfurGrok since_time:<last run>` — a second sweep
  so one flaky endpoint can't drop a post.

If every source fails the run exits non-zero without touching state, so the next run retries the
same window. The first run looks back 24 hours; later runs fetch only what is new (plus a
3-minute overlap).

## Secrets and channel

Uses the repo's existing `TWAPI_KEY`, `SLACK_BOT_TOKEN` and `ANTHROPIC_API_KEY`. The channel id is
set in the workflow (`SLACK_MAIN_CHANNEL: C0C1QG37ZDZ`); the bot user must be a member of the
channel.

## Test

```bash
python3 -m py_compile monitor.py
python3 test_profiles.py                                   # offline: kinds + message shape
TWAPI_KEY=... SLACK_BOT_TOKEN=x SLACK_MAIN_CHANNEL=x python3 monitor.py --dry
```

From GitHub: Actions → "ArfurGrok post feed" → Run workflow with `extra` = `--dry` first.
