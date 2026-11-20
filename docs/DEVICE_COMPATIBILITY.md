# Inverter compatibility and candidate-model register

Compatibility list for the current implemented profiles.
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
- **Register-map candidate:** external model-specific register evidence overlaps an
  implemented profile, but this Bridge's EyeBond path and model behavior are unverified.
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
| **DGK DGKINV02-24 6 kW** with **WFBLE.DTU.Bar** | Possible `must_pv3300` association | The source's PV3300 record lists this retail alias; require actual marker/read evidence before accepting the association [C17], [S5] | Experimental candidate; the alias does not prove all DGK units use MUST firmware |
| **MUST PV3900**; retail label **MUST PV39-8048 TLV** | Canonical `must_pv_ph18`; retained alias `must_pv3900`, PV/3900 marker | Common MUST conventions and marker-selected optional BMS subset [C18] | Experimental common variant; actual optional channels require valid replies |
| **Bluesun BSM15K-B** | `hopewind_0237` | External FC03 capture matches Hopewind protocol 0237/567. AC generation is not necessarily household load [C19] | Experimental common readings and three source-defined regulation controls available |
| **Kevolt PD0080G-TPM-EU**; alias **Kevolt 8 kW Three-Phase Hybrid** | `deye_3ph_high_80kw` internal key; actual source unit is **8 kW** | External type 5 / protocol 0x0104 / rated-power words 80000 raw at 0.1 W. The profile key does not indicate an 80 kW retail rating [C20] | Experimental 60-reading/118-control inventory; actual model applicability still requires read evidence |
| **ZL Power GSIII 12 kW / GSIII** | `eybond_09c1`, fixed-column Q1/QF/PV?/F | External 09C1 evidence [C22]; distinct from PI30/G-ASCII/Short-ASCII. Family responses do not uniquely identify a retail model | Up to 24 readings/status fields including optional PV1/PV2; no write commands or new local hardware qualification |

### Additional register-map candidates

The following are **register-map candidates**, not newly hardware-qualified Bridge
devices. Sources use RS232/RS485, direct USB Modbus or Solarman, so they establish
model/map associations rather than a supported factory EyeBond connection. A matching
collector, live profile checks and setting-specific readback are still required.
Only the named labels are listed; neighboring power ratings or suffixes are not inferred.

| Model / source label | Existing profile to compare | Evidence and limitations |
| --- | --- | --- |
| **PowMr POW-HVM5.5K-48V**, **POW-HVM5.5K-48V-P**; **Qoltec 53963**; **ANENJI 3 kW, 24 VDC / 120 VAC**; **SMG III 6.2 kW, 48 V** | `smg_legacy` / read-matched low SMG variant | External supported-device list and standard SMG register table agree on grid 202, output 210/213 and battery 215 [M1]. No native protocol number is assigned from a retail label. The source warns that some SMG III registers differ; SUF choices and battery voltage classes are model-specific. A separate SMG II 6 kW USB-A/wakeup variant in the same source has a different map and is excluded. |
| **MUST PV18-5248 Pro**, **PH18-5248 Pro**, **PV18-3024 VHM**, **PV18-3224 VPM**, **PV18-1012 VPM**, **PV18-2012 ECO**, **PV19-6248 EXP** | `must_pv_ph18` common map | External community-confirmed model list [M2]; PV18/PV19 configurations use the same 15205 PV voltage and 25205/25206/25207 battery/output/grid voltage blocks [M2-map]. Optional fields, load scaling, model markers and 12/24/48 V settings still need live checks. Do not infer the PV3300/PV3900 variant from the retail name. |
| **SRNE ASF48100U200-H** | `srne_modbus` | External hardware-tested reference explicitly targets SRNE Hybrid Modbus v1.96 [M3], the revision used by our profile. Register availability is device-specific; the external generated configuration is not imported into Bridge. |
| **SRNE HSI-1500S**; **ANENJI 12 kW split-phase, 48 V**, exact SKU unspecified | `srne_modbus` common subset | External SRNE implementations and HSI register observations [M4], [M4-map]. Core SOC/voltage fields match 0x0100/0x0101; HSI is 12 V, single-phase/single-MPPT and rejects several extended blocks. The ANENJI source is split-phase, but our profile does not promise combined split-phase totals. Confirm current direction, optional fields and per-12-V settings against the actual firmware. |
| **Growatt SPF 5000 ES**; **SPF 3000 ES** | `growatt_spf` | External SPF5000ES implementation and register definitions identify battery 17, SOC 18, grid 20/21 and output 22/23. The source explicitly describes SPF3000ES as a related variant with different charging limits, not as a separately measured unit [M5], [M5-map]. Those source limits are not applied to our controls. |
| **Growatt SPF 6000 ES Plus** | `growatt_spf` common subset | Model-specific ESPHome configuration matches FC04 PV/output power, battery 17 at 0.01 V and SOC 18 [M6], [M6-map]. Its optional BMS block starts at 203 rather than our generic BMS-SOC address 93; that optional coverage is not established. Matching base telemetry does not qualify every energy/BMS field or control. |
| **Deye SUN-5K-SG03LP1-EU** | `deye_lv` | Exact-model external report [M7-model] plus the single-phase map: battery 183/184, grid 150 and load power 178 [M7]. The external project also records an energy-reading issue; no blanket correctness of optional counters is claimed. Solarman transport is different from EyeBond. |
| **Deye SUN-8K-SG04LP3-EU**, **SUN-12K-SG04LP3-EU** | `deye_3ph_high_80kw` common map | External exact-model reports [M8-model], [M8-model-12] and SG04LP3 definitions match battery 587/588/590, grid 598–600/625 and PV 672/676 [M8]. The profile ID's `80kw` suffix is historical, not the inverter rating. Model-specific controls remain unqualified; the 12 kW report concerns a write issue, not proof of successful control. |
| **Solis S5-EH1P5K-L**, **S5-EH1P6K-L**, **RHI-3K-48ES-5G**, **S6-EH1P6K-L-PRO** | `solis_esinv` | External tested-model list and hybrid sensor definitions match 33073 grid voltage, 33093 temperature, 33094 frequency and 33133/33134/33139 battery readings [M9], [M9-map]. Our profile is monitoring-only. The external project's Solis dongle/Modbus TCP/serial support and writable schedules are not part of this Bridge. |

No new runtime profile, model discriminator or setting limit was added for this
documentation expansion. These candidates use the existing read-based recognition
path if their actual collector and replies match; external support labels are not
transferred into this project's hardware-verification status.

## 2. Named research candidates not yet claimed as a matching device profile

These remain in the possible-device register so reports can resolve them. They
are not hidden or rejected just because their retail name is unknown.

| Model / report label | Available evidence | What is still needed |
| --- | --- | --- |
| **ANENJI ANJ-HHP-II-6.2KP-WIFI** | External native-cloud binary EyeBond to `ess.eybond.com:502` [S6] | Our binary envelope is implemented; the exact inverter payload/map must match a proposal or be added from a report |
| **EM11000, reported 11 kW installation** | Binary reported on `vip1.eybond.com:18899` and 502; exact manufacturer/SKU is not established [S7] | Reliable original exchange and native signature. Some issue examples were reconstructed with bad CRCs and cannot serve as captures |
| **Vevor EM3500-24L**, integrated Wi-Fi | DNS names `iot3.eybond.com` and `dtu_ess.eybond.com` reported [S8] | Collector dialect, port and inverter map; DNS alone is not protocol evidence |
| **EASUN SMG II 8 kW / 11 kW** | Related register-map sources [S9] | Exact SKU, firmware, collector session and native signature. Existing SMG maps may fit; no blanket family hardware claim |
| **Yingfa YF6.2K-2K-LEL-IF** | An owner reports the model, but the formerly attributed PI30 capture actually belonged to Sumry devices [C21] | Correct evidence for this particular Yingfa; do not borrow support from YF6.2K-LEL-1B |
| **Sumry devices from the corrected Yingfa report**, exact SKUs unspecified | External PI30 evidence was reattributed to Sumry [C21] | Exact retail models; common PI30 can be tested, but the source does not justify inventing SKU names |
| **LVYUAN TY-SIC-6.5KBE-W1** | External catalog describes a separate captured Modbus map, not the G-ASCII map used by the 3.6 kW model [M10] | A new reviewed map/recognition path. The current `g_ascii` profile must not be assigned from the shared brand/name |

## 3. Implemented families without an exhaustive retail-model list

| Family / source descriptor | Available profile | Scope |
| --- | --- | --- |
| **SMG 6200 / SMG family 4200 variant** | `smg_legacy`, `smg_1`, `smg_11` | Generic firmware labels; the compiled source includes 11/30721 for one 4200 variant [S1] |
| **SRNE-compatible Modbus / Anenji SRNE** | `srne_modbus` | Source map, default slave 1 / 9600 8N1; named register-map candidates are listed above, not locally hardware-qualified [C23] |
| **Growatt SPF Off-Grid** | `growatt_spf` | Matching input/holding layouts; the named ES/ES Plus candidates above are not an exhaustive SPF or logger list [S1] |
| **Deye single-phase low-voltage hybrid** | `deye_lv` | The low-register family, distinct from the high three-phase map; named SUN-series candidates require their own live checks [S1] |
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
5. For a new runtime map or model-specific behavior, add a source-pinned model row
   and regression fixture. Documentation-only register-map candidates do not change
   runtime recognition or control coverage. Mark hardware monitoring or write/readback
   evidence only for the actual tested device/firmware/build.

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
[M1]: https://github.com/syssi/esphome-smg-ii/blob/796423feeb0ec0fff418712ab65ccd36d110c124/README.md
[M2]: https://github.com/vladyspavlov/esphome-must-inverter/blob/e3c43a4915901dcc399dc2ac68eb7a5eb36a426d/README.md
[M2-map]: https://github.com/vladyspavlov/esphome-must-inverter/blob/e3c43a4915901dcc399dc2ac68eb7a5eb36a426d/esp32-pv19.yaml
[M3]: https://github.com/yudaihata/esphome-srne-inverter/blob/ba7b661a34df228869855f0197f108299ecf68e1/README.md
[M4]: https://github.com/RAR/esphome-srne-inverter/blob/c52bb3fb502f6a8e5099c475b2fccf0b7249b261/README.md
[M4-map]: https://github.com/RAR/esphome-srne-inverter/blob/c52bb3fb502f6a8e5099c475b2fccf0b7249b261/REGISTER_MAP_HSI1500S.md
[M5]: https://github.com/Tobster86/growatt-spf5000es-linux-control/blob/4978dfee8074a99119e7bb289d96961216b335dc/README.md
[M5-map]: https://github.com/Tobster86/growatt-spf5000es-linux-control/blob/4978dfee8074a99119e7bb289d96961216b335dc/common/spf5000es_defs.h
[M6]: https://github.com/moongu0514/esphome-growatt-spf6000esplus-modbus/blob/0ff699c3308e86ccf4e23779a866bd79643af6c4/README.md
[M6-map]: https://github.com/moongu0514/esphome-growatt-spf6000esplus-modbus/blob/0ff699c3308e86ccf4e23779a866bd79643af6c4/growatt-esphome.yaml
[M7]: https://github.com/StephanJoubert/home_assistant_solarman/blob/690747497f763de0d7c99aa7c1145a7361f3e07d/custom_components/solarman/inverter_definitions/deye_hybrid.yaml
[M7-model]: https://github.com/kellerza/sunsynk/issues/608
[M8]: https://github.com/StephanJoubert/home_assistant_solarman/blob/690747497f763de0d7c99aa7c1145a7361f3e07d/custom_components/solarman/inverter_definitions/deye_sg04lp3.yaml
[M8-model]: https://github.com/kellerza/sunsynk/issues/330
[M8-model-12]: https://github.com/kellerza/sunsynk/issues/586
[M9]: https://github.com/Pho3niX90/solis_modbus/blob/3a00b647c2afe6d6ce64806559fe389840c9589a/README.md
[M9-map]: https://github.com/Pho3niX90/solis_modbus/blob/3a00b647c2afe6d6ce64806559fe389840c9589a/custom_components/solis_modbus/sensor_data/hybrid_sensors.py
[M10]: https://github.com/groove-max/ha-eybond-local/blob/03d3681a4f065a629871f2edc2255d0cf8632e57/catalog/inverter_models/models/lvyuan_ty_sic_6_5kbe_w1.json
