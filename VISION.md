# Vision

## A calm control room for participating on Reddit

Managing a Reddit account is currently split across browser tabs, reminders, spreadsheets, analytics tools, and half-remembered community rules. That fragmentation makes thoughtful participation harder. It also makes the easiest form of automation the least healthy one: posting more, faster, with less context.

`redditctl` should take the opposite approach. It should be a calm, local-first control room that helps one person make fewer, better-informed posts and take responsibility for what happens after publishing.

The product succeeds when a user can answer five questions with confidence:

1. What have I posted, and how is it doing over time?
2. Did interested readers follow the links I shared?
3. Which communities would actually welcome this contribution?
4. Does this draft respect the target community's rules and norms?
5. What have I promised to publish or update, and when will it happen?

## The problem is not publishing

Submitting a Reddit post is easy. Making a useful contribution requires context that the submission form cannot hold:

- Community rules vary, contain exceptions, and change.
- A topic can be relevant to several subreddits while only fitting the culture of one.
- Scores and replies are visible, but meaningful comparisons require historical snapshots and consistent time windows.
- Outbound interest is difficult to understand without owning the link measurement path.
- Follow-ups are valuable, but promises to update a thread are easy to forget.
- Generative models can improve a draft while also producing generic, inaccurate, or noncompliant copy.

`redditctl` should assemble that context at the moment of decision. It is not a growth bot. It is an accountability tool for authors.

## Who it is for

The primary user is an individual who participates under their own account: an open-source maintainer sharing a release, a maker documenting a project, a researcher recruiting carefully, a creator answering questions, or a community member maintaining a long-running guide.

They are comfortable in a terminal, value control over their data, and want assistance without handing their voice or account to an opaque service.

Teams, agencies, moderators, and high-volume social media operations are not the initial audience. Supporting them too early would pull the design toward campaigns, permissions, and throughput rather than personal judgment and community fit.

## The product loop

The central loop is deliberate and inspectable:

```text
Understand past work
        ↓
Find a fitting community → read its evidence and rules
        ↓
Draft with context → review claims, tone, and rule checks
        ↓
Publish now or schedule within explicit limits
        ↓
Observe outcomes → answer replies → deliver promised updates
        └───────────────────────────────────────────────────↺
```

Each step should leave a useful artifact: a metric snapshot, recommendation rationale, rules version, draft diff, publication preview, scheduled action, or audit event. The user should be able to reconstruct why an action occurred.

## What “intelligent” means here

Intelligence is not measured by how much text the tool generates. It is measured by whether the tool brings the right constraints into view.

For drafting, the model should receive only the necessary context and produce an annotated proposal. It should point to the rules it relied on, identify uncertain claims, retain the author's facts, and show revisions as diffs. It should be replaceable: local and remote models are implementation choices, not the product's identity.

For discovery, a useful answer is not a leaderboard of subscriber counts. It is a small set of candidates with evidence, tradeoffs, exclusions, and confidence. “There is no suitable subreddit” is a successful result when that is the honest conclusion.

For scheduling, intelligence means respecting context: community-specific cooldowns, duplicate-content policies, the user's quiet hours, rule changes, account eligibility, and promises already made. A scheduler should often slow the user down.

## Trust is a feature

The tool will hold account credentials, unpublished writing, behavioral history, and possibly commercially sensitive links. Trust therefore shapes the architecture rather than appearing as a settings page later.

### Local ownership

The default system of record lives on the user's device in documented, exportable formats. Network calls are attributable to a feature the user invoked. A hosted component is optional and narrowly scoped.

### Meaningful consent

Before sending content to a foundation-model provider, `redditctl` should show which provider and account are active and what classes of data may leave the device. Authentication uses supported provider flows, never captured browser cookies or private session tokens. Before changing Reddit state, it should show the exact post, comment, edit, or deletion. Scheduled approval is still approval only when the intended content and target are fixed and auditable.

### Minimal analytics

Link measurement should answer whether a link was followed, not who followed it. Aggregate counts, short raw-event retention, bot filtering, and transparent redirect behavior are sufficient. Fingerprinting, cross-site profiles, and identity enrichment are outside the vision.

### Visible uncertainty

Unavailable metrics stay unavailable. Incomplete rules stay marked incomplete. Model judgments carry reasons and confidence, not a false compliance badge. Failures are surfaced in the TUI and audit log; they are not silently retried forever.

## Community safety

Reddit is a network of communities, not a distribution channel. The product should encode that distinction.

It will not optimize for maximum posting frequency, automate engagement, generate deceptive personas, coordinate votes, evade bans or rate limits, or help disguise repeated promotion. It should detect materially similar scheduled posts, warn about cross-post and self-promotion rules, and require stronger review as actions become more repetitive.

Automation must remain bounded:

- Reading, organizing, comparing, and drafting can be highly automated.
- Publishing can be scheduled after an explicit preview and approval.
- Material rule changes invalidate approval.
- Replies should not be autonomously generated and posted.
- Deletion and other difficult-to-reverse actions require fresh confirmation.

The aim is not to guarantee moderator acceptance. Only moderators can interpret and enforce their community's rules. The aim is to make good-faith compliance easier and mistakes more obvious.

## Product pillars

### 1. A durable account memory

The user gets a searchable history of their submissions, comments, drafts, metrics, links, and commitments. Measurements preserve their source and timestamp. Exports are useful without `redditctl`, and deleting the local history is straightforward.

### 2. Explainable community discovery

Recommendations connect a proposed contribution to concrete community evidence. Users can understand, challenge, and tune the ranking. Relevance, rules, culture, and eligibility outweigh raw audience size.

### 3. Rule-aware authorship

Rules are captured as versioned source material and checked at drafting and publication time. LLM assistance helps adapt structure and tone while preserving facts and authorship. Every generated draft remains editable plain text.

### 4. Responsible orchestration

The scheduler handles time zones, restarts, retries, spacing, approvals, and permitted thread updates. Its most important states are not only “queued” and “sent,” but also “needs review,” “rules changed,” “ineligible,” and “cancelled.”

### 5. Privacy-preserving feedback

Post metrics and optional redirect counts create a feedback loop without building reader dossiers. The product helps users learn which contributions resonate, while avoiding claims that noisy community reactions reveal objective content quality.

## A day in the intended product

A maintainer imports notes for a release. `redditctl` suggests two communities and rejects three others with reasons. The maintainer chooses one, synchronizes its rules, reviews the exact context that will be sent, and asks the configured foundation model for a draft. The result flags that the title sounds promotional and that a project affiliation must be disclosed.

After revision, the user previews the exact submission and schedules it for a suitable local time. A second, similar post is automatically spaced a week later because that community permits it and the user approves the variation. Overnight, a rule changes; the second action moves to “needs review” instead of publishing.

The first post's score and replies are recorded at consistent intervals. An optional first-party redirect reports aggregate clicks. Three days later, the tool reminds the maintainer about a promised benchmark update and prepares—but does not post—a follow-up comment. Months later, the full history can be exported as JSON and the redirect events can be deleted independently.

That is the standard: useful automation that creates more awareness, not less.

## Success measures

Early success should be evaluated through reliability and judgment rather than volume:

- users can identify their best-performing contributions at comparable ages;
- scheduled actions execute once, at the intended time, or fail visibly and safely;
- rule changes are detected before they cause an avoidable submission;
- users accept subreddit recommendations for understandable reasons and frequently reject poor fits;
- drafts require less editing while retaining the user's facts and voice;
- promised updates are completed more consistently;
- credentials do not appear in logs, exports, prompts, or crash reports;
- every remote data transfer and Reddit mutation can be explained from the audit trail.

Posting frequency, total karma, and raw click count are diagnostic metrics, not north-star goals. Optimizing them directly would reward behavior the product is intended to temper.

## Boundaries and non-goals

The project does not aim to become:

- a general social-media management suite;
- a multi-account growth or influence platform;
- an autonomous content farm;
- a vote, comment, direct-message, or moderation bot;
- a data broker or reader-identification service;
- a permanent archive of other people's deleted content;
- a promise of rule compliance, placement, engagement, or business results.

Moderation tooling may be a worthwhile separate project, but it should not distort this one. Browser and desktop interfaces may eventually share the same core, but terminal quality comes first.

## Delivery horizons

### Horizon 1: earn read access

Build a dependable, read-only account view. Prove authentication, local storage, metric provenance, exports, and terminal accessibility before adding account mutations.

### Horizon 2: earn drafting trust

Capture rules, show their sources and changes, and build a provider-neutral drafting workspace. Start with Gemini's supported installed-app OAuth flow, and make every remote data transfer understandable and attributable.

### Horizon 3: earn write access

Add previewed publishing, then a durable scheduler with idempotency, bounded retries, approval invalidation, and auditability. Treat edits and follow-up comments as distinct actions with distinct permissions.

### Horizon 4: complete the feedback loop

Add explainable discovery and optional click measurement. Test whether recommendations lead to better fit and whether analytics remain useful under a deliberately minimal data policy.

### Horizon 5: make it boringly dependable

Stabilize the command contract, migrations, backups, recovery, packaging, documentation, and accessibility. A tool trusted with an account should be predictable before it is clever.

## Open decisions

Several choices should remain open until prototypes provide evidence:

- whether later releases should add Claude, OpenAI, or local-model adapters after the Gemini MVP;
- how much rule data is available through supported interfaces and what requires user-supplied context;
- the snapshot cadence that is useful without excessive API traffic;
- whether the redirect service ships as a reference deployment or a separately maintained component;
- which recommendation techniques work well with public, policy-compliant data;
- how approval should behave when a scheduled draft changes only cosmetically;
- which operating systems can provide an acceptable credential-storage experience.

These are product decisions with technical consequences. They should be recorded as short decision documents as the project learns.

## The long view

The best version of `redditctl` is quiet. It does not demand a daily streak or encourage another post. It remembers context, reveals constraints, carries out approved work reliably, and gets out of the way.

If it helps people contribute where they belong, write in their own voice, keep promises to readers, and learn without surveilling anyone, it will have fulfilled its purpose.
