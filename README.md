# redditctl

`redditctl` is a local-first CLI and terminal UI for managing a Reddit presence from one place. Its MVP synchronizes an account and metric history, measures aggregate outbound clicks, finds communities where a contribution belongs, drafts against versioned rules with Gemini, and executes explicitly approved scheduled posts or thread updates.

The MVP is usable but pre-release. In particular, Reddit API credentials and a Google Cloud project with Vertex AI access are external prerequisites that this project cannot provision.

`redditctl` is an independent project and is not affiliated with, endorsed by, or operated by Reddit.

## What it does

- Show synchronized posts and comments in sortable CLI and TUI tables with scores and replies.
- Record metric snapshots so trends can be viewed over time rather than only as current totals.
- Create first-party redirect links and report aggregate clicks without fingerprinting readers.
- Suggest suitable subreddits based on topic fit, rules, posting requirements, and the author's preferences.
- Draft posts with Gemini through installed-app OAuth using a versioned rules snapshot.
- Explain potential rule conflicts before anything is submitted.
- Schedule posts, space similar submissions apart, and plan edits or follow-up comments on existing threads.
- Keep every scheduled publish, edit, and follow-up action approval-gated and auditable.

## Product principles

1. **Fit before reach.** Recommendations should favor relevant communities, not merely large ones.
2. **Rules are inputs, not fine print.** A draft is tied to the rule snapshot used to create it.
3. **The human publishes.** LLM output is a draft, and automation is explicit, reviewable, and reversible where Reddit permits.
4. **No spam machinery.** Rate limits, duplicate detection, cooldowns, and subreddit-specific policies are product features.
5. **Local first.** Credentials, drafts, schedules, and analytics stay on the user's machine unless a configured service is required.
6. **Honest analytics.** Click counts are aggregate measurements with documented limits, not invasive reader tracking.

The long-term product rationale is in [VISION.md](VISION.md). The implementation baseline is in [MVP_DESIGN.md](MVP_DESIGN.md).

## Quick start

All software comes from the pinned Nix flake; do not install Python or project libraries on the host. Initialize the private local config and database:

```console
$ nix run . -- init
$ $EDITOR ~/.config/redditctl/config.toml
```

Set `reddit.client_id` to an approved Reddit installed-app client ID, then authorize and synchronize:

```console
$ nix run . -- auth reddit
$ nix run . -- posts sync
$ nix run . -- posts list --sort score
$ nix run . -- posts list --sort replies --format json

# Inspect a post and its metric history
$ nix run . -- posts show t3_abc123

# Find communities using metadata, current rules, and recent discussions
$ nix run . -- discover "self-hosted photo backup for families"

# Fetch rules and prepare a rule-aware draft
$ nix run . -- rules sync DataHoarder
$ nix run . -- rules check DataHoarder --title "Backup lessons" --body post.md
$ nix run . -- draft new DataHoarder --from notes.md

# Freeze, review, and approve a future post
$ nix run . -- schedule add draft-ab12cd34 --at "2026-09-03T10:00:00-04:00"
$ nix run . -- schedule approve action-ab12cd3456
$ nix run . -- worker

# Plan a permitted update to an existing thread
$ nix run . -- update plan t3_abc123 --edit-body update.md --at "+2d"
$ nix run . -- update plan t3_abc123 --comment follow-up.md --at "+1w"

# Make a measurable, shareable link
$ nix run . -- auth relay
$ nix run . -- links create https://example.com/launch --slug launch-notes \
    --relay-url https://go.example.com
$ nix run . -- links stats launch-notes --relay-url https://go.example.com

# Open the local read-only dashboard
$ nix run . -- tui
```

For Gemini, create a Google desktop OAuth client, enable Vertex AI in a Google Cloud project, and set `gemini.enabled`, `gemini.oauth_client`, `gemini.project`, and optionally `gemini.location`. `redditctl auth gemini` stores the resulting refresh credential in the OS credential store. The exact notes and cached rules sent to Gemini are explicit inputs to `draft new`; Reddit credentials are never sent to the model.

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

## Beyond the MVP

The current implementation establishes the local account, rules, draft, schedule, audit, discovery, and relay boundaries. Likely post-MVP work includes richer metric comparisons and exports, draft revision screens, additional officially supported foundation-model providers, complete TUI command parity, backup/restore and retention controls, and broader accessibility and security review.

## Development environment

The MVP uses Python 3.13, Textual, SQLite, and a Gemini foundation-model adapter. All development tools—including Python, Python libraries, formatters, tests, Git, and GitHub CLI—are supplied by the pinned Nix flake. Installing project software directly on the host with `pip`, `uv`, Homebrew, `apt`, `npm`, or similar tools is not supported.

```console
$ nix develop --command ruff format --check .
$ nix develop --command ruff check .
$ nix develop --command mypy src
$ nix develop --command coverage run -m pytest
$ nix develop --command coverage report
$ nix flake check
```

`flake.lock` is committed and is the dependency lock for development. The flake check builds the package and runs formatting, linting, strict type checking, tests, branch coverage, and wheel/sdist construction in the same self-contained environment used by CI.

## Contributing

Useful contributions include:

- documenting real account-management workflows and failure cases;
- testing what information is reliably available for different post types;
- improving stable machine-readable command output;
- expanding keyboard navigation with screen-reader-friendly labels;
- defining fixtures for rule changes, rate limits, deleted posts, and scheduler restarts.

Any proposal that increases posting volume should also explain its safeguards against repetition, poor community fit, and policy violations.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).
