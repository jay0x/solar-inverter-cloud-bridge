# Product and technical principles

These rules define the current product and its implementation boundaries.

| Area | Rule |
| --- | --- |
| Product | One integration in Home Assistant Core: Solar Inverter Cloud Bridge, domain `solar_inverter_bridge` |
| Runtime | No separate app, MQTT bridge or second backend |
| Transport | Collector-initiated EyeBond AT/binary sessions on TCP 502/18899/38899; one active inverter I/O owner per physical path |
| Authorization | Manual controls require an active HA administrator context; all interfaces share one executor |
| Availability | Implemented writable settings are available after profile acceptance and fresh read checks; hardware R/O, transport and unresolved-operation barriers apply |
| Numeric settings | Preserve exact scaling, encoding and known dependencies; wire limits are not manufacturer operating limits |
| Commands | Persist intent and send claim before transmission; verify independently; never replay writes after reconnect/restart |
| Compatibility | Recognize unlisted models from read evidence and offer source-defined profiles for explicit acceptance |
| Profile binding | Bind acceptance to the definition digest, route and observed signature; changes require explicit recheck |
| Data ownership | SQLite owns the ledger, Recorder owns measurement history, HA registries own names and overrides |
| Network configuration | DNS and routing belong to the router or local resolver; the integration only generates instructions |
| Maintenance | Clock sync and Wi-Fi recovery are separate opt-ins; recovery is capability-checked and durably rate-limited |
| Automations | User automations and energy optimization belong outside the integration |
| Documentation | Public content is en-US and describes current capabilities, usage, limitations and evidence; internal development chronology stays private |
| Licensing | MPL-2.0 with required third-party copyright and permission notices preserved |

## Implementation boundaries

All three listeners share dialect detection. A failed listener is reported without
disabling healthy listeners; no silent port fallback is made. AT's auxiliary
channel is not another poller. Source IP, port and retail brand do not identify a map.

Same-profile binding renewal retains HA device/entity IDs and cannot bypass an
unresolved operation. Unknown manufacturer bounds do not make a known R/W field
read-only; its warning and documented validation remain visible.

## Publication and qualification

Fixtures are software evidence, and packet readback is not proof of physical effects.
Publication and hardware-changing work require explicit scope. Recheck documentation
against the exact release candidate. Follow [publication](publication.md),
[documentation policy](documentation-policy.md) and [verification](../verification/README.md).
