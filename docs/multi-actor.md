# Several people and agents

Stead is no longer a single-operator notebook. Several humans and several
agents may read and write the same checkout. The files stay the source of
truth. Git is how those writers share. SQLite is not replaced.

## Why SQLite stays

`state.db` is an index. `stead init` rebuilds it from markdown. It is
gitignored on purpose, so two people never merge a binary database.

A shared Postgres (or any server database) would only be worth it if the
database became the place knowledge lives. That would throw away the reason
the files exist: you can leave, clone, and still have the notes. Multi-user
does not require that.

Each checkout keeps its own index. Writers share `context/*.md` through git,
the same way they share code. Concurrent edits are git conflicts in text,
which a person can read. They are not lock fights inside a database file.

SQLite is a poor database to put on a network share. Do not point two
machines at one `state.db`. Give each machine its own index.

A future hosted Stead, if it exists, would still store knowledge as markdown
and keep a database only as that server's index. That hosted index might be
Postgres because many processes would write it. It would still not be the
source of truth. That host is not this release.

## What actually has to change

Identity, not storage.

An **actor** is a human or an agent. One markdown file per actor:

```yaml
---
id: actor-ada
type: actor
title: Ada
created: 2026-11-21
updated: 2026-11-21
status: active
kind: human          # human | agent
---
```

`kind: agent` is for a coding agent that writes here. The file can name the
tool. It does not store an API key.

Objects may set `actor:` to the id of whoever last wrote them. That is
attribution, not a login. Git history remains the audit trail.

## How sharing works

1. One git remote. Humans and agents clone it.
2. Each clone runs `stead init` and gets its own `state.db`.
3. Writes go to markdown, then get committed.
4. Pull before a long edit. If two people change the same file, git shows a
   text conflict. Do not invent a silent merge in the database.

Two ways to share:

- **Several clones.** Each person runs a loopback cockpit. They meet in git.
  Each clone has its own `state.db`.
- **One shared server.** Docker runs a single process with an access token.
  Several browsers use that one index. Do not scale the container. See
  [Deploy](deploy.md).

A normal `stead ui` stays on loopback even after you choose Shared server.
The choice is recorded in gitignored `stead.json`. The open port is the
container, started with `STEAD_ACCESS_TOKEN` set.

## What is not built yet

- No accounts, passwords, or sessions.
- No per-object permission checks in the CLI. If you can write the file, you
  can write the object. Repository access is the permission.
- `actor:` is stamped when someone is selected (`stead actor use` or Settings).
  It is not a login.
- Agents are not registered for you. Add an actor file when a new agent
  starts writing.

## Private notes

`context/documents/` and `context/meetings/` are still private strategy.
Pushing the Stead application to GitHub does not mean every checkout's notes
should be public. A team that shares a private remote can share those notes.
A public project remote should not contain one person's private strategy.
Keep private checkouts private. Contribution files remain the public cache.
