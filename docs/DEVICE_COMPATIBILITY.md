# Inverter compatibility and candidate-model register

Reviewed November 7, 2026 against candidate 0.8.1 and the 0.8.0 protocol expansion.
This is the consolidated list of
models and families identified in the project's reviewed public sources, including
experimental and unresolved candidates. It is not a claim to enumerate every OEM
rebadge or every inverter ever made. An unlisted device can still be recognized
by its protocol responses and offered an existing profile.

**Transport prerequisite:** the collector must establish a supported AT or binary
EyeBond session, with a full collector identity. A compatible register map alone
does not add support for a proprietary Growatt/Deye/Solis logger, direct serial,
USB, a vendor cloud API or conventional Modbus TCP.

Status legend:

- **Verified reference:** readings observed with this Bridge on the local test HA.
- **Experimental profile available:** an implemented common profile can be proposed
  when actual read evidence matches. Hardware has not been tested by this project.
- **Research candidate:** source evidence exists, but a matching driver/map or
  collector path is not established. Recognition/report collection is still useful.
- **Family only:** a protocol/map is implemented, but the reviewed evidence does
  not establish an exhaustive list of exact retail SKUs.

External projects' "supported" or "hardware confirmed" labels remain **external
evidence**; they are not copied into our own verification status. Control coverage
is profile-specific; implemented source inventories do not establish model-wide hardware qualification.
See [PROFILE_EXPANSION.md](PROFILE_EXPANSION.md) for exact measurement/control counts.

## 1. Models with a reference or an implemented experimental path

| Manufacturer / model label | Profile or native evidence | Collector / qualification boundary | Bridge status |
| --- | --- | --- | --- |
| **ANENJI ANJ-11KW-48V-W-P** | Original `modbus_protocol_4`, 184=4 / 171=32771 | Local AT/raw RTU on 18899; auxiliary AT on 38899. Current reference installation | **Verified reference** for readings; not blanket physical qualification of all controls |
| **Sandisolar SD 11KP48V WIFI** | 4/32771; original profile or common `smg_4` | External AT session and later binary-framed local session. Product name cannot choose a dialect [C1] | Experimental profile available |
| **ANENJI ANJ-11KW-48V-WIFI** | `smg_4`, 4/33793 (`0x8401`) | External AT support archive. The source owner says this model is non-parallel; do not append `-P` [C2] | Experimental profile available |
| **ANENJI ANJ-11KW-48V-WIFI-P** | `smg_4`, 4/32768 (`0x8000`) | Source model record; exact factory-cloud transport not established by that record [C2] | Experimental profile available if the collector/read checks pass |
| **ANENJI ANJ-6200W-48V** | `smg_legacy`, low-address SMG map | External working AT/raw-RTU bridge [S2] | Experimental profile available; native signature must be observed rather than borrowed from another 6200 model |
| **ANENJI 6200, single output** | `smg_1` or common low map; source 1/14080, firmware `3700_A6250424v1` | Exact retail SKU is not given in the source model record [C3] | Experimental profile available |
| **ANENJI ANJ-4000W-24V**; source alias **Anenji 4200 (Protocol 1)** | `smg_1`, source 1/13569, firmware `3501_A6251128v1` | A 24 V model: do not inherit 48 V battery setpoints [C4] | Experimental common telemetry/display controls available |
| **ANENJI ANJ-4000W-24V-WIFI** | `smg_legacy` / read-matched SMG variant | External mixed AT/raw-RTU proxy lists this model; the Wi-Fi suffix is kept distinct from the previous source record [S3] | Experimental candidate path; exact signature still needs a report |
| **ANENJI ANJ-5KW-48V-WIFI** | `smg_11`, source 11/30977 (`0x7901`), rated 5000 W | Additional entry in the pinned runtime catalog [S1] | Experimental common profile available |
| **ANENJI HHS-11kW-WIFI (without parallel)** | `smg_3`, source 3/29440 (`0x7300`) | Exact fingerprint and external read evidence; factory-cloud path still needs confirmation here [C5] | Experimental common profile available |
| **ANENJI ANJ-6200-48PL** | `smg_2`, source 2/8960 (`0x2300`) | Model-specific SUB/SBU/SUF/ZEC choices are implemented; SUF permits export and ZEC requires external CT configuration [C6] | Experimental common profile and source-defined settings available |
| **ANENJI GES48120M250-500P**; source description **white 12 kW split-phase** | `sumry_ges_7530`; source identity model 45 / class 10 / protocol raw 220 | High-address 30000/30024/30058 battery and phase-A subset. Not the low SMG map; no inferred split-phase totals [C7] | Experimental nine-reading profile available |
| **Aninerel 6200, dual output**; aliases **Aninerel 6.2KW**, **SMG OP2 6200** | `smg_11`, source 11/30979, firmware `7903_A6260126v1` | Alias records refer to a shared observed fingerprint, not independent hardware tests [C8] | Experimental common profile available; extended OP2 controls are not implied |
| **Aninerel ANL-4200T-24L-W-PRO** | `smg_11`, source 11/30723 | 24 V model; source register/controls differ from inherited 48 V templates [C9] | Experimental common telemetry/display controls available |
| **Sandisolar SD-HYM-4862HWP** | `smg_1`, source 1/7680 (`0x1E00`), rated 6200 W | External maintainer hardware reference; its local raw identity says generic SMG, not the retail name [C10] | Experimental profile available in this Bridge |
| **Yingfa YF6.2K-LEL-1B**; source alias **Yingfa 6.2K** | Common `pi30` / PI30 MAX; shared raw model `VMII-NXPW5KW`, 6200 W / 48 V | External EyeBond AT-text evidence, firmware `VERFW:00074.09` [C11] | Experimental PI30 readings and source-defined enum/voltage controls available |
| **Victor NM-PRO-6.2KW** | Common `pi30`; shared raw model `VMII-NXPW5KW`, 6200 W / 48 V | External support archive, firmware `VERFW:00021.12`; optional energy commands reportedly return NAK [C12] | Experimental PI30 common path available; no invented energy counters |
| **PowMr 4.2KW** | Common `pi30`; raw model `VMII-NXPW5KW` | Raw model token is shared across brands and powers; it is not a unique 4.2 kW identity. The source also describes a separate SmartESS 0925 route [C13] | Experimental PI30 path available; 0925-specific Modbus map not claimed |
| **PowMr 6.2 kW installation, exact SKU unspecified** | Common `pi30` candidate; external binary RTU/PI30 proxy | External binary EyeBond on 502, with RTU slave 5. Native registers 4501–4561 are not given guessed meanings. The proxy's 9001+ registers are virtual [S4] | Experimental PI30 path can be tested; not a claim for every PowMr 6.2 kW SKU |
| **LVYUAN TY-SIC-3.6KBE-W1** | `g_ascii`; source rating 220 V / 16 A / 24 V / 50 Hz, software 4.003 | External SmartValue/EyeBond AT-family capture, `iot.eybond.com`-style endpoint [C14] | Expanded monitoring and 22 source-defined controls available after matching-profile acceptance; no model-specific write qualification |
| **Gootu GT-H2436M14P5**; alias **Gootu Hybrid 24V 3.6kW** | `g_ascii`; source rating 230 V / 15 A / 24 V / 50 Hz, software 4.007 | External support/proxy evidence. G-ASCII is distinct from PI30 despite both being text [C15] | Expanded experimental monitoring/settings; fresh setting-specific readback required |
| **MUST PV18-3024** | `must_pv_ph18`, inner slave 4 | Source PV18/PV1800 marker, 19200 8N1 serial side. Our integration does not change the collector's UART configuration [C16] | Experimental common telemetry and 27 source-defined controls; unavailable fields remain unavailable |
| **MUST-compatible PV3300** | Canonical `must_pv_ph18`; retained alias `must_pv3300`, PV/3300 marker | Whole-percent load differs from the common MUST map. The variant is selected by marker/read evidence, not retail name [C17] | Experimental variant and optional BMS voltage/current/temperature/SOC channels |
| **DGK DGKINV02-24 6 kW** with **WFBLE.DTU.Bar** | Possible `must_pv3300` association | Earlier research only established the endpoint. The pinned source's PV3300 record now lists this retail alias; require the actual marker/read evidence before accepting that association [C17], [S5] | Experimental candidate; the alias does not prove all DGK units use MUST firmware |
| **MUST PV3900**; retail label **MUST PV39-8048 TLV** | Canonical `must_pv_ph18`; retained alias `must_pv3900`, PV/3900 marker | Common MUST conventions and marker-selected optional BMS subset [C18] | Experimental common variant; actual optional channels require valid replies |
| **Bluesun BSM15K-B** | `hopewind_0237` | External FC03 capture matches Hopewind protocol 0237/567. AC generation is not necessarily household load [C19] | Experimental common readings and three source-defined regulation controls available |
| **Kevolt PD0080G-TPM-EU**; alias **Kevolt 8 kW Three-Phase Hybrid** | `deye_3ph_high_80kw` internal key; actual source unit is **8 kW** | External type 5 / protocol 0x0104 / rated-power words 80000 raw at 0.1 W. The historical profile key must not be read as an 80 kW retail rating [C20] | Experimental 60-reading/118-control inventory; actual model applicability still requires read evidence |
| **ZL Power GSIII 12 kW / GSIII** | `eybond_09c1`, fixed-column Q1/QF/PV?/F | External 09C1 evidence [C22]; distinct from PI30/G-ASCII/Short-ASCII. Family responses do not uniquely identify a retail model | Up to 24 readings/status fields including optional PV1/PV2; no write commands or new local hardware qualification |

## 2. Named research candidates not yet claimed as a matching device profile

These remain in the possible-device register so reports can resolve them. They
are not hidden or rejected just because their retail name is unknown.

| Model / report label | Available evidence | What is still needed |
| --- | --- | --- |
| **ANENJI ANJ-HHP-II-6.2KP-WIFI** | External native-cloud binary EyeBond to `ess.eybond.com:502` [S6] | Our binary envelope is implemented; the exact inverter payload/map must match a proposal or be added from a report |
| **EM11000, reported 11 kW installation** | Binary reported on `vip1.eybond.com:18899` and 502; exact manufacturer/SKU is not established [S7] | Reliable original exchange and native signature. Some issue examples were reconstructed with bad CRCs and cannot serve as captures |
| **Vevor EM3500-24L**, integrated Wi-Fi | DNS names `iot3.eybond.com` and `dtu_ess.eybond.com` reported [S8] | Collector dialect, port and inverter map; DNS alone is not protocol evidence |
| **EASUN SMG II 8 kW / 11 kW** | Related register-map sources and the project predecessor [S9] | Exact SKU, firmware, collector session and native signature. Existing SMG maps may fit; no blanket family hardware claim |
| **Yingfa YF6.2K-2K-LEL-IF** | An owner reports the model, but the formerly attributed PI30 capture actually belonged to Sumry devices [C21] | Correct evidence for this particular Yingfa; do not borrow support from YF6.2K-LEL-1B |
| **Sumry devices from the corrected Yingfa report**, exact SKUs unspecified | External PI30 evidence was reattributed to Sumry [C21] | Exact retail models; common PI30 can be tested, but the source does not justify inventing SKU names |

## 3. Implemented families without an exhaustive retail-model list

| Family / source descriptor | Available profile | Scope |
| --- | --- | --- |
| **SMG 6200 / SMG family 4200 variant** | `smg_legacy`, `smg_1`, `smg_11` | Generic firmware labels; the compiled source includes 11/30721 for one 4200 variant [S1] |
| **SRNE-compatible Modbus / Anenji SRNE** | `srne_modbus` | Source map, default slave 1 / 9600 8N1; no exhaustive exact-SKU or local hardware list [C23] |
| **Growatt SPF Off-Grid** | `growatt_spf` | Matching input/holding register layouts through a supported EyeBond session; not every SPF product/logger [S1] |
| **Deye single-phase low-voltage hybrid** | `deye_lv` | The low-register family, distinct from the high three-phase map; no fabricated SUN-series SKU list [S1] |
| **Deye-compatible three-phase high-map hybrid** | `deye_3ph_high_80kw` | Includes the Kevolt source candidate; hardware/rating variants require actual evidence [S1], [C20] |
| **Solis Hybrid ESINV** | `solis_esinv` | Matching high input-register family through a supported collector; proprietary Solis logger transport is not added [S1] |
| **Sandi / Aohai FSA** | `aohai_fsa` | Matching input-register telemetry; exact retail SKUs not established in reviewed evidence [S1] |
| **Hopewind String, protocol 0237** | `hopewind_0237` | Includes the Bluesun source candidate; exact model/rating comes from the user/source record [S1], [C19] |
| **Sumry / GES 0x7530** | `sumry_ges_7530` | Nine common battery/phase-A readings, not an entire split-phase/PV/BMS map [C7] |
| **SmartESS 0912 / 0921 map families** | `smartess_0912`, `smartess_0921` | Protocol/map identifiers, not brand names or proof that every SmartESS collector uses those maps [S1] |
| **PI30 / PI30 MAX / VMII-NXPW5KW-compatible OEMs** | `pi30`, `pi30_max` | Separate command variants; shared firmware identifiers do not establish a brand, power rating or write dialect [S1], [C11], [C12], [C13] |
| **PI30-like PIP/GK / PI41 variants** | Separate variant evidence required | An identified PI41 response is rejected by PI30 recognition. Similar-looking ASCII replies do not justify applying PI30/MAX write grammars [S1] |
| **PI18-compatible devices** | `pi18` | A protocol driver is implemented; the reviewed corpus does not supply a trustworthy exhaustive retail-SKU list [S1] |
| **EyeBond / JsdSolar G-ASCII OEMs** | `g_ascii` | Common GPDAT0/GMOD path, including the independently reported LVYUAN and Gootu candidates [C14], [C15] |

Other source families such as addressed EyeBond Short-ASCII require their own
codec; their names are not aliases for an implemented driver. Unknown OEM rebadges
may share any implemented family, but are added to the named list only with a source
or a user report establishing the exact label and observed protocol.

## 4. How a new model enters the list

1. Run bounded recognition and review any proposed profile's readings.
2. Explicitly accept a matching proposal after its warning. Acceptance covers
   readings and implemented controls together; there is no separate control toggle.
3. Collect a compatibility ZIP, exact model/revision, firmware if known, and a few
   simultaneous display readings with time and units.
4. Share the ZIP and generated issue description with the project maintainer.
   Use [GitHub Issues](https://github.com/jay0x/solar-inverter-cloud-bridge/issues).
   No report is uploaded automatically.
5. Add a source-pinned model row and regression fixture. Mark hardware monitoring
   or write/readback evidence only for the actual tested device/firmware/build.

No test write, load cycling, router change or cloud credential is required to
request model support. Raw exchange can contain identifiers; its export is optional
and explicitly labeled. See [PROFILE_EXPANSION.md](PROFILE_EXPANSION.md).

## Sources

All C references below are records in the pinned external catalog. Their evidence
statements belong to that project; private originals mentioned there were not
downloaded or redistributed for this implementation.

[S1]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/custom_components/eybond_local/protocol_catalogs/inverter_catalog.json
[S2]: https://github.com/samuelolteanu/Local-Cloud-Bridge-for-Anenji-Easun-MPP-Solar-Inverters/blob/34f5abe/README.md
[S3]: https://github.com/smedynsky-sudo/anenji-domoticz-proxy/blob/e1c3943/README.md
[S4]: https://github.com/andronick83/powmr-eybond-proxy/blob/b7a3ada/proxy.py
[S5]: https://github.com/groove-max/ha-eybond-local/issues/46
[S6]: https://github.com/atraca90/inverter-bridge/blob/ffc533e/README.md
[S7]: https://github.com/groove-max/ha-eybond-local/issues/71#issuecomment-6526884941
[S8]: https://github.com/Paxy/SmartESS-proxy/issues/7
[S9]: https://github.com/alcestide/easun-smg-ii-11kw/tree/17ae11f9c9b77660371f264a57cea712e1f6730e
[C1]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/sandisolar_sd_11kp48v_wifi.json
[C2]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/anenji_anj_11kw_48v_wifi_p.json
[C3]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/anenji_6200_single_output.json
[C4]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/anenji_4200_protocol_1.json
[C5]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/anenji_hhs_11kw_wifi_no_parallel.json
[C6]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/anenji_anj_6200_48pl.json
[C7]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/anenji_ges48120m250_500p.json
[C8]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/aninerel_6200_dual_output.json
[C9]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/aninerel_anl_4200t_24l_w_pro.json
[C10]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/sandisolar_sd_hym_4862hwp.json
[C11]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/yingfa_yf6_2k_lel_1b.json
[C12]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/victor_nm_pro_6_2kw.json
[C13]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/powmr_4_2kw.json
[C14]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/lvyuan_ty_sic_3_6kbe_w1.json
[C15]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/gootu_gt_h2436m14p5.json
[C16]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/must_pv18_3024.json
[C17]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/must_pv3300.json
[C18]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/must_pv3900.json
[C19]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/bluesun_bsm15k_b.json
[C20]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/kevolt_pd0080g_tpm_eu.json
[C21]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/yingfa_yf6_2k_2k_lel_if.json
[C22]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/zl_power_gsiii_12kw.json
[C23]: https://github.com/groove-max/ha-eybond-local/blob/6ca2b23/catalog/inverter_models/models/srne_modbus_family.json
