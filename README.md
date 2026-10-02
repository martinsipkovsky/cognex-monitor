# Cognex Monitor

A self-hosted web app that watches Cognex vision cameras in one place. It reads
each camera's pass/fail counters (by polling it, or by letting the camera push
its results), keeps **reset-proof running totals** per camera and job, logs
everything to a database, and sends alerts (for example to a WhatsApp group)
when scrap is high or a camera drops off the network.

It is a Python/FastAPI app with a dark-mode web UI, logins with per-user
permissions, and PostgreSQL storage, shipped as a Docker image.

> **Project status: early, not yet validated on real hardware.** All
> communication protocols, including SLMP, have been developed and tested
> against simulators and unit tests only. None has been tested with a real
> Cognex camera or Mitsubishi PLC yet. Expect to adjust protocol settings, and
> please report what works and what doesn't. See
> [Known issues and limitations](docs/known-issues.md).

## Features

- **Many protocols, one file each:** Cognex Data Channel, Modbus/TCP, generic
  TCP / Native Mode, TCP and UDP listeners (the camera pushes data to the app),
  Mitsubishi SLMP / MC protocol (as client or as a fake PLC the camera writes
  to), PROFINET via a gateway, and a built-in simulator.
- **Reset-proof counters:** if an operator resets the counters on the camera,
  the running totals keep going. A job change freezes the old job's totals and
  starts new ones.
- **Production state:** a camera that stops counting for its idle timeout is
  shown grayed out and gets no scrap alerts, so idle lines don't cause false
  alarms.
- **Camera view:** an OK/NOK chart over 1 h, 8 h, 24 h or 7 days, plus manual
  Start/Stop of production.
- **Alerts:** scrap rate, fail count and disconnect rules with a cooldown,
  delivered through pluggable providers (webhook, Green API, Meta Cloud API).
- **Users and permissions:** login required, with granular permissions per user.
- **Camera export/import** as JSON, and an admin **Database tab** to move the
  app to another PostgreSQL server.
- **Backups:** download all data as one file, import it again, and automatic
  scheduled backups to an FTP/FTPS server, with a reminder when the last
  backup is more than a week old.

## Quick start (build from source)

You need Docker with the Compose plugin.

```bash
git clone <this repository> cognex-monitor
cd cognex-monitor
cp .env.example .env          # set SECRET_KEY and passwords before real use
docker compose up -d --build
```

Open <http://localhost:8000> and sign in as `Admin` / `1234`. Change that
password straight away under *Account*.

To try it without any hardware, add a camera with the **Simulated camera**
protocol on the Cameras tab.

## Documentation

| Guide | What it covers |
|---|---|
| [Installation and deployment](docs/installation.md) | Building from source, running on a server, firewall ports, updates, backups |
| [Configuration](docs/configuration.md) | Environment variables and the Database tab |
| [User guide](docs/user-guide.md) | Dashboard, cameras, production state, camera view, data, users, export/import |
| [Protocols](docs/protocols.md) | How to connect each camera type, with every config field |
| [Notifications](docs/notifications.md) | Alert rules and WhatsApp group delivery |
| [Development](docs/development.md) | Running locally, tests, project layout, adding a protocol |
| [Known issues and limitations](docs/known-issues.md) | What is untested or doesn't work yet |

## Security notes

- The default admin password (`1234`) and `SECRET_KEY` must be changed before
  the app is reachable by anyone else.
- The app is meant for a plant network. If you expose it to the internet, put
  it behind HTTPS (a reverse proxy) and restrict access.
- The listener ports (5100-5119 by default) accept data from any sender unless
  you set the camera's *Host* field to its IP.

## License

[MIT](LICENSE)
