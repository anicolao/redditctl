CREATE TABLE accounts (
    reddit_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE things (
    fullname TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('submission', 'comment')),
    subreddit TEXT NOT NULL,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    url TEXT,
    permalink TEXT,
    score INTEGER,
    reply_count INTEGER,
    is_self INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thing_fullname TEXT NOT NULL REFERENCES things(fullname) ON DELETE CASCADE,
    observed_at TEXT NOT NULL,
    score INTEGER,
    reply_count INTEGER,
    UNIQUE (thing_fullname, observed_at)
);

CREATE INDEX metric_snapshots_thing_time
    ON metric_snapshots (thing_fullname, observed_at DESC);

CREATE TABLE rule_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subreddit TEXT NOT NULL,
    source_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    UNIQUE (subreddit, content_hash)
);

CREATE INDEX rule_snapshots_subreddit_time
    ON rule_snapshots (subreddit, retrieved_at DESC);

CREATE TABLE drafts (
    id TEXT PRIMARY KEY,
    subreddit TEXT NOT NULL,
    created_at TEXT NOT NULL,
    current_revision INTEGER
);

CREATE TABLE draft_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id TEXT NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    content_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    author_kind TEXT NOT NULL,
    provider TEXT,
    model TEXT,
    rule_hash TEXT,
    UNIQUE (draft_id, revision_number)
);

CREATE TABLE recommendation_runs (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    created_at TEXT NOT NULL,
    results_json TEXT NOT NULL
);

CREATE TABLE scheduled_actions (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    state TEXT NOT NULL,
    due_at TEXT NOT NULL,
    subreddit TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    rule_hash TEXT,
    approved_at TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    lease_until TEXT,
    worker_id TEXT,
    last_error TEXT,
    remote_fullname TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX scheduled_actions_due
    ON scheduled_actions (state, due_at);

CREATE TABLE audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    action_id TEXT,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL
);

CREATE INDEX audit_events_action_time
    ON audit_events (action_id, occurred_at);

CREATE TABLE link_mappings (
    slug TEXT PRIMARY KEY,
    destination TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE link_snapshots (
    slug TEXT NOT NULL,
    bucket_at TEXT NOT NULL,
    referrer_class TEXT NOT NULL,
    bot INTEGER NOT NULL,
    count INTEGER NOT NULL,
    PRIMARY KEY (slug, bucket_at, referrer_class, bot)
);
