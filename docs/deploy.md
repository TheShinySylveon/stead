# Deploying for several people

Single-user is the default. `stead ui` binds to this computer and does not ask
for a password. Multi-user is a shared server: one process, one index, several
browsers. Each person signs in. The access token is only the bootstrap until
the first account exists.

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

Copy the token, then pull the published image:

```bash
# PowerShell
$env:STEAD_ACCESS_TOKEN = "the-token"
docker compose pull
docker compose up --no-build
```

```bash
# bash
export STEAD_ACCESS_TOKEN="the-token"
docker compose pull
docker compose up --no-build
```

Open `http://127.0.0.1:8765/`. Until an account exists, enter the token. Then
add a person and sign in by name. The session cookie stays in that browser.
Passwords are hashes in the private volume, not in `context/`.

```bash
docker compose exec stead python -m stead actor add --title "Ada" --kind human
docker compose exec stead python -m stead account add --name ada --actor actor-ada
```

The password is printed once. `stead account list` never prints it. After
that account exists, the token no longer signs anyone in. You can leave
`STEAD_ACCESS_TOKEN` unset on the next start. The private volume keeps the
hashes.

## Image

The published image is `ghcr.io/theshinysylveon/stead`. `main` pushes `latest`
and the commit sha after the tests pass. Pull requests build the image and
do not push it. The package is public. A pull does not need a token.

```bash
docker compose pull
docker compose up --no-build
```

`docker compose up --build` still builds this checkout. The image sets
`STEAD_DEPLOYMENT=multi` and `STEAD_BIND=0.0.0.0`. `context/` is a volume, so
notes survive a rebuild. `private/` is a second volume. Password hashes live
there, not in `context/`. `state.db` is recreated if the container is new.
That is safe. The files are the source of truth.

Do not publish port 8765 to the public internet without a TLS proxy in front.
A sign-in is a password for one actor. It is not a second database.

## Settings

After the first project exists, Settings can switch deployment, rotate the
token, add a sign-in, and add actors (`kind: human` or `kind: agent`).

```bash
python -m stead actor add --title "Ada" --kind human
python -m stead actor add --title "Review bot" --kind agent
python -m stead actor list
python -m stead account add --name ada --actor actor-ada
python -m stead account list
python -m stead account reset --name ada
```

Actors are attribution. An account is the sign-in for one actor on a shared
server. This computer still has no login. Repository or host access is still
the real permission if you also share the files through git.

## What this is not

- Not a second database. Do not replace SQLite for this.
- Not a password manager. Hashes live in the private volume, not in git.
- Not a license to put `state.db` on a network share.
