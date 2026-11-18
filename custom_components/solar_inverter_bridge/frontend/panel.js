class SolarInverterBridgePanel extends HTMLElement {
  constructor() {
    super();
    this._drafts = {};
    this._pending = {};
    this._results = {};
    this._baselines = {};
    this._tab = "overview";
    this._search = "";
    this._disclosures = {};
  }

  set hass(hass) {
    this._hass = hass;
    const storageKey = `solar_inverter_bridge:${hass.user?.id || "admin"}`;
    if (this._storageKey !== storageKey) {
      this._storageKey = storageKey;
      try {
        const saved = JSON.parse(localStorage.getItem(storageKey) || "{}");
        this._drafts = saved.drafts || {};
        this._pending = saved.pending || {};
        this._results = saved.results || {};
        this._baselines = saved.baselines || {};
      } catch (_) {
        this._error = "Saved drafts could not be loaded.";
      }
    }
    if (!this._timer) {
      this._routeListener = () => { this._readRoute(); this._render(); };
      window.addEventListener("hashchange", this._routeListener);
      this._readRoute();
      this._timer = setInterval(() => this._load(), 2000);
      this._sidebarListener = event => this._sidebarHome(event);
      window.addEventListener("click", this._sidebarListener, true);
      this._load();
      this._loadRouterHints();
      this._loadCollectorDomains();
    }
  }

  _sidebarHome(event) {
    if (!this._device && !this._wizard) return;
    const hit = (event.composedPath?.() || []).find(node => {
      if (node?.nodeType !== 1) return false;
      const href = node.getAttribute?.("href") || (typeof node.href === "string" ? node.href : "");
      return String(href).includes("solar-inverter-bridge")
        || node.getAttribute?.("data-panel") === "solar-inverter-bridge"
        || node.panel === "solar-inverter-bridge"
        || node.getAttribute?.("aria-label") === "Inverters";
    });
    if (!hit) return;
    event.preventDefault();
    event.stopPropagation();
    this._navigate("sib");
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
    window.removeEventListener("hashchange", this._routeListener);
    window.removeEventListener("click", this._sidebarListener, true);
  }

  _readRoute() {
    const parts = location.hash.replace(/^#/, "").split("/");
    this._wizard = parts[0] === "sib" && parts[1] === "add";
    this._wizardStep = this._wizard ? Math.min(3, Math.max(0, Number(parts[2]) || 0)) : 0;
    this._device = parts[0] === "sib" && parts[1] === "device" ? parts[2] : null;
    this._tab = ["overview", "sensors", "settings", "connection", "activity"].includes(parts[3]) ? parts[3] : "overview";
  }

  async _loadRouterHints() {
    try {
      this._routerHints = await this._hass.callWS({type: "solar_inverter_bridge/network_hints"});
      if (this.isConnected) this._render();
    } catch (_) {
      // Setup can still be completed manually when HA network discovery is unavailable.
      this._routerHints = {};
    }
  }

  _routerGuideUrl() {
    const hints = new URLSearchParams();
    for (const key of ["ha_ip", "subnet", "router_ip", "dns_ip"]) {
      if (this._routerHints?.[key]) hints.set(key, this._routerHints[key]);
    }
    hints.set("addresses", JSON.stringify(this._routerHints?.addresses || []));
    return "/solar_inverter_bridge/routers.html?v=0.24.0#" + hints.toString();
  }

  async _loadCollectorDomains() {
    try {
      const response = await fetch("/solar_inverter_bridge/collector-domains.json?v=0.24.0");
      if (!response.ok) throw new Error("Domain catalogue unavailable");
      this._collectorDomains = await response.json();
    } catch (_) {
      this._collectorDomains = [];
    }
    if (this.isConnected) this._render();
  }

  _navigate(route) {
    const previousStep = this._wizard ? this._wizardStep : null;
    location.hash = route;
    this._readRoute();
    this._render();
    if (this._wizard && previousStep !== this._wizardStep) this.querySelector(".setup-flow")?.scrollIntoView({block: "start"});
  }

  async _load() {
    if (!this._hass || this._loading) return;
    this._loading = true;
    try {
      this._status = await this._hass.callWS({type: "solar_inverter_bridge/status"});
      for (const device of this._status.devices || []) {
        const pending = this._pending[device.device_id];
        const record = device.operations?.find(item => item.operation_id === pending?.operation_id);
        if (pending && record) this._operationResult(device.device_id, record);
      }
      this._loadError = "";
    } catch (error) {
      this._loadError = error.message || "Unable to read the bridge.";
    } finally {
      this._loading = false;
    }
    // HA embeds custom panels in nested shadow roots. document.activeElement
    // points at a host, not at the select whose native popup is currently open.
    if (!this._editing()) this._render();
    else this._updateSaveButtons();
  }

  _updateSaveButtons() {
    if (!this._status) return;
    const value = id => this.querySelector('#' + id)?.value;
    const checked = id => this.querySelector('#' + id)?.checked;
    const sources = items => JSON.stringify([...new Set(items)].sort());
    const connection = config => {
      const method = config.method || 'redirect';
      const ip = (config.collector_ip || '').trim();
      if (method === 'redirect') return JSON.stringify([method, ip]);
      return JSON.stringify(ip ? [method, ip, (config.callback_host || '').trim(), Number(config.callback_port ?? 8899), Number(config.udp_port ?? 58899)] : [method, '']);
    };
    const comparisons = {
      'clock': device => checked('clock-sync') !== Boolean(device.clock_sync),
      'auto-reset': device => checked('auto-reset') !== Boolean(device.auto_reset),
      'poll-options': device => checked('poll-enabled') !== (device.enabled !== false) || Number(value('poll-interval')) !== Number(device.poll_interval ?? 10),
      'network': () => sources((value('allowed-sources') || '').split(/[,\s]+/).filter(Boolean)) !== sources(this._status.allowed_sources || []),
      'bootstrap-save': () => value('bootstrap-preference') !== (this._status.bootstrap_preference || 'auto'),
      'incident-configure': () => checked('incident-enabled') !== (this._status.incidents?.enabled !== false),
      'save-connection': device => connection({method:value('connection-method'), collector_ip:value('collector-ip'), callback_host:value('callback-host'), callback_port:value('callback-port'), udp_port:value('callback-udp-port')}) !== connection(device.connection_options || {}),
    };
    for (const [action, changed] of Object.entries(comparisons)) {
      this.querySelectorAll(`button[data-action="${action}"]`).forEach(button => {
        const device = this._status.devices?.find(item => item.device_id === button.dataset.device);
        if (button.dataset.device && !device) return;
        button.classList.toggle('primary', changed(device));
      });
    }
    const recording = this.querySelector('#incident-recording-status');
    const toggle = this.querySelector('#incident-enabled');
    if (recording && toggle) {
      const saved = this._status.incidents?.enabled !== false;
      const changed = toggle.checked !== saved;
      const text = `Saved state: recording ${saved ? 'enabled' : 'disabled'}. ` + (changed
        ? `Unsaved change: ${toggle.checked ? 'enable' : 'disable'} recording. Press Save incident recording to apply.`
        : 'All changes saved.');
      if (recording.textContent !== text) recording.textContent = text;
      recording.classList.toggle('unsaved', changed);
    }
  }

  _editing() {
    if (this.querySelector("dialog[open]")) return true;
    let active = this.getRootNode().activeElement || document.activeElement;
    while (active?.shadowRoot?.activeElement) active = active.shadowRoot.activeElement;
    return this.contains(active) && active.matches("input, select, textarea, [contenteditable=true]");
  }

  async _call(data, onSuccess) {
    if (this._busy) return;
    this._busy = true;
    this._error = "";
    this._render();
    try {
      const result = await this._hass.callWS(data);
      if (onSuccess) onSuccess(result);
      await this._load();
    } catch (error) {
      this._error = error.message || "Request failed.";
    } finally {
      this._busy = false;
      this._render();
    }
  }

  _saveDrafts() {
    try {
      localStorage.setItem(this._storageKey, JSON.stringify({drafts: this._drafts, baselines: this._baselines, pending: this._pending, results: this._results}));
      return true;
    } catch (_) {
      this._error = "Browser storage is unavailable. The request was not sent.";
      return false;
    }
  }

  _draft(device, key, fallback) {
    return this._drafts[`${device}:${key}`] ?? fallback;
  }

  _clearDraft(device, key) {
    delete this._drafts[`${device}:${key}`];
    delete this._baselines[`${device}:${key}`];
    if (this._editingField === `${device}:${key}`) this._editingField = null;
    this._saveDrafts();
  }

  _inputValue(item, raw) {
    if (item.kind === "number") {
      if (String(raw).trim() === "") return "";
      const value = Number(raw);
      return value === 0 && item.zero_value ? item.zero_value : value;
    }
    if (item.kind === "time" && /^\d{2}:\d{2}$/.test(String(raw))) return `${raw}:00`;
    return raw;
  }

  _isDirty(item, raw, observed) {
    return this._inputValue(item, raw) !== observed;
  }

  _updateEditorActions(input, fromInput = true) {
    const row = input.closest("[data-parameter]");
    if (!row) return;
    const item = this._parameters(row.dataset.device).find(field => field.key === row.dataset.parameter);
    const device = this._status.devices.find(field => field.device_id === row.dataset.device);
    const dirty = this._isDirty(item, input.value, device.settings[item.key]);
    input.setCustomValidity(item.allowed_values && !item.allowed_values.includes(Number(input.value)) ? "Choose one of the supported values: " + item.allowed_values.join(", ") : "");
    if (fromInput && !dirty) {
      delete this._drafts[input.dataset.draft];
      delete this._baselines[input.dataset.draft];
    }
    row.querySelector('[data-action="apply"]').hidden = !dirty || !input.checkValidity();
    row.classList.toggle("has-draft", dirty);
    const note = row.querySelector(".draft-note");
    if (note) note.hidden = !dirty;
  }

  _operationResult(device, result) {
    const request = this._pending[device] || {};
    this._results[device] = {
      ...result,
      setting_key: result.setting_key || request.key,
      desired_value: result.desired_value ?? result.send_value ?? request.value,
      previous_value: result.previous_value ?? request.expected_value,
      actor_name: result.actor_name || this._hass?.user?.name || null,
      created_at: result.created_at || new Date().toISOString(),
    };
    if (result.state === "completed" && !result.unresolved) {
      const request = this._pending[device];
      if (request && (result.outcome === "confirmed" || ["readback_matched", "accepted_current_value"].includes(result.resolution))) {
        this._clearDraft(device, request.key);
      }
      delete this._pending[device];
    }
    this._saveDrafts();
  }

  async _applyParameter(device, key) {
    if (this._busy || this._pending[device]) return;
    const descriptor = this._parameters(device).find(item => item.key === key);
    const input = this.querySelector("#edit-" + key);
    if (!input.checkValidity()) { input.reportValidity(); return; }
    const raw = input.value;
    // Numeric-looking enum labels (voltage/frequency) must remain strings.
    const value = this._inputValue(descriptor, raw);
    if (descriptor.allowed_values && !descriptor.allowed_values.includes(Number(raw))) {
      this._error="Choose one of the supported values: "+descriptor.allowed_values.join(", ");this._render();return;
    }
    const current = this._status.devices.find(item => item.device_id === device)?.settings?.[key];
    if (!this._isDirty(descriptor, raw, current)) return;
    if (descriptor.kind === "number" && (!raw.trim() || !Number.isFinite(Number(raw)))) {
      this._error = "Enter a valid number.";
      this._render();
      return;
    }
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    const operation_id = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
    const expected_value = this._baselines[`${device}:${key}`] ?? this._status.devices.find(item => item.device_id === device)?.settings?.[key] ?? null;
    const request = {type: "solar_inverter_bridge/apply", device_id: device, key, value, operation_id, expected_value};
    delete this._results[device];
    this._pending[device] = request;
    if (!this._saveDrafts()) {
      delete this._pending[device];
      this._render();
      return;
    }
    this._busy = true;
    this._error = "";
    this._render();
    try {
      this._operationResult(device, await this._hass.callWS(request));
    } catch (error) {
      if (error.code === "request_rejected") {
        delete this._pending[device];
        this._saveDrafts();
      }
      this._error = this._errorMessage(error.message || "Request result is unknown.");
    } finally {
      this._busy = false;
      await this._load();
      this._render();
    }
  }

  _parameterName(status, key) {
    return status?.parameters?.find(item => item.key === key)?.name || "Setting";
  }

  _changeText(record, status) {
    const name = this._parameterName(status, record?.setting_key);
    const next = record?.desired_value;
    const previous = record?.previous_value;
    const nextLabel = next == null ? null : this._valueLabel(next);
    const previousLabel = previous == null || previous === next ? null : this._valueLabel(previous);
    if (record?.unresolved) return `${name} is waiting for confirmation`;
    if (record?.outcome === "not_sent") return `${name} was not changed`;
    if (record?.resolution === "accepted_current_value") return `${name} was left at ${this._valueLabel(record.last_observed_value)}`;
    if (nextLabel && previousLabel) return `${name} changed from ${previousLabel} to ${nextLabel}`;
    if (nextLabel) return `${name} is now ${nextLabel}`;
    return name;
  }

  _operationView(device) {
    const pending = this._pending[device];
    const status = this._status;
    const history = status?.devices?.find(item => item.device_id === device)?.operations || [];
    const result = (pending ? history.find(item => item.operation_id === pending.operation_id) : history[0]) || this._results[device];
    const shown = {...(pending || {}), ...result, setting_key: result?.setting_key || pending?.key, desired_value: result?.desired_value ?? pending?.value, previous_value: result?.previous_value ?? pending?.expected_value};
    if (pending && !shown.outcome) shown.unresolved = true;
    const uncertain = pending || shown.unresolved;
    const id = pending?.operation_id || shown.operation_id;
    if (!id) return "";
    const when = this._formatTime(shown.resolved_at || shown.created_at);
    const actor = shown.actor_name ? ` · ${this._escape(shown.actor_name)}` : "";
    return `<section class="operation ${uncertain ? "attention" : ""}" aria-live="polite">
      <div class="icon-tile">${this._icon(uncertain ? "clock" : "check")}</div><div class="grow"><h3>${this._escape(this._changeText(shown, status))}</h3>
      <p>${uncertain ? "Check the inverter before making another change. The request is not sent again automatically." : `${this._escape(when)}${actor}`}</p>
      ${shown.unresolved && shown.last_observed_value != null ? `<p>The inverter currently reports <strong>${this._escape(this._valueLabel(shown.last_observed_value))}</strong>. You can keep that value without sending another write.</p>` : ""}
      ${shown.reason && uncertain ? `<p>${this._escape(shown.reason)}</p>` : ""}</div>
      <div class="actions">${uncertain ? `<button data-action="check" data-device="${device}" data-value="${this._escape(id)}">Check result</button>` : ""}
      ${shown.unresolved && shown.last_observed_value != null ? `<button data-action="accept-current" data-device="${device}" data-value="${this._escape(id)}">Keep current value</button>` : ""}
      ${pending ? `<button class="text-button" data-action="resume" data-device="${device}">Retry this change</button>` : ""}</div></section>`;
  }

  _render() {
    const focusedDisclosure = this.querySelector('details[data-disclosure] > summary:focus')?.parentElement.dataset.disclosure;
    const status = this._status || {devices: [], candidates: [], parameters: []};
    const devices = status.devices || [];
    const selected = this._device && devices.find(item => item.device_id === this._device);
    const body = !this._status ? '<section class="empty-state"><h2>Connecting to your bridge…</h2><p>Reading the saved devices and their latest measurements.</p></section>' : this._wizard ? this._wizardView(status) : selected ? this._deviceView(selected, status) : this._home(status);
    const firstSetup = !selected && !devices.length;
    const support = this._wizard ? "" : firstSetup ? this._disclosure("home-help", "Connection help and diagnostics", this._compatibilityView(status, false), this._reportOpen) : this._compatibilityView(status);
    if (!this.querySelector(".sib")) this.innerHTML = `<link rel="stylesheet" href="/solar_inverter_bridge/panel.css?v=0.24.0"><div class="sib"></div>`;
    this.querySelector(".sib").innerHTML = `<header class="appbar"><button class="icon-button" aria-label="Open Home Assistant menu" data-action="menu">${this._icon("menu")}</button>
      <img class="brand-logo" src="/solar_inverter_bridge/icon.png" srcset="/solar_inverter_bridge/icon@2x.png 2x" width="32" height="32" alt=""><span class="brand">Solar Inverter Cloud Bridge</span><span class="local-label">Local connection</span></header>
      <main class="${this._wizard || firstSetup ? "setup-layout" : ""}">${this._loadError || this._error ? `<div class="banner attention" role="alert">${this._icon("info")}<span>${this._escape(this._errorMessage(this._loadError || this._error))}</span><button class="text-button" data-action="dismiss">Dismiss</button></div>` : ""}${body}${support}</main>${this._removeDialog(status)}`;
    this.querySelectorAll("details[data-disclosure]").forEach(details => {
      if (details.dataset.disclosure in this._disclosures) details.open = this._disclosures[details.dataset.disclosure];
      details.querySelector("summary").onclick = () => { this._disclosures[details.dataset.disclosure] = !details.open; };
      details.ontoggle = () => { if (this.contains(details)) this._disclosures[details.dataset.disclosure] = details.open; };
      if (details.dataset.disclosure === focusedDisclosure) details.querySelector("summary")?.focus({preventScroll: true});
    });
    this.querySelectorAll("[data-action]").forEach(button => {
      if (this._busy) button.disabled = true;
      button.onclick = () => this._action(button.dataset.action, button.dataset.value, button.dataset.device);
    });
    this.querySelectorAll("[data-draft]").forEach(input => {
      if (input.id.startsWith("edit-")) this._updateEditorActions(input, false);
      input.oninput = () => {
        if (input.id.startsWith("edit-") && !(input.dataset.draft in this._baselines)) {
          const key = input.id.slice(5);
          this._baselines[input.dataset.draft] = this._status.devices.find(item => item.device_id === this._device)?.settings?.[key] ?? null;
        }
        this._drafts[input.dataset.draft] = input.type === "checkbox" ? input.checked : input.value;
        if (input.id.startsWith("edit-")) this._updateEditorActions(input);
        this._saveDrafts();
        this._updateSaveButtons();
        if (input.id === 'incident-watch-device') {
          this._render();
          this.querySelector('#incident-watch-device')?.focus();
        }
      };
    });
    const incidentRaw = this.querySelector('#incident-raw');
    if (incidentRaw) incidentRaw.oninput = () => { this._incidentRaw = incidentRaw.checked; };
    this._updateSaveButtons();
    const search = this.querySelector("#parameter-search");
    if (search) search.oninput = () => {
      const position = search.selectionStart;
      this._search = search.value;
      this._render();
      const updated = this.querySelector("#parameter-search");
      updated.focus();
      updated.setSelectionRange(position, position);
    };
    const dialog = this.querySelector("#remove-dialog");
    if (dialog) {
      dialog.showModal();
      dialog.oncancel = event => { event.preventDefault(); this._removeTarget = null; this._removeConfirm = ""; this._render(); };
      const confirmation = this.querySelector("#remove-confirmation");
      confirmation.oninput = () => {
        this._removeConfirm = confirmation.value;
        const target = status.devices.find(item => item.device_id === this._removeTarget);
        this.querySelector('[data-action="confirm-remove"]').disabled = this._busy || this._removeConfirm !== target.name;
      };
    }
  }

  _removeDialog(status) {
    const target = status.devices.find(item => item.device_id === this._removeTarget);
    if (!target) return "";
    return `<dialog id="remove-dialog" aria-labelledby="remove-title"><h2 id="remove-title">Remove ${this._escape(target.name)}?</h2>
      <p>This removes its registration and bridge entities from Home Assistant. Inverter settings are unchanged. The operation journal is retained.</p>
      <p>To add it again, run a new read-only connection check.</p>
      ${this._error ? `<p class="dialog-error" role="alert">${this._escape(this._error === "device_busy_or_unresolved" ? "Finish or resolve the pending operation before removing this inverter." : this._error)}</p>` : ""}
      <label class="field-label" for="remove-confirmation">Type <strong>${this._escape(target.name)}</strong> to confirm</label>
      <input id="remove-confirmation" autocomplete="off" value="${this._escape(this._removeConfirm || "")}">
      <div class="dialog-actions"><button data-action="cancel-remove">Cancel</button><button class="danger" data-action="confirm-remove" data-device="${target.device_id}" ${this._removeConfirm === target.name ? "" : "disabled"}>Remove inverter</button></div></dialog>`;
  }

  _home(status) {
    const devices = status.devices || [];
    const online = devices.filter(device => device.connected && !device.stale).length;
    const cards = devices.map(device => `<article class="device-card">
      <button class="card-open" data-action="open-overview" data-device="${device.device_id}" aria-label="Open ${this._escape(device.name)} overview">
        <span class="card-heading"><span class="device-heading"><span class="icon-tile accent">${this._icon("inverter")}</span><span><span class="card-title">${this._escape(device.name)}</span><span class="card-subtitle">Solar inverter · Local monitoring</span></span></span>${this._statusChip(device)}</span>
        ${this._powerMetrics(device)}
      </button>
      <div class="card-footer access-summary">${this._modeSummary(device)}</div>
    </article>`).join("");
    return `<div class="page-heading"><div><div class="eyebrow">YOUR ENERGY</div><h1>Inverters</h1><p>Generation, storage, and home power. All in one place.</p></div>
      ${devices.length ? `<button class="primary" data-action="add">${this._icon("plus")} Add inverter</button>` : ""}</div>
      ${devices.length ? `<div class="overview-strip"><span><i class="status-dot ${online ? "online" : ""}"></i> ${online} of ${devices.length} connected</span><span>Updates automatically</span><span>Direct local readings</span></div>
      <div class="device-grid">${cards}</div>` : `<section class="empty-state"><span class="large-icon">${this._icon("sun")}</span><h2>Your energy starts here</h2><p>Connect an inverter through its Wi-Fi collector to see live generation, battery charge, and output power.</p><button class="primary" data-action="add">${this._icon("plus")} Connect your first inverter</button></section>`}
      ${devices.length ? `<div class="quiet-note">${this._icon("shield")}<span>Each inverter has its own settings and readings. Add another here — one bridge handles all your devices.</span></div>` : ""}`;
  }

  _disclosure(id, title, content, initiallyOpen = false) {
    return `<details class="setup-disclosure" data-disclosure="${id}" ${(this._disclosures[id] ?? initiallyOpen) ? "open" : ""}><summary>${this._escape(title)}</summary><div class="disclosure-body">${content}</div></details>`;
  }

  async _verifyCollector(collector) {
    if (this._busy) return;
    this._checkingCollector = collector;
    try {
      await this._call({type: "solar_inverter_bridge/verify", collector_sha256: collector}, result => {
        const candidate = this._status.pending?.find(item => item.identity_sha256 === collector);
        if (candidate) Object.assign(candidate, result);
        if (result.ready) this._navigate("sib/add/3");
      });
      if (this._error) await this._load();
    } finally {
      this._checkingCollector = null;
      this._render();
    }
  }

  _connectionHelp(status) {
    return `<p>Use local DNS to send the collector's connection to Home Assistant. Router setup provides the addresses and commands for your network.</p>
      <div class="connection-target"><span>Home Assistant LAN IP</span><strong>${this._escape(this._routerHints?.ha_ip || "Choose it in Router setup")}</strong><span>TCP ports</span><strong>502 · 18899 · 38899</strong></div>
      <a class="router-setup-link" href="${this._escape(this._routerGuideUrl())}" target="_blank" rel="noopener">Open router setup ${this._icon("arrow")}</a><p class="field-help">Opens in a new tab. Return here after configuring your router; connections appear automatically.</p>
      ${this._disclosure("setup-dns-details", "DNS domains and troubleshooting", `<div class="connection-domains"><h3>Collector domains</h3><p>Resolve the names used by your collector to the Home Assistant LAN IP. Choose individual names or the wildcard in Router setup.</p>
        ${(this._collectorDomains || []).length ? `<ul>${this._collectorDomains.map(domain => `<li class="${!domain.suffix && domain.name.endsWith(".eybond.com") ? "domain-child" : ""}"><code>${this._escape(domain.name)}</code><small>${this._escape(domain.description)}</small></li>`).join("")}</ul>` : '<p>Open Router setup to view the domain list.</p>'}</div>
        <p>The inverter must use the DNS server where you add the records. Set it through DHCP or its network settings. TCP redirection is usually unnecessary when DNS points directly to HA and the ports are reachable.</p>
        <p>Changes take effect on a new connection. Reconnect the collector's Wi-Fi or restart its Wi-Fi module through its app if supported. Cached DNS may take time to expire.</p>${this._discoveryView(status)}`)}`;
  }

  _connectionMethodForm(status, device = null) {
    const scope = device ? device.device_id + ":connection" : "setup";
    const saved = device?.connection_options || {};
    const method = this._draft(scope, "method", saved.method || (device ? "redirect" : "auto"));
    const request = (status.connection_requests || []).find(r => r.request_id === this._drafts[scope + ":connection_request"]);
    const labels = {waiting:"Callback requested. Waiting for the collector's TCP connection…", connected:device ? "Collector connection identified. Fresh inverter reads are checked separately." : "Collector identified. Select its connection above to check inverter readings.", disconnected:"The collector disconnected. Retry the connection when it is ready.", timed_out:"The connection attempt expired. Check the addresses and retry.", failed:"The callback could not be confirmed. Check the connection details.", waiting_for_connection:"Waiting for a redirected collector connection.", saved_paused:"Connection preference saved. Enable Collect readings to start polling and automatic callback requests."};
    return `<div class="subsection"><h3>Connection method</h3>
      <label class="field-label" for="connection-method">How to connect</label><select id="connection-method" data-draft="${scope}:method">
      ${[["auto","Automatic"],["callback","Local connection (UDP callback)"],["redirect","Redirected cloud connection"]].map(([id,name])=>`<option value="${id}" ${method===id ? "selected" : ""}>${name}</option>`).join("")}</select>
      <label class="field-label" for="collector-ip">Wi-Fi collector IP address (optional in Automatic)</label>
      <input id="collector-ip" data-draft="${scope}:collector_ip" value="${this._escape(this._draft(scope,"collector_ip",saved.collector_ip || ""))}" placeholder="For example, 192.168.1.50" autocomplete="off">
      <p class="field-help">Automatic keeps a usable connection; with an IP it requests callback when disconnected. Without an IP it waits for a redirected connection. Local callback requires a reachable collector IP. Readings and supported controls both travel over TCP.</p>
      <p class="field-help">Available commands depend on the inverter profile and negotiated session, not just this connection method. Implemented setting writes work on AT and Binary EyeBond. Clock sync is implemented for Protocol 4 on both. Binary collector reset is not implemented; the AT reset command is available on AT sessions. You can collect a compatibility report for an unsupported function.</p>
      ${this._disclosure(scope+":callback-advanced","Callback network settings",`<label class="field-label" for="callback-host">Home Assistant LAN IP for the callback</label><input id="callback-host" data-draft="${scope}:callback_host" value="${this._escape(this._draft(scope,"callback_host",saved.callback_host || this._routerHints?.ha_ip || ""))}">
        <label class="field-label" for="callback-port">Home Assistant TCP port</label><input id="callback-port" type="number" min="1024" max="65535" data-draft="${scope}:callback_port" value="${this._escape(this._draft(scope,"callback_port",saved.callback_port || 8899))}">
        <label class="field-label" for="callback-udp-port">Collector UDP port</label><input id="callback-udp-port" type="number" min="1" max="65535" data-draft="${scope}:udp_port" value="${this._escape(this._draft(scope,"udp_port",saved.udp_port || 58899))}">`)}
      <p class="field-help">${device ? "Saving waits for the current exchange, then selects the requested connection for this same collector. Entities and history are preserved. Redirected mode requires DNS/router routing to this HA; saving does not change the router. While collection is paused, the preference is saved without sending a callback." : "Connect sends a targeted callback request when needed."} Depending on firmware, callback can affect the collector's cloud connection. It does not change electrical settings.</p>
      <button data-action="${device ? "save-connection" : "connect-collector"}" ${device ? `data-device="${this._escape(device.device_id)}"` : ""} ${device && (device.unresolved || this._pending[device.device_id]) ? "disabled" : ""}>${request && ["timed_out","failed","disconnected"].includes(request.state) ? "Retry connection" : device ? "Save connection" : "Connect collector"}</button>
      ${request ? `<p role="status">${this._escape(labels[request.state] || request.state)}${request.reason ? " " + this._escape(request.reason) : ""}</p>` : ""}</div>`;
  }

  _wizardView(status) {
    const pending = status.pending || [];
    const collector = this._draft("setup", "collector", "");
    const selected = pending.find(item => item.identity_sha256 === collector);
    const searches = (status.profile_searches || []).filter(search => search.collector_sha256 === collector);
    const activeSearch = searches.some(search => ["searching", "waiting_for_reconnect"].includes(search.state));
    const step = this._wizardStep;
    const name = this._draft("setup", "name", "Inverter " + ((status.devices || []).length + 1));
    const sources = status.allowed_sources || [];
    const sourceInput = `<label class="field-label" for="network-source">Additional allowed IP or subnet</label><input id="network-source" data-draft="setup:source" value="${this._escape(this._draft("setup", "source", sources.length ? "" : this._routerHints?.subnet || ""))}" placeholder="${this._escape(this._routerHints?.subnet || "Collector IP or LAN/IoT CIDR")}"><p class="field-help">Use the collector's network, or the router address if it translates source addresses. Existing allowed sources are kept.</p>`;
    let content;
    if (step === 0) content = `<h2>Name your inverter</h2><p>This is how it will appear in Home Assistant.</p>
      <label class="field-label" for="setup-name">Inverter name</label><input id="setup-name" data-draft="setup:name" value="${this._escape(name)}" maxlength="80" placeholder="For example, House inverter">
      ${sources.length ? `<p class="field-help">Allowed network: <strong>${this._escape(sources.join(", "))}</strong></p>${this._disclosure("setup-network", "Use a different collector network", sourceInput)}` : sourceInput}
      <button class="primary" data-action="setup-next">Continue to connection ${this._icon("arrow")}</button>`;
    else if (step === 1) content = `<h2>${pending.length ? "Choose your collector" : "Connect your Wi-Fi collector"}</h2><p>${pending.length ? "Connection found. Select the collector for this inverter; we will check its readings next." : "The collector sends inverter readings to Home Assistant. Configure its local connection, then select it here."}</p>
      ${!sources.length ? '<div class="banner attention">No source addresses are allowed. Go to the previous step and enter the collector network.</div>' : ""}
      <div class="collector-list" aria-live="polite">${pending.length ? pending.map(candidate => `<div class="candidate found"><div><strong>${this._icon("check")} Collector connected</strong><p>Source ${this._escape(candidate.source)}<br>Collector ${this._escape(candidate.identity_ref)}</p><small>${this._escape(candidate.transport || "AT")} · TCP ${this._escape(candidate.listener_port || "—")}</small></div><button class="primary" data-action="choose-collector" data-value="${this._escape(candidate.identity_sha256)}">Use this connection ${this._icon("arrow")}</button></div>`).join("") : '<div class="waiting-state"><span class="status-dot"></span><div><strong>Waiting for a collector…</strong><p>This list updates automatically. Already added inverters are not listed again.</p></div></div>'}</div>
      ${pending.length ? this._disclosure("setup-another", "Connect another collector", this._connectionMethodForm(status)+this._connectionHelp(status), Boolean(this._disclosures["setup-dns-details"])) : this._connectionMethodForm(status)+this._connectionHelp(status)}`;
    else if (step === 2) content = `<h2>${this._checkingCollector ? "Checking your inverter…" : activeSearch ? "Finding a compatible profile…" : searches.length ? "Review compatibility" : "Check the connection"}</h2>
      <p>We read the inverter to identify its protocol and check its measurements. No inverter settings are changed.</p>
      ${searches.length && !this._checkingCollector ? this._profileSuggestions({...status, pending: [], profile_searches: searches}, true) : selected ? `<div class="verification-count" role="status"><strong>${selected.snapshots || 0}<span> / 2</span></strong><p>Complete readings${this._checkingCollector ? " · Please wait" : ""}</p></div>${this._checkingCollector ? "" : `<button class="primary" data-action="verify" data-value="${this._escape(selected.identity_sha256)}">Check connection ${this._icon("arrow")}</button>`}` : '<div class="banner attention">The selected collector is no longer connected. Select it again when it returns.</div><button class="primary" data-action="setup-connections">Choose a connection</button>'}
      ${searches.length && !activeSearch && !searches.some(search => search.candidates?.length) ? `<button class="primary" data-action="setup-connections">Choose a connection</button>` : ""}`;
    else content = `<span class="large-icon success">${this._icon("check")}</span><h2>${selected?.ready ? "Ready to add" : "Check the connection first"}</h2>
      <p>${selected?.ready ? "Two complete snapshots received. Supported settings will be available to edit after adding the inverter." : "Verification is no longer available. Go back and run the read-only check."}</p>
      <div class="review-row"><span>Name</span><strong>${this._escape(name)}</strong></div>
      ${selected?.ready ? `<div class="review-row"><span>Profile</span><strong>${this._escape(selected.profile_name || selected.profile_id || "Protocol 4")}${selected.model_code != null ? " · Model " + this._escape(selected.model_code) : ""}${selected.experimental ? " · Experimental" : ""}</strong></div>${this._profileLayers(selected.profile_layers)}<button class="primary" data-action="enroll" data-value="${this._escape(selected.identity_sha256)}">Add inverter ${this._icon("arrow")}</button>` : `<button class="primary" data-action="${selected ? "verify" : "setup-connections"}" data-value="${this._escape(collector)}">${selected ? "Check connection again" : "Choose a connection"}</button>`}`;
    return `<div class="setup-flow"><div class="page-heading"><div><div class="eyebrow">STEP ${step + 1} OF 4</div><h1>${status.devices?.length ? "Add inverter" : "Add your first inverter"}</h1></div></div>
      <ol class="stepper" aria-label="Setup progress">${["Name", "Connect", "Check", "Add"].map((label, index) => `<li ${index === step ? 'aria-current="step"' : ""} class="${index === step ? "active" : index < step ? "complete" : ""}"><span>${index < step ? this._icon("check") : index + 1}</span><strong>${label}</strong></li>`).join("")}</ol>
      <section class="wizard-panel" aria-busy="${Boolean(this._checkingCollector)}">${content}<div class="wizard-footer">${step ? `<button class="text-button" data-action="setup-back">${this._icon("back")} Previous step</button>` : ""}<button class="text-button" data-action="back">Cancel setup</button></div></section>
      ${this._disclosure("setup-help", "Connection help and diagnostics", this._compatibilityView(status, false), this._reportOpen)}</div>`;
  }

  _deviceView(device, status) {
    const tabs = [["overview", "Overview"], ["sensors", "Sensors"], ["settings", "Configuration"], ["connection", "Connection"], ["activity", "Activity"]];
    let body;
    if (this._tab === "settings") body = this._settingsView(device, status);
    else if (this._tab === "sensors") body = this._sensorsView(device, status);
    else if (this._tab === "connection") body = this._connectionView(device, status);
    else if (this._tab === "activity") body = this._activityView(device, status);
    else body = this._overviewView(device);
    return `<button class="back-link" data-action="back">${this._icon("back")} All inverters</button>
      <div class="page-heading"><div><div class="eyebrow">INVERTER</div><h1>${this._escape(device.name)}</h1><p>${this._age(device)}</p></div><div class="device-native-actions">${this._statusChip(device)}${device.ha_device_id ? `<a class="ha-entities-link" href="/config/devices/device/${encodeURIComponent(device.ha_device_id)}">Home Assistant entities ${this._icon("arrow")}</a><small>Sensors and controls for your dashboards and automations.</small>` : ""}</div></div>
      <nav class="tabs" aria-label="Inverter sections">${tabs.map(([key, label]) => `<button class="${this._tab === key ? "selected" : ""}" aria-current="${this._tab === key ? "page" : "false"}" data-action="tab" data-device="${device.device_id}" data-value="${key}">${label}</button>`).join("")}</nav>
      ${device.profile_change_required ? '<div class="banner attention">The accepted profile evidence changed. Control is paused. Recheck the profile and review the new proposal in Configuration.</div>' : ""}${body}`;
  }

  _settingsView(device, status) {
    const settings = device.settings || {};
    const grouped = {};
    for (const item of device.parameters || status.parameters || []) {
      if (this._search && !`${item.name} ${item.group}`.toLowerCase().includes(this._search.toLowerCase())) continue;
      (grouped[item.group || "Parameters"] ||= []).push(item);
    }
    const tables = Object.entries(grouped).map(([group, items]) => {
      const rows = items.map(item => {
        const observed = settings[item.key] == null ? "Not observed" : this._valueLabel(settings[item.key]);
        const fresh = device.parameter_freshness?.[item.key]?.available ?? (device.settings_available !== false);
        const editable = device.capabilities?.inverter_write !== false && fresh && device.enabled !== false && device.connected && settings[item.key] != null && item.execution_ready && this._reason(item) === "Editable" && !this._pending[device.device_id] && !device.unresolved;
        const desired = this._draft(device.device_id, item.key, settings[item.key] ?? "");
        const draft = `${device.device_id}:${item.key}`;
        const dirty = this._drafts[draft] != null && this._isDirty(item, desired, settings[item.key]);
        const editing = editable && (this._editingField === draft || dirty);
        const unit = settings[item.key] != null && settings[item.key] !== "full_recovery" && item.unit ? ` <span class="unit">${this._escape(item.unit)}</span>` : "";
        const reason = device.capabilities?.inverter_write === false ? "Writes unavailable for this profile or connection" : this._pending[device.device_id] || device.unresolved ? "Waiting for the previous operation" : !fresh || !device.connected || device.enabled === false || settings[item.key] == null ? "Waiting for fresh readings from the current session" : this._reason(item);
        const limitsWarning = item.warning === "manufacturer_limits_unknown";
        const warningText = "Manufacturer limits are undocumented. Verify this value for your inverter and battery; register-format checks do not establish a supported operating range.";
        const indicator = item.access === "read_only"
            ? `<span class="value-status" role="img" tabindex="0" title="${this._escape(reason)}" aria-label="${this._escape(reason)}">${this._icon("lock")}</span>`
            : limitsWarning ? `<span class="value-status limits-warning" role="img" tabindex="0" title="${warningText}" aria-label="Manufacturer limits undocumented: ${this._escape(item.name)}">${this._icon("warning")}</span>`
              : '<span class="value-spacer" aria-hidden="true"></span>';
        let control;
        if (editing) {
          const shown = item.zero_value && desired === item.zero_value ? 0 : desired;
          const bounds = item.bounds || item.wire_bounds;
          const input = item.options
            ? `<select aria-label="${this._escape(item.name)} value" id="edit-${item.key}" data-draft="${draft}">${item.options.map(option => `<option value="${this._escape(option)}" ${desired === option ? "selected" : ""}>${this._escape(this._valueLabel(option))}</option>`).join("")}</select>`
            : `<input required aria-label="${this._escape(item.name)} value" id="edit-${item.key}" data-draft="${draft}" value="${this._escape(item.kind === "time" ? String(shown).slice(0, 5) : shown)}" ${item.kind === "number" ? `type="number" step="${item.step || 1}" ${bounds ? `min="${bounds[0]}" max="${bounds[1]}"` : ""}` : 'type="time" step="60"'}>`;
          control = `<div class="editor-controls">${input}<button class="primary compact" data-action="apply" data-value="${item.key}" data-device="${device.device_id}" ${dirty ? "" : "hidden"}>Apply</button><button class="icon-button" data-action="discard" data-device="${device.device_id}" data-value="${item.key}" aria-label="Cancel editing ${this._escape(item.name)}" title="Cancel editing">${this._icon("close")}</button></div>
            <small class="draft-note" ${dirty ? "" : "hidden"}>Unsaved · Current: ${this._escape(observed)}${unit}</small>
            ${limitsWarning ? `<small class="limits-note">${warningText}</small>` : ""}
            ${item.allowed_values ? `<small class="field-help">Supported values: ${item.allowed_values.map(v=>this._escape(v)).join(", ")}</small>` : ""}
            ${item.zero_value ? '<small class="field-help">0 means full recovery, not a 0 V threshold.</small>' : ""}`;
        } else if (editable) {
          control = `<button class="value-button" data-action="edit" data-device="${device.device_id}" data-value="${item.key}" aria-label="Edit ${this._escape(item.name)}: ${this._escape(observed)}"><strong>${this._escape(observed)}${unit}</strong></button>`;
        } else {
          control = `<div class="value-static" title="${this._escape(reason)}"><strong>${this._escape(observed)}${unit}</strong></div>`;
        }
        return `<div class="parameter-row ${editing ? "is-editing" : ""} ${dirty ? "has-draft" : ""}" data-parameter="${item.key}" data-device="${device.device_id}"><div><h4>${this._escape(item.name)}</h4>${!fresh ? '<small>Last known value</small>' : ""}</div><div class="parameter-value aligned-value"><span class="parameter-indicator">${indicator}</span><div class="parameter-control">${control}</div></div></div>`;
      }).join("");
      return `<section class="parameter-group"><div class="section-heading"><h3>${this._escape(group)}</h3><span>${items.length} settings</span></div>${rows}</section>`;
    }).join("");
    return `${device.capability_reason ? `<div class="banner attention">${this._escape(device.capability_reason)}</div>` : ""}
      ${device.profile_layers ? `<section class="surface">${this._profileLayers(device.profile_layers)}</section>` : ""}
      ${device.profile_acceptance ? `<section class="surface"><h3>Accepted experimental profile</h3><p>Compatibility is inferred. The accepted profile enables its implemented writable settings. Readback confirms reported values, not a physical effect.</p>${device.profile_layers?.variants?.length ? `<label class="field-label" for="profile-variant">Protocol write dialect</label><select id="profile-variant" data-draft="${device.device_id}:profile_variant">${device.profile_layers.variants.map(v=>`<option value="${this._escape(v.id)}" ${this._draft(device.device_id,"profile_variant",device.profile_layers.selected_variant)===v.id ? "selected" : ""}>${this._escape(v.name)}</option>`).join("")}</select><p class="field-help">Select the dialect documented for your inverter, then recheck and review the proposal. Writes are never retried with a different command case.</p>` : ""}<button data-action="profile-recheck" data-device="${device.device_id}">Recheck this profile</button></section>` : ""}
      <section class="surface"><h3>Function availability and feedback</h3><p>Implemented controls are available even when your model or firmware has not been hardware-tested, after profile acceptance and fresh read checks. Check the reported result on the inverter. Share the model, firmware, attempted setting, and outcome through a compatibility report to help qualify it. A function without an implemented command cannot be enabled by a permission switch.</p><button data-action="compatibility-open">Collect compatibility report</button></section>
      <section class="clock-panel"><div class="icon-tile">${this._icon("clock")}</div><div class="grow"><h3>Automatic clock sync</h3><p>${!["modbus_protocol_4","smg_4"].includes(device.profile_id) ? "Clock writes are not implemented for this profile. Collect a compatibility report to help add support; your preference is retained." : device.capabilities?.clock_write === false ? "Waiting for a connected, qualified Protocol 4 session. Clock writes are implemented on AT and Binary EyeBond; your preference is retained." : "Corrects any difference of one minute or more, including differences of several hours, using Home Assistant local time. Smaller differences can come from read delay and are left unchanged."}</p><small>Inverter time: ${this._escape(settings.inverter_datetime?.replace("T", " ") || "Not observed")}</small></div>
      <label class="switch-label"><input id="clock-sync" data-draft="${device.device_id}:clock" type="checkbox" ${this._draft(device.device_id, "clock", device.clock_sync) ? "checked" : ""}> Enabled</label><button data-action="clock" data-device="${device.device_id}">Save clock setting</button></section>
      <section class="clock-panel"><div class="icon-tile">${this._icon("refresh")}</div><div class="grow"><h3>Automatic Wi-Fi recovery</h3><p>Restart the Wi-Fi module after no complete inverter readings for at least 5 minutes and three polling intervals. At most once per hour, including after Home Assistant restarts.</p><small>${device.transport === "binary" ? "Binary collector reset is not implemented. Collect a compatibility report to help add support. The AT reset command cannot be sent over a binary session. " : device.transport === "at" ? "The reset command is implemented on this AT connection. " : ""}Paused when collection is disabled. Requires a connected module; cannot repair missing DNS or a disconnected collector.</small></div>
      <label class="switch-label"><input id="auto-reset" data-draft="${device.device_id}:auto_reset" type="checkbox" ${this._draft(device.device_id, "auto_reset", device.auto_reset || false) ? "checked" : ""}> Enabled</label><button data-action="auto-reset" data-device="${device.device_id}">Save recovery setting</button></section>
      ${this._operationView(device.device_id)}
      <div class="settings-toolbar"><div><h2>Inverter configuration</h2><p>Click a value to edit. Apply appears only when it changes.</p></div><label class="search-box">${this._icon("search")}<input id="parameter-search" value="${this._escape(this._search)}" placeholder="Find a setting" aria-label="Find a setting"></label></div>
      <div class="parameter-legend"><span>${this._icon("lock")} Hardware read-only</span><span class="limits-warning">${this._icon("warning")} Manufacturer limits undocumented</span></div>
      ${tables || `<div class="empty-state small"><h3>No matching settings</h3><p>${device.parameters?.length === 0 ? "No source-defined controls are implemented for this profile yet. Collect a report to help add them." : "Try another name or clear the search."}</p></div>`}`;
  }

  _sensorsView(device, status) {
    const sensors = device.ha_sensors || [];
    return `<section class="surface"><div class="section-heading"><h2>Sensors</h2><span>${sensors.length} Home Assistant entities</span></div>
      <p>${status.recorder_available ? "Open a sensor's history in Home Assistant. Recorder provides the graph according to your recording and retention settings." : "Current Home Assistant sensor values. Enable Recorder in Home Assistant to record history."}</p>
      ${sensors.length ? `<div class="sensor-list">${sensors.map(sensor => {
        const prefix = device.name || "";
        const remainder = prefix && sensor.name.startsWith(prefix) ? sensor.name.slice(prefix.length) : "";
        const name = /^[\s:·–—-]/.test(remainder) ? remainder.replace(/^[\s:·–—-]+/, "") || sensor.name : sensor.name;
        const unavailable = ["unavailable", "unknown"].includes(sensor.state);
        const value = sensor.disabled ? "Disabled in Home Assistant" : unavailable ? this._valueLabel(sensor.state) : `${this._valueLabel(sensor.state)}${sensor.unit ? " " + sensor.unit : ""}`;
        return `<div class="sensor-row"><div><strong>${this._escape(name)}</strong><small>${this._escape(sensor.entity_id)}</small></div><span class="sensor-reading">${this._escape(value)}</span><button data-action="sensor-history" data-device="${device.device_id}" data-value="${this._escape(sensor.entity_id)}" aria-label="${status.recorder_available ? "History" : "Details"}: ${this._escape(name)}" ${sensor.has_state ? "" : "disabled"}>${status.recorder_available ? "History" : "Details"}</button></div>`;
      }).join("")}</div>` : '<p class="field-help">Sensors will appear here after Home Assistant registers this inverter.</p>'}</section>`;
  }

  _summary(device) {
    const values = device.telemetry;
    if (!values) return "PV — · Battery — · Load —";
    return `PV ${values.pv_power.value} ${values.pv_power.unit || ""} · Battery ${values.battery_soc.value}% · Load ${values.output_power.value} ${values.output_power.unit || ""}`;
  }

  _icon(name) {
    const paths = {
      sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
      inverter: '<rect x="5" y="3" width="14" height="18" rx="3"/><path d="M8 7h8M8 12h3l2-3-2 7 2-3h3M9 18h6"/>',
      battery: '<rect x="4" y="6" width="15" height="12" rx="2"/><path d="M22 10v4M8 10v4m4-4v4m4-4v4"/>',
      home: '<path d="m3 10 9-7 9 7M5 9v12h14V9M9 21v-8h6v8"/>',
      arrow: '<path d="M4 12h15m-6-6 6 6-6 6"/>',
      back: '<path d="M20 12H5m6-6-6 6 6 6"/>',
      plus: '<path d="M12 5v14M5 12h14"/>',
      check: '<path d="m5 12 4 4L19 6"/>',
      shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
      clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
      info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v1"/>',
      menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
      search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',
      link: '<path d="m9 15 6-6M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 10a4 4 0 0 0 6 0l4-4a4 4 0 0 0-6-6l-1 1"/>',
      download: '<path d="M12 3v12m-5-5 5 5 5-5M4 15v6h16v-6"/>',
      edit: '<path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 15v5Z"/>',
      lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/>',
      close: '<path d="m6 6 12 12M18 6 6 18"/>',
      warning: '<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3h.01"/>',
    };
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.info}</svg>`;
  }

  _age(device) {
    if (device.age_seconds == null) return "Waiting for first readings";
    const age = Math.round(device.age_seconds);
    return age < 60 ? `Updated ${age}s ago` : `Last reading ${Math.floor(age / 60)}m ago`;
  }

  _statusChip(device) {
    const paused = device.enabled === false;
    const fresh = !paused && device.connected && !device.stale;
    const label = paused ? "Paused" : !device.connected ? "Offline" : device.stale ? "Waiting for data" : "Connected";
    return `<span class="status-chip ${fresh ? "healthy" : "muted"}"><i class="status-dot ${fresh ? "online" : ""}"></i>${label}</span>`;
  }

  _metric(device, key, label, icon) {
    const reading = device.stale || device.enabled === false ? null : device.telemetry?.[key];
    let value = reading?.value;
    let unit = reading?.unit || "";
    if (typeof value === "number" && unit === "W" && Math.abs(value) >= 1000) { value /= 1000; unit = "kW"; }
    const formatted = value == null ? "—" : typeof value === "number" ? new Intl.NumberFormat("en-US", {maximumFractionDigits: unit === "kW" ? 2 : 1}).format(value) : this._valueLabel(value);
    return `<div class="metric"><span class="metric-label">${this._icon(icon)}${label}</span><div class="metric-value">${this._escape(formatted)}<span>${value == null ? "" : this._escape(unit)}</span></div>
      ${key === "battery_soc" && typeof value === "number" ? `<meter min="0" max="100" value="${value}" aria-label="Battery charge">${value}%</meter>` : ""}</div>`;
  }

  _powerMetrics(device) {
    return `<div class="overview-metrics">${this._metric(device, "pv_power", "Solar generation", "sun")}${this._metric(device, "battery_soc", "Battery charge", "battery")}${this._metric(device, "output_power", ["smg_3","smg_5"].includes(device.profile_id) ? "Output load L1" : "Output load", "home")}${this._metric(device, "operating_mode", "Operating mode", "inverter")}</div>`;
  }

  _modeSummary(device, action = "open") {
    return `<span class="icon-tile accent">${this._icon("edit")}</span><span class="grow"><span class="card-title">Inverter settings</span><span class="card-subtitle">Edit supported parameters with readback confirmation.</span></span><button class="primary" data-action="${action}" data-device="${device.device_id}" data-value="settings">Configuration ${this._icon("arrow")}</button>`;
  }

  _overviewView(device) {
    return `${device.stale || !device.connected ? `<div class="banner attention">${this._icon("info")}<span>${device.connected ? "Waiting for a complete reading. Old values are not shown as current." : "The collector is offline. Your inverter keeps its own settings. Check the local connection to restore live readings."}</span><button class="text-button" data-action="tab" data-value="connection" data-device="${device.device_id}">View connection</button></div>` : ""}
      <section class="live-panel"><div class="section-heading"><h2>Live power</h2><span>${this._age(device)}</span></div>${this._powerMetrics(device)}</section>
      <div class="two-column"><section class="surface"><div class="section-heading"><h2>At a glance</h2></div>
      <div class="detail-row"><span>${this._escape(device.measurement_labels?.grid_voltage || "Grid voltage")}</span><strong>${this._reading(device, "grid_voltage")}</strong></div>
      <div class="detail-row"><span>Battery voltage</span><strong>${this._reading(device, "battery_voltage")}</strong></div>
      <div class="detail-row"><span>PV energy today</span><strong>${this._reading(device, "pv_energy_today")}</strong></div>
      <div class="detail-row"><span>Output frequency</span><strong>${this._reading(device, "output_frequency")}</strong></div></section>
      <section class="surface access-summary">${this._modeSummary(device, "tab")}</section></div>
      ${this._operationView(device.device_id)}`;
  }

  _reading(device, key) {
    const reading = device.stale || device.enabled === false ? null : device.telemetry?.[key];
    return reading?.value == null ? "—" : `${this._escape(reading.value)} <span class="unit">${this._escape(reading.unit || "")}</span>`;
  }

  _connectionView(device, status) {
    return `<div class="two-column"><section class="surface"><div class="section-heading"><h2>Collector connection</h2>${this._statusChip(device)}</div>
      <div class="detail-row"><span>Transport</span><strong>${device.transport === "binary" ? "Binary EyeBond" : "AT / raw RTU"}</strong></div><div class="detail-row"><span>Listener ports</span><strong>${(status.listeners || [{port:502},{port:18899},{port:38899}]).filter(p=>p.bound!==false).map(p=>this._escape(p.port)).join(" · ")}</strong></div>
      <div class="detail-row"><span>Connection preference</span><strong>${this._escape({auto:"Automatic",callback:"Local callback",redirect:"Redirected connection"}[device.connection_options?.method || "redirect"])}</strong></div>
      <div class="detail-row"><span>Active TCP port</span><strong>${this._escape(device.listener_port || "Not connected")}</strong></div>
      ${device.connection_options?.collector_ip ? `<div class="detail-row"><span>Collector IP</span><strong>${this._escape(device.connection_options.collector_ip)}</strong></div>` : ""}
      ${device.connection_error ? `<p class="banner attention">${this._escape(device.connection_error)}. Check the collector identity before reconnecting.</p>` : ""}
      ${device.route ? `<div class="detail-row"><span>Outer route / inner slave</span><strong>${this._escape(device.route.outer.join("/"))} / ${this._escape(device.route.inner_slave)}</strong></div>` : ""}
      <div class="detail-row"><span>Protocol profile</span><strong>${this._escape(device.profile_layers?.base_map?.name || device.profile_id?.replaceAll("_", " ") || "Not identified")}</strong></div>
      <div class="detail-row no-line"><span>Last complete reading</span><strong>${this._age(device)}</strong></div>
      ${this._connectionMethodForm(status, device)}
      <div class="subsection"><h3>Wi-Fi module</h3>
      ${(device.transport === "binary" ? [["firmware_version", "Firmware"], ["hardware_version", "Hardware"]] : [["firmware_version", "Firmware"], ["at_version", "AT version"], ["module_type", "Module type"], ["wifi_status", "Wi-Fi status"], ["cloud_assignment", "Cloud assignment"]]).map(([key, label], index, list) => `<div class="detail-row${index === list.length - 1 ? " no-line" : ""}"><span>${label}</span><strong>${this._escape(device.module?.[key] || "Not read")}</strong></div>`).join("")}
      <p class="field-help">These are read from the collector. Cloud assignment is never written back.</p>
      <p class="field-help">${device.module?.read_at ? `Last read ${this._escape(this._formatTime(device.module.read_at))}.` : "Not read yet."}</p>
      <button data-action="module-info" data-device="${device.device_id}">Read module details</button></div></section>
      <section class="surface"><h2>Data collection</h2><p>These settings affect the bridge's polling, not the inverter's electrical operation.</p>
      <label class="switch-label"><input id="poll-enabled" type="checkbox" data-draft="${device.device_id}:enabled" ${this._draft(device.device_id, "enabled", device.enabled !== false) ? "checked" : ""}> Collect readings</label>
       <p class="field-help">When unchecked, regular polling and new setting writes are paused. An exchange already in progress may finish. The inverter keeps operating; entities and history are retained. Existing TCP connections may keep heartbeats, but automatic callback requests stop.</p>
       <label class="field-label" for="poll-interval">Pause between polls, seconds</label><input id="poll-interval" type="number" min="1" max="300" step="1" data-draft="${device.device_id}:poll_interval" value="${this._escape(this._draft(device.device_id, "poll_interval", device.poll_interval || 10))}">
        <p class="field-help">1–300 seconds after each completed telemetry cycle, not a fixed update interval. A 10-second cycle with a 1-second pause starts the next cycle about 11 seconds later. Polls never overlap. Complete settings are refreshed at least ${this._escape(device.settings_refresh_interval || Math.max(30,device.poll_interval || 10))} seconds apart and after reconnects or writes. Every command still reads its baseline independently. Readings become stale after ${this._escape(device.telemetry_ttl_seconds || (60 + Number(device.poll_interval || 10)))} seconds without an update: 60 seconds plus the pause, so a 300-second pause remains current for 360 seconds.</p><button data-action="poll-options" data-device="${device.device_id}">Save collection settings</button>
      <div class="subsection"><h3>Wi-Fi module</h3><p>Restarts only the collector module. Inverter settings stay unchanged, and readings pause until it reconnects.</p>
       <button class="danger-outline" data-action="reset-module" data-device="${device.device_id}" ${device.capabilities?.module_reset === false ? "disabled" : ""}>Restart Wi-Fi module</button><p class="field-help">Collector reset is implemented for AT sessions. The binary reset command is not implemented; a different connection method alone does not establish support.</p><button data-action="compatibility-open">Collect compatibility report</button></div>
      <div class="subsection"><h3>Allowed network sources</h3><p>Only new collector connections from these addresses are admitted. Use the router IP when the router translates source addresses.</p>
      <label class="field-label" for="allowed-sources">IP addresses or CIDR networks</label><input id="allowed-sources" data-draft="network:sources" value="${this._escape(this._draft("network", "sources", (status.allowed_sources || []).join(", ")))}" placeholder="192.168.10.1">
      <p class="field-help">Separate addresses with commas. An empty list rejects new connections. This setting is shared by all inverters.</p><button data-action="network">Save allowed sources</button></div></section></div>
      ${device.profile_layers ? `<section class="surface">${this._profileLayers(device.profile_layers)}</section>` : ""}
      <section class="surface remove-section"><div><h2>Remove this inverter</h2><p>Remove its saved connection and bridge entities. This does not reset the inverter.</p>${device.unresolved ? '<p class="field-help">Resolve the pending operation first.</p>' : ""}</div><button class="danger-outline" data-action="remove" data-device="${device.device_id}" ${device.unresolved || this._pending[device.device_id] ? "disabled" : ""}>Remove inverter</button></section>`;
  }

  _activityView(device, status) {
    const issue = device.last_issue || (status.last_error ? {code: status.last_error, occurred_at: status.last_error_at} : null);
    const pending = this._pending[device.device_id] || device.unresolved;
    const changes = (device.operations || []).map(record => {
      const actor = record.actor_name ? ` · ${this._escape(record.actor_name)}` : "";
      return `<div class="detail-row"><span>${this._escape(this._changeText(record, status))}<small class="history-time">${this._escape(this._formatTime(record.resolved_at || record.created_at))}${actor}</small></span></div>`;
    }).join("");
    return `${pending ? this._operationView(device.device_id) : ""}
      ${changes ? `<section class="surface"><h2>Recent changes</h2>${changes}</section>` : `<section class="empty-state small"><span class="icon-tile">${this._icon("check")}</span><h2>No recorded changes</h2><p>Applied settings will show the parameter, previous value, new value, time, and who made the change.</p></section>`}
      <section class="surface"><div class="section-heading"><h2>Connection health</h2><span class="heading-actions"><button data-action="journal" data-device="${device.device_id}">${this._icon("download")} Download journal</button><button data-action="download" data-device="${device.device_id}">${this._icon("download")} Download diagnostics</button></span></div>
      <div class="detail-row"><span>Listening for collectors</span><strong>${status.listening ? "Yes" : "No"}</strong></div><div class="detail-row"><span>Unresolved operations</span><strong>${device.unresolved || 0}</strong></div>
      <div class="detail-row"><span>Retry delay</span><strong>${device.poll_backoff_seconds || 0}s</strong></div><div class="detail-row"><span>Rejected connections</span><strong>${status.rejected || 0}</strong></div>
      <div class="detail-row"><span>Last recorded issue</span><strong>${issue ? this._escape(this._issueLabel(issue.code)) : "None recorded"}${issue ? `<small class="history-time">${this._escape(this._formatTime(issue.occurred_at))}${issue.stage ? " · " + this._escape(this._valueLabel(issue.stage)) : ""}</small>` : ""}</strong></div>
       <p class="field-help">Diagnostics omit names, source addresses, credentials, and raw traffic. The journal export keeps operation IDs for maintenance and does not delete them. Repeated identical faults are recorded at most once a minute.</p></section>${this._incidentsView(status, device)}`;
  }

  _formatTime(value) {
    if (!value) return "Time not recorded";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "Time not recorded";
    return new Intl.DateTimeFormat("en-US", {dateStyle: "medium", timeStyle: "medium", timeZone: this._status?.time_zone || undefined}).format(date);
  }

  _compatibilityView(status, showSuggestions = true) {
    const capture = status.compatibility || {};
    const report = this._compatibility || {};
    return `${showSuggestions ? this._profileSuggestions(status) : ""}<section class="surface compatibility-panel"><div class="section-heading"><h2>Compatibility and discovery</h2><button data-action="compatibility-toggle">${this._reportOpen ? "Close report tools" : "Collect compatibility report"}</button></div>
      ${(status.listeners || []).map(port => `<div class="detail-row"><span>TCP ${this._escape(port.requested_port)}</span><strong>${port.bound ? "Listening" : this._escape(`${port.error || "Unavailable"} (${port.errno ?? "unknown"})`)}</strong></div>`).join("")}
      ${(status.profile_catalogue || []).length ? `<details data-disclosure="profile-catalogue"><summary>Available protocol profiles (${status.profile_catalogue.length})</summary><p>Grouped by family; variants and fallback maps are not interchangeable protocols. Counts are implemented maxima: fields absent from a device remain unavailable. Unknown models can use a checked common map after acceptance.</p>${this._catalogueGroups(status.profile_catalogue)}</details>` : ""}
      ${this._device && this._tab === 'activity' ? '' : this._disclosure('incident-diagnostics', 'Diagnostics: local incidents and manual reports', this._incidentsView(status))}
      ${this._reportOpen ? `${this._discoveryView(status)}<p>Works before adding an inverter. Collect for up to two minutes, then download one package with local findings. Reconnect the collector to include startup. No diagnostic writes or resets are sent.</p>
        ${[["inverter_model", "Exact inverter model"], ["collector_model", "Collector model"], ["firmware", "Known firmware"], ["original_endpoint", "Original cloud host:port"], ["symptom", "Symptoms"], ["network_setup", "DNS/routing setup"], ["reference_readings", "Optional display/app readings with time and units"]].map(([key, label]) => `<label class="field-label" for="report-${key}">${label} <span class="optional">Optional</span></label><input id="report-${key}" maxlength="500" data-draft="report:${key}" value="${this._escape(this._draft("report", key, ""))}" placeholder="Unknown is OK">`).join("")}
        <div class="actions"><button class="primary" data-action="compatibility-start" ${capture.active ? "disabled" : ""}>Start collection</button><button data-action="compatibility-stop" ${capture.active ? "" : "disabled"}>Stop collection</button><button data-action="compatibility-analyze">Analyze collected evidence</button></div>
        <p>${capture.active ? `Collecting · ${capture.remaining_seconds}s remaining` : capture.report_id ? "Collection stopped or expired" : "Waiting for a collection"} · ${capture.events || 0} events · ${capture.wire_bytes || 0} wire bytes · ${capture.dropped_events || 0} dropped. Completed traces expire after 15 minutes.</p>
        ${report.analysis ? `<h3>Coverage</h3><p>${Object.entries(report.analysis.coverage || {}).map(([key, value]) => `${this._escape(this._valueLabel(key))}: ${this._escape(value)}`).join(" · ")}</p><ul>${(report.analysis.findings || []).map(item => `<li><strong>${this._escape(this._valueLabel(item.code))}</strong>: ${this._escape(item.next_action)}</li>`).join("")}</ul>` : ""}
        <label class="switch-label"><input id="report-raw" type="checkbox" data-draft="report:raw" ${this._draft("report", "raw", false) ? "checked" : ""}> Include raw protocol exchange</label><p class="field-help">Original bytes may contain hardware identifiers or network settings. Without them, unknown parser failures may not be reproducible. The description you entered is included; review it before sharing. Nothing is uploaded automatically.</p>
        <div class="actions"><button data-action="compatibility-download">Download compatibility ZIP</button><button data-action="compatibility-copy" ${report.analysis ? "" : "disabled"}>Copy issue description</button></div>
        <details><summary>Advanced: silent collector bootstrap</summary><p>Applies to new silent connections on all ports. Port numbers are hints, not protocol proof. With shared NAT, isolate the collector during setup if its dialect cannot be identified.</p><label class="field-label" for="bootstrap-preference">Transport override</label><select id="bootstrap-preference" data-draft="network:bootstrap"><option value="auto" ${this._draft("network", "bootstrap", status.bootstrap_preference || "auto") === "auto" ? "selected" : ""}>Auto</option><option value="at" ${this._draft("network", "bootstrap", status.bootstrap_preference) === "at" ? "selected" : ""}>AT</option><option value="binary" ${this._draft("network", "bootstrap", status.bootstrap_preference) === "binary" ? "selected" : ""}>Binary EyeBond</option></select><button data-action="bootstrap-save">Save bootstrap preference</button></details>` : ""}</section>`;
  }

  _issueSearchLink(value) {
    // Backend/user text is not a trusted navigation target, even after HTML escaping.
    try {
      const url = new URL(value);
      if (url.origin !== 'https://github.com' || url.username || url.password
          || url.pathname !== '/jay0x/solar-inverter-cloud-bridge/issues') return '';
      return `<a class="ha-entities-link" href="${this._escape(url.href)}" target="_blank" rel="noopener noreferrer">Search existing GitHub issues</a>`;
    } catch (_) { return ''; }
  }

  _incidentMetadataFields(scope, prefix, failure = false) {
    const fields = [['inverter_model', 'Inverter model'], ['collector_model', 'Collector model'], ['firmware', 'Firmware']];
    if (failure) fields.push(['symptom', 'Symptoms']);
    return `<div class="incident-fields">${fields.map(([key, label]) => `<label class="field-label">${label} <span class="optional">Optional</span><input id="${prefix}-${key}" maxlength="500" data-draft="${this._escape(scope + ':' + key)}" value="${this._escape(this._draft(scope, key, ''))}"></label>`).join('')}</div>`;
  }

  _incidentReportView(scope, kind) {
    const report = this._incidentReports?.[scope]?.[kind];
    if (!report?.issue_summary) return '';
    return `<div class="incident-report"><h3>Downloaded report description</h3><pre>${this._escape(report.issue_summary)}</pre><div class="incident-actions"><button data-action="incident-copy" data-value="${kind}">Copy report description</button>${this._issueSearchLink(report.search_url)}</div></div>`;
  }

  _incidentsView(status, device = null) {
    const view = (device ? device.incidents : status.incidents) || {};
    const global = status.incidents || view;
    const limits = global.limits || view.limits || {};
    const scope = device?.device_id || 'global';
    const entries = view.incidents || [];
    const devices = status.devices || [];
    const target = device || devices.find(item => item.device_id === this._draft('incidents', 'watch_device', '')) || devices[0];
    const watch = global.watch || {};
    const watches = watch.items || (watch.device_id ? [watch] : []);
    const targetWatch = target?.incidents?.watch || watches.find(item => item.device_id === target?.device_id) || {};
    const watchScope = 'incident-watch:' + (target?.device_id || 'none');
    const failureScope = 'incident-report:' + scope;
    const feedbackScope = 'incident-feedback:' + scope;
    const esc = value => this._escape(value ?? 'Unknown');
    return `<section class="surface incident-panel" data-incident-scope="${esc(scope)}"><h2>Local incident black box</h2>
      <p>Evidence stays in Home Assistant. Nothing is uploaded automatically and no GitHub issue is created. Download a report, review it, search existing issues, then choose whether to share it.</p>
      <div class="incident-recording-controls"><label class="switch-label"><input id="incident-enabled" type="checkbox" data-draft="incidents:enabled" aria-describedby="incident-recording-status" ${this._draft('incidents', 'enabled', global.enabled !== false) ? 'checked' : ''}> Enable local incident recording</label><div class="incident-actions"><button data-action="incident-configure">Save incident recording</button></div><p id="incident-recording-status" class="field-help" role="status" aria-live="polite"></p></div>
      <p class="field-help">Global setting for all devices and bridge/pre-enrollment events. Known recovered problems update these counters without pop-up alerts.</p>
      <div class="incident-storage"><p>Persistence: ${esc(global.persistence || 'unknown')} · ${global.pending_write ? 'Pending write' : 'No pending write'}</p>
      ${global.persistence === 'memory_only' ? '<p>Memory-only evidence does not survive a Home Assistant restart.</p>' : ''}
      ${global.persistence_error ? `<p class="dialog-error">Persistence error: ${esc(global.persistence_error)}</p>` : ''}
      <p>Rolling buffer: ${esc(limits.ring_seconds ?? 60)} seconds before failure + ${esc(limits.tail_seconds ?? 10)} seconds after · ${esc(limits.ring_bytes ?? 524288)} bytes maximum.</p>
      <p>Storage bounds: ${esc(limits.fingerprints ?? 32)} fingerprints · ${esc(limits.samples_per_problem ?? 3)} samples per problem · ${esc(global.serialized_sample_bytes ?? 0)} / ${esc(limits.serialized_sample_bytes ?? 16777216)} serialized sample bytes.</p>
      <p>Dropped events: ${esc(global.dropped_events ?? 0)} · Evicted incidents: ${esc(global.evicted_incidents ?? 0)}</p></div>
      <div class="subsection incident-watch"><h3>Catch next failure</h3><p>A watch only observes events; it never starts polling, resumes collection, connects a collector, or sends device commands. An active watch can retain its next failure even when global recording is off. Its status and expiration are saved by the backend when persistence is available.</p>
      ${!device && devices.length ? `<label class="field-label" for="incident-watch-device">Watch device</label><select id="incident-watch-device" data-draft="incidents:watch_device">${devices.map(item => `<option value="${esc(item.device_id)}" ${item === target ? 'selected' : ''}>${esc(item.name || item.device_id)}</option>`).join('')}</select>` : ''}
      ${target ? `${target.enabled === false ? '<p class="field-help">Collection is paused for this device. This watch will not enable it; a polling failure can only be captured if collection is separately resumed.</p>' : ''}
      <p class="watch-status">Watch: ${esc(targetWatch.status || (targetWatch.active ? 'armed' : 'not armed'))} · ${targetWatch.active ? 'Active' : 'Inactive'}${targetWatch.expires_at ? ' · Expires: ' + esc(this._formatTime(targetWatch.expires_at)) : ''}${targetWatch.fingerprint ? ' · Captured: ' + esc(targetWatch.fingerprint) : ''}</p>
      <label class="field-label" for="incident-watch-hours">Watch duration, hours (1–24)</label><input id="incident-watch-hours" type="number" required min="1" max="24" step="1" data-draft="${esc(watchScope + ':hours')}" value="${esc(this._draft(watchScope, 'hours', 1))}">
      <div class="incident-actions"><button data-action="incident-watch" data-device="${esc(target.device_id)}">Catch next failure</button><button data-action="incident-cancel_watch" data-device="${esc(target.device_id)}" ${targetWatch.active ? '' : 'disabled'}>Cancel watch</button></div>` : '<p>Add an inverter to arm a device watch. Bridge and pre-enrollment incidents are still listed below.</p>'}
      ${!device && watches.length > 1 ? `<ul>${watches.map(item => `<li>${esc(devices.find(d => d.device_id === item.device_id)?.name || item.device_id)}: ${esc(item.status)}${item.expires_at ? ' · Expires: ' + esc(this._formatTime(item.expires_at)) : ''}${item.fingerprint ? ' · Captured: ' + esc(item.fingerprint) : ''}</li>`).join('')}</ul>` : ''}</div>
      <div class="subsection"><h3>Recorded incidents (${entries.length})</h3><p>Repeated failures share a fingerprint and counters; retained samples are bounded.</p>
      <div class="incident-cards">${entries.map(item => `<article class="incident-card ${item.needs_attention ? 'attention' : ''}" data-fingerprint="${esc(item.fingerprint)}"><h3>${esc(item.known_issue?.title || item.code)}</h3>
        <p>${esc(devices.find(d => d.device_id === item.device_id)?.name || item.device_id || 'Bridge / pre-enrollment')}</p>
        <dl><div><dt>Fingerprint</dt><dd><code>${esc(item.fingerprint)}</code></dd></div><div><dt>Code</dt><dd>${esc(item.code)}</dd></div><div><dt>Stage / profile / transport</dt><dd>${esc(item.stage)} / ${esc(item.profile_id)} / ${esc(item.transport)}</dd></div>
        <div><dt>First seen</dt><dd>${esc(this._formatTime(item.first_seen))}</dd></div><div><dt>Last seen</dt><dd>${esc(this._formatTime(item.last_seen))}</dd></div>
        <div><dt>Count / recovered / samples</dt><dd>${esc(item.count ?? 0)} / ${esc(item.recovered_count ?? 0)} / ${esc(item.sample_count ?? 0)}</dd></div><div><dt>Status</dt><dd>${esc(item.status)} · ${item.needs_attention ? 'Needs attention' : 'No attention needed'}</dd></div></dl>
        ${item.known_issue ? `<p>${esc(item.known_issue.status)}: ${esc(item.known_issue.advice || '')}</p>` : ''}
        <div class="incident-actions">${this._issueSearchLink(item.search_url)}<button data-action="incident-download" data-value="${esc(item.fingerprint)}" data-device="${esc(item.device_id ?? device?.device_id ?? '')}">Download incident ZIP</button><button class="danger-outline" data-action="incident-delete" data-value="${esc(item.fingerprint)}" data-device="${esc(item.device_id ?? device?.device_id ?? '')}">Delete local evidence</button></div></article>`).join('') || '<p>No incidents recorded.</p>'}</div>
      <details data-disclosure="incident-export-metadata"><summary>Optional failure report description</summary>${this._incidentMetadataFields(failureScope, 'incident-report', true)}</details>
      <label class="switch-label"><input id="incident-raw" type="checkbox" ${this._incidentRaw ? 'checked' : ''}> Include raw protocol exchange in the next incident export</label><p class="field-help">Sanitized by default. Raw bytes may contain hardware identifiers or network settings. This choice resets after export or page reload. Your optional description is included verbatim; review it before sharing. Deleting local evidence does not remove downloaded reports.</p>
      ${this._incidentReportView(scope, 'failure')}</div>
      <details class="subsection" data-disclosure="incident-feedback"><summary>User compatibility feedback</summary><p>A separate user-reported compatibility report, not a failure export. No capture or device command is started. Download and review the report before manually sharing it.</p>
      ${this._incidentMetadataFields(feedbackScope, 'incident-feedback')}
      <label class="field-label" for="incident-feedback-feature">Feature ID</label><input id="incident-feedback-feature" required maxlength="96" pattern="[A-Za-z_][A-Za-z0-9_.:\\-]{0,95}" data-draft="${esc(feedbackScope + ':feature')}" value="${esc(this._draft(feedbackScope, 'feature', 'telemetry'))}"><p class="field-help">For example: telemetry, clock_sync, or setting.output_voltage_setting.</p>
      <label class="field-label" for="incident-feedback-result">Result</label><select id="incident-feedback-result" data-draft="${esc(feedbackScope + ':result')}">${[['unknown', 'Unknown'], ['working', 'Working'], ['not_working', 'Not working']].map(([key, label]) => `<option value="${key}" ${this._draft(feedbackScope, 'result', 'unknown') === key ? 'selected' : ''}>${label}</option>`).join('')}</select>
      <label class="field-label" for="incident-feedback-comment">Comment <span class="optional">Optional</span></label><textarea id="incident-feedback-comment" rows="3" maxlength="2000" data-draft="${esc(feedbackScope + ':comment')}">${esc(this._draft(feedbackScope, 'comment', ''))}</textarea>
      <p class="field-help">Model, firmware, and comments are included verbatim and may identify you. Nothing is uploaded automatically.</p><button data-action="incident-feedback" ${device ? `data-device="${esc(device.device_id)}"` : ''}>Download feedback report</button>${this._incidentReportView(scope, 'feedback')}</details></section>`;
  }

  _incidentAction(action, fingerprint, device) {
    const command = action.slice('incident-'.length);
    const scope = this.querySelector('[data-incident-scope]')?.dataset.incidentScope || 'global';
    if (command === 'copy') {
      const summary = this._incidentReports?.[scope]?.[fingerprint]?.issue_summary || '';
      return Promise.resolve().then(() => navigator.clipboard.writeText(summary)).catch(() => {
        this._error = 'Clipboard unavailable. Select the report description below to copy it.';
        this._render();
      });
    }
    const request = {type: 'solar_inverter_bridge/incidents', action: command};
    if (device !== undefined) request.device_id = device;
    if (command === 'configure') request.enabled = this.querySelector('#incident-enabled').checked;
    if (command === 'watch') {
      const input = this.querySelector('#incident-watch-hours');
      if (!input?.reportValidity() || !Number.isInteger(Number(input.value))) return;
      request.hours = Number(input.value);
    }
    if (command === 'delete' || command === 'download') request.fingerprint = fingerprint;
    if (command === 'download' || command === 'feedback') {
      const prefix = command === 'download' ? 'incident-report' : 'incident-feedback';
      request.metadata = {};
      for (const key of ['inverter_model', 'collector_model', 'firmware', ...(command === 'download' ? ['symptom'] : [])]) {
        request.metadata[key] = (this.querySelector(`#${prefix}-${key}`)?.value || '').slice(0, 500);
      }
      if (command === 'download') request.include_raw = this.querySelector('#incident-raw')?.checked === true;
      else {
        const feature = this.querySelector('#incident-feedback-feature');
        if (!feature?.reportValidity()) return;
        request.feedback = [{feature: feature.value, result: this.querySelector('#incident-feedback-result').value,
          comment: this.querySelector('#incident-feedback-comment').value.slice(0, 2000)}];
      }
    }
    return this._call(request, result => {
      if (command === 'configure') this._clearDraft('incidents', 'enabled');
      if (command === 'download' || command === 'feedback') {
        this._incidentReports ||= {};
        this._incidentReports[scope] ||= {};
        this._incidentReports[scope][command === 'download' ? 'failure' : 'feedback'] = result.analysis;
        if (command === 'download') this._incidentRaw = false;
        if (result.base64) {
          const data = Uint8Array.from(atob(result.base64), char => char.charCodeAt(0));
          const url = URL.createObjectURL(new Blob([data], {type: 'application/zip'}));
          const link = document.createElement('a'); link.href = url; link.download = result.filename; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }
      }
    });
  }

  _discoveryView(status) {
    const labels = {tcp_received:"TCP connection received",source_rejected:"Source rejected by the allowlist",dialect_selected:"Dialect candidate selected",identity_confirmed:"Full collector identity confirmed",route_qualified:"Inverter route and native profile verified",native_signature_rejected:"Unsupported or unconfirmed inverter map",verification_failed:"Inverter verification failed",admission_failed:"Collector identity not established",bootstrap_exhausted:"Silent bootstrap exhausted; review Advanced preference or shared NAT"};
    return (status.discovery || []).length ? `<div class="subsection"><h3>Recent discovery progress</h3><ul>${status.discovery.map(attempt => `<li>TCP ${this._escape(attempt.listener_port)} · ${this._escape(labels[attempt.stage] || attempt.stage)}${attempt.dialect ? " · " + this._escape(attempt.dialect) : ""}${attempt.model_code ? " · native " + this._escape(attempt.protocol_number) + "/" + this._escape(attempt.model_code) : ""}</li>`).join("")}</ul></div>` : "";
  }

  _parameters(deviceId) {
    return this._status?.devices?.find(device => device.device_id === deviceId)?.parameters || this._status?.parameters || [];
  }

  _profileSuggestions(status, compact = false) {
    const searches = status.profile_searches || [];
    const collectors = status.pending || [];
    if (!collectors.length && !searches.length) return "";
    const stages = {searching:"Checking available profiles",waiting_for_reconnect:"Waiting for the collector to reconnect",candidates_available:"Choose a compatible profile",more_probes_available:"More profiles can be checked",complete:"No matching profile found",expired:"The check has expired",cancelled:"Check stopped",selected:"Profile confirmed"};
    return `<section class="${compact ? "profile-review" : "surface"} compatibility-panel">${compact ? "" : '<h2>Find a compatible profile</h2><p>Unknown models can be checked against available protocol families. Only read queries are used; you review a possible match before adding it.</p>'}
      ${collectors.map(item => `<div class="candidate"><span>${this._escape(item.identity_ref)} · ${this._escape(item.transport || "AT")}</span><button data-action="profile-discover" data-value="${this._escape(item.identity_sha256)}">Recognize protocol and profile</button></div>`).join("")}
      ${searches.map(search => `<div class="subsection"><h3 role="status">${this._escape(stages[search.state] || this._valueLabel(search.state))}</h3><p>${search.state === "waiting_for_reconnect" ? "The check will continue when the collector returns. You can leave this page open." : search.candidates?.length ? "Compare these readings with the inverter display, then confirm the profile below." : search.state === "searching" ? "Reading the inverter. This may take several connections; no settings are changed." : "You can check other profiles or collect a report for device support."}</p><small>${search.tested} of ${search.total} profile/route checks</small>
        ${(search.candidates || []).map(item => `<article class="surface"><h3>${this._escape(item.name)}</h3><p>Source-derived, not hardware verified.</p>${this._profileLayers(item.profile_layers)}<p>${Object.entries(item.values || {}).slice(0,8).map(([key,reading])=>`${this._escape(this._valueLabel(key))}: ${this._escape(reading.value)} ${this._escape(reading.unit || "")}`).join(" · ")}</p><p class="banner attention">${this._escape(item.warning)}</p>
        <label class="switch-label"><input id="ack-${item.fingerprint}" type="checkbox" data-draft="profile:${item.fingerprint}:ack" ${this._drafts[`profile:${item.fingerprint}:ack`] ? "checked" : ""}> I accept this inferred profile for readings and its implemented controls</label>
        <div class="actions"><button class="primary" data-action="profile-select" data-device="${this._escape(search.collector_sha256)}" data-value="${item.fingerprint}" ${search.state === "searching" || search.state === "expired" ? "disabled" : ""}>${item.profile_layers?.common_only ? "Use common map" : "Use this profile"} ${this._icon("arrow")}</button></div></article>`).join("")}
        ${!["searching","waiting_for_reconnect","complete","selected"].includes(search.state) ? `<button data-action="${search.state === "expired" ? "profile-discover" : "profile-more"}" data-value="${this._escape(search.collector_sha256)}">${search.state === "expired" ? "Start a new check" : "Check other available profiles"}</button>` : ""}
        ${["searching","waiting_for_reconnect"].includes(search.state) ? `<button data-action="profile-cancel" data-value="${this._escape(search.collector_sha256)}">Stop recognition</button>` : ""}
        ${compact ? '<p class="field-help">Need help? Open Connection help and diagnostics below to collect a support report.</p>' : '<p>Collect a compatibility report to help support this device. Nothing is uploaded automatically.</p><button data-action="compatibility-open">Collect data for device support</button>'}</div>`).join("")}</section>`;
  }

  _catalogueGroups(profiles) {
    const groups = {};
    for (const profile of profiles) (groups[profile.family_name || "Other profiles"] ||= []).push(profile);
    return Object.entries(groups).map(([family,items]) => `<section class="profile-family"><h3>${this._escape(family)}</h3><ul>${items.map(profile=>`<li><strong>${this._escape(profile.variant || profile.name)}</strong> · ${profile.measurements} measurements · ${profile.controls} source-defined controls.<br>${this._escape(profile.evidence)}${profile.profile_layers ? `<details data-disclosure="profile-map-${this._escape(profile.profile_id)}"><summary>Map composition</summary>${this._profileLayers(profile.profile_layers)}</details>` : ""}</li>`).join("")}</ul></section>`).join("");
  }

  _profileLayers(layers) {
    if (!layers) return "";
    const extension = layers.extension;
    const basis = {native_protocol_and_model: "Native protocol and model signature",
      source_identity_anchors_and_two_snapshots: "Model identity markers and two matching snapshots",
      source_catalog_signature_and_two_snapshots: "Source-listed signature and two matching snapshots",
      family_shape_and_two_snapshots: "Family read checks and two matching snapshots",
      selected_profile_definition: "Selected profile definition; no new device check"};
    const evidence = {catalogue: "Catalog definition, not device verification", proposal: "Read-based proposal; acceptance required",
      checked: "Enrollment read checks completed", observed: "Current readings available",
      saved: "Saved profile; waiting for current readings", recheck_required: "Evidence changed; profile recheck required"};
    return `<div class="profile-layers"><h3>Profile composition</h3>
      ${layers.family_name ? `<div class="detail-row"><span>Family / variant</span><strong>${this._escape(layers.family_name)} · ${this._escape(layers.variant)}</strong></div>` : ""}
      <div class="detail-row"><span>Common map</span><strong>${this._escape(layers.base_map?.name || "Not identified")}</strong></div>
      <div class="detail-row"><span>${extension?.kind === "command_variant" ? "Protocol variant" : extension?.kind === "reference_inventory" ? "Reference extension" : "Model extension"}</span><strong>${extension ? this._escape(extension.name) : "None — common map only"}</strong></div>
      ${extension ? `<ul>${(extension.changes || []).map(change => `<li>${this._escape(change)}</li>`).join("")}</ul>${extension.required ? '<p class="field-help">Required by this profile. Corrections and identity checks cannot be disabled separately.</p>' : ""}` : '<p class="field-help">Only the implemented common subset is used. An exact retail model name is not required; model-specific functions are not added automatically.</p>'}
      <div class="detail-row"><span>Selection basis</span><strong>${this._escape(basis[layers.selection_basis] || this._valueLabel(layers.selection_basis))}</strong></div>
      ${layers.protocol_number != null || layers.model_code != null ? `<div class="detail-row"><span>Native identity</span><strong>${layers.protocol_number != null ? "Protocol " + this._escape(layers.protocol_number) + " · " : ""}${layers.model_code != null ? "Model code " + this._escape(layers.model_code) : "Model code not read"}</strong></div>` : ""}
      ${layers.qualification ? `<p class="field-help">${this._escape(layers.qualification)}</p>` : ""}
      <p class="field-help">${this._escape(evidence[layers.evidence_state] || "Profile evidence not available")}</p></div>`;
  }

  _issueLabel(code) {
    return {TimeoutError: "Inverter response timed out", ConnectionResetError: "Collector connection reset",
      collector_closed: "Collector disconnected", crc_mismatch: "Invalid response checksum",
      clock_correction_too_large: "Clock correction blocked by a previous version's limit", clock_correction_not_required: "Clock is already within the synchronization threshold", storage_unavailable: "Storage unavailable",
      unsupported_or_unconfirmed_identity: "Unsupported inverter signature"}[code] || this._valueLabel(code);
  }

  _downloadJournal(offset = 0, records = []) {
    return this._call({type: "solar_inverter_bridge/journal", offset, limit: 200}, page => {
      const next = records.concat(page.records || []);
      if ((page.records || []).length < page.limit) {
        const payload = {exported_at: new Date().toISOString(), retained: page.retained, max_operations: page.max_operations, records: next};
        const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"}));
        const link = document.createElement("a"); link.href = url; link.download = "solar-inverter-bridge-journal.json"; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        return;
      }
      this._downloadJournal(offset + page.records.length, next);
    });
  }

  _errorMessage(code) {
    return {
      baseline_conflict: "The inverter value changed while you were editing. Your draft is kept. Discard it to use the latest value, then review your change.",
      ambiguous_schedule_window: "Start time must be earlier than stop time. Overnight windows are not supported.",
      soc_recovery_must_exceed_protection: "Recovery SOC must be higher than protection SOC.",
      editing_not_allowed: "The saved control mode does not allow this change.",
      transport_write_unsupported: "Control is unavailable for the current profile/session. Check implemented commands, profile acceptance, and fresh readings from this connection.",
      transport_reset_unsupported: "Module reset is not qualified for this transport. No cooldown or reset command was reserved.",
      binary_route_not_qualified: "No supported inverter route/profile could be verified. Collect a compatibility report with the original exchange below.",
      binary_full_identity_missing: "The collector did not supply an authoritative full PN. Collect startup evidence; a heartbeat prefix is insufficient.",
      unsupported_or_unconfirmed_identity: "The inverter's native signature is not admitted. Collect a compatibility report below; a connected collector alone does not select a register map.",
      permissions_changed: "Control settings changed while the request was waiting. Review the mode before trying again.",
      device_busy_or_unresolved: "A pending operation must be resolved first. Open Activity to check its result.",
      collector_not_connected: "The collector is offline. Wait for it to reconnect before applying a change.",
      collector_reset_rejected: "The Wi-Fi module did not accept the restart command. No inverter setting was written.",
      collector_at_rejected: "The collector did not answer a module query. No configuration was written.",
      parameter_not_observed: "A valid reading of this parameter is required before it can be changed.",
      value_outside_register_step: "The value does not match the parameter step. It was not rounded or sent.",
      value_outside_register_range: "The value cannot be encoded in this unsigned register.",
      value_outside_documented_bounds: "The value is outside the documented range for this parameter.",
      finite_numeric_value_required: "Enter a finite numeric value.",
      observed_value_changed: "The value changed again. Check the result before confirming it.",
      invalid_allowed_sources: "Enter valid IP addresses or CIDR networks, separated by commas.",
      verification_required: "Run the read-only connection check again before adding this inverter.",
      unsupported_or_unconfirmed_identity: "The standard profile did not match. Checking other available profiles for your review.",
      unrestricted_source: "Use a specific IP address or network instead of an unrestricted network.",
      device_capacity_reached: "This bridge already has 16 saved inverters. Remove one before adding another.",
      operation_capacity_reached: "The operation journal is full. Monitoring is still available; download the journal for maintenance. Operation IDs are not deleted automatically.",
      storage_unavailable: "The bridge could not save its data. The request was not confirmed.",
      storage_backup_in_progress: "A Home Assistant backup is copying the bridge database. Try the change again when it finishes.",
      storage_corrupt: "The bridge database failed its integrity check and was not opened.",
    }[code] || code;
  }

  _valueLabel(value) {
    const labels = {sub: "SUB", sbu: "SBU", suf: "SUF", sof: "SOF", snu: "SNU", oso: "OSO", sor: "SOR", mains: "Utility power", off_grid: "Off-grid", fault: "Fault"};
    const text = String(value);
    if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return text.replace("T", " ");
    return labels[text] || text.replaceAll("_", " ").replace(/^./, char => char.toUpperCase());
  }

  _reason(item) {
    if (item.access === "read_only") return "Read-only";
    if (item.kind === "datetime") return "Managed by automatic clock sync";
    if (!item.execution_ready) return "Write path not enabled yet";
    return "Editable";
  }

  _escape(value) {
    return String(value).replace(/[&<>"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char]));
  }

  _action(action, value, device) {
    if (action.startsWith('incident-')) return this._incidentAction(action, value, device);
    if (action === "compatibility-open") { this._reportOpen=true; this._disclosures['setup-help']=true; this._disclosures['home-help']=true; this._render(); this.querySelector('#report-inverter_model')?.scrollIntoView({block:'center'}); return; }
    if (action === "profile-discover" || action === "profile-more") return this._call({type:"solar_inverter_bridge/profile",action:"discover",collector_sha256:value,resume:action==="profile-more"});
    if (action === "profile-cancel") return this._call({type:"solar_inverter_bridge/profile",action:"cancel",collector_sha256:value});
    if (action === "profile-recheck") return this._call({type:"solar_inverter_bridge/profile",action:"recheck",device_id:device,...(this.querySelector('#profile-variant') ? {variant_id:this.querySelector('#profile-variant').value} : {})});
    if (action === "profile-select") {
      if (!this.querySelector(`#ack-${value}`)?.checked) { this._error="Read and acknowledge the inferred-profile warning first.";return this._render(); }
      return this._call({type:"solar_inverter_bridge/profile",action:"select",collector_sha256:device,fingerprint:value,acknowledged:true},result=>{
        if(result.ready){
          if(result.device_id) { this._clearDraft(result.device_id,'profile_variant'); return this._navigate(`sib/device/${result.device_id}/settings`); }
          const candidate = this._status.pending?.find(item => item.identity_sha256 === device);
          if (candidate) Object.assign(candidate, result);
          this._drafts['setup:collector']=device;this._saveDrafts();this._navigate('sib/add/3');
        }
      });
    }
    if (action === "compatibility-toggle") { this._reportOpen = !this._reportOpen; return this._render(); }
    if (action === "bootstrap-save") return this._call({type: "solar_inverter_bridge/configure_network", allowed_sources: this._status.allowed_sources || [], bootstrap_preference: this.querySelector("#bootstrap-preference").value}, () => this._clearDraft("network", "bootstrap"));
    if (action === "compatibility-copy") return navigator.clipboard.writeText(this._compatibility?.analysis?.issue_summary || "").catch(() => { this._error = "Clipboard unavailable. Download the ZIP and copy README.txt."; this._render(); });
    if (action.startsWith("compatibility-")) {
      const command = {"compatibility-start": "start", "compatibility-stop": "stop", "compatibility-analyze": "status", "compatibility-download": "download"}[action];
      if (!command) return;
      const metadata = {};
      for (const key of ["inverter_model", "collector_model", "firmware", "original_endpoint", "symptom", "network_setup", "reference_readings"]) metadata[key] = this.querySelector(`#report-${key}`)?.value || "";
      const include_raw = this.querySelector("#report-raw")?.checked || false;
      return this._call({type: "solar_inverter_bridge/compatibility", action: command, metadata, include_raw}, result => {
        this._compatibility = result;
        if (result.base64) {
          const data = Uint8Array.from(atob(result.base64), char => char.charCodeAt(0));
          const url = URL.createObjectURL(new Blob([data], {type: "application/zip"}));
          const link = document.createElement("a"); link.href = url; link.download = result.filename; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }
      });
    }
    if (action === "sensor-history") {
      const sensor = this._status?.devices.find(item => item.device_id === device)?.ha_sensors?.find(item => item.entity_id === value);
      if (!sensor?.has_state) return;
      return this.dispatchEvent(new CustomEvent("hass-more-info", {detail: {entityId: value}, bubbles: true, composed: true}));
    }
    if (action === "module-info") return this._call({type: "solar_inverter_bridge/module_info", device_id: device});
    if (action === "reset-module") return this._call({type: "solar_inverter_bridge/reset_collector", device_id: device});
    if (action === "remove") { this._removeTarget = device; this._removeConfirm = ""; this._error = ""; return this._render(); }
    if (action === "cancel-remove") { this._removeTarget = null; this._removeConfirm = ""; return this._render(); }
    if (action === "confirm-remove") {
      const target = this._status.devices.find(item => item.device_id === device);
      if (!target || this._removeConfirm !== target.name) return;
      return this._call({type: "solar_inverter_bridge/remove_device", device_id: device}, () => {
        this._removeTarget = null;
        this._removeConfirm = "";
        for (const key of Object.keys(this._drafts)) if (key.startsWith(device + ":")) { delete this._drafts[key]; delete this._baselines[key]; }
        delete this._pending[device]; delete this._results[device];
        this._saveDrafts();
        this._navigate("sib");
      });
    }
    if (action === "menu") return this.dispatchEvent(new Event("hass-toggle-menu", {bubbles: true, composed: true}));
    if (action === "dismiss") { this._error = ""; this._loadError = ""; }
    if (action === "add") { this._error=""; this._reportOpen=false; this._disclosures['setup-help']=false; return this._navigate("sib/add/0"); }
    if (action === "back" || action === "close") return this._navigate("sib");
    if (action === "open") return this._navigate(`sib/device/${device}/settings`);
    if (action === "open-overview") return this._navigate(`sib/device/${device}/overview`);
    if (action === "tab") return this._navigate(`sib/device/${device}/${value}`);
    if (action === "setup-back") return this._navigate(`sib/add/${Math.max(0, this._wizardStep - 1)}`);
    if (action === "setup-connections") { this._error=""; return this._navigate("sib/add/1"); }
    if (action === "connect-collector" || action === "save-connection") {
      const scope = action === "save-connection" ? device + ":connection" : "setup";
      const config = {method:this.querySelector('#connection-method').value,
        collector_ip:this.querySelector('#collector-ip').value.trim(),
        callback_host:this.querySelector('#callback-host').value.trim(),
        callback_port:Number(this.querySelector('#callback-port').value),
        udp_port:Number(this.querySelector('#callback-udp-port').value)};
      if (config.method === 'callback' && !config.collector_ip) { this._error='Enter the Wi-Fi collector IP address.';return this._render(); }
      if (config.method !== 'redirect' && config.collector_ip && !config.callback_host) { this._error='Enter a Home Assistant LAN IP in Callback network settings.';return this._render(); }
      const signature=JSON.stringify(config);
      const previous=(this._status.connection_requests || []).find(r=>r.request_id===this._drafts[scope+':connection_request']);
      if (this._drafts[scope+':connection_signature']!==signature || !this._drafts[scope+':connection_request'] || (previous && ['failed','timed_out','disconnected','superseded'].includes(previous.state))) {
        this._drafts[scope+':connection_request']=crypto.randomUUID();
        this._drafts[scope+':connection_signature']=signature;
      }
      if (!this._saveDrafts()) return;
      return this._call({type:'solar_inverter_bridge/'+(action === 'save-connection' ? 'set_connection' : 'connect_collector'),...(action === 'save-connection' ? {device_id:device} : {}),request_id:this._drafts[scope+':connection_request'],...config},result=>{
        this._status.connection_requests=[...(this._status.connection_requests || []).filter(r=>r.request_id!==result.request_id),result];
        if (action === 'save-connection') for (const key of ['method','collector_ip','callback_host','callback_port','udp_port']) this._clearDraft(scope,key);
      });
    }
    if (action === "choose-collector") {
      this._drafts["setup:collector"] = value;
      this._saveDrafts();
      const candidate = this._status.pending?.find(item => item.identity_sha256 === value);
      if (candidate?.ready) return this._navigate("sib/add/3");
      this._navigate("sib/add/2");
      if (this._status.profile_searches?.some(search => search.collector_sha256 === value && ["searching","waiting_for_reconnect"].includes(search.state))) return;
      return this._verifyCollector(value);
    }
    if (action === "setup-next") {
      const name = this.querySelector("#setup-name").value.trim();
      if (!name) { this._error = "Give your inverter a name."; return this._render(); }
      this._drafts["setup:name"] = name;
      this._saveDrafts();
      const source = this.querySelector("#network-source").value.trim();
      if (source) return this._call({type: "solar_inverter_bridge/configure_network", allowed_sources: [...new Set([...(this._status.allowed_sources || []), ...source.split(/[,\s]+/).filter(Boolean)])]}, () => this._navigate("sib/add/1"));
      return this._navigate("sib/add/1");
    }
    if (action === "verify") { this._navigate("sib/add/2"); return this._verifyCollector(value); }
    if (action === "enroll") {
      const name = this._draft("setup", "name", "Inverter");
      const request=(this._status.connection_requests || []).find(r=>r.request_id===this._drafts['setup:connection_request']);
      const connection = request && (!request.collector_ip || request.collector_sha256===value) ? {connection_request_id:request.request_id} : {};
      return this._call({type: "solar_inverter_bridge/enroll", collector_sha256: value, name,...connection}, result => {
        for (const key of ["name", "source", "collector", "method", "collector_ip", "callback_host", "callback_port", "udp_port", "connection_request", "connection_signature"]) this._clearDraft("setup", key);
        this._navigate(`sib/device/${result.device_id}/overview`);
      });
    }
    if (action === "clock") {
      return this._call({type: "solar_inverter_bridge/set_clock_sync", device_id: device, enabled: this.querySelector("#clock-sync").checked}, () => this._clearDraft(device, "clock"));
    }
    if (action === "auto-reset") {
      return this._call({type: "solar_inverter_bridge/set_auto_reset", device_id: device, enabled: this.querySelector("#auto-reset").checked}, () => this._clearDraft(device, "auto_reset"));
    }
    if (action === "apply") {
      return this._applyParameter(device, value);
    }
    if (action === "edit") {
      this._editingField = `${device}:${value}`;
      if (!(this._editingField in this._baselines)) this._baselines[this._editingField] = this._status.devices.find(item => item.device_id === device)?.settings?.[value];
      this._render();
      this.querySelector("#edit-" + value)?.focus();
      return;
    }
    if (action === "check") {
      return this._call({type: "solar_inverter_bridge/check_operation", device_id: device, operation_id: value}, result => this._operationResult(device, result));
    }
    if (action === "resume" && this._pending[device]) {
      return this._call(this._pending[device], result => this._operationResult(device, result));
    }
    if (action === "accept-current") {
      const record = this._status.devices.find(item => item.device_id === device)?.operations?.find(item => item.operation_id === value) || this._results[device];
      return this._call({type: "solar_inverter_bridge/accept_current_value", device_id: device, operation_id: value, expected_value: record.last_observed_value, expected_observed_at: record.last_observed_at}, result => this._operationResult(device, result));
    }
    if (action === "discard") this._clearDraft(device, value);
    if (action === "network") {
      const sources = this.querySelector("#allowed-sources").value.split(/[,\s]+/).filter(Boolean);
      return this._call({type: "solar_inverter_bridge/configure_network", allowed_sources: sources}, () => this._clearDraft("network", "sources"));
    }
    if (action === "poll-options") {
      if (!this.querySelector("#poll-interval").reportValidity()) return;
      return this._call({type: "solar_inverter_bridge/set_collection", device_id: device, enabled: this.querySelector("#poll-enabled").checked, poll_interval: Number(this.querySelector("#poll-interval").value)}, () => {
        this._clearDraft(device, "enabled"); this._clearDraft(device, "poll_interval");
      });
    }
    if (action === "journal") return this._downloadJournal();
    if (action === "download") {
      return this._call({type: "solar_inverter_bridge/diagnostics"}, diagnostic => {
        diagnostic.frontend = {version: "0.24.0", view: this._tab};
        const url = URL.createObjectURL(new Blob([JSON.stringify(diagnostic, null, 2)], {type: "application/json"}));
        const link = document.createElement("a"); link.href = url; link.download = "solar-inverter-bridge-diagnostics.json"; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      });
    }
    this._render();
  }
}

if (!customElements.get("solar-inverter-bridge-panel")) {
  customElements.define("solar-inverter-bridge-panel", SolarInverterBridgePanel);
}
