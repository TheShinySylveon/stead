# Getting started

Stead is a local app. The command is `stead`. You clone it, run it, and it
keeps your notes on this machine. This computer does not ask you to sign in.
It does not call a model unless you ask for a draft.

## Requirements

- Python 3.11 or newer. The standard library is enough. There is no `pip install`.
- Git, if you want history. The app does not require a remote.
- Optional: the [GitHub CLI](https://cli.github.com) (`gh`), signed in, if you
  want a read-only cache of your issues and pull requests, or if a repo is
  allowed to open or merge a pull request.
- Optional: Docker, if several people will use one shared server. The image
  is `ghcr.io/theshinysylveon/stead`. See [Deploy](deploy.md).
- Optional: [uv](https://docs.astral.sh/uv/) and `specify-cli`, if you later
  want Spec Kit scaffolding in a code repository. The app works without them.

Check Python:

```bash
python3 --version
```

On Windows, `python` is often the same interpreter.

## Install

```bash
git clone https://github.com/TheShinySylveon/stead.git
cd stead
python -m stead ui
```

That opens a browser on `127.0.0.1`. A fresh checkout has an empty `context/`
folder. The page asks for a project title, an optional GitHub URL, and whether this
copy is for this computer or a shared Docker server. Details:
[First run](first-run.md) and [Deploy](deploy.md).

Without a browser:

```bash
python -m stead welcome --title "My Project"
```

`state.db` is created on first use. It is an index. Delete it and the markdown
files still have your notes. `python -m stead init` rebuilds the index.

## What you get

| Path | What it is |
|---|---|
| `context/` | Your notes. Empty until the first run. Includes `actors/` once you add people or agents. |
| `inbox/` | Unsorted capture. File it into `context/` or delete it. |
| `examples/context/` | Samples. Not part of your data. |
| `factories/` | The three workflows: digest, project status, feature builder. |
| `ctx/` | The CLI and the cockpit. |
| `docs/` | These pages. |

## Tests

From the repository root:

```bash
python -m unittest discover -s tests
```

## Next

- [Concepts](concepts.md), if you want the model before the screens.
- [Cockpit](cockpit.md), if you are staying in the browser.
- [CLI](cli.md), if you want the commands.
