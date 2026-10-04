-- 0001_init: the schema from docs/spec.md section 5, plus three additions the spec was
-- silent on (each marked ADDED with its reason).
--
-- Everything lives in its own schema so this app can share a Neon project with others
-- without table-name collisions, and so `DROP SCHEMA changelog_forge CASCADE` is a clean
-- uninstall.

CREATE SCHEMA IF NOT EXISTS changelog_forge;

CREATE TABLE IF NOT EXISTS changelog_forge.repos (
    id             bigserial PRIMARY KEY,
    owner          text NOT NULL,
    name           text NOT NULL,
    default_branch text,
    fetched_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (owner, name)
);

-- The (repo, sha) cache. A commit never changes, so a row here is never refetched.
CREATE TABLE IF NOT EXISTS changelog_forge.commits (
    repo_id    bigint NOT NULL REFERENCES changelog_forge.repos (id) ON DELETE CASCADE,
    sha        text NOT NULL,
    author     text,
    date       timestamptz,
    message    text NOT NULL,
    parents    smallint NOT NULL DEFAULT 1,
    html_url   text NOT NULL DEFAULT '',
    pr_number  integer,
    pr_title   text,
    pr_body    text,
    pr_url     text,
    labels     jsonb NOT NULL DEFAULT '[]'::jsonb,
    files      jsonb,              -- NULL = not fetched, [] = touched nothing
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (repo_id, sha)
);

-- ADDED: ETag cache for the repo and compare calls. A 304 does not count against an
-- authenticated client's GitHub rate limit. `body` holds the slimmed response we use,
-- never the raw one (a compare response can carry megabytes of patches).
CREATE TABLE IF NOT EXISTS changelog_forge.http_cache (
    key        text PRIMARY KEY,
    etag       text NOT NULL,
    body       jsonb NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS changelog_forge.runs (
    id              uuid PRIMARY KEY,
    repo_id         bigint REFERENCES changelog_forge.repos (id) ON DELETE SET NULL,
    repo            text NOT NULL,     -- "owner/name", denormalised for display
    base            text NOT NULL,
    head            text NOT NULL,
    status          text NOT NULL DEFAULT 'queued' CHECK (status IN
                    ('queued', 'collecting', 'mapping', 'reducing', 'verifying', 'done', 'failed')),
    audiences       text[] NOT NULL DEFAULT ARRAY['user', 'dev'],
    commit_count    integer,
    group_count     integer,
    prompt_versions jsonb NOT NULL DEFAULT '{}'::jsonb,
    routing         jsonb NOT NULL DEFAULT '{}'::jsonb,
    usage           jsonb,
    error           text,
    -- ADDED: rate limiting and resumable processing.
    client_key      text,              -- sha256(salt + client IP); never the IP itself
    attempts        smallint NOT NULL DEFAULT 0,
    lease_until     timestamptz,       -- set while a /process request owns the run
    created_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX IF NOT EXISTS runs_client_recent ON changelog_forge.runs (client_key, created_at);
CREATE INDEX IF NOT EXISTS runs_created ON changelog_forge.runs (created_at);

-- Append-only progress stream; (run_id, seq) is also the SSE event id.
CREATE TABLE IF NOT EXISTS changelog_forge.run_events (
    run_id  uuid NOT NULL REFERENCES changelog_forge.runs (id) ON DELETE CASCADE,
    seq     integer NOT NULL,
    at      timestamptz NOT NULL DEFAULT now(),
    kind    text NOT NULL,
    message text NOT NULL,
    data    jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, seq)
);

-- ADDED: per-stage checkpoints (collected input, each map group, each reduce draft) so a
-- serverless request killed at its time limit resumes instead of starting over.
CREATE TABLE IF NOT EXISTS changelog_forge.run_checkpoints (
    run_id     uuid NOT NULL REFERENCES changelog_forge.runs (id) ON DELETE CASCADE,
    key        text NOT NULL,
    data       jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, key)
);

CREATE TABLE IF NOT EXISTS changelog_forge.run_outputs (
    run_id   uuid NOT NULL REFERENCES changelog_forge.runs (id) ON DELETE CASCADE,
    audience text NOT NULL CHECK (audience IN ('user', 'dev')),
    markdown text NOT NULL,
    json     jsonb NOT NULL,
    verified jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (run_id, audience)
);

CREATE TABLE IF NOT EXISTS changelog_forge.eval_runs (
    id                 uuid PRIMARY KEY,
    golden_set_version text NOT NULL,
    scores             jsonb NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
