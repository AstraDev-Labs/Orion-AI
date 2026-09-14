# Telemetry

Orion is local-first. **It sends no usage analytics.** Analytics is
off, and Orion ships with no analytics server or key built in. The code
below only runs if you set up an endpoint of your own. This page documents
what it would collect in that case, and how to keep it off.

## TL;DR

- **Off by default, with no built-in destination.** Nothing is sent
  unless you set `[analytics] enabled = true` *and* your own `host` and
  `key` (or `OPENORION_ANALYTICS_HOST` / `OPENORION_ANALYTICS_KEY` for
  `install.sh`).
- If you do enable it: anonymous (one random UUID per install, no
  email, name or IP), and **no chat content, ever**, only counts,
  timings and feature names.
- The opt-in savings leaderboard likewise has no built-in database; it
  does nothing unless a build sets `VITE_SUPABASE_URL` and
  `VITE_SUPABASE_ANON_KEY`.

The rest of this page describes the event catalogue and safeguards for
anyone who turns analytics on for their own deployment.

## What we collect

### Lifecycle events

| Event | Source | Why we send it |
|---|---|---|
| `install_started` | `install.sh` | Top of install funnel |
| `install_stage_completed` | `install.sh` | Per-stage timing — where do people drop off? |
| `install_completed` | `install.sh` | Did the install succeed? |
| `install_failed` | `install.sh` | Which stage failed, and on what OS |
| `app_opened` | Backend + frontend | DAU / WAU / MAU |
| `setup_completed` | Frontend | First-run wizard finished |
| `first_chat_sent` | Backend | First-ever message — activation |
| `uninstall_started` | `uninstall.sh` (if user runs it) | Churn signal |

### Usage events

| Event | Why we send it |
|---|---|
| `chat_session_ended` | Aggregated per-session: turn count, tokens, latency, tool count |
| `tool_first_used` | Which built-in tools are actually adopted |
| `model_changed` | How often users switch models |
| `feature_used` | Which features get traffic, which don't |
| `connector_auth_completed` | Which connectors people set up |
| `error_shown_to_user` | User-visible error class (not stack trace) |
| `feedback_submitted` | Was a rating given? Was a comment included? |
| `settings_changed` | Which settings get toggled |
| `usage_daily_summary` | Once-per-day aggregated counts |

The canonical, authoritative list with every property name and its
type validator lives in
[`src/orion/analytics/events.py`](../src/orion/analytics/events.py).
That file is the only place new events can be added — PR review is
the gate.

## What we never collect

Hard guardrails, enforced by code:

- **Chat content** — prompts, model outputs, system messages, tool args.
- **File paths** — anything matching `~/`, `$HOME`, `/Users/<name>`, `/home/<name>`, `file://`.
- **Emails, names, phone numbers, addresses.**
- **IP addresses** (IPv4 + IPv6). PostHog's IP geo lookup is disabled server-side too.
- **MAC addresses, hardware serials, drive UUIDs.**
- **Stack traces** — only error class enums.
- **API keys, OAuth tokens, JWTs, bearer tokens, password assignments** —
  matched and dropped at value level.
- **Hostnames** that look personal (e.g. `alice-macbook.local`).
- **Lists, dicts, sets** — composite values are never sent so PII can't
  smuggle through inside containers.

Two independent filters run before every event leaves the machine:

1. [`src/orion/analytics/redaction.py`](../src/orion/analytics/redaction.py) — value-level pattern matching (20+ regexes for PII).
2. [`src/orion/analytics/events.py`](../src/orion/analytics/events.py) — structural allowlist (event name + property name + type validator).

Any failure at either layer → the event or property is silently
dropped. Tests covering the patterns: [`tests/analytics/test_redaction.py`](../tests/analytics/test_redaction.py).

## Where the data goes

- **Nowhere, by default.** Orion has no analytics server. Events go only
  to the PostHog `host` you configure yourself.

## Opting out

Three independent ways to disable analytics — any one is sufficient:

1. **Set an env var** (no config file edit needed):
   ```bash
   export DO_NOT_TRACK=1            # W3C convention, honored by other tools too
   # or
   export OPENORION_NO_ANALYTICS=1 # project-specific, leaves other DNT-aware tools unaffected
   ```
   Both are checked at runtime; any truthy value (`1`, `true`, `yes`,
   `on`) disables analytics for that process. Truthy = anything other
   than empty, `0`, `false`, `no`, `off`.

2. **Edit `~/.orion/config.toml`**:
   ```toml
   [analytics]
   enabled = false
   ```

3. **Delete the anon ID** (`rm ~/.orion/anon_id`) — events for
   the prior identity are orphaned, but a new identity will be
   created on the next run. Combine with #1 or #2 to fully stop.

Env-var opt-out takes precedence over the config file, so setting
`DO_NOT_TRACK=1` overrides `enabled = true` in the config.

## Retention

- Default retention: **365 days**, then events are deleted by PostHog
  automatically.
- `orion analytics reset-id` lets you orphan all of your past events
  by generating a fresh anonymous ID for future events.

## How identity works

A single UUID v4 is generated on first install and stored at
`~/.orion/anon_id`. The install script, backend, and frontend all
read the same file so events across the full lifecycle tie to one
person — without us ever knowing who that person is.

Delete the file (`rm ~/.orion/anon_id`) and a fresh UUID will be
generated next time the app runs. The previous UUID and its events
are then orphaned.

## For researchers and contributors

- **Adding an event**: edit `src/orion/analytics/events.py`,
  declare the spec, then update this page. PR review enforces both.
- **Adding a PII pattern**: edit `src/orion/analytics/redaction.py`
  and add a test case in `tests/analytics/test_redaction.py`.
- **Inspecting what your install sends**: run with
  `OPENORION_LOG_LEVEL=DEBUG` and grep for `Analytics`. You'll see
  every event name and (redacted) property dict before it ships.

## Related

- Local telemetry (FLOPs, energy, latency stored in
  `~/.orion/telemetry.db`) is a **separate** subsystem documented
  in [`src/orion/telemetry/`](../src/orion/telemetry/). It
  never leaves the machine and is controlled by `[telemetry]` (not
  `[analytics]`) in `config.toml`.
- The leaderboard / contest opt-in (`OptInModal.tsx`) is a separate,
  voluntary feature that publicly shares your energy and savings on
  the Orion leaderboard. It is **not** the same as analytics and
  requires explicit opt-in with a display name and email.
