# redditctl

`redditctl` is a proposed CLI and terminal UI for managing a Reddit presence from one place. It is designed to help an individual understand how their posts perform, measure outbound link clicks, find communities where a post genuinely belongs, draft rule-aware submissions with an LLM, and schedule posts or follow-up updates.

> [!IMPORTANT]
> This repository currently contains the product specification only. The commands and screens below describe the intended interface; they are not implemented yet.

`redditctl` is an independent project and is not affiliated with, endorsed by, or operated by Reddit.

## What it should do

- Show posts and comments in sortable tables with scores, comments, age, subreddit, and locally collected metrics.
- Record metric snapshots so trends can be viewed over time rather than only as current totals.
- Create first-party redirect links and report aggregate clicks without fingerprinting readers.
- Suggest suitable subreddits based on topic fit, rules, posting requirements, and the author's preferences.
- Draft and revise posts with an LLM using a cited snapshot of the target subreddit's rules.
- Explain potential rule conflicts before anything is submitted.
- Schedule posts, space similar submissions apart, and plan edits or follow-up comments on existing threads.
- Keep every publish, edit, and delete action visible and confirmable by default.

## Product principles

1. **Fit before reach.** Recommendations should favor relevant communities, not merely large ones.
2. **Rules are inputs, not fine print.** A draft is tied to the rule snapshot used to create it.
3. **The human publishes.** LLM output is a draft, and automation is explicit, reviewable, and reversible where Reddit permits.
4. **No spam machinery.** Rate limits, duplicate detection, cooldowns, and subreddit-specific policies are product features.
5. **Local first.** Credentials, drafts, schedules, and analytics stay on the user's machine unless a configured service is required.
6. **Honest analytics.** Click counts are aggregate measurements with documented limits, not invasive reader tracking.

The longer product rationale is in [VISION.md](VISION.md). The proposed implementation baseline is in [MVP_DESIGN.md](MVP_DESIGN.md).

## Proposed experience

Launch the terminal UI:

```console
$ redditctl
```

Or use composable commands:

```console
# Review recent submissions by score, comments, or click-through rate
$ redditctl posts list --since 30d --sort score
$ redditctl posts list --sort ctr --format json

# Inspect a post and its metric history
$ redditctl posts show t3_abc123
$ redditctl metrics watch t3_abc123

# Find communities that fit a topic or draft
$ redditctl discover "self-hosted photo backup for families"
$ redditctl discover --from draft.md --exclude-subreddit selfpromotion

# Fetch rules and prepare a rule-aware draft
$ redditctl rules sync r/DataHoarder
$ redditctl draft new --subreddit DataHoarder --from notes.md
$ redditctl draft check draft-018

# Review before publishing now or later
$ redditctl publish draft-018 --dry-run
$ redditctl schedule add draft-018 --at "2026-09-03 10:00 America/Toronto"
$ redditctl schedule list

# Plan a permitted update to an existing thread
$ redditctl update plan t3_abc123 --edit-body update.md --at "+2 days"
$ redditctl update plan t3_abc123 --comment follow-up.md --at "+1 week"

# Make a measurable, shareable link
$ redditctl links create https://example.com/launch --slug launch-notes
$ redditctl links stats launch-notes --since 7d
```

### TUI outline

```text
┌ redditctl ──────────────────────────────────────────────────────────┐
│ Overview  Posts  Drafts  Discover  Schedule  Links  Rules  Settings│
├─────────────────────────────────────────────────────────────────────┤
│ Post                         Subreddit      Score  Replies  Clicks  │
│ Building a quiet home server r/homelab       184       31      92  │
│ Backup lessons after 1 year  r/DataHoarder    73       18      41  │
│                                                                  ▲ │
├─────────────────────────────────────────────────────────────────────┤
│ score +27/24h · replies +6/24h · 4 scheduled actions · 1 warning  │
└─────────────────────────────────────────────────────────────────────┘
```

Keyboard-driven navigation, command parity, accessible colors, and a non-interactive JSON output mode are all intended requirements. The TUI should never be the only way to perform an operation.

## Core workflows

### Review performance

The app periodically stores snapshots of fields available to the authenticated account and combines them with locally owned click data. Views should support:

- sorting and filtering by subreddit, post type, age, score, replies, clicks, and click-through rate;
- comparing performance at equivalent ages, such as the first hour or first day;
- distinguishing values reported by Reddit from values measured by `redditctl`;
- CSV and JSON export;
- clear gaps when the app was offline or a metric was unavailable.

Historical charts are only as complete as the snapshots collected. `redditctl` must not invent missing observations or imply that score is a precise vote count.

### Measure link clicks

Reddit post data alone may not provide the outbound click detail a user wants. The proposed link service uses a redirect URL on a domain the user controls:

```text
reader -> https://go.example.com/launch-notes -> https://example.com/launch
```

The redirect records only the minimum needed for aggregate reporting: timestamp, link ID, and an optional coarse referrer classification. Raw IP addresses and full user-agent strings should not be retained. Bot filtering, retention, and the fact that redirects are being used must be documented.

The redirect component is optional. It can run locally for development, on the user's infrastructure, or through a future hosted companion. Direct destination links continue to work without analytics.

### Discover suitable subreddits

Discovery should combine public community information with user-supplied context. A recommendation includes:

- a plain-language explanation of topical fit;
- relevant rules with source links and retrieval times;
- known format, flair, account-age, karma, or approval requirements;
- evidence from representative recent discussions;
- activity and likely audience, without treating size as quality;
- uncertainty and a reason to exclude a community when appropriate.

The user can tune preferences such as promotional tolerance, community size, language, geography, NSFW exclusion, and communities to always exclude. Discovery is decision support, not an invitation to broadcast the same post everywhere.

### Draft with an LLM

A draft request packages the user's notes, target community, desired post type, tone, and a timestamped rules snapshot. The result should contain:

- title and body variants;
- suggested flair and required disclosures;
- a rule-by-rule check with citations;
- assumptions or claims that need the author's verification;
- a diff when revising an existing draft.

Foundation-model providers are adapters. The MVP uses the Gemini API through Google's installed-application OAuth flow because it offers a supported browser login without reusing private web-session credentials. Before each request, `redditctl` shows which account/provider is active and what draft, rules, and account context will leave the machine. Secrets must never be inserted into prompts or logs. Claude and OpenAI adapters may follow behind the same interface, using only authentication methods their providers officially support.

Passing an automated check does not guarantee moderator acceptance. Rules can be incomplete, ambiguous, or changed after synchronization, so `redditctl` should re-check them shortly before publication and stop on material changes.

### Schedule responsibly

The scheduler stores intended actions locally and executes them only while a worker is running. It should support:

- one-time publication at an absolute time with an explicit time zone;
- minimum spacing between posts globally and per subreddit;
- configurable quiet hours and randomized windows;
- a final rule and eligibility check before submission;
- dry runs, approval queues, retries with bounded backoff, and an audit log;
- scheduled self-post body edits or follow-up comments when the post type and Reddit permissions allow them.

A title or link target may not be editable after submission, and locked, archived, removed, or otherwise restricted threads may reject updates. The planner must validate the actual action instead of promising that every thread can be changed.

## Proposed architecture

```text
                         ┌────────────────────┐
                         │ CLI / terminal UI  │
                         └─────────┬──────────┘
                                   │
                 ┌─────────────────▼─────────────────┐
                 │ Application service and policies │
                 └──────┬──────────┬─────────┬───────┘
                        │          │         │
                ┌───────▼───┐ ┌────▼────┐ ┌──▼──────────┐
                │ Reddit API│ │LLM adapter│ │ Scheduler   │
                └───────────┘ └──────────┘ └─────┬───────┘
                                                  │
                ┌────────────┐ ┌────────────┐ ┌───▼──────┐
                │ Link relay │ │ Rule cache │ │ SQLite   │
                └────────────┘ └────────────┘ └──────────┘
```

The CLI and TUI share the same application layer. SQLite stores posts, metric snapshots, drafts, rule snapshots, schedules, and audit events. External concerns—Reddit, LLMs, secret storage, and redirect analytics—sit behind replaceable adapters so the core can be tested without network access.

## Configuration sketch

The eventual configuration format is expected to resemble:

```toml
[profile.personal]
reddit_account = "my-account"
timezone = "America/Toronto"
database = "~/.local/share/redditctl/personal.db"

[profile.personal.scheduling]
require_approval = true
minimum_global_gap = "6h"
minimum_subreddit_gap = "7d"
quiet_hours = ["22:00-08:00"]

[profile.personal.llm]
provider = "gemini"
model = "configured-by-user"
oauth_client = "~/.config/redditctl/google-oauth-client.json"

[profile.personal.links]
base_url = "https://go.example.com"
retain_aggregate_days = 365
retain_event_days = 7
```

Configuration may name credential records but must not contain tokens or API keys. Reddit and Gemini refresh tokens belong in the operating system's credential store. The MVP fails closed when no supported secure store is available rather than silently writing a plaintext fallback.

## Data and safety boundaries

- Use Reddit's supported authentication and API mechanisms, honor platform and subreddit limits, and make request pacing observable.
- Never automate votes, impersonate organic engagement, rotate accounts to bypass limits, evade moderation, or mass-message users.
- Do not scrape private or deleted content into a permanent archive.
- Require explicit opt-in before sending draft text or account context to a remote LLM.
- Encrypt or keychain-protect credentials and redact them from diagnostics.
- Maintain an append-only action log for submissions, edits, comments, failures, and cancellations.
- Provide deletion and export commands for all locally held user data.

Before implementation or release, the project must verify its behavior against the then-current Reddit API terms, developer policies, and community rules. Those external policies can change independently of this repository.

## Intended command groups

| Command | Purpose |
| --- | --- |
| `auth` | Connect accounts and inspect granted scopes |
| `posts` | List, inspect, and compare submissions and comments |
| `metrics` | Collect snapshots, show trends, and export data |
| `links` | Create redirect links and view aggregate click reports |
| `discover` | Research and rank candidate communities |
| `rules` | Synchronize, diff, and inspect subreddit rules |
| `draft` | Create, revise, lint, and compare post drafts |
| `publish` | Preview and submit an approved draft |
| `schedule` | Plan, approve, run, pause, or cancel future actions |
| `update` | Plan permitted edits or follow-up comments |
| `audit` | Inspect the history of account-changing actions |
| `config` | Manage profiles, providers, privacy, and defaults |

Mutating commands should support `--dry-run`. Read commands should support `--format table|json|csv` where meaningful. Stable machine-readable output is part of the public interface.

## Roadmap

### 0.1 — Read-only foundation

- OAuth login and account profiles
- Post/comment inventory and metric snapshots
- SQLite schema, JSON/CSV export, and audit log
- CLI plus read-only overview TUI

### 0.2 — Rules and drafting

- Rule snapshots and change detection
- Draft workspace and linting
- Gemini OAuth and structured drafting adapter
- Human-readable publication preview

### 0.3 — Publishing and scheduling

- Explicitly approved submissions
- Durable scheduler with spacing policies
- Planned edits and follow-up comments
- Recovery, idempotency, and failure reporting

### 0.4 — Discovery and links

- Explainable subreddit recommendations
- Optional privacy-preserving redirect service
- Click reports joined to post metrics
- Backup, restore, retention, and deletion tools

### 1.0 — Trustworthy daily use

- Stable command and data-export contracts
- Accessibility and cross-platform packaging
- Security and privacy review
- Complete operational documentation

## Development environment and status

The proposed MVP uses Python 3.13, Textual, SQLite, and a Gemini foundation-model adapter. All development tools—including Python, Python libraries, formatters, tests, Git, and GitHub CLI—are supplied by the pinned Nix flake. Installing project software directly on the host with `pip`, `uv`, Homebrew, `apt`, `npm`, or similar tools is not supported.

```console
$ nix develop --command python --version
$ nix flake check
```

`flake.lock` is committed and is the dependency lock for development. Commands in project documentation and CI run through `nix develop --command ...` or `nix flake check`. The first implementation milestone remains read-only until its data model and credential handling have been reviewed.

## Contributing

Early contributions are best made as design discussions or narrowly scoped prototypes. Useful starting points include:

- documenting real account-management workflows and failure cases;
- testing what information is reliably available for different post types;
- specifying the SQLite schema and machine-readable command output;
- prototyping keyboard navigation with screen-reader-friendly labels;
- defining fixtures for rule changes, rate limits, deleted posts, and scheduler restarts.

Any proposal that increases posting volume should also explain its safeguards against repetition, poor community fit, and policy violations.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
