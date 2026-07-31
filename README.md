# MatX mention bot

Posts new, relevant public X and LinkedIn mentions of **MatX** to `#matx-mentions`.
X runs every 15 minutes; LinkedIn runs hourly. Both jobs deduplicate posts, translate non-English
content, use a conservative relevance check, and hold unclear results for review rather than
polluting the main feed.

## What it monitors

- MatX, `matx.com`, and the MatX One chip.
- Relevant references to founders Reiner Pope and Mike Gunter.
- MatX’s LLM hardware context: SRAM-resident weights, HBM KV cache, systolic arrays, throughput,
  low latency, training, RL, and inference.

The judge excludes the unrelated Israeli manufacturing accelerator MatX (`matx-il.com`). No
unverified X account is treated as MatX’s official account.

## Required GitHub repository secrets

| Secret | Purpose |
|---|---|
| `TWAPI_KEY` | twitterapi.io API key |
| `APIFY_TOKEN` | Apify token for LinkedIn search |
| `SLACK_BOT_TOKEN` | Bot token; invite that bot to `#matx-mentions` before running |
| `ANTHROPIC_API_KEY` | Optional but recommended relevance / translation judge |
| `SLACK_REVIEW_WEBHOOK_URL` | Optional destination for uncertain items |

The workflow already targets `#matx-mentions` by channel ID. It posts with `SLACK_BOT_TOKEN`;
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
