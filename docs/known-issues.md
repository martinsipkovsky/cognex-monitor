# Known issues and limitations

## Not tested on real hardware

Every protocol (Data Channel, Modbus/TCP, Native Mode, TCP and UDP listeners,
SLMP client, SLMP server, PROFINET gateway) has only been tested against
simulators and automated tests. **None has been run against a real Cognex
In-Sight camera or a real Mitsubishi PLC.** Field layouts, register widths,
word order and SLMP framing in particular may need adjusting. Reports from
real installations are very welcome.

## Data Channel event mode drops consecutive passes

With the `datachannel` protocol in `mode: "event"`, each poll reads one record
and reports it as raw pass = 1 or fail = 1. The counter logic only counts
*increases* in raw values, so two passes in a row look like "1 then 1" and the
second one is not counted (the same applies to consecutive fails). Parts the
camera sends between polls are also missed, because only one record is read
per poll.

**Workaround:** use `counter` mode (have the camera send its running totals),
or use the **TCP listener** or **UDP listener** in event mode, which count every
record the camera pushes.

## PROFINET is gateway mode only

Native PROFINET IO is not supported and can't be from a user-space Python app.
The `profinet` driver reads counters through a PROFINET-to-Modbus/TCP gateway
or a PLC that exposes the data over Modbus/TCP. See
[Protocols](protocols.md#profinet-profinet-gateway-mode-only).

## WhatsApp groups need your own gateway

Meta's official API can't post to WhatsApp groups. Group alerts need a
WhatsApp gateway service that you set up and run (or a paid third-party one
such as Green API). See [Notifications](notifications.md).

## Counts lost across a camera reset

If a camera's counters are reset between two readings, parts counted after the
last reading and before the reset can't be seen. Running totals are never
reduced. A shorter poll interval, or a push protocol, narrows the gap.

## Single app instance

The poller and the listeners run inside the web process. Run one app
container per database; several replicas would poll each camera several times
and fight over listener ports.
