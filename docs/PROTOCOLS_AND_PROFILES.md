# Ports, collector protocols, and inverter profiles

Solar Inverter Cloud Bridge technical reference for users and contributors.
Current version: integration 0.8.2 / panel 0.16.1. Checks and hardware qualification
are described in `docs/verification/README.md` in the source repository.

**Implemented now:** mixed AT/binary EyeBond on TCP 502/18899/38899, the native
Protocol 4 / model 32771 reference alias within **24 family-grouped profile variants**, and
pre-enrollment compatibility collection, recognition, local analysis and offline
replay. Additional profiles are offered for explicit user acceptance after two
plausible snapshots. Unknown model names are not rejected merely for being absent
from a catalog. See [the complete profile/measurement/control matrix](PROFILE_EXPANSION.md).
Binary and additional-family evidence is **source-derived and simulator-tested**,
not new hardware verification. Inferred profiles may use implemented source-defined
controls after the user accepts the profile warning. Binary collector
reset/management and inverter clock writes remain separately unavailable.

Read the release's own status before configuring a newly documented capability.
A protocol described below is not automatically supported by the installed build.
Installation and UI instructions: [INSTALL.md](INSTALL.md).

## 1. Four independent layers

```text
Wi-Fi collector initiates TCP to a host and port
  -> collector session dialect: AT text or binary EyeBond envelope
    -> inverter payload: Modbus RTU, PI30, PI18, G-ASCII, ...
      -> exact inverter profile: identity, addresses, registers, scales, controls
        -> Home Assistant entities and Recorder history
```

| Layer | Determines | Does not determine |
| --- | --- | --- |
| Network endpoint | Where the TCP connection goes | Frame syntax or supported inverter model |
| Collector dialect | Identity handshake, liveness, framing, routing | Meaning of inverter registers |
| Inverter payload protocol | Request/reply syntax and checksums | Every model-specific register value or setting |
| Inverter profile | Native signature, map, scaling, units, capabilities and limits | Whether a different collector firmware uses the same transport |

A cloud app name, brand, DNS name, or port is useful context, not a replacement
for identifying these layers. Two devices with the same product name may have
different collector firmware, payload protocols, or register maps.

## 2. Connection direction and ports

The collector opens an outgoing connection. The local bridge accepts that
connection in place of the vendor endpoint. HA does not open a standard Modbus
TCP client connection to port 502 on the inverter.

| Port / protocol | Current Bridge behavior | Evidence and intended use |
| --- | --- | --- |
| TCP 18899 | Mixed AT/binary admission; qualified active inverter channel | Current AT hardware reference uses it; binary path is simulator-tested |
| TCP 38899 | Mixed admission; AT remains auxiliary for inverter I/O | The reference collector's second AT connection is not a second inverter or poller; a qualified binary connection is independent of the port |
| TCP 502 | Mixed admission; experimental binary monitoring | Not a standard Modbus TCP service; per-port bind errors are reported |
| UDP/TCP 53 | **No DNS listener in this integration** | DNS belongs to the router or an external resolver. Optional router interception sends requests there |
| UDP 58899 / TCP 8899 | **Not used by this integration** | Some other projects use a UDP callback request and a separate TCP local session. That is a different connection path |
| HTTPS / MQTT cloud endpoints | **Not used for inverter polling/control** | Vendor APIs and web apps are separate interfaces; account credentials are not required here |

The same classifier runs on all three listeners; port numbers do not force a
decoder. Existing AT 38899 auxiliary behavior is retained.

Binding TCP 502 may require suitable host/container permissions and a free port.
The integration reports each listener's readiness and bind error. Healthy listeners
remain available when another bind fails; all-listener failure refuses setup.
Changing the DNS answer cannot work around a missing 502 listener: DNS records
contain an address, not a replacement TCP port.

## 3. DNS and routing

### Start with DNS-only where possible

1. Give HA and the local DNS resolver stable, reachable LAN addresses.
2. Add local answers for the names actually used by the collector, pointing to HA.
3. Ensure the collector queries **that resolver**, through DHCP/device settings or
   optional source-scoped UDP/TCP 53 interception on its gateway.
4. Create a new collector TCP session. An existing cloud connection does not move
   merely because DNS/NAT changed; cached DNS may also need time to expire.
5. Check fresh complete inverter readings, not just a connected socket.

If the collector connects directly to HA on the correct listener port, TCP DNAT
is usually unnecessary. Cached or hardcoded cloud addresses may require it.
Preserve ports by default: 502→502, 18899→18899 and 38899→38899. Port translation does not
convert AT, binary EyeBond, or standard Modbus TCP into each other.

Source-scoped rules use a collector IP or LAN/IoT subnet directly. If an individual
IP is matched, reserve that lease in DHCP. Shared subnet rules are less sensitive
to address changes. HA's source allowlist must still admit the address seen after
any source NAT. Same-subnet DNAT may need a symmetric return path; direct DNS-based
connections on the same LAN normally do not need that hairpin translation.

The bundled Router setup guide generates commands for the selected platform; it
does not execute them. DNS interception and the `*.eybond.com` wildcard start
unchecked. The integration contains no mini-DNS service.

### Collector domains

These roles come from local reference observations or attributed external
implementations/reports. They are not a universal hostname-to-protocol map.

| Name | Reported port / role | Evidence scope |
| --- | --- | --- |
| `dtu_ess.eybond.com` | 18899, AT plus raw RTU | Current reference and external AT implementations |
| `iot3.eybond.com` | 38899, AT identity/heartbeat | Current reference's auxiliary channel |
| `ess.eybond.com` | 502, binary EyeBond | External ANENJI and PowMr implementations |
| `m2m.eybond.com` | 18899 default, SmartValue AT family | External profile default, not proof for every device |
| `iot.eybond.com` | 18899 default, ValueCloud/AT family | External profiles and device reports; inner payload may be G-ASCII |
| `vip1.eybond.com` | 18899 and 502, binary reported | External installation report with evidence limitations |
| `www.shinemonitor.com` | Website; also a binary-502 firmware default | Attributed firmware analysis, not an endpoint observed on the current reference |

`*.eybond.com` is an optional DNS scope covering the listed EyeBond names, not an
additional collector endpoint. Generator suffix rules may also cover the apex
`eybond.com`. A broad suffix override does not add missing transport support.

`api.dessmonitor.com`, `ios.shinemonitor.com`, `dessmonitor.com`, and
`www.dessmonitor.com` are also offered in the domain selector, initially unchecked,
with their API/website roles indicated. Other research names such as
`android.shinemonitor.com`, `android1.shinemonitor.com`, `web.dessmonitor.com`,
`web1.dessmonitor.com`, `api.valueclouds.com`, and `mqtts.valueclouds.com` are
application infrastructure, not established collector targets for this Bridge.
Rewriting an app/API name to HA can interrupt that service for clients of the resolver.

The bundled selectable list is
[`collector-domains.json`](../custom_components/solar_inverter_bridge/frontend/collector-domains.json).
Both the wizard and router guide read the same list. Metadata must distinguish
reported endpoints from supported transports; adding a checkbox does not add a driver.

## 4. Existing AT/raw-RTU transport

After classification, AT admission accepts a full unsolicited identity or sends
`AT+DTUPN?` and validates the returned full
collector product number. Normal liveness uses `AT+HTBT?`, currently every
37 seconds for the qualified AT path. Supported read-only module queries include
firmware, AT version, module type, Wi-Fi status, and configured cloud endpoint.

On the active channel, inverter Modbus RTU requests and responses are transmitted
directly as raw bytes with CRC16. AT identity/heartbeat and inverter RTU are
separate exchanges on the same owned connection. The secondary channel retains
its liveness exchanges but does not run a competing inverter poller.

The current `AT+RESET=S` action restarts the Wi-Fi module, not the inverter's
electrical configuration. Its semantics must not be assumed for a binary collector.
Automatic Wi-Fi recovery is opt-in and rate limited; it cannot reset a module
that has no usable connection to the bridge.

An AT session alone does not prove a Modbus payload: AT-family collectors can also
carry PI30 or G-ASCII. The selected profile determines the inverter payload decoder.

## 5. Binary EyeBond transport

The implementation is independently written from attributed community wire facts.
It is experimental, not a complete manufacturer specification or a hardware claim.

### Envelope

| Byte offset | Size | Field |
| --- | --- | --- |
| 0 | 2 | Transaction ID (TID), unsigned big-endian |
| 2 | 2 | Collector device/tunnel code, unsigned big-endian |
| 4 | 2 | Length L, number of bytes after the first six bytes |
| 6 | 1 | Outer device address / route |
| 7 | 1 | Outer function code |
| 8 | L−2 | Function payload |

Encoding is `>HHHBB`. Total length is `6 + L`, equivalently `8 + payload_length`.
There is no universal magic prefix or additional outer CRC in the reviewed codecs.
TCP can split one frame or combine multiple frames. A reader must retain stream
boundaries and enforce size/deadline limits. Current cap: 4096 total bytes.

### Outer functions

| Function | Meaning | Current scope |
| --- | --- | --- |
| FC1 | Collector heartbeat/startup; includes UTC time/interval in known requests | Qualified bootstrap and liveness |
| FC2 | Read collector parameters | Full PN and supported metadata; validate status and echoed parameter |
| FC3 | Write collector configuration | Not part of initial binary monitoring; no guessed reset/UART/endpoint writes |
| FC4 | Forward a complete request/reply to an inverter | Modbus/ASCII monitoring; source-defined controls for explicitly accepted experimental profiles use the common durable executor |
| 0x11–0x13 | Additional functions named in external sources | Behavior not qualified for implementation here |

FC4 carrying Modbus contains the **complete RTU frame including its CRC**. It is
not a Modbus function-04 register read. FC3 is not Modbus function 16. Binary FC4
may instead contain ASCII protocols; dispatch those to the appropriate driver.

Example, **synthetic**, not captured hardware traffic:

```text
12 34 00 01 00 0a ff 04 | 01 03 00 b8 00 01 04 2f
<--- EyeBond header ---> | <--- complete RTU read --->
```

This has TID `0x1234`, outer code 1, outer address 255, outer FC4, and inner slave 1
reading one word at register 184. The example route is not a universal setting.

### Identity, routes and correlation

The outer device/tunnel code, outer address, inner Modbus slave, native inverter
protocol number, and native model code are five different concepts. A reported
collector uses outer address 255 and inner slave 5; the current AT inverter uses
slave 1. Copying one number into all route fields is incorrect.

A heartbeat may contain only a truncated PN prefix. Prefer a qualified full-PN
query before durable enrollment. Match replies by session generation, TID,
function and route policy; also validate the inner response. Some firmware is
reported to rewrite outer route fields, so exceptions require explicit profile
evidence rather than globally ignoring mismatches.

Some collectors send a greeting, while others wait for a server challenge.
Auto detection therefore combines bounded incoming-data analysis with
qualified bootstrap attempts and an advanced AT/Binary override. A port supplies
a possible challenge order, not proof of the dialect. No unbounded trial loop
or parser switch in the middle of an incomplete frame is acceptable.

Current budgets: 500 ms passive receive, 5 s identity transaction, 15 s admission.
Silent Auto uses AT-first on 18899/38899 and binary-first on 502, then at most one
alternate dialect on a subsequent connection. Two unsuccessful dialects pause
silent probing for ten minutes, with a reportable shared-source ambiguity. Advanced
Auto/AT/Binary override applies to new connections, not to durable device identity.
FC2 parameter 2 must yield a full PN; an FC1 prefix alone is insufficient.

Initial read qualification tests outer routes 1/1 and 1/255 with inner slaves 1/5,
at most four route/slave candidates under a 15 s budget (2 s per signature read).
Replies must match TID, function and route exactly. No header-rewrite exception is
enabled without firmware-specific evidence. One route and inverter per collector
are supported. TIDs are not reused: the session closes before 16-bit wrap and waits
for the collector to reconnect. Heartbeat time fields are collector liveness, not
inverter clock-register writes.

## 6. Inverter payload protocols

| Payload | Essential distinction | Current support |
| --- | --- | --- |
| Modbus RTU | Slave byte, function, binary register data, little-endian CRC16 bytes | AT and binary FC4, profile-specific holding/input reads; source-defined FC06/16 controls where implemented |
| PI30 / PI30 MAX / PI18 | Protocol-specific ASCII commands, responses and checksums | Separate setting grammars: 20/20/23 controls, independent readback and optional telemetry; MAX requires explicit dialect selection |
| G-ASCII / SmartValue variants | Different ASCII fingerprints and value layouts | GPDAT0/GMOD plus optional groups; 22 sourced setters with setting-specific readback and no PI30 CRC assumption |
| EyeBond 09C1 | Fixed-column Q1/QF/PV?/F, plain ASCII plus CR without a checksum/address prefix | Source-derived monitoring; distinct from addressed Short-ASCII; no defined write commands |
| Standard Modbus TCP | MBAP transport semantics, normally no RTU CRC payload | Not the implemented collector protocol; port 502 does not imply it |

In particular, the label **Protocol 4** in the native inverter map is unrelated
to **outer EyeBond FC4** and **Modbus function 04**. The current read code uses
Modbus function 03 and validates native identification registers 184 and 171.

## 7. Inverter profiles and compatibility evidence

A profile contains:

- Native identification method and exact accepted signatures.
- Inner slave/address policy and compatible payload family.
- Telemetry/settings blocks and expected reply lengths.
- Word order, scaling, units, enums, missing-value handling and HA metadata.
- Read/write capability, documented bounds, dependencies and evidence references.
- Qualification status by model/firmware; control evidence separate from readings.

### Reference Protocol 4 map

`modbus_protocol_4` uses AT slave 1; binary routes independently qualify slave 1 or 5.
It defines these telemetry blocks, as
`(start register, word count)`:

```text
(201,7), (227,5), (252,5), (277,5), (302,4), (338,16), (384,8), (702,3)
```

Settings blocks are `(600,12), (630,26), (677,8), (689,2), (693,2), (696,6)`.
There are 35 published measurement/status sensors and 51 parameter definitions;
48 parameters have native HA editors, two are hardware read-only, and the inverter
datetime is managed through the separate clock-sync feature.

Automatic admission currently accepts **register 184 = 4 and register 171 = 32771**.
Signatures 4/32768 and 4/33793 remain experimental and are not silently enrolled by
the exact reference gate. Recognition can offer the common `smg_4` profile
for them, or an unknown model with matching protocol/read evidence, for explicit
acceptance. Both IDs use the same map; the qualification evidence differs. A known
register layout is not blanket hardware-write qualification.

Implementation anchors:
[profile gate](../custom_components/solar_inverter_bridge/core/profiles.py),
[parameter definitions](../custom_components/solar_inverter_bridge/core/parameters.py),
[RTU framing](../custom_components/solar_inverter_bridge/core/framing.py).

### Model evidence matrix

| Exact model / installation | Transport/map evidence | Current support |
| --- | --- | --- |
| ANENJI ANJ-11KW-48V-W-P reference installation | AT/raw RTU, 4/32771 | Current hardware-read reference; write failure boundaries are extensively simulated, not blanket physical qualification |
| Sandisolar SD 11KP48V WIFI | External AT session and 4/32771; another local callback session was binary-framed | Strong additional candidate; not independently tested with this Bridge |
| ANENJI ANJ-11KW-48V-WIFI | External AT evidence, 4/33793 | Experimental common `smg_4` proposal available; explicit acceptance, no local hardware claim |
| ANENJI ANJ-11KW-48V-WIFI-P | External 4/32768 map; collector path not established in the reviewed model record | Experimental common `smg_4` proposal available when reads match |
| ANENJI ANJ-6200W-48V / ANJ-4000W-24V-WIFI | External AT/raw-RTU examples with another or unqualified map | Legacy common SMG profile available for read-based recognition; do not choose by brand |
| ANENJI ANJ-HHP-II-6.2KP-WIFI | External binary EyeBond to ess.eybond.com:502 | Binary transport implemented; exact payload/map must match an available proposal |
| PowMr 6.2 kW, exact SKU unspecified | External binary 502 implementation, slave 5, RTU/PI30 examples | PI30 common path available; native 4501-range semantics remain unqualified. The proxy's 9001-range registers are virtual, not inverter addresses |
| Reported EM11000 installation | Binary reported on vip1.eybond.com:18899 and 502 | Research candidate, not a qualified model family |
| Yingfa YF6.2K-LEL-1B / LVYUAN TY-SIC-3.6KBE-W1 | AT-family evidence with PI30 / G-ASCII respectively | Source-derived common payload drivers available; exact hardware still unverified |
| MUST PV18-3024 | External MUST map, slave 4; factory cloud transport not established here | Source-derived common MUST profile available; collector/session still requires confirmation |

Use these status labels consistently: **implemented**, **source-derived and
simulator-tested**, **hardware-read verified**, **hardware-write/readback verified**,
**candidate**, **unsupported**. Attach the exact build, collector firmware, route,
native map and evidence source. A model name alone must never select a decoder.

## 8. Ownership, controls, and history

One owner controls inverter I/O for a physical path. Multiple collector sockets
must not become independent pollers. The collector's full identity, not its IP,
binds enrollment; source allowlists remain independent network restrictions.

Implemented writable settings are available by default without control modes,
including documented R/W fields without known manufacturer limits, with an explicit
warning. Wire encoding limits are not manufacturer operating limits. All backend
entry points use the same availability checks and durable operation journal.

Effective editability intersects current-session evidence, implemented commands
and saved profile permission. The binary 32771 reference supports implemented
Protocol 4 setting writes after current-session qualification; accepted profiles expose source-defined controls
after the warning. Permission is bound to the profile definition digest/signature/
route; it survives restart but is not silently carried to changed evidence. Binary
clock writes and module reset remain unsupported. Possible-send failures remain unresolved;
reconnect does not replay the command. An outer binary ACK alone does not prove an
inverter setting changed.

SQLite owns the command journal and related state; HA Recorder owns measurement
history. The Sensors tab opens native HA history using the actual entity ID.
Collector heartbeat, TCP reconnect and opening the UI do not refresh telemetry.

## 9. Compatibility reports and development rules

Normal diagnostics export cached operational data. **Collect compatibility report**
is available on the main page and during setup, including with zero enrolled devices.
Enter optional model/firmware/endpoint/symptom/reference readings, start collection,
reconnect the collector, inspect local findings and download one ZIP. It contains
report/analysis JSON, timeline, observations, manifest hashes and an issue summary.
Collection is bounded to 120 s, 4096 events and 4 MiB of raw bytes; startup and a tail
are retained if truncated. Completed traces expire after 15 minutes. Established
devices reuse ordinary polling; additional verification is read-only and reports busy
instead of interrupting commands. No automatic upload, profile installation or reset.

Original receive chunks are included only with **Include raw protocol exchange**.
They may contain PN/serial/network data. Without them, structured findings remain
useful but a new parser failure may not be replayable. Earlier operational summaries
are marked as preceding collection; the analyzer explicitly flags missing startup.
The developer tool `tools/replay_compatibility.py <archive.zip>` validates schema,
size and hashes, then reruns analysis/framing/inner validation without executing
archive contents, extracting paths or contacting a collector. No guessed route
rewrite or map is automatically admitted from a report.

Binary support is source-derived and tested with fixtures. It has no project
hardware qualification. Community reports can establish actual
model/firmware compatibility. Reports must support offline reproduction without
executing user-supplied code. Raw unknown payloads may contain hardware identifiers;
their inclusion must be described separately from ordinary redacted diagnostics.

When adding a transport/profile, contributors must:

1. Pin sources and review licenses before code reuse.
2. Add framing/identity/correlation and profile fixtures; preserve source versus
   synthetic versus local-hardware evidence labels.
3. Verify reads independently of writes; never infer writable ranges from values
   that happened to be observed.
4. Update this port/capability/model matrix, router instructions and report analyzer
    in the same release. A documented future feature must remain labeled planned
   until implemented and tested.
5. Preserve existing device/entity IDs and journal guarantees during upgrades.

## 10. Protocol sources

The public manufacturer solution description does not provide a complete wire
specification. The binary details above are based on community codecs and reports:

- [ANENJI binary 502 implementation, ffc533e](https://github.com/atraca90/inverter-bridge/blob/ffc533e/inverter_bridge.py).
- [PowMr binary proxy and codec, b7a3ada](https://github.com/andronick83/powmr-eybond-proxy/blob/b7a3ada/proxy.py).
- [EyeBond codec, 6ca2b23](https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/custom_components/eybond_local/collector/protocol.py).
- [Collector management parameters, 6ca2b23](https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/custom_components/eybond_local/collector/parameter_registry.py).
- [Independent ha-dessmonitor codec, b3af875](https://github.com/andreas-glaser/ha-dessmonitor/blob/b3af875/custom_components/dessmonitor/local/protocol.py).
- [Sandisolar model record, 6ca2b23](https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/sandisolar_sd_11kp48v_wifi.json)
  and [owner's AT-session archive reference](https://github.com/groove-max/ha-eybond-local/issues/13#issuecomment-5415591865).
- [Firmware/endpoint analysis for binary 18899/502](https://github.com/groove-max/ha-eybond-local/issues/71#issuecomment-6526884941).

Some early examples in the last issue were reconstructed with incorrect CRCs;
they must not become alleged raw-capture fixtures. A callback-path success is not
proof of identical behavior on the collector's permanent factory-cloud session.
