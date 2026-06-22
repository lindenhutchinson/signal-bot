# Deploying signal-bot

Images are built in CI and pulled on the host — the host never builds. Same model
as `oh-hell-online`.

- **`release.sh`** — cut a release from your dev machine. Tags `vX.Y.Z`, pushes it,
  publishes a GitHub Release. The tag push triggers
  [`.github/workflows/release.yml`](../.github/workflows/release.yml), which runs
  lint + tests then builds and pushes two images to GHCR:
  - `ghcr.io/lindenhutchinson/signal-bot/bot`
  - `ghcr.io/lindenhutchinson/signal-bot/signal-bridge`
- **`update.sh`** — run on the host. Pulls the latest images and (re)starts the
  stack via [`../docker-compose.prod.yml`](../docker-compose.prod.yml).

## Cut a release (dev machine)

```bash
./deploy/release.sh            # patch bump (or pass an explicit X.Y.Z)
# watch the build:
gh run watch $(gh run list --workflow=release.yml -L1 --json databaseId -q '.[0].databaseId')
```

The GHCR packages are private by default. Either make them public (GHCR package
settings → Change visibility), or `docker login ghcr.io` on the host with a PAT
that has `read:packages` before the first pull.

## First deploy (on the Mac Mini — `ssh mac`)

This runs **alongside** the home media server. It is its own compose project
(`-p signal-bot`) with its own network and publishes no ports, so it does not
touch the media stack. Memory is capped (`mem_limit`): ~448 MB bridge + ~320 MB
bot, well within the Colima VM's headroom.

```bash
ssh mac
git clone https://github.com/lindenhutchinson/signal-bot.git ~/signal-bot
cd ~/signal-bot
cp .env.example .env && nano .env        # paste in your prepared .env
```

Bring up just the bridge to register the bot's Signal number (one time):

```bash
SIGNALBOT_IMAGE_TAG=latest \
  docker compose -p signal-bot -f docker-compose.prod.yml up -d signal-cli-rest-api
```

Then follow the **registration + join-group** steps in the main
[README](../README.md#2-register-the-bots-number-one-time) — solve the captcha,
register `BOT_NUMBER`, join the group via its invite link, and copy the group id
into `ALLOWED_GROUP_IDS` in `.env`. The bridge is reachable at
`http://127.0.0.1:8080` on the host for those `curl` calls.

Start the full stack:

```bash
./deploy/update.sh
```

Once registered and joined, comment out the `ports:` block on
`signal-cli-rest-api` in `docker-compose.prod.yml` (nothing needs to reach the
bridge from the host anymore) and re-run `./deploy/update.sh`.

## Migrating an existing account (instead of registering fresh)

If the bot is already registered on another machine and you're moving it here,
copy the signal-cli account store into the **named volume** rather than
re-registering (re-registering takes the number over and breaks the old host).

1. On the old machine, **stop the bot** (`docker compose down`) so the account db
   is flushed, then zip its signal-cli data dir (the `./signal-cli-config` next to
   its compose file, or the contents of `~/.local/share/signal-cli`).
2. Copy the zip here and extract it to `~/signal-bot/signal-cli-config/` (so
   `signal-cli-config/data/<id>` and `data/accounts.json` exist).
3. Seed the named volume from it, owned by uid 1000 (the uid signal-cli runs as):

   ```bash
   docker volume create signal-bot_signal-cli-config
   docker run --rm \
     -v signal-bot_signal-cli-config:/dest \
     -v ~/signal-bot/signal-cli-config:/src:ro \
     alpine sh -c 'cp -a /src/. /dest/ && chown -R 1000:1000 /dest'
   ```

   (Compose prefixes the volume with the project name, so it's
   `signal-bot_signal-cli-config`.) Then `docker compose -p signal-bot -f
   docker-compose.prod.yml up -d signal-cli-rest-api` and confirm:
   `curl -s http://127.0.0.1:8080/v1/accounts` lists the number. Once the new host
   is confirmed working, retire the old one and delete the extracted
   `signal-cli-config/` dir (the volume is now the source of truth).

> A host bind mount does **not** work for this on macOS/Colima: virtiofs maps the
> files to root and ignores `chown`, so signal-cli (uid 1000) can't write its db.

## Routine updates

```bash
ssh mac 'cd ~/signal-bot && git pull && ./deploy/update.sh'
```

`./data` (history) and `./signal-cli-config` (account keys) persist across updates.
