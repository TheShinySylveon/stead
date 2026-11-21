# Deploying for several people

Single-user is the default. `stead ui` binds to this computer and does not ask
for a password. Multi-user is a shared server: one process, one index, several
browsers. It does not start without an access token.

SQLite stays the index. Do not run two containers against one `state.db`.
The compose file is one service on purpose.

## Choose at first run

Welcome asks:

- **This computer.** Loopback. No login.
- **Shared server.** Writes `stead.json` (gitignored) and shows an access
  token once. This window does not open the port. You start Docker yourself.

```bash
python -m stead welcome --title "Team notes" --deployment multi
```

Copy the token, then:

```bash
# PowerShell
$env:STEAD_ACCESS_TOKEN = "the-token"
docker compose up --build
```

```bash
# bash
export STEAD_ACCESS_TOKEN="the-token"
docker compose up --build
```

Open `http://127.0.0.1:8765/` and enter the token. The cookie stays in that
browser. The token is not written into `context/`.

## Image

`Dockerfile` is a Python 3.12 image. It sets `STEAD_DEPLOYMENT=multi` and
`STEAD_BIND=0.0.0.0`. `context/` is a volume, so notes survive a rebuild.
`state.db` is recreated if the container is new. That is safe. The files are
the source of truth.

Do not publish port 8765 to the public internet without a TLS proxy in front.
The token is a shared password, not a user account.

## Settings

After the first project exists, Settings can switch deployment, rotate the
token, and add actors (`kind: human` or `kind: agent`).

```bash
python -m stead actor add --title "Ada" --kind human
python -m stead actor add --title "Review bot" --kind agent
python -m stead actor list
```

Actors are attribution. They are not logins. Anyone with the access token can
use the shared cockpit. Repository or host access is still the real permission
if you also share the files through git.

## What this is not

- Not a second database. Do not replace SQLite for this.
- Not accounts or per-person passwords.
- Not a license to put `state.db` on a network share.
