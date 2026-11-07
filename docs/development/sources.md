# Source provenance and licensing

Solar Inverter Cloud Bridge is MPL-2.0. The original MIT copyright/permission notice for
inherited InverterLocalBridge portions is retained in full in
[THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md). The predecessor is not a runtime
dependency. Its credentials, databases, private captures and process/backend are
not imported by the integration.

## Protocol sources

| Source | Pinned evidence and boundary |
| --- | --- |
| [SRNE Modbus v1.96 document](https://github.com/syssi/esphome-smg-ii/blob/b0ff1caec3ce395d774fcf496fcc03a75f925ca2/docs/SRNE.Solar.Charge.Inverter.MODBUS.Protocol1.96.pdf) | Primary facts used by 0.8.0: unsigned voltage/frequency/power, phase-A scope, positive-discharge current, per-12-V battery settings and 32-register read limit. Rated-voltage text is read-only despite a conflicting table annotation |
| [mpp-solar protocol documents](https://github.com/jblance/mpp-solar/tree/eafdd4328c77f516cf82430c5bcb6fa042c45d3a/docs/protocols) | PI18 20170926, PI30 20150924 and PI30MAX 20210217 primary documents. Paired setters, units, command case and current-unit addressing take precedence over inconsistent library labels |
| [Solar2MQTT](https://github.com/softwarecrash/Solar2MQTT/tree/4390ab343e6546d3a37c0067d8f5eddcbe48ce53) | Protocol reference, protocol PDFs and example replies; independent cross-reference, not a runtime dependency or evidence that every UART/RS485 family supports our collector transport |
| [MUST protocol documents](https://github.com/vladyspavlov/esphome-must-inverter/tree/e3c43a4915901dcc399dc2ac68eb7a5eb36a426d/docs) | Primary spreadsheets 1.4.3 and 1.4.15; energy high word is 1000 kWh, low word 0.1 kWh, not binary uint32. Battery current 25274 is in A |
| [Independent MUST integration](https://github.com/mukaschultze/ha-must-inverter/tree/9fd33151694ce05ac1aa20f4a6b51c8135a21021) | Independent FC06 cross-reference; implementation not copied |
| [GivEnergy protocol internals](https://jak.github.io/givenergy-modbus/protocol.html) | Reviewed November 7, 2026: fixed TID 0x5959, proprietary transparent framing, adapter serial/padding, heartbeat and 60-aligned requests. A different transport, not implemented EyeBond compatibility |
| [Classic SMG RS232 document via syssi](https://github.com/syssi/esphome-smg-ii/blob/b0ff1caec3ce395d774fcf496fcc03a75f925ca2/docs/SMG-RS232%2BCommunication%2BProtocol%2BV1.0.1.pdf) | November 2021 v1.0; SHA-256 `35a0594c30afe074f47069883f3ff1bd5021c80120f42241d443b4c771bccf9d`. Register 171 is reserved and 184 invalid; do not infer native protocol number 1 from the document version |
| [Native Modbus documents via PreK](https://github.com/PreK/esphome-anenji-11kw-native-modbus/tree/55a330585846d57b4f24e6467201d8dde8985ee7) | Communication Protocol No. 3–10, v1.0, November 2024; document SHA-256 `c863516e3a842bea2c853151aa403b30f98354888a9dd80568cd092f0b3a9c70`. Original manufacturer files are not redistributed |
| [EASUN comparison](https://github.com/alcestide/easun-smg-ii-11kw/tree/17ae11f9c9b77660371f264a57cea712e1f6730e) | Related map comparison; primary documentation takes precedence when labels/scales disagree |
| [Local Cloud Bridge](https://github.com/samuelolteanu/Local-Cloud-Bridge-for-Anenji-Easun-MPP-Solar-Inverters/tree/34f5abe1afec820175a135daa0fe79b3b739c902) | GPL-3.0 protocol reference for AT/low SMG behavior; its implementation is not copied |
| [ANENJI binary example](https://github.com/atraca90/inverter-bridge/blob/ffc533e/inverter_bridge.py) | External native-cloud binary EyeBond observation; not a universal map/route guarantee |
| [PowMr proxy](https://github.com/andronick83/powmr-eybond-proxy/tree/b7a3ada) | MIT, copyright 2026 andronick83. Binary framing, FC4 and PI30 cross-reference; its virtual proxy registers are not native inverter addresses |
| [ha-eybond-local](https://github.com/groove-max/ha-eybond-local/tree/6ca2b23cda042f5919e3831a907f784000d5de27) | MPL-2.0. Public codecs, parameter/profile catalogs and model records; selected facts independently implemented, not copied driver/schema files |
| [ha-dessmonitor codec](https://github.com/andreas-glaser/ha-dessmonitor/blob/b3af875/custom_components/dessmonitor/local/protocol.py) | Independent framing cross-reference; callback success does not establish every factory-cloud session |

The [profile guide](../PROFILE_EXPANSION.md#evidence-and-sources) lists exact schema,
payload and control source paths. The [device register](../DEVICE_COMPATIBILITY.md)
links exact model records, including uncertain or corrected attributions. Keep those
links with the fields/models they justify rather than duplicating whole catalogs here.

## Evidence rules

- Separate documented facts, synthetic fixtures, external reports, local hardware
  reads, hardware write/readback and independently observed physical effects.
- A shared firmware/model token, brand, hostname or port is not unique retail identity.
- Check both request and response semantics. Do not silently repair a CRC and call
  the resulting bytes an original capture.
- Report source disagreements, such as response-route rewrites or model-specific
  load scaling. Do not globally disable validation to hide them.
- Source-derived control support does not establish manufacturer operating limits
  or qualify every enum value on every firmware.
- Review the license before copying any actual implementation. Protocol research
  is not permission to redistribute source or vendor documents under another license.

New adapters/maps and register/ASCII fixtures are independently written from these
facts. No additional hardware capture was relabeled as project-owned evidence.
Detailed original local import hashes and research transcripts remain private history.

The November 7, 2026 family review is summarized in the
[profile guide](../PROFILE_EXPANSION.md#protocol-family-review--november-7-2026).
The 2024 document explicitly lists protocol numbers 3/4/5/6 despite its "3-10"
filename. The pinned SmartESS catalog and HEAD `88436d8629ef72835b4aae95297aa9332c51d11e`
both specify 0912 telemetry FC04/address4 versus 0921 FC03/address1. Those are
source-derived facts, not new hardware results. Version 0.7.0 corrects 0912 and
checks the actual FC04/slave4 request plan independently, with original-wire replay.
Paxy's reviewed decoder handles 0925 and
does not independently qualify 0912 or 0921.

The [remaining-family audit](../PROFILE_EXPANSION.md#remaining-family-audit--november-7-2026)
compares the other 15 entries with the pinned register/control/command schemas.
In particular, `profiles/eybond_g_ascii/base.json` has 22 capability definitions;
the earlier zero-control subset was an implementation gap. Version 0.8.0 implements
those 22 setting-specific grammars/readbacks. MUST schemas inherit one base, whereas Deye LV/high-map and the four
ASCII payload families are not interchangeable. Source counts are not manufacturer
coverage percentages. Additional independent projects located were kellerza/sunsynk,
rany2/spf5000es-server and Pho3niX90/solis_modbus; their existence does not qualify
our selected maps or a different logger transport.

The current expansion is independently implemented in `core/extended_maps.py`,
`core/modbus_settings.py`, `core/ascii_settings.py` and `core/ascii_telemetry.py`.
Their field tables use the pinned donor paths in the profile guide, reconciled with
the primary documents above. In particular, PI18 total ET is kWh despite a library
label of Wh; MAX QLT is load energy, not grid import; MAX QPIGS2 is three PV2 fields,
not the PI41 phase-L2 layout. PI30 and MAX write case/current syntax remain separate.
The source documents and external implementation files are not redistributed.

Remaining gaps are explicit: Sumry PI30/HGX examples do not extend the GES 30000+
map; JSD/Senergy Modbus documents do not establish G-ASCII commands; 09C1 has no
verified writable map. Deye high register 653 retains a raw label without an asserted
power unit where scale is ambiguous. No additional profile has local hardware-write
qualification. Synthetic executor tests establish software behavior, not electrical effects.

The 0.5.0 09C1 implementation uses fixed-column facts from the pinned
`payload/urtu09c1.py` and `drivers/eybond_09c1.py` references. No address byte,
checksum, unique retail identity or writable map is inferred. Expanded controls
were checked against the protocol-specific SMG profiles, MUST PV/PH18 profile and
PI30 setting/readback definitions. Model-dependent voltage limits are not imported
from another battery-voltage grade. The raw-session 50 ms turnaround and queued-byte
guard preserve a behavior documented in the MIT predecessor's continuous reader;
the new implementation uses the existing async adapter/deadline boundaries.
