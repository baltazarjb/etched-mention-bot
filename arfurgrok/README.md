# @ArfurGrok post feed

Posts every new X post from [@ArfurGrok](https://x.com/ArfurGrok) ("anon simultaneously at every
tech company") to `#twitter-arfurgrok`. Runs every 15 minutes on GitHub Actions
(`.github/workflows/arfurgrok-monitor.yml`), same as the mention monitors.

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

If both sources fail the run exits non-zero without touching state, so the next run retries the
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
