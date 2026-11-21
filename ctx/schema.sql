-- Shared Context operational schema (SQLite, Python stdlib sqlite3).
-- state.db is a REBUILDABLE artifact: `python3 -m ctx init` drops and
-- recreates these tables, then re-indexes from the markdown source of truth.
-- Knowledge lives in context/*.md; this database is an index + run ledger.

DROP TABLE IF EXISTS tasks;
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
