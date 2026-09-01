# MVP code design

Status: implemented MVP baseline

Last reviewed: 2026-09-01

This document turns the product direction in [README.md](README.md) and [VISION.md](VISION.md) into a concrete first implementation. It is intentionally opinionated. The MVP should prove that account synchronization, rule-aware drafting, explainable discovery, click measurement, and scheduled Reddit actions can coexist safely in one terminal application.

The first release is a single-user, single-account, local-first application. It is not a hosted service and not a framework for arbitrary bots.

## Decisions at a glance

| Area | MVP choice | Why |
| --- | --- | --- |
| Language | Python 3.13 | Fast iteration, strong terminal and LLM ecosystem, sufficient performance for a personal network-bound tool; the exact interpreter comes from Nix |
| TUI | Textual | Async-native application model, built-in tables/forms/screens, CSS-like layout, and headless interaction testing |
| CLI | Typer | Typed subcommands, shell completion, readable help, and direct reuse of application services |
| HTTP | HTTPX async client | One client for Reddit and the optional link relay, with explicit timeouts and testable transports; Gemini uses Google's SDK transport |
| Validation | Pydantic | Strict validation at untrusted JSON boundaries and JSON Schema generation for LLM output |
| Database | SQLite through the standard `sqlite3` module | Local, inspectable, zero-service storage with explicit SQL and transactions |
| Migrations | Numbered, forward-only SQL files | The MVP schema is small enough that an ORM migration framework adds more machinery than value |
| Scheduler | A small database-backed worker owned by this project | Approval invalidation, preflight checks, leases, and uncertain remote outcomes are domain behavior, not generic cron jobs |
| Reddit client | A thin in-repository OAuth/API adapter | Makes scopes, rate information, raw capabilities, and failures visible; avoids coupling the domain to a wrapper |
| MVP LLM | Gemini on Vertex AI through installed-app OAuth | Google supports browser OAuth and structured Pydantic output; an explicit Cloud project/location avoids private web-session tokens and API keys |
| Discovery | Reddit search plus SQLite FTS5/BM25 and explicit heuristics | Explainable and cheap; embeddings and a vector database are unnecessary for the first release |
| Secrets | OS credential store through `keyring` | Keeps refresh tokens and relay credentials out of TOML and SQLite |
| Development environment | `flake.nix` and `flake.lock` | Pins Python, every Python library, native tools, and CI inputs without installing project software on the host |
| Python packaging | `pyproject.toml` with Hatchling | Keeps standard wheel metadata while builds and tools still run entirely inside the Nix environment |
| Link relay | Optional Starlette/Uvicorn companion process | A redirect must be publicly reachable, but it should remain isolated from Reddit credentials and the local application database |

`flake.lock` pins the complete development dependency graph, including nixpkgs. `pyproject.toml` describes the distributable Python package but is not allowed to create or mutate a host or project virtual environment. Dependency upgrades are reviewed `flake.lock` changes accompanied by `nix flake check`.

## Why Python

The MVP is dominated by HTTP, terminal interaction, text transformation, SQLite queries, and waiting for scheduled times. Native-code throughput is not a constraint. Python makes it possible to test the product assumptions with less implementation overhead and has first-class libraries for all of those tasks.

Python also lets the CLI, TUI, scheduler, rule checker, and redirect service share typed models without forcing them into the same process.

The tradeoffs are startup time, packaging size, and weaker compile-time guarantees than Go or Rust. The MVP accepts those costs and counters them with strict type checking, boundary validation, small modules, and locked dependencies. If profiling later shows that distribution or resource use is a product problem, the service boundaries in this design allow individual components to be replaced.

### Alternatives considered

- **Go with Bubble Tea:** attractive single binaries and concurrency, but more UI assembly work and a thinner LLM/text-processing ecosystem for the speed at which this MVP needs to learn.
- **Rust with Ratatui:** excellent correctness and distribution properties, but ownership and async complexity would slow a feature-heavy first iteration.
- **TypeScript with Ink:** productive for component-oriented UI, but Node distribution and SQLite/native package behavior are less appealing for a local system tool.
- **Python with Rich alone:** excellent rendering, but Textual supplies the application lifecycle, focus, events, screens, widgets, workers, and test pilot the product needs.

The language choice is revisited only after a working vertical slice and measured evidence, not because another language is theoretically faster.

## MVP scope

The MVP includes one narrow version of every defining product capability:

1. Authenticate one Reddit account through a sanctioned API flow.
2. Synchronize the account's recent submissions and comments.
3. Record score and reply-count snapshots and compare posts at similar ages.
4. Synchronize subreddit rules with source URL and retrieval time.
5. Discover candidate subreddits using Reddit search, public community metadata, rules, and representative recent posts.
6. Produce an explainable deterministic ranking; optionally ask Gemini to summarize the evidence after a data-sharing preview.
7. Draft a self-post or link post through Gemini and validate its structured response.
8. Run deterministic rule checks independently of the LLM.
9. Preview, approve, publish, or schedule a post.
10. Schedule a self-post body edit or a follow-up comment on a thread the account owns.
11. Enforce global and per-subreddit spacing before scheduled submission.
12. Create redirect mappings, pull aggregate redirect counts from an optional self-hosted relay, and join them to posts.
13. Expose the same use cases through a CLI and a keyboard-driven TUI.
14. Record every Reddit mutation and scheduler transition in an audit log.

The MVP does not include multiple Reddit accounts, additional foundation-model providers, autonomous replies, embeddings, semantic vector search, a managed relay, a browser interface, team workflows, desktop notifications, or Windows service installation. The Python application should remain portable, but supported MVP installation and worker examples target macOS and Linux under Nix.

## External feasibility gate

Reddit API access is the largest project risk, not a library decision. Before scaffolding the full application, build a disposable access spike that proves the project can obtain approved credentials and perform the required operations using Reddit's then-current supported interfaces.

The spike must demonstrate, against a dedicated test account:

- browser authorization and refresh without storing a password;
- identity lookup;
- listing the authenticated user's submissions and comments;
- reading subreddit metadata and rules;
- reading representative recent posts;
- submitting and then editing a test self-post in a controlled test subreddit;
- posting a follow-up comment;
- observing rate-limit and error metadata.

The requested OAuth scopes must be derived from the endpoints used and shown to the user during setup. The adapter sends a truthful, stable user agent and never attempts to work around access controls.

If sanctioned access is not available, implementation pauses and this design is revised. HTML scraping, browser-cookie automation, and undocumented private endpoints are not fallbacks.

## Process model

The project installs one executable with four modes:

```console
redditctl <command>       # finite CLI operation
redditctl tui             # interactive terminal UI; also the default
redditctl worker          # long-running scheduler and metric collector
redditctl relay serve     # optional public redirect component
```

The CLI and TUI may run at the same time. Only one scheduler worker may own a profile database. The relay is a separate deployment with a separate database and must never receive Reddit or LLM credentials.

The TUI does not execute schedules itself. Closing it does not cancel approved work, and leaving it open is not required. On macOS or Linux, the user runs `redditctl worker` through `launchd`, `systemd --user`, a process supervisor, or a foreground terminal. Example service definitions belong in the repository, but installing a daemon automatically is outside the MVP.

## Code organization

Use a `src` layout and one installable package:

```text
.
├── flake.nix
├── flake.lock
├── pyproject.toml
├── src/redditctl/
│   ├── __main__.py
│   ├── bootstrap.py             # composition root
│   ├── cli/                     # Typer commands and output formatting
│   ├── tui/
│   │   ├── app.py
│   │   ├── screens/
│   │   └── widgets/
│   ├── domain/                  # entities, value objects, state machines
│   ├── application/             # use cases and transaction boundaries
│   ├── reddit/                  # OAuth, DTOs, API adapter, pacing
│   ├── rules/                   # normalization and deterministic checks
│   ├── discovery/               # collection, features, scoring, explanations
│   ├── drafting/                # prompts, schemas, provider interface
│   ├── scheduling/              # planner, worker, leases, reconciliation
│   ├── links/                   # local relay client and reports
│   ├── relay/                   # optional Starlette redirect service
│   ├── persistence/             # sqlite connection, repositories, migrations
│   ├── config.py
│   ├── credentials.py
│   ├── clock.py
│   └── errors.py
├── migrations/
│   ├── 0001_initial.sql
│   └── 0002_fts.sql
└── tests/
    ├── unit/
    ├── integration/
    ├── contract/
    ├── tui/
    └── fixtures/
```

Dependencies point inward:

```text
CLI / TUI / worker / relay
              ↓
       application use cases
              ↓
        domain and policies
              ↑
Reddit / Gemini / SQLite / keyring adapters
```

The domain package does not import Textual, Typer, HTTPX, `sqlite3`, or provider-specific types. UI handlers call use cases and render returned view models; they do not issue SQL or HTTP requests.

Avoid a large abstract repository hierarchy. Define a `Protocol` only at a boundary that has at least two implementations in tests or production, such as `RedditGateway`, `LlmGateway`, `CredentialStore`, and `Clock`. Straightforward SQLite repositories can remain concrete.

## Runtime dependencies

`flake.nix` is the authoritative development environment. It constructs `python313.withPackages` with every runtime and test library and adds non-Python tools such as Git, GitHub CLI, Ruff, SQLite, and `nixfmt`. Contributors enter it with `nix develop`; CI invokes the same environment with `nix develop --command ...` and validates it with `nix flake check`.

The repository must not instruct contributors or automation to run `pip install`, `uv`, Poetry, Conda, Homebrew, `apt`, `npm install`, or any equivalent host mutation. `PYTHONNOUSERSITE=1` prevents accidental use of user-site packages. Adding a dependency means editing `flake.nix`, updating `flake.lock`, and extending the environment import check. A tool that is not available inside `nix develop` is not part of the supported workflow.

### Required application dependencies

| Package | Use | Constraint |
| --- | --- | --- |
| `textual` | TUI screens, widgets, workers, themes, and interaction tests | UI layer only |
| `typer` | CLI command tree, validation, help, and completion | CLI layer only |
| `httpx` | Async HTTP with pooled clients and injectable transports | One long-lived client per Reddit/relay service |
| `pydantic` | Reddit/Gemini/relay response validation and foundation-model output schemas | Boundary models only; domain models use dataclasses |
| `google-genai` | Supported Gemini client and structured generation | Contained in the Gemini adapter |
| `google-auth` and `google-auth-oauthlib` | Installed-app browser OAuth and token refresh | Contained in the Gemini credential adapter |
| `keyring` | Reddit, Gemini, and relay refresh/admin token storage | No silent plaintext fallback |
| `platformdirs` | OS-appropriate config, data, cache, and log directories | Paths may always be overridden for tests |

Textual brings Rich as a transitive dependency; application code may use Rich renderables but should not add a separate rendering abstraction.

### Optional relay dependencies

| Package | Use |
| --- | --- |
| `starlette` | Minimal redirect and authenticated admin endpoints |
| `uvicorn` | ASGI server for the reference relay deployment |

These remain a `relay` optional extra in wheel metadata, but are present in the Nix development shell so the whole repository can be tested without installing anything else.

### Development dependencies

| Package | Use |
| --- | --- |
| `pytest` and `pytest-asyncio` | Unit, integration, and async tests |
| `respx` | HTTPX request mocking and adapter contract tests |
| `pytest-textual-snapshot` | TUI interaction and terminal-size snapshots |
| `hypothesis` | Scheduler state-machine and date/spacing property tests |
| `ruff` | Formatting, import sorting, and linting |
| `mypy` | Strict static type checking |
| `coverage` | Branch coverage reporting |

Do not add SQLAlchemy, Alembic, APScheduler, PRAW, an LLM orchestration framework, or a vector database in the MVP. Do not add provider CLIs or SDKs outside the Nix closure. Each can be reconsidered if a concrete limitation appears. At this scale, explicit SQL, provider calls, prompts, and scheduler transitions are easier to inspect and test.

## Configuration and files

Use `platformdirs` for defaults and allow `REDDITCTL_CONFIG_DIR`, `REDDITCTL_DATA_DIR`, and `REDDITCTL_CACHE_DIR` overrides. A profile contains:

```text
config.toml             # non-secret user configuration
redditctl.db            # account, draft, metric, and schedule data
redditctl.db-wal        # present while WAL mode is active
logs/redditctl.jsonl    # redacted structured diagnostics
```

TOML is read with the standard library's `tomllib`. Configuration is validated once into immutable dataclasses at process startup. Unknown keys are errors, not ignored typos.

Secret values are referenced by logical name and stored through `keyring`. If no secure backend is available, setup fails with instructions. The MVP does not silently write refresh tokens or keys to TOML, environment files, SQLite, logs, or command history. A user-supplied Google desktop OAuth client JSON is configuration input and is kept outside the repository; the resulting Gemini refresh token goes to the credential store. Environment variables may provide secrets only for non-interactive CI and relay container deployment.

All timestamps are stored as UTC ISO 8601 strings with microseconds. A separate IANA time-zone name is retained for displaying and interpreting user input. Python's standard `zoneinfo` handles time zones. Absolute schedule input must include an offset or `--timezone`; relative input is deliberately limited to unambiguous forms such as `+2h`, `+3d`, and `+1w`.

## SQLite design

Use the standard `sqlite3` module with rows mapped explicitly to dataclasses. Each process creates short-lived connections through a connection factory configured with:

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;
```

Writes use explicit transactions. Scheduler claims use `BEGIN IMMEDIATE`; ordinary reads do not hold transactions across network calls. A repository method either accepts an existing unit-of-work connection or opens and closes its own transaction—never both implicitly.

### Initial tables

| Table | Purpose and important keys |
| --- | --- |
| `accounts` | Local profile and Reddit account ID; no tokens |
| `things` | Normalized owned submissions/comments keyed by Reddit fullname |
| `metric_snapshots` | Append-only `(thing_id, observed_at)` score/reply observations |
| `subreddits` | Latest public community metadata |
| `rule_snapshots` | Versioned raw and normalized rules with content hash/source/retrieval time |
| `community_samples` | Recent post titles/bodies used as expiring discovery evidence |
| `drafts` | Current draft metadata and immutable revision pointer |
| `draft_revisions` | Append-only authored/generated text, prompt metadata, and content hash |
| `recommendation_runs` | Query, candidates, feature values, explanations, and model version |
| `scheduled_actions` | Frozen payload, target, due time, state, lease, approval, and retry data |
| `audit_events` | Append-only local record of state-changing intent and result |
| `link_mappings` | Local copy of slug, destination, and relay identity |
| `link_snapshots` | Aggregate redirect counts observed from the relay |
| `schema_migrations` | Applied migration number and checksum |

Store raw external JSON only where it is required for diagnosis or future normalization, and apply a retention limit. Normal queries use typed columns. Draft bodies and rules remain plain text rather than opaque blobs.

Migrations are forward-only SQL scripts embedded in the wheel. At startup, the application verifies checksums and applies pending migrations inside a transaction. Before a migration that rebuilds or drops data, it creates a timestamped SQLite backup and reports its path. Every released schema version has an upgrade fixture.

## Reddit adapter

Build the adapter directly on a dedicated `httpx.AsyncClient`. It owns:

- OAuth authorization, callback, refresh, and scope reporting;
- the stable user agent;
- cursor pagination and `raw_json=1` where supported;
- response validation into Pydantic DTOs;
- request pacing informed by returned rate metadata;
- bounded retries for safe reads and token refresh;
- conversion from API failures into typed application errors;
- redacted request diagnostics.

The application layer consumes normalized domain objects and never depends on Reddit response dictionaries.

One-shot browser authorization uses a loopback callback server bound to `127.0.0.1` on a random port. The callback validates the OAuth `state`, accepts one request, and shuts down. It is implemented with the Python standard library; Starlette is not pulled into the core application for one route.

### Read synchronization

`sync_account` pages through the account's recent submissions and comments, upserts mutable fields, and appends a metric snapshot only when an observed value changed or the configured snapshot interval elapsed. Missing values are stored as unavailable, never zero.

The worker's default collection cadence is conservative and configurable. It prioritizes newer owned posts and backs off older posts. The UI displays observation time and gaps. “Click-through rate” is shown only if a defensible denominator is available; otherwise the MVP reports redirect hits separately from Reddit metrics.

### Write operations

All write methods require a fully materialized request with a client-generated operation ID. The audit log records the content hash, target, and intent before the network request, then records the outcome afterward.

A timeout after a submission request is an **uncertain outcome**, not an automatic retry. The adapter searches the account's recent content for a matching target, kind, time window, and content hash. If exactly one match exists it reconciles success; if not, the action moves to `needs_review`. This prevents duplicate posts when Reddit accepted a request but the response was lost.

## Rules

A rule snapshot contains the subreddit, normalized rule ID, short name, body, applicable post types when available, source URL, retrieval timestamp, and hash of the ordered content. Keep the source representation so normalization can be improved later.

The rule engine has two independent passes:

1. **Deterministic checks:** title/body length, required or banned terms explicitly configured from rules, link/domain restrictions that can be represented safely, flair presence, duplicate scheduling, and account eligibility that can be observed.
2. **LLM review:** a non-authoritative explanation of possible conflicts, missing disclosures, tone concerns, and ambiguous rules.

The UI never merges these into a “compliant” badge. Each finding is `error`, `warning`, or `unknown` and cites the exact rule snapshot used. A changed rule hash invalidates publication approval and moves a scheduled action to `needs_review`.

## LLM drafting

The production interface is deliberately small:

```python
class LlmGateway(Protocol):
    async def draft(self, request: DraftRequest) -> DraftProposal: ...
    async def review(self, request: ReviewRequest) -> RuleReview: ...
```

The MVP implements `GeminiGateway` with Google's `google-genai` SDK. It requests structured JSON using a schema generated from Pydantic and validates the result again before creating a draft revision. Invalid output may be repaired once with the validation errors; a second failure is shown to the user and preserved as a redacted diagnostic.

`DraftProposal` includes title variants, body, suggested flair, disclosures, factual assumptions, and rule references. Model text never becomes a scheduled payload automatically. The user saves or edits a revision, runs checks, previews the exact rendered content, and approves that immutable revision hash.

Prompts are versioned files in the package. Each generated revision records prompt version, provider kind, configured model name, rule snapshot hash, source-note hash, request time, and provider request ID when available. It does not store hidden model reasoning. User notes are delimited as untrusted content and cannot introduce new tool permissions.

### Gemini authentication

The supported MVP path is Google's installed-application OAuth flow for Gemini on Vertex AI, not a copied Gemini browser cookie and not an unofficial ChatGPT/Claude login bridge. Setup requires the user to create or select a Google Cloud project, enable Vertex AI, create a desktop OAuth client, and configure the project and location alongside the downloaded client JSON. `redditctl auth gemini` opens the system browser on Google's authorization page, binds a one-shot loopback callback to `127.0.0.1`, validates OAuth state, and stores the resulting refresh token through `keyring`.

The exact OAuth scopes and SDK behavior are proven in a provider access spike and pinned by adapter contract tests. The TUI shows the authenticated Google account identifier when available, the configured Gemini model, and a disclosure of the fields about to be sent. Every draft/review action requires a positive provider-enabled setting; there is no automatic fallback to a different provider or model.

Google also documents API-key authentication, but it is not the primary interactive MVP flow. It may be enabled for headless CI/manual testing through a credential-store record, never a committed environment file. OpenAI's published API path uses API keys rather than a ChatGPT device-login flow, and Anthropic documents Claude API billing separately from Claude subscriptions. The project therefore does not reuse either consumer product's browser session. OpenAI and Anthropic adapters are deferred until they use officially supported API authentication and share the same disclosure, structured-output, retention, and redaction contract.

A deterministic fake gateway is used in tests. Live Gemini tests are manual, opt-in, and use a dedicated project with a spending/quota limit. Model identifiers live in configuration and fixtures rather than being silently upgraded in code.

## Subreddit discovery

Discovery is a two-stage, explainable pipeline.

### Candidate collection

1. Normalize the user's topic or draft into search terms.
2. Ask Reddit's supported community search for a bounded candidate set.
3. Add explicit user-supplied candidate subreddits.
4. Remove configured exclusions and ineligible/NSFW communities according to user preferences.
5. Fetch public description, rules, and a small sample of recent posts for the remaining candidates.

The MVP caches evidence with retrieval timestamps and short retention. It does not crawl Reddit broadly or retain deleted third-party content.

### Deterministic ranking

Index community descriptions, rule text, and sample titles in an SQLite FTS5 table. Rank lexical fit with BM25, then apply visible feature adjustments for:

- exact topic/title matches;
- post-type and domain eligibility;
- explicit self-promotion or disclosure rules;
- observable account requirements;
- recent activity;
- user size/language/NSFW preferences;
- duplicate or cooldown conflicts with the user's own history.

Store every feature and weight with the recommendation run. The TUI shows the top candidates, exclusions, evidence age, and a short deterministic rationale. Gemini may rewrite that evidence into clearer prose after the user accepts the data-sharing preview, but it cannot change the candidate score or remove warnings. This keeps discovery useful when the provider is unavailable and makes rankings testable.

## Scheduler

Do not use APScheduler for the MVP. The difficult part is not waking up at a timestamp; it is preserving human approval and handling remote side effects safely.

### Action types

- `submit_self`
- `submit_link`
- `edit_self_body`
- `post_followup_comment`

Titles and link targets are immutable after scheduling. Updating a scheduled payload creates a new revision and invalidates its approval. Existing-thread actions are rejected during planning if the action is incompatible with the known post type; eligibility is checked again at execution.

### State machine

```text
draft → pending_approval → approved → running → succeeded
              ↑              │          │
              └─ needs_review┘          ├─ retry_wait → approved
                                       ├─ needs_review
                                       └─ failed

pending_approval / approved / retry_wait / needs_review → cancelled
```

State changes use compare-and-swap SQL updates and always append an audit event in the same transaction. `succeeded`, `failed`, and `cancelled` are terminal. A failed action is copied into a new action if the user wants to try again.

### Claim and execute

For each due action, the worker:

1. Opens `BEGIN IMMEDIATE` and claims one `approved` action whose lease is free.
2. Sets `running`, increments the attempt, writes a lease expiry and worker ID, then commits.
3. Re-fetches the target, account status, and subreddit rules outside the transaction.
4. Moves to `needs_review` if content, eligibility, rules, spacing, or thread state changed materially.
5. Writes the remote-operation intent and payload hash to the audit log.
6. Performs the Reddit request once.
7. Reconciles an uncertain outcome rather than blindly retrying.
8. Records success, retry, failure, or review state and releases the lease.

Only safe transient failures enter `retry_wait`, using bounded exponential backoff with jitter and a maximum attempt count. Authentication errors, permission errors, material rate-policy changes, ambiguous results, locked threads, and rule changes require review.

The process holds a profile-specific advisory lock file to enforce one local worker. The database lease still supports crash recovery. A lease expiry never proves the remote operation did not happen, so recovery inspects the intent audit event and reconciles before any new request.

### Spacing

The planner checks `minimum_global_gap`, `minimum_subreddit_gap`, quiet hours, and conflicts with other approved actions. The worker repeats the check against actual successful posts. If an earlier action ran late, later actions are moved forward only when the user enabled automatic spacing; otherwise they enter `needs_review`.

The MVP does not add random timing windows. Staggering means explicit, inspectable spacing, not behavior intended to disguise automation.

## Link relay

Outbound clicks cannot be measured by the local application unless requests pass through a reachable service. The optional relay is therefore a small, separately deployed ASGI application.

Public endpoint:

```text
GET /r/{slug} → validate active mapping → increment aggregate bucket → 302 destination
```

Authenticated admin endpoints create/disable mappings and return aggregate hourly or daily counts. The admin token is hashed in the relay database, sent only over HTTPS, and never shared with Reddit.

The relay records redirect hits, not people or guaranteed human clicks. It does not store IP addresses, cookies, full user-agent strings, or cross-link identifiers. A request may be classified as an obvious bot in memory before those inputs are discarded. Stored rows contain slug, UTC time bucket, coarse referrer class when available, bot classification, and count.

Destinations are validated when a mapping is created. Redirect responses set a restrictive referrer policy and `Cache-Control: no-store`. The public route performs no outbound fetch, preventing server-side request forgery. The MVP supports only `https` destinations by default and never accepts a destination in the public request.

The local application periodically pulls cumulative bucket counts and upserts them idempotently. A relay outage delays analytics but never blocks Reddit publishing. The reference deployment uses its own SQLite database and one Uvicorn worker; multi-worker or high-volume operation requires a different aggregate store and is outside the MVP.

## CLI design

Typer command functions are thin adapters. They parse values, build a request DTO, invoke one application use case, and render the result. Business rules do not live in callbacks.

Conventions:

- read commands support `--format table|json|csv` where applicable;
- JSON output has a top-level `schema_version` and stable field names;
- mutating commands support `--dry-run` and display the exact intended target/content;
- non-interactive mutations require `--yes` or an approved schedule ID;
- prompts go to the terminal, never stdin, so pipes remain machine-safe;
- stdout contains requested data; diagnostics and progress use stderr;
- exit codes distinguish validation, authentication, policy, network, and internal failures.

Running `redditctl` with no arguments launches `redditctl tui` only when stdin and stdout are terminals; otherwise it prints help and exits with a usage error.

## TUI design

Textual screens correspond to use cases rather than duplicating a browser-like site:

- **Overview:** sync health, recent performance deltas, due actions, and warnings.
- **Posts:** sortable owned content and a metric-history detail pane.
- **Drafts:** source notes, revision diff, rules findings, preview, and approval.
- **Discover:** topic input, candidate evidence, exclusions, and ranking details.
- **Schedule:** state-grouped actions, preflight findings, approve/cancel/reschedule.
- **Links:** mappings and aggregate redirect-hit series.
- **Rules:** current snapshot, source, age, and diff from the previous snapshot.

Long HTTP or database operations run in Textual workers and return messages to the UI thread. Each screen renders loading, empty, stale, partial, error, and success states. Tables never rely on color alone; status has text and symbols. All actions are keyboard accessible, and key bindings are shown in the footer.

The TUI consumes the same view models as CLI formatters. A screen can add presentation state such as selection and sorting, but cannot invent another interpretation of scheduler or rule status.

## Error model and logging

Application errors use a closed hierarchy:

- `UsageError`
- `ConfigurationError`
- `AuthenticationError`
- `PermissionError`
- `RateLimitedError`
- `PolicyError`
- `ValidationError`
- `NetworkError`
- `UncertainOutcomeError`
- `StorageError`
- `InternalError`

Each error carries a safe user message, stable machine code, retryability, and optional redacted context. Raw response bodies are not shown by default.

Use the standard `logging` package with a small JSON formatter. Every operation receives a correlation ID. Logs include endpoint templates, status codes, durations, action IDs, and content hashes—not tokens, authorization URLs, full post bodies, prompts, destinations with sensitive query strings, or raw external JSON. A redaction filter runs before every handler, and tests assert representative secrets never appear.

## Testing strategy

### Unit tests

Test rule normalization, deterministic checks, recommendation scoring, schedule parsing, spacing, state transitions, retry classification, content hashing, and output serialization without network or disk.

Inject `Clock`, ID generation, and random jitter. Scheduler tests never wait for wall time.

### Integration tests

Run repositories and migrations against temporary file-backed SQLite databases, including WAL and concurrent CLI/worker access. Test upgrades from every released schema fixture. Exercise the relay through ASGI without opening a port.

### Adapter contract tests

Use HTTPX mock transports through `respx` and sanitized fixtures for Reddit and relay responses, plus an injected fake transport/client for Gemini. Cover pagination, Reddit and Google token refresh, rate metadata, malformed JSON, timeouts, 429s, permission failures, and schema drift. Live Reddit and Gemini tests are manual, opt-in, and restricted to dedicated test accounts/projects.

### Scheduler crash tests

Simulate termination at each boundary:

- before claim commit;
- after claim but before preflight;
- after intent audit but before request;
- after remote acceptance but before local success commit;
- during reconciliation;
- after success commit.

The acceptance rule is at-most-one intentional remote mutation. An ambiguous case stops for review rather than risking a duplicate.

### TUI tests

Use Textual's pilot to press keys and assert state, plus snapshots at 80×24, 120×40, and a narrow supported layout. Snapshot stable structure and labels, not timestamps or generated IDs. Critical flows—open a post, inspect a warning, preview a draft, approve a schedule, and cancel an action—need interaction tests.

### Quality gates

CI runs on supported Python versions and operating systems:

```console
nix flake check
nix develop --command ruff format --check .
nix develop --command ruff check .
nix develop --command mypy src tests
nix develop --command pytest --cov=redditctl --cov-branch
nix develop --command python -m build
```

Coverage is used to find untested behavior, not as a substitute for scenario tests. Scheduler, approval, credential redaction, and migration code require branch coverage before release.

## Security and privacy baseline

- Request the minimum OAuth scopes for enabled features and display them during authorization.
- Store refresh tokens only in an accepted OS credential backend.
- Never accept a Reddit password.
- Bind the OAuth callback only to loopback and validate a high-entropy state value.
- Require HTTPS for Reddit, remote relay administration, and redirect destinations.
- Allow only the configured Gemini API host in the MVP provider adapter; provider changes require explicit configuration and re-authentication.
- Freeze and hash approved content; invalidate approval on any material change.
- Keep account-changing network calls out of TUI render/event plumbing.
- Redact secrets and authored content from logs and crash output.
- Export and delete local data by category.
- Put third-party sample content on a short, enforced retention schedule.
- Report redirect hits honestly and collect no reader identifiers.

Before a release, document a threat model covering credential theft, malicious draft/source text, prompt injection, duplicate scheduled submissions, relay open redirects, SSRF, local database disclosure, and dependency compromise.

## Packaging and release

Use a standard `pyproject.toml` with Hatchling and these entry points:

```toml
[project]
license = "GPL-3.0-only"

[project.scripts]
redditctl = "redditctl.__main__:main"

[project.optional-dependencies]
relay = ["starlette", "uvicorn"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Commit `flake.nix` and `flake.lock`. CI evaluates the flake, builds a wheel and source distribution inside the dev shell, and smoke-tests the wheel in an isolated Nix derivation. No CI step installs into the runner's host Python. The first developer and source-install path is `nix develop`; a `packages.default` Nix application output is added when runtime code exists. Publishing wheels or self-contained binaries can be evaluated after the MVP without weakening the Nix-only contributor workflow.

Configuration and database formats are versioned independently from the Python package. A release never downgrades the database automatically.

## Implementation sequence

### Milestone 0: API access spike

Complete the external feasibility gate and record supported endpoints, scopes, rate behavior, and test-account constraints. No other milestone proceeds without a sanctioned path.

### Milestone 1: local read model

Scaffold the Nix-only development environment, Python packaging, configuration, keyring, migrations, Reddit adapter, account sync, snapshots, CLI tables/JSON, and the Posts/Overview TUI screens. This milestone is read-only after OAuth.

### Milestone 2: rules, discovery, and drafts

Add the Google installed-app OAuth flow, rule snapshots/diffs, candidate collection, FTS5 ranking, Gemini structured drafting, deterministic findings, provider disclosure, revision history, and preview. Still no Reddit mutations.

### Milestone 3: audited writes

Add immediate previewed submission and owned self-post edits behind explicit confirmation. Prove uncertain-outcome reconciliation and audit behavior before scheduling.

### Milestone 4: durable scheduling

Add action states, approval hashes, spacing, worker locking/leases, preflight invalidation, retries, follow-up comments, crash tests, and service examples.

### Milestone 5: optional click loop

Add relay mapping/admin routes, minimal aggregation, reference deployment, local synchronization, Links UI, retention, and deletion tools.

## MVP acceptance criteria

The MVP is complete when a new user can:

1. Install the wheel, initialize a profile, authorize a test account, and see exactly where its token is stored.
2. Synchronize owned posts/comments twice and see changed metric snapshots without duplicate rows.
3. Export the same post view from the CLI as stable JSON and inspect it in the TUI.
4. Search for candidate communities and see a reproducible ranking with sources, evidence age, feature contributions, and exclusions.
5. Synchronize and diff rules, then create a locally generated structured draft tied to one rule snapshot.
6. Edit that draft, preview it, approve its immutable revision, and publish it exactly once.
7. Schedule two posts with a configured gap and observe that a late first post safely moves or blocks the second according to policy.
8. Schedule a valid self-post body edit and follow-up comment; see an invalid thread action rejected before approval.
9. Change a rule snapshot after approval and see the scheduled action stop in `needs_review`.
10. Recover from a simulated lost submission response without automatically creating a duplicate.
11. Run the optional relay, create a safe mapping, follow it, pull aggregate hits, and see them separately from Reddit metrics.
12. Inspect an audit trail that explains every local transition and Reddit mutation without exposing a credential or full prompt.

Performance targets are modest but explicit: cached screens should render perceptibly immediately, ordinary local queries should complete within 100 ms on a representative database, and no network request may block TUI input. Correctness and visible failure take priority over throughput.

## Decision triggers after MVP

Revisit a choice only when evidence crosses one of these thresholds:

- Replace explicit SQLite repositories if query duplication or migration complexity becomes a recurring source of defects.
- Adopt a scheduler library only if it can preserve the domain state machine and uncertain-outcome reconciliation without duplicating state.
- Add embeddings when lexical ranking fails a documented discovery evaluation set, not merely because semantic search is fashionable.
- Add OpenAI, Anthropic, or local-model adapters only after each has supported authentication plus provider-specific disclosure, credential, retention, and redaction behavior.
- Replace the relay's SQLite store when a real deployment requires multiple workers or sustained write concurrency.
- Reconsider Python packaging when installation failure or startup/resource measurements materially harm adoption.

## Primary references

- [Textual guide](https://textual.textualize.io/guide/) and [Textual testing guide](https://textual.textualize.io/guide/testing/)
- [Typer documentation](https://typer.tiangolo.com/)
- [HTTPX async support](https://www.python-httpx.org/async/)
- [Python keyring documentation](https://keyring.readthedocs.io/en/stable/)
- [SQLite FTS5 documentation](https://www.sqlite.org/fts5.html)
- [Gemini OAuth quickstart](https://ai.google.dev/gemini-api/docs/oauth), [Python Gen AI SDK](https://googleapis.github.io/python-genai/), and [Gemini structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Nix flake command reference](https://nix.dev/manual/nix/latest/command-ref/new-cli/nix3-flake.html) and the pinned nixpkgs revision in `flake.lock`
- [OpenAI Responses API reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) and [Anthropic's API/subscription separation](https://support.anthropic.com/en/articles/9876003-i-subscribe-to-a-paid-claude-ai-plan-why-do-i-have-to-pay-separately-for-api-usage-on-console)
- [Reddit API reference](https://www.reddit.com/dev/api/)

External APIs and policies change. These links are design inputs, not a promise that every endpoint or access path will remain available; the feasibility gate and adapter contract tests are responsible for detecting that reality.
