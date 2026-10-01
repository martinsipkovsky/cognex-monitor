# Configuration

## Environment variables

Set these in `.env` next to `docker-compose.yml`. Compose reads it
automatically. When running without Docker, the app also reads `.env` from the
working directory.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | local SQLite file `./cognex.db` | SQLAlchemy URL. Compose sets it to the bundled Postgres container. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `cognex` / `cognex` / `cognex` | Credentials for the bundled Postgres container (compose only) |
| `SECRET_KEY` | `change-me-in-production` | Signs login session cookies. **Change it.** |
| `DEFAULT_ADMIN_USER` / `DEFAULT_ADMIN_PASSWORD` | `Admin` / `1234` | First admin account, created only when the database has no users |
| `POLL_ENABLED` | `true` | Run the background poller. Set `false` for tests or a read-only instance. |
| `WEB_PORT` | `8000` | Host port for the web UI (compose only) |
| `LISTEN_PORTS` | `5100-5119` | Port range, TCP and UDP, for cameras that push data |
| `DATA_DIR` | `./data` (`/srv/data` in Docker) | Where the Database tab saves its setting |

Login sessions last 12 hours.

## Database tab (admins only)

The *Database* tab shows which database the app is using and lets an admin
switch to another PostgreSQL server:

1. Enter the new server's connection details and press **Test**.
2. Optionally tick the option to **copy all current data** into it. The target
   database must be empty for this.
3. **Save**, then **Restart** the app so it reconnects.

The tab also shows ready-to-copy `docker run` and `docker compose` snippets for
starting a new PostgreSQL container.

The choice is saved in `DATA_DIR` (the `app_data` volume), so it survives image
updates. If the saved database can't be reached at startup, the app falls back
to `DATABASE_URL` so you can still log in and fix it. Removing the saved
setting returns the app to `DATABASE_URL` after a restart.

## Schema changes

The app creates its tables on startup and adds new columns to an existing
database automatically when an update needs them. There is no separate
migration step.
