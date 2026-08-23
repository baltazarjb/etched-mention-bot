# Fractile mention bot

Posts new, relevant public X and LinkedIn mentions of **Fractile** to `#fractile-mentions`.
X runs every 15 minutes; LinkedIn runs hourly. Both jobs deduplicate posts, translate non-English
content, use a conservative relevance check, and hold unclear results for review rather than
polluting the main feed.

## What it monitors

- Fractile, `fractile.ai`, and Fractile’s AI-inference hardware.
- Walter Goodwin on sight; Pete Hughes and Chris Smith only alongside Fractile / AI-hardware
  context (common names never auto-post).

Every search query is anchored to the company — there is no topic-only monitoring
(“compute in memory”, SRAM, …), because those queries flooded the review thread with
unrelated industry posts. A post whose resolved content doesn’t name Fractile is dropped;
the review thread only gets links the bot genuinely could not read.

The classifier explicitly rejects statistical uses of “fractile” and the unrelated Fractile Labs.
No unverified X account is treated as Fractile’s official account.

## Required GitHub repository secrets

| Secret | Purpose |
|---|---|
| `TWAPI_KEY` | twitterapi.io API key |
| `APIFY_TOKEN` | Apify token for LinkedIn search |
| `SLACK_BOT_TOKEN` | Bot token; invite that bot to `#fractile-mentions` before running |
| `ANTHROPIC_API_KEY` | Optional but recommended relevance / translation judge |
| `SLACK_REVIEW_WEBHOOK_URL` | Optional destination for uncertain items |

The workflow already targets `#fractile-mentions` by channel ID. It posts with `SLACK_BOT_TOKEN`;
an incoming `SLACK_WEBHOOK_URL` is supported as an alternative. For a threaded review queue, also
provide `SLACK_REVIEW_CHANNEL` (or a `SLACK_REVIEW_WEBHOOK_URL`).

## Test and launch

```bash
python3 -m py_compile monitor.py linkedin.py
python3 test_profiles.py
TWAPI_KEY=... SLACK_WEBHOOK_URL=... python3 monitor.py --dry
APIFY_TOKEN=... SLACK_WEBHOOK_URL=... python3 linkedin.py --dry
```

Push to GitHub and enable the two Actions workflows. The initial X search looks back three hours;
the initial LinkedIn search uses a one-hour window. Neither posts during a `--dry` run.
