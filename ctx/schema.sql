-- Shared Context operational schema (SQLite, Python stdlib sqlite3).
-- state.db is a REBUILDABLE artifact: `python -m stead init` drops and
-- recreates these tables, then re-indexes from the markdown source of truth.
-- Knowledge lives in context/*.md; this database is an index + run ledger.

DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS repos;
DROP TABLE IF EXISTS contributions;
DROP TABLE IF EXISTS prompt_versions;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS evals;

-- Mirror of context/tasks/ frontmatter (files are the source of truth).
CREATE TABLE tasks (
    id       TEXT PRIMARY KEY,          -- e.g. task-first-shadow-run
    title    TEXT NOT NULL,
    project  TEXT,                      -- project id (frontmatter relation)
    status   TEXT NOT NULL DEFAULT 'to-do'
             CHECK (status IN ('to-do', 'doing', 'done', 'blocked')),
    path     TEXT NOT NULL,             -- repo-relative markdown path
    created  TEXT NOT NULL,             -- ISO date
    updated  TEXT NOT NULL              -- ISO date
);

-- Mirror of context/repos/ frontmatter (own projects + OSS repos).
-- Files are the source of truth; `stead sync github` upserts these rows.
CREATE TABLE repos (
    id             TEXT PRIMARY KEY,      -- e.g. repo-example-org-example-repo
    title          TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'oss'
                   CHECK (kind IN ('own', 'oss')),
    url            TEXT,                  -- https://github.com/<owner>/<name>
    default_branch TEXT,
    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'paused', 'archived')),
    contributing   TEXT,                  -- CONTRIBUTING url or path
    notes          TEXT,
    path           TEXT NOT NULL,         -- repo-relative markdown path
    created        TEXT NOT NULL,         -- ISO date
    updated        TEXT NOT NULL          -- ISO date
);

-- Mirror of context/contributions/ frontmatter: issues/PRs the user is
-- involved with. GitHub-derived data is PUBLIC; private strategy/notes live
-- in context/documents/ instead. Rebuilt from markdown by `stead init`.
CREATE TABLE contributions (
    id         TEXT PRIMARY KEY,          -- contribution-<owner>-<repo>-<kind>-<number>
    title      TEXT NOT NULL,
    repo       TEXT NOT NULL,             -- repo id (frontmatter relation)
    kind       TEXT NOT NULL CHECK (kind IN ('issue', 'pr')),
    number     INTEGER NOT NULL,          -- GitHub issue/PR number
    url        TEXT,
    role       TEXT NOT NULL DEFAULT 'author'
               CHECK (role IN ('author', 'assignee', 'reviewer')),
    state      TEXT NOT NULL DEFAULT 'open'
               CHECK (state IN ('open', 'closed', 'merged')),
    ci         TEXT NOT NULL DEFAULT 'none'
               CHECK (ci IN ('pending', 'pass', 'fail', 'none')),
    review     TEXT NOT NULL DEFAULT 'none'
               CHECK (review IN ('requested', 'approved', 'changes', 'none')),
    method     TEXT NOT NULL DEFAULT 'spec-kit'
               CHECK (method IN ('builtin', 'spec-kit')),
    visibility TEXT NOT NULL DEFAULT 'public',
    path       TEXT NOT NULL,             -- repo-relative markdown path
    created    TEXT NOT NULL,             -- ISO date
    updated    TEXT NOT NULL              -- ISO date
);

-- Versioned factory prompts: testing -> production -> retired.
CREATE TABLE prompt_versions (
    factory  TEXT NOT NULL,             -- e.g. weekly-project-status
    version  TEXT NOT NULL,             -- e.g. v1
    status   TEXT NOT NULL DEFAULT 'testing'
             CHECK (status IN ('testing', 'production', 'retired')),
    path     TEXT NOT NULL,             -- repo-relative prompt markdown path
    created  TEXT NOT NULL,
    PRIMARY KEY (factory, version)
);

-- One row per factory run (or manually logged run). Append-only ledger.
CREATE TABLE runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    factory        TEXT NOT NULL,
    task_ref       TEXT NOT NULL,       -- unit of factory work (project id for status factory)
    project        TEXT,                -- project id, when applicable
    prompt_version TEXT NOT NULL,
    mode           TEXT NOT NULL DEFAULT 'shadow'
                   CHECK (mode IN ('shadow', 'live')),
    bundle_path    TEXT,                -- repo-relative run directory / bundle
    output         TEXT,                -- generated text, supplied by human/agent
    note           TEXT,                -- human review note. Never replaces output.
    verdict        TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|pass|fail
    created        TEXT NOT NULL        -- ISO UTC timestamp
);

-- Eval cases loaded from factories/*/evals/*.json at init time.
CREATE TABLE evals (
    id            TEXT PRIMARY KEY,
    factory       TEXT NOT NULL,
    title         TEXT NOT NULL,
    input         TEXT NOT NULL,        -- description of the test input
    pass_criteria TEXT NOT NULL,        -- how judgement is made
    path          TEXT NOT NULL
);
