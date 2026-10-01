# User guide

## Dashboard

The dashboard shows every camera with its connection state, current job, and
the running pass/fail totals and scrap rate for that job.

Cameras that are not in production (see below) are shown **grayed out**.
Click a camera to open its camera view.

## Cameras tab

Add a camera with:

| Field | Meaning |
|---|---|
| Name | Unique display name |
| Host / Port | For polled protocols: the camera's or PLC's address. For listener protocols: *Port* is the port the app listens on, and *Host* optionally restricts which IP may send (blank = anyone). |
| Protocol | How the app talks to this camera. See [Protocols](protocols.md). |
| Config (JSON) | Protocol settings. The form lists the fields for the chosen protocol. |
| Poll interval | Seconds between reads, for polled protocols |
| Idle timeout | Minutes without a new pass before the camera counts as idle (default 30) |

**Poll now** reads a polled camera immediately, which is the quickest way to
check a new configuration.

### Export and import

**Export** downloads every camera's settings as one JSON file. **Import** reads
such a file: cameras with a new name are added, cameras whose name already
exists are updated. Counters and history are never touched. If any camera in
the file is invalid, nothing is imported.

## How counting works

Every reading gives the camera's raw pass and fail counters and the current
job name. The app adds the **increase** since the previous reading to a running
total for that camera and job.

- **Counter reset on the camera:** the app sees a counter drop, treats the
  new values as counted from zero, and keeps adding. Banked totals are never
  lost, but parts counted between the last reading and the reset can't be
  seen, so poll often enough for your line speed.
- **Job change:** the old job's totals are frozen and a new running total
  starts. If an earlier job comes back, its totals continue where they stopped.

## Production state

A camera is **running** while its pass counter keeps increasing. If the pass
counter does not increase for the camera's idle timeout, the camera becomes
**idle**: it is grayed out on the dashboard and scrap-rate and fail-count
alerts are suppressed, because NOK counts on a stopped line are usually false
signals. The next pass puts it back into production.

Disconnect alerts are still sent for idle cameras.

## Camera view

Opening a camera shows an OK/NOK chart over 1 hour, 8 hours, 24 hours or
7 days, and two buttons:

- **Stop** puts the camera out of production by hand. It stays stopped until
  someone presses Start, even if parts are counted.
- **Start** clears a manual stop and restarts the idle clock. A camera that
  still doesn't count goes idle again after its timeout.

## Data tab

Running totals per camera and job, and the raw reading history, as stored in
the database.

## Notifications tab

Alert rules and delivery providers. See [Notifications](notifications.md).

## Users and permissions

Every page and API call requires a login. A user is either an
**administrator** (full access, including the Database tab) or a normal user
with any of these permissions. Users with `manage_users` create users and
assign permissions. The last administrator can't be deleted.

| Permission | Allows |
|---|---|
| `view_dashboard` | View dashboards and camera data, export camera settings |
| `manage_devices` | Create, edit, delete and import cameras |
| `control_connections` | Start/stop camera connections, polling and production |
| `view_data` | Browse logged readings and counters |
| `manage_notifications` | Configure notification rules and providers |
| `manage_users` | Create users and edit their permissions |

The navigation only shows the tabs a user may open. The Database tab is for
administrators only.

Each user can change their own password under *Account*.
