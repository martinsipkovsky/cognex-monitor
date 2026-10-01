# Installation and deployment

Cognex Monitor runs as two containers: the web app and a PostgreSQL database.
There are two ways to get the app image:

1. **Build it from this source code** (works for everyone).
2. **Pull a prebuilt image** from a Docker registry (only if you have access to
   one, see below).

## Requirements

- Docker Engine 24+ with the Compose plugin (`docker compose`), on Linux,
  Windows or macOS. Images build for `linux/amd64` and `linux/arm64`.
- Network access from the server to the cameras (for polled protocols) and
  from the cameras to the server (for listener protocols).

## Option 1: build from source

```bash
git clone <this repository> cognex-monitor
cd cognex-monitor
cp .env.example .env
```

Edit `.env` and set at least:

| Variable | Set it to |
|---|---|
| `SECRET_KEY` | A long random string (e.g. `openssl rand -hex 32`) |
| `POSTGRES_PASSWORD` | A password for the bundled database |
| `DEFAULT_ADMIN_PASSWORD` | The first admin's password (only used on first start) |

Then build and start:

```bash
docker compose up -d --build
```

The app is at `http://<server>:8000` (change the host port with `WEB_PORT`).
To update later, pull the new source and run the same command again.

The root `docker-compose.yml` has both `build: .` and an `image:` name. With
`--build` it builds locally and tags the result with that name; nothing is
pushed anywhere.

## Option 2: prebuilt image

`deploy/docker-compose.yml` runs a prebuilt image without any source code on
the server. It points at `azanar666/cognex-monitor:latest`, which is a
**private** Docker Hub repository; only accounts given access can pull it.
To use your own registry instead, build and push the image yourself and change
the `image:` line:

```bash
docker buildx build --platform linux/amd64,linux/arm64 \
  -t <your-registry>/cognex-monitor:latest --push .
```

On the server, put `deploy/docker-compose.yml` and `deploy/.env.example` in one
folder, then:

```bash
cp .env.example .env          # set SECRET_KEY, POSTGRES_PASSWORD, admin password
docker login                  # only needed for a private repository
docker compose up -d
```

`pull_policy: always` makes `docker compose up -d` fetch the newest image each
time, so updating the server is the same command.

## Ports and firewall

| Port | Protocol | Used by |
|---|---|---|
| `8000` (`WEB_PORT`) | TCP | Web UI and API |
| `5100-5119` (`LISTEN_PORTS`) | TCP and UDP | Cameras that push data: TCP listener, UDP listener, SLMP server. One port per camera. |

Compose publishes the whole listener range on both TCP and UDP. Open it in the
host firewall too, for example:

```bash
sudo ufw allow 5100:5119/tcp
sudo ufw allow 5100:5119/udp
```

Polled protocols (Data Channel, Modbus, Native Mode, SLMP client, PROFINET
gateway) need no inbound ports; the app connects out to the camera or PLC.

If you change `LISTEN_PORTS`, the app and the published ports both follow it,
since compose uses the same variable for each.

## Data and backups

Two Docker volumes hold everything that must survive an update:

| Volume | Contents |
|---|---|
| `db_data` | The bundled PostgreSQL database: users, cameras, counters, readings, alerts |
| `app_data` | `/srv/data` in the app container: the database choice saved on the Database tab |

Back up the database with:

```bash
docker compose exec db pg_dump -U cognex cognex > cognex-backup.sql
```

`docker compose down` keeps the volumes; `docker compose down -v` deletes
them, and all data with them.

## First login

Sign in with `DEFAULT_ADMIN_USER` / `DEFAULT_ADMIN_PASSWORD` (default
`Admin` / `1234`). These are only used to create the first account on an empty
database; changing them later has no effect. Change the password under
*Account* and create other users under *Users*.

## Health check

`GET /healthz` returns 200 when the app is up. The image's Docker
`HEALTHCHECK` uses it.
