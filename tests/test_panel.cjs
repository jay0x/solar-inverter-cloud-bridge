// Real Chromium journeys against synthetic HA data. No live HA access or writes.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const {execFileSync} = require("node:child_process");
const {chromium} = require("playwright");

const root = path.resolve(__dirname, "..");
const frontend = path.join(root, "custom_components/solar_inverter_bridge/frontend");
const parameters = JSON.parse(execFileSync("python3", ["-c", "import json; from custom_components.solar_inverter_bridge.core.parameters import inventory; print(json.dumps(inventory()))"], {cwd: root, encoding: "utf8"}));
const profileParameters = JSON.parse(execFileSync("python3", ["-c", "import json; from custom_components.solar_inverter_bridge.core.drivers import fields_for; from custom_components.solar_inverter_bridge.core.parameters import inventory; print(json.dumps({key:inventory(fields_for(key)) for key in ('modbus_protocol_4','smg_4','must_pv3300')}))"], {cwd: root, encoding: "utf8"}));
const profileLayers = JSON.parse(execFileSync("python3", ["-c", "import json; from custom_components.solar_inverter_bridge.core.profile_layers import describe_profile as d; print(json.dumps({'reference':d('modbus_protocol_4',identity={'protocol_number':4,'model_code':32771},evidence='observed'),'unknown':d('smg_4',binding={'signature':[4,45678]},basis='family_shape_and_two_snapshots',evidence='proposal'),'pi30':d('pi30',basis='family_shape_and_two_snapshots',evidence='proposal'),'must':d('must_pv3300',binding={'signature':[[20000,20566],[20001,3300]]},basis='source_identity_anchors_and_two_snapshots',evidence='proposal')}))"], {cwd: root, encoding: "utf8"}));
const fixture = {
  listening: true, recorder_available: true, rejected: 0, last_error: null, allowed_sources: ["192.168.10.0/24"], pending: [], parameters,
  devices: [{device_id: "test-device", ha_device_id: "native-ha-device", name: "House inverter", profile_id: "modbus_protocol_4", control_mode: "full", clock_sync: false,
    profile_layers: profileLayers.reference,
    enabled: true, poll_interval: 10, connected: true, stale: false, age_seconds: 3, unresolved: 0,
    ha_sensors: [{entity_id:'sensor.renamed_roof_pv',name:'House inverter PV power',state:'2460',unit:'W',has_state:true,disabled:false},
      {entity_id:'sensor.grid_voltage',name:'Grid voltage',state:'unavailable',unit:'V',has_state:true,disabled:false},
      {entity_id:'sensor.disabled_measurement',name:'Disabled measurement',state:'unavailable',has_state:false,disabled:true}],
    settings: {primary_output_priority: "sbu", output_voltage_setting: "230", secondary_charging_start: "07:00:00", battery_protection_soc_ac: 20,
      battery_recovery_soc_ac: 80, inverter_datetime: "2026-11-02T15:00:00",
      maximum_charging_current: 50, maximum_ac_charging_current: 20.4, equalization_voltage: 57.6,
      battery_protection_voltage_ac: 46.8, op1_protection_voltage_offgrid: 44.4,
      battery_protection_voltage_offgrid: 42.1, battery_recovery_voltage_ac: "full_recovery"},
    telemetry: {pv_power: {value: 2460, unit: "W"}, battery_soc: {value: 78, unit: "%"}, output_power: {value: 1120, unit: "W"},
      operating_mode: {value: "mains", unit: null}, grid_voltage: {value: 231.4, unit: "V"}, battery_voltage: {value: 52.4, unit: "V"},
      pv_energy_today: {value: 8.3, unit: "kWh"}, output_frequency: {value: 50, unit: "Hz"}}}],
};
const html = `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Inverter UI simulation</title></head><body style="margin:0">
<div id="ha-shell"></div><script src="/panel.js"></script><script>
window.state = ${JSON.stringify(fixture)}; window.calls = []; window.operations = {}; window.loseReply = false;
window.deviceTemplate = structuredClone(state.devices[0]); window.holdVerification = false;
window.profileLayerFixtures = ${JSON.stringify(profileLayers)};
const shell = document.querySelector('#ha-shell').attachShadow({mode:'open'});
shell.innerHTML = '<div id="ha-main"></div>';
const main = shell.querySelector('#ha-main').attachShadow({mode:'open'});
main.innerHTML = '<solar-inverter-bridge-panel></solar-inverter-bridge-panel>';
const element = window.testPanel = main.querySelector('solar-inverter-bridge-panel');
element.hass = {user: {id: 'test-admin'}, callWS: async function(request) {
  calls.push(structuredClone(request));
  if (request.type.endsWith('/status')) return structuredClone(state);
  if (request.type.endsWith('/network_hints')) return {ha_ip:'192.168.10.77',subnet:'192.168.10.0/24',router_ip:'192.168.10.1',dns_ip:'192.168.10.1',addresses:[{address:'192.168.10.77',network:'192.168.10.0/24',default:true}]};
  if (request.type.endsWith('/configure_network')) { state.allowed_sources=request.allowed_sources; if (request.bootstrap_preference) state.bootstrap_preference=request.bootstrap_preference; return {}; }
  if (request.type.endsWith('/compatibility')) {
    if (request.action==='start') state.compatibility={active:true,report_id:'report-test',events:1,wire_bytes:0,remaining_seconds:120};
    if (request.action==='stop') state.compatibility.active=false;
    const result={...state.compatibility,analysis:{coverage:{network:'missing',full_identity:'missing',writes:'not_qualified_by_diagnostics'},findings:[{code:'no_incoming_connection',next_action:'Check DNS and reconnect.'}],issue_summary:'Report report-test: check DNS'}};
    if (request.action==='download') Object.assign(result,{filename:'compatibility-report-test.zip',base64:btoa('ZIP simulation')});
    return result;
  }
  if (request.type.endsWith('/profile')) {
    if (request.action==='select') {
      const item=state.pending.find(x=>x.identity_sha256===request.collector_sha256);
      Object.assign(item,{ready:true,snapshots:2,profile_id:'pi30',profile_name:'PI30 common telemetry',experimental:true,profile_layers:profileLayerFixtures.pi30});
      return structuredClone(item);
    }
    return {started:true};
  }
  if (request.type.endsWith('/verify')) { if (holdVerification) await new Promise(resolve => {window.finishVerification=resolve;}); const item=state.pending.find(x=>x.identity_sha256===request.collector_sha256); item.ready=true; item.snapshots=2; item.model_code=32771; return structuredClone(item); }
  if (request.type.endsWith('/enroll')) { state.devices.push({...structuredClone(state.devices[0] || deviceTemplate),device_id:'second-device',name:request.name,control_mode:'full',operations:[]}); state.pending=[]; return {device_id:'second-device'}; }
  if (request.type.endsWith('/remove_device')) {state.devices=state.devices.filter(item=>item.device_id!==request.device_id); return {removed:true,device_id:request.device_id};}
  if (request.type.endsWith('/set_clock_sync')) { state.devices[0].clock_sync=request.enabled; return {}; }
  if (request.type.endsWith('/set_auto_reset')) { state.devices[0].auto_reset=request.enabled; return {}; }
  if (request.type.endsWith('/set_collection')) { Object.assign(state.devices[0],{enabled:request.enabled,poll_interval:request.poll_interval}); return {}; }
  if (request.type.endsWith('/diagnostics')) return {schema:2,parameter_inventory:state.parameters,devices:[{parameters:{values:state.devices[0].settings},telemetry:{values:state.devices[0].telemetry}}],recent_issues:[state.devices[0].last_issue].filter(Boolean)};
  if (request.type.endsWith('/apply')) {
    if ('expected_value' in request && state.devices[0].settings[request.key] !== request.expected_value) throw {code:'request_rejected',message:'baseline_conflict'};
    if (!operations[request.operation_id]) operations[request.operation_id]={operation_id:request.operation_id,device_id:request.device_id,state:'completed',outcome:'confirmed',unresolved:false};
    if (loseReply) { loseReply=false; throw {code:'unknown_result',message:'Connection interrupted'}; }
    return operations[request.operation_id];
  }
  if (request.type.endsWith('/get_operation') || request.type.endsWith('/check_operation')) return operations[request.operation_id] || {operation_id:request.operation_id,state:'completed',outcome:'confirmed',unresolved:false};
  if (request.type.endsWith('/accept_current_value')) { const record=state.devices[0].operations.find(item=>item.operation_id===request.operation_id); Object.assign(record,{state:'completed',resolution:'accepted_current_value',unresolved:false}); state.devices[0].unresolved=0; return structuredClone(record); }
  throw new Error('Unexpected command: '+request.type);
}};
</script></body></html>`;

(async () => {
  const server = http.createServer((req, res) => {
    if (req.url.includes("collector-domains.json")) {res.setHeader("Content-Type", "application/json"); res.end(fs.readFileSync(path.join(frontend,"collector-domains.json"))); return;}
    if (req.url.includes("/icon")) {res.setHeader("Content-Type", "image/png"); res.end(fs.readFileSync(path.join(frontend,"../brand",req.url.includes("@2x")?"icon@2x.png":"icon.png")));}
    else if (req.url.includes("routers.html")) {res.setHeader("Content-Type", "text/html"); res.end(fs.readFileSync(path.join(frontend, "routers.html")));}
    else if (req.url.includes("router-guide.js")) {res.setHeader("Content-Type", "text/javascript"); res.end(fs.readFileSync(path.join(frontend, "router-guide.js")));}
    else if (req.url.includes("panel.js")) {res.setHeader("Content-Type", "text/javascript"); res.end(fs.readFileSync(path.join(frontend, "panel.js")));}
    else if (req.url.includes("panel.css")) {res.setHeader("Content-Type", "text/css"); res.end(fs.readFileSync(path.join(frontend, "panel.css")));}
    else {res.setHeader("Content-Type", "text/html"); res.end(html);}
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({headless: true});
  const context = await browser.newContext();
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  const out = process.env.SIB_SCREENSHOTS || "/tmp/opencode/sib-ui";
  fs.mkdirSync(out, {recursive: true});
  const panel = () => page.locator("solar-inverter-bridge-panel");
  const refresh = () => page.evaluate(() => window.testPanel._load());
  const overflow = async () => assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "page overflows horizontally");
  const edit = async key => {
    if (!await page.locator('#edit-'+key).count()) await page.locator(`[data-action="edit"][data-value="${key}"]`).click();
    return page.locator('#edit-'+key);
  };
  try {
    await page.goto(url);
    await page.getByRole("button", {name: "Configuration", exact: true}).click();
    assert((await page.url()).endsWith('/settings'));
    assert.equal(await page.locator('[data-action="apply"]:visible').count(),0);
    assert.equal(await page.locator('.value-button svg').count(),0);
    const valueStart = await page.locator('[data-parameter="primary_output_priority"] .value-button strong').evaluate(element=>element.getBoundingClientRect().x);
    assert.equal(await page.locator('#control-mode, #experimental-control').count(),0);
    await page.evaluate(() => {
      state.profile_catalogue=[{profile_id:'smg_4',name:'SMG 4',measurements:13,controls:24,evidence:'Source-derived',profile_layers:profileLayerFixtures.unknown}];
    });
    await refresh();
    const catalogue=page.locator('[data-disclosure="profile-catalogue"]');
    const map=page.locator('[data-disclosure="profile-map-smg_4"]');
    await catalogue.locator('summary').first().click();
    await map.locator('summary').click();
    for(let index=0;index<3;index++) await refresh();
    assert(await catalogue.evaluate(node=>node.open));
    assert(await map.evaluate(node=>node.open));
    await map.locator('summary').click();
    await refresh();
    assert(await catalogue.evaluate(node=>node.open));
    assert.equal(await map.evaluate(node=>node.open),false);
    await catalogue.locator('summary').first().click();
    await refresh();
    assert.equal(await catalogue.evaluate(node=>node.open),false);
    await page.evaluate(()=>{state.profile_catalogue=[];});
    await refresh();
    console.log('PASS profile catalog and nested composition retain expanded/collapsed state across polling');
    await edit('primary_output_priority');
    const editorStart = await page.locator('#edit-primary_output_priority').evaluate(element=>element.getBoundingClientRect().x+parseFloat(getComputedStyle(element).paddingLeft)+parseFloat(getComputedStyle(element).borderLeftWidth));
    assert(Math.abs(valueStart-editorStart)<1,'editing shifts the value column');
    assert(await page.locator('[data-action="apply"][data-value="primary_output_priority"]').isHidden());
    await page.locator('#edit-primary_output_priority').selectOption('sub');
    assert(await page.locator('[data-action="apply"][data-value="primary_output_priority"]').isVisible());
    await page.locator('#edit-primary_output_priority').selectOption('sbu');
    assert(await page.locator('[data-action="apply"][data-value="primary_output_priority"]').isHidden());
    await page.evaluate(() => {window.focusedSelect = testPanel.querySelector('#edit-primary_output_priority');});
    await refresh();
    assert(await page.evaluate(() => focusedSelect === testPanel.querySelector('#edit-primary_output_priority')));
    console.log('PASS nested Shadow DOM: active parameter dropdown survives refresh; no control-mode selector');
    await (await edit('battery_protection_soc_ac')).fill("25");
    await refresh();
    assert.equal(await page.locator("#edit-battery_protection_soc_ac").inputValue(), "25");
    await (await edit('output_voltage_setting')).selectOption("240");
    await page.reload();
    await page.locator("#edit-output_voltage_setting").waitFor();
    assert.equal(await page.locator("#edit-output_voltage_setting").inputValue(), "240");
    assert.equal(await page.locator("#edit-battery_protection_soc_ac").inputValue(), "25");
    await page.locator('[data-action="apply"][data-value="output_voltage_setting"]').click();
    await page.getByRole("heading", {name: "Output voltage setting changed from 230 to 240"}).waitFor();
    const voltage = await page.evaluate(() => calls.find(call => call.type.endsWith("/apply")));
    assert.equal(voltage.value, "240");
    assert(voltage.operation_id);
    console.log("PASS drafts survive polling/reload; numeric enum remains a string");

    await page.evaluate(() => { window.loseReply = true; });
    await page.locator('[data-action="apply"][data-value="battery_protection_soc_ac"]').click();
    await page.getByRole("heading", {name: "Battery protection SOC in AC mode is waiting for confirmation"}).waitFor();
    const pendingId = await page.evaluate(() => window.testPanel._pending['test-device'].operation_id);
    await page.reload();
    await page.getByRole("heading", {name: "Battery protection SOC in AC mode is waiting for confirmation"}).waitFor();
    assert.equal(await page.evaluate(() => calls.filter(call => call.type.endsWith("/apply")).length), 0);
    await page.getByRole("button", {name: "Check result", exact: true}).click();
    await page.getByRole("heading", {name: "Battery protection SOC in AC mode changed from 20 to 25"}).waitFor();
    assert.equal(await page.evaluate(() => calls.find(call => call.type.endsWith("/check_operation")).operation_id), pendingId);
    console.log("PASS lost reply survives reload without replay; read-only result lookup");

    await (await edit('battery_protection_soc_ac')).fill('26');
    await page.evaluate(() => {state.devices[0].settings.battery_protection_soc_ac=21;});
    await refresh();
    await page.locator('[data-action="apply"][data-value="battery_protection_soc_ac"]').click();
    await page.getByRole('alert').filter({hasText:'changed while you were editing'}).waitFor();
    assert.equal(await page.locator('#edit-battery_protection_soc_ac').inputValue(),'26');
    await page.locator('[data-action="discard"][data-value="battery_protection_soc_ac"]').click();
    assert.equal(await page.locator('#edit-battery_protection_soc_ac').count(),0);
    assert.match(await page.locator('[data-action="edit"][data-value="battery_protection_soc_ac"]').innerText(),/21/);
    await page.evaluate(()=>{state.devices[0].control_mode='monitoring';});
    await refresh();
    assert.equal(await page.locator('.parameter-row').count(),51);
    assert.equal(await page.locator('[data-action="apply"]:visible').count(),0);
    assert.equal(await page.locator('[data-action="edit"][data-value="maximum_charging_current"]').count(),1);
    console.log('PASS baseline conflict keeps draft; legacy mode data cannot hide or disable writable fields');

    const advancedKeys=['maximum_charging_current','maximum_ac_charging_current','equalization_voltage',
      'battery_protection_voltage_ac','op1_protection_voltage_offgrid','battery_protection_voltage_offgrid'];
    for (const key of advancedKeys) {
      assert.equal(await page.locator(`[data-parameter="${key}"] .limits-warning`).count(),1);
      assert.equal(await page.locator(`[data-action="edit"][data-value="${key}"]`).count(),1);
    }
    assert.equal(await page.locator('.parameter-indicator .value-status:not(.limits-warning)').count(),2);
    const currentInput=await edit('maximum_charging_current');
    assert.equal(await currentInput.getAttribute('step'),'0.1');
    await currentInput.fill('72.55');
    assert(await page.locator('[data-action="apply"][data-value="maximum_charging_current"]').isHidden());
    await currentInput.fill('72.5');
    assert(await page.locator('[data-parameter="maximum_charging_current"] .limits-note').isVisible());
    await page.locator('[data-action="apply"][data-value="maximum_charging_current"]').click();
    await page.getByRole('heading',{name:'Maximum charging current changed from 50 to 72.5',exact:true}).waitFor();
    const decimal=await page.evaluate(()=>calls.find(call=>call.type.endsWith('/apply')&&call.key==='maximum_charging_current'));
    assert.equal(decimal.value,72.5);
    assert.equal(decimal.expected_value,50);
    const recovery=await edit('battery_recovery_voltage_ac');
    assert.equal(await recovery.inputValue(),'0');
    assert(await page.locator('[data-action="apply"][data-value="battery_recovery_voltage_ac"]').isHidden());
    await recovery.fill('52.3');
    assert(await page.locator('[data-action="apply"][data-value="battery_recovery_voltage_ac"]').isVisible());
    await page.locator('[data-action="discard"][data-value="battery_recovery_voltage_ac"]').click();
    await page.evaluate(()=>{state.devices[0].control_mode='full';});
    await refresh();
    for (const key of advancedKeys) {
      assert.equal(await page.locator(`[data-parameter="${key}"] .limits-warning`).count(),1);
      assert.equal(await page.locator(`[data-parameter="${key}"] .value-mode`).count(),0);
      assert.equal(await page.locator(`[data-action="edit"][data-value="${key}"]`).count(),1);
    }
    assert.equal(await page.evaluate(()=>calls.filter(call=>call.type.endsWith('/set_mode')).length),0);
    console.log('PASS decimal writes available by default with warnings; only hardware read-only fields have locks');

    const writesBefore = await page.evaluate(() => calls.filter(call=>call.type.endsWith('/apply')).length);
    await page.evaluate(() => {state.devices[0].unresolved=1; state.devices[0].operations=[{operation_id:'unresolved-server-request',setting_key:'primary_output_priority',state:'reconciling',outcome:'uncertain',unresolved:true,last_observed_value:'sub',last_observed_at:'2026-11-02T15:00:00+00:00'}];});
    await refresh();
    await page.getByRole('button',{name:'Keep current value',exact:true}).click();
    await page.getByRole('heading',{name:'Primary output priority was left at SUB',exact:true}).waitFor();
    assert.equal(await page.evaluate(() => calls.filter(call=>call.type.endsWith('/apply')).length),writesBefore);
    console.log('PASS explicit keep-current resolution without an apply request');

    await page.evaluate(() => {state.time_zone='Europe/Moscow'; state.devices[0].last_issue={code:'TimeoutError',occurred_at:'2026-11-02T12:34:56+00:00',stage:'settings_read',register_address:630,register_count:26}; testPanel._navigate('sib/device/test-device/activity');});
    await refresh();
    assert.match(await panel().innerText(), /Nov 2, 2026/);
    assert.match(await panel().innerText(), /3:34:56/);
    const downloaded = page.waitForEvent('download');
    await page.getByRole('button',{name:'Download diagnostics'}).click();
    const download = await downloaded;
    const diagnostic = JSON.parse(fs.readFileSync(await download.path(),'utf8'));
    assert.equal(diagnostic.schema,2);
    assert.equal(diagnostic.parameter_inventory.length,51);
    assert.equal(diagnostic.recent_issues[0].register_address,630);
    assert.equal(diagnostic.frontend.version,'0.16.1');
    console.log('PASS timestamped issue in HA time zone and backend diagnostics download');

    await page.evaluate(() => window.testPanel._navigate("sib/device/test-device/settings"));
    assert.equal(await page.locator("#auto-reset").isChecked(), false);
    await page.locator("#auto-reset").check();
    await refresh();
    assert.equal(await page.locator("#auto-reset").isChecked(), true);
    await page.getByRole("button", {name: "Save recovery setting"}).click();
    await page.waitForFunction(() => state.devices[0].auto_reset === true);
    await page.locator("#auto-reset").uncheck();
    await page.getByRole("button", {name: "Save recovery setting"}).click();
    await page.waitForFunction(() => state.devices[0].auto_reset === false);
    assert.equal(await page.evaluate(() => calls.some(call => call.type.endsWith("/reset_collector"))), false);
    const routerGuide = await page.request.get(url + "/solar_inverter_bridge/routers.html");
    assert.equal(routerGuide.status(), 200);
    const guideText = await routerGuide.text();
    for (const topic of ["Generate commands", "DNS only", "Select all", "UDP and TCP", "OpenWrt", "pfSense", "OPNsense", "nftables"]) assert(guideText.includes(topic));
    console.log("PASS recovery preference preserves drafts without reset; bundled DNS/router instructions");

    assert.equal(await page.locator("solar-inverter-bridge-panel button.back-link").evaluate(button => button.classList.contains("text-button")), false);
    await page.evaluate(() => window.testPanel._navigate("sib/device/test-device/settings"));
    await page.evaluate(() => {
      const link = document.createElement("a");
      link.href = "/solar-inverter-bridge";
      link.setAttribute("data-panel", "solar-inverter-bridge");
      link.textContent = "Inverters";
      document.body.appendChild(link);
      link.click();
      link.remove();
    });
    assert.equal(await page.evaluate(() => location.hash), "#sib");
    assert.equal(await page.locator("solar-inverter-bridge-panel h1").innerText(), "Inverters");
    console.log("PASS sidebar Inverters returns to the inverter list");
    await page.evaluate(() => {
      window.beforeFirstSetup=structuredClone(state);
      state.devices=[];state.pending=[];state.profile_searches=[];
      testPanel._drafts={};testPanel._disclosures={};testPanel._reportOpen=false;
      testPanel._navigate('sib');
    });
    await refresh();
    assert.equal(await page.locator('[data-action="add"]:visible').count(),1);
    assert.equal(await page.getByRole('heading',{name:'Find a compatible profile'}).count(),0);
    await page.getByRole('button',{name:'Connect your first inverter'}).click();
    assert.equal(await page.getByRole('button',{name:'Connect your first inverter'}).count(),0);
    assert(await page.getByRole('heading',{name:'Name your inverter'}).isVisible());
    assert(await page.locator('#network-source').isHidden());
    await page.locator('#setup-name').fill('First inverter');
    const networkSaves=await page.evaluate(()=>calls.filter(c=>c.type.endsWith('/configure_network')).length);
    await page.getByRole('button',{name:'Continue to connection'}).click();
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.type.endsWith('/configure_network')).length),networkSaves);
    assert(await page.getByText('Waiting for a collector…',{exact:true}).isVisible());
    assert(await page.getByRole('link',{name:'Open router setup'}).isVisible());
    assert(await page.locator('.connection-domains').isHidden());
    await page.locator('[data-disclosure="setup-dns-details"] > summary').click();
    await refresh();
    assert(await page.locator('.connection-domains').isVisible());
    await page.evaluate(() => {
      state.pending=[{identity_sha256:'first-collector',identity_ref:'sha256:first',source:'192.168.10.58',transport:'at',listener_port:18899,ready:false,snapshots:0}];
    });
    await refresh();
    assert(await page.getByRole('button',{name:'Use this connection'}).isVisible());
    assert(await page.locator('[data-action="choose-collector"]').evaluate(button=>button.classList.contains('primary')));
    assert(await page.locator('.connection-domains').isVisible(),'expanded help closed when a connection arrived');
    await page.locator('[data-disclosure="setup-another"] > summary').click();
    const geometry=async()=>{
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      await overflow();
      const boxes=await page.locator('.setup-flow > *').evaluateAll(elements=>elements.map(element=>{const r=element.getBoundingClientRect();return {class:element.className,x:r.x,width:r.width,top:r.top,bottom:r.bottom};}));
      for(const box of boxes) {assert(Math.abs(box.x-boxes[0].x)<1,'wizard columns have different left edges');assert(Math.abs(box.width-boxes[0].width)<1,'wizard columns have different widths');}
      for(let i=1;i<boxes.length;i++) assert(Math.abs(boxes[i].top-boxes[i-1].bottom-24)<1,`wizard blocks do not have a 24px gap: ${JSON.stringify(boxes)}`);
    };
    for(const dark of [false,true]) {
      await page.evaluate(dark=>{document.documentElement.style.cssText=dark?'--primary-background-color:#111a21;--card-background-color:#1b2730;--primary-text-color:#e8eef2;--secondary-text-color:#a9b8c4;--divider-color:#33424d;--primary-color:#52b8aa;--text-primary-color:#102520;':'--primary-color:#147d78;';},dark);
      for(const width of [360,390,768,1440]) {
        await page.setViewportSize({width,height:1000});
        await geometry();
        const button=await page.locator('[data-action="choose-collector"]').boundingBox();
        assert(button.y+button.height<1000,'found connection action is below the first screen');
        await page.screenshot({path:path.join(out,`first-connection-${width}-${dark?'dark':'light'}.png`),fullPage:true});
      }
    }
    await page.evaluate(()=>{holdVerification=true;state.pending.push({...state.pending[0],identity_sha256:'other-collector',identity_ref:'sha256:other',source:'192.168.10.59'});});
    await refresh();
    assert.equal(await page.locator('[data-action="choose-collector"]:visible').count(),2);
    const verificationCalls=await page.evaluate(()=>calls.filter(c=>c.type.endsWith('/verify')).length);
    await page.getByRole('button',{name:'Use this connection'}).first().click();
    assert(await page.getByRole('heading',{name:'Checking your inverter…'}).isVisible());
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.type.endsWith('/verify')).length),verificationCalls+1);
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.type.endsWith('/verify')).at(-1).collector_sha256),'first-collector');
    await geometry();
    await page.evaluate(()=>{holdVerification=false;finishVerification();});
    await page.getByRole('heading',{name:'Ready to add'}).waitFor();
    await geometry();
    assert.equal(await page.evaluate(()=>state.devices.length),0,'verification enrolled without confirmation');
    await page.evaluate(()=>{state.pending[0].ready=false;});
    await refresh();
    assert.equal(await page.locator('[data-action="enroll"]').count(),0);
    assert(await page.getByRole('button',{name:'Check connection again'}).isVisible());
    await page.evaluate(()=>{window.disconnectedCandidate=state.pending.shift();});
    await refresh();
    assert(await page.getByRole('button',{name:'Choose a connection'}).isVisible());
    await page.getByRole('button',{name:'Choose a connection'}).click();
    assert.equal(await page.locator('[data-action="choose-collector"]').count(),1);
    await page.evaluate(()=>{state.pending.unshift(disconnectedCandidate);testPanel._navigate('sib/add/3');});
    await refresh();
    await page.getByRole('button',{name:'Check connection again'}).click();
    await page.getByRole('heading',{name:'Ready to add'}).waitFor();
    await page.getByRole('button',{name:'Add inverter',exact:true}).click();
    await page.getByRole('heading',{name:'First inverter',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>state.devices[0].control_mode),'full');
    await page.evaluate(()=>{state=structuredClone(beforeFirstSetup);testPanel._drafts={};testPanel._disclosures={};testPanel._navigate('sib');});
    await refresh();
    console.log('PASS first inverter: single entry point, existing network, prioritized connection, automatic read-only check, explicit enrollment, aligned widths and 24px gaps');
    await page.evaluate(() => window.testPanel._navigate("sib/device/test-device/overview"));
    await page.getByRole("button", {name: "All inverters"}).click();
    await page.getByRole("button", {name: "Add inverter", exact: true}).click();
    await page.locator("#setup-name").fill("Garage inverter");
    await page.getByRole("button", {name: "Continue", exact: false}).click();
    await page.evaluate(() => { state.pending=[{identity_sha256:'a'.repeat(64),identity_ref:'sha256:test',source:'192.168.10.1',ready:false,snapshots:0}]; });
    await refresh();
    await page.getByRole("button", {name: "Use this connection"}).click();
    await page.getByRole("heading", {name: "Ready to add"}).waitFor();
    await page.getByRole("button", {name: "Add inverter", exact: false}).click();
    await page.getByRole("heading", {name: "Garage inverter", exact: true}).waitFor();
    assert.equal(await page.evaluate(() => state.devices.length), 2);
    await page.goBack();
    assert((await page.url()).includes("#sib/add/3"));
    console.log("PASS four-step add flow and browser navigation");

    for (const dark of [false, true]) {
      await page.evaluate(dark => {
        document.documentElement.style.cssText = dark ? '--primary-background-color:#111a21;--card-background-color:#1b2730;--primary-text-color:#e8eef2;--secondary-text-color:#a9b8c4;--divider-color:#33424d;--primary-color:#52b8aa;--text-primary-color:#102520;--success-color:#6ac49a;' : '--primary-color:#147d78;';
      }, dark);
      for (const width of [360, 390, 768, 1440]) {
        await page.setViewportSize({width, height: 1000});
        for (const route of ["sib", "sib/device/test-device/overview", "sib/device/test-device/sensors", "sib/device/test-device/settings", "sib/device/test-device/connection", "sib/device/test-device/activity", "sib/add/0", "sib/add/1"]) {
          await page.evaluate(route => window.testPanel._navigate(route), route);
          await overflow();
          if (route.startsWith('sib/device/')) {
            const link = page.getByRole('link', {name:'Home Assistant entities'});
            assert.equal(await link.getAttribute('href'), '/config/devices/device/native-ha-device');
            assert(await link.isVisible());
          }
          if (route === 'sib/add/1') {
            const guide = page.getByRole('link',{name:'Open router setup'});
            await page.waitForFunction(() => {
              const link = window.testPanel.querySelector('.router-setup-link');
              return link && parseFloat(getComputedStyle(link).fontSize) >= 18;
            });
            const linkStyle = await guide.evaluate(link => ({fontSize:getComputedStyle(link).fontSize, className:link.className}));
            assert(parseFloat(linkStyle.fontSize) >= 18, `router guide style at ${width}: ${JSON.stringify(linkStyle)}`);
            const domains = page.locator('.connection-domains');
            const dnsDetails = page.locator('[data-disclosure="setup-dns-details"]');
            if (!await dnsDetails.evaluate(element => element.open)) await dnsDetails.locator('summary').click();
            assert.equal(await domains.locator('li').count(),12);
            for (const name of ['*.eybond.com','ess.eybond.com','m2m.eybond.com','iot.eybond.com','vip1.eybond.com','www.shinemonitor.com']) assert((await domains.innerText()).includes(name));
            assert(await domains.evaluate(element => element.getBoundingClientRect().bottom <= [...element.parentNode.querySelectorAll('p')].find(p => p.textContent.startsWith('The inverter must use')).getBoundingClientRect().top));
          }
          const spacing = await page.locator("solar-inverter-bridge-panel").evaluate(panel => {
            const selector = "main .surface, main .live-panel, main .operation, main .banner, main .info-box, main .empty-state, main .parameter-group, main .access-panel, main .clock-panel, main .device-card, main .settings-toolbar";
            const blocks = [...panel.querySelectorAll(selector)];
            const gaps = [];
            for (let index = 1; index < blocks.length; index += 1) {
              if (blocks[index - 1].nextElementSibling !== blocks[index]) continue;
              const above = blocks[index - 1].getBoundingClientRect();
              const below = blocks[index].getBoundingClientRect();
              const sideBySide = below.top < above.bottom - 1 && Math.abs(above.left - below.left) > 8;
              const gap = Math.round(below.top - above.bottom);
              if (!sideBySide && below.top + 1 >= above.bottom && ![0, 16, 24, 28].includes(gap)) {
                gaps.push(`${blocks[index - 1].className} -> ${blocks[index].className}: ${gap}`);
              }
            }
            const reading = [...panel.querySelectorAll(".detail-row")].find(row => row.textContent.includes("Last complete reading"));
            return {
              gaps,
              reconnect: panel.innerText.includes("Reconnects refresh the connection"),
              readingLine: reading ? getComputedStyle(reading).borderBottomWidth : null,
            };
          });
          assert.deepEqual(spacing.gaps, [], `uneven spacing on ${route} at ${width}`);
          assert.equal(spacing.reconnect, false);
          if (route.endsWith("/connection")) assert.equal(spacing.readingLine, "0px");
          if (route.endsWith('/settings')) {
            const positions=await page.locator('.parameter-control > .value-button strong, .parameter-control > .value-static strong').evaluateAll(elements=>elements.map(element=>element.getBoundingClientRect().x));
            assert(Math.max(...positions)-Math.min(...positions)<1,'parameter values are not aligned');
            assert.equal(await page.locator('.parameter-indicator').count(),51);
          }
        }
        if (width === 390 || width === 1440) {
          for (const [name, route] of [["home", "sib"], ["settings", "sib/device/test-device/settings"], ["setup", "sib/add/0"]]) {
            await page.evaluate(route => window.testPanel._navigate(route), route);
            await page.screenshot({path: path.join(out, `${name}-${width}-${dark ? 'dark' : 'light'}.png`), fullPage: true});
          }
        }
      }
    }
    console.log("PASS 64 responsive screen checks (360/390/768/1440, light/dark)");
    await page.evaluate(() => {
      window.sensorHistoryEvents = [];
      window.addEventListener('hass-more-info', event => sensorHistoryEvents.push(event.detail));
      testPanel._navigate('sib/device/test-device/sensors');
    });
    assert.deepEqual(await page.locator('.tabs button').allTextContents(), ['Overview','Sensors','Configuration','Connection','Activity']);
    assert((await page.locator('.sensor-list').innerText()).includes('2460 W'));
    assert.deepEqual(await page.locator('.sensor-row strong').allTextContents(), ['PV power','Grid voltage','Disabled measurement']);
    await page.getByRole('button',{name:'History: PV power',exact:true}).click();
    assert.deepEqual(await page.evaluate(() => sensorHistoryEvents), [{entityId:'sensor.renamed_roof_pv'}]);
    await page.getByRole('button',{name:'History: Grid voltage',exact:true}).click();
    assert.equal(await page.evaluate(() => sensorHistoryEvents[1].entityId), 'sensor.grid_voltage');
    assert(await page.getByRole('button',{name:'History: Disabled measurement',exact:true}).isDisabled());
    await page.evaluate(() => {state.recorder_available=false;});
    await refresh();
    assert(await page.getByRole('button',{name:'Details: PV power',exact:true}).isVisible());
    assert((await panel().innerText()).includes('Enable Recorder'));
    await page.evaluate(() => {state.recorder_available=true;});
    console.log('PASS Sensors: actual entity IDs, native history event across Shadow DOM, unavailable history and Recorder fallback');

    await page.evaluate(() => {
      state.devices[0].control_mode = 'full';
      Object.assign(state.devices[0].settings, {primary_output_priority:'sub', battery_protection_soc_ac:20, secondary_charging_start:'07:00:00'});
      testPanel._drafts = {}; testPanel._baselines = {}; testPanel._pending = {}; testPanel._editingField = null;
      testPanel._navigate('sib/device/test-device/settings');
    });
    await refresh();
    for (const width of [360,390,768,1440]) {
      await page.setViewportSize({width,height:1000});
      for (const [key, before, after] of [['primary_output_priority','sub','sbu'], ['battery_protection_soc_ac','20','21'], ['secondary_charging_start','07:00','08:00']]) {
        const editor = await edit(key);
        const row = page.locator(`[data-parameter="${key}"]`);
        const geometry = () => row.evaluate(element => {
          const origin = element.getBoundingClientRect();
          const boxes = [element, element.querySelector('.editor-controls'), element.querySelector('input, select'), element.querySelector('[data-action="apply"]'), element.querySelector('[data-action="discard"]'), element.querySelector('.draft-note')];
          return boxes.map(box => {const r=box.getBoundingClientRect();return [r.x-origin.x,r.y-origin.y,r.width,r.height];});
        });
        const initial = await geometry();
        const apply = row.locator('[data-action="apply"]');
        assert(await apply.isHidden());
        const setValue = value => key === 'primary_output_priority' ? editor.selectOption(value) : editor.fill(value);
        await setValue(after);
        assert(await apply.isVisible());
        for (const values of [await geometry(), (await refresh(), await geometry())]) {
          for (let box=0;box<initial.length;box++) for (let axis=0;axis<4;axis++) assert(Math.abs(initial[box][axis]-values[box][axis])<1, `editor jumps: ${key}, ${width}px, box ${box}, axis ${axis}`);
        }
        await setValue(before);
        assert(await apply.isHidden());
        const restored = await geometry();
        for (let box=0;box<initial.length;box++) for (let axis=0;axis<4;axis++) assert(Math.abs(initial[box][axis]-restored[box][axis])<1, `editor jumps after reverting ${key} at ${width}`);
        await row.locator('[data-action="discard"]').click();
      }
    }
    console.log('PASS stable editor geometry: select/number/time, Apply/Cancel/draft note, polling and revert at four widths');

    await page.evaluate(() => testPanel._navigate('sib/device/second-device/connection'));
    await page.getByRole('button',{name:'Remove inverter',exact:true}).click();
    const dialog = page.getByRole('dialog');
    const remove = dialog.getByRole('button',{name:'Remove inverter',exact:true});
    assert(await remove.isDisabled());
    await dialog.locator('#remove-confirmation').fill('Garage');
    await refresh();
    assert.equal(await dialog.locator('#remove-confirmation').inputValue(),'Garage');
    assert(await remove.isDisabled());
    await dialog.locator('#remove-confirmation').fill('Garage inverter');
    await remove.click();
    await page.getByRole('heading',{name:'Inverters',exact:true}).waitFor();
    assert.equal(await page.evaluate(() => state.devices.length),1);
    console.log('PASS removal requires name confirmation and preserves the other inverter');
    await page.evaluate(() => {
      state.pending=[{identity_sha256:'unknown-collector',identity_ref:'unknown',transport:'binary'}];
      testPanel._drafts['setup:collector']='unknown-collector';
      state.profile_searches=[{collector_sha256:'unknown-collector',state:'candidates_available',tested:1,total:22,
        candidates:[{fingerprint:'abc123',profile_id:'pi30',name:'PI30 common telemetry',basis:'family_shape_and_two_snapshots',profile_layers:profileLayerFixtures.pi30,warning:'Inferred mapping may damage equipment if controls are wrong.',values:{battery_voltage:{value:48,unit:'V'}}}]}];
      state.profile_searches.push({collector_sha256:'unrelated-collector',state:'searching',tested:0,total:22,candidates:[]});
      testPanel._navigate('sib/add/2');
    });
    await refresh();
    assert.equal(await page.locator('.profile-review').count(),1);
    assert.equal(await page.getByText('Checking available profiles',{exact:true}).count(),0);
    await geometry();
    assert((await page.locator('.profile-layers').innerText()).includes('None — common map only'));
    await page.getByRole('button',{name:'Use common map',exact:true}).click();
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.type.endsWith('/profile') && c.action==='select').length),0);
    await page.locator('#ack-abc123').check();
    assert.equal(await page.locator('#control-abc123').count(),0);
    await page.getByRole('button',{name:'Use common map',exact:true}).click();
    await page.waitForFunction(()=>calls.some(c=>c.type.endsWith('/profile') && c.action==='select'));
    const selection=await page.evaluate(()=>calls.find(c=>c.type.endsWith('/profile') && c.action==='select'));
    assert.equal(selection.acknowledged,true);assert.equal('allow_control' in selection,false);
    assert((await panel().innerText()).includes('PI30 common telemetry'));
    for(const width of [360,390,768,1440]) {await page.setViewportSize({width,height:1000});await overflow();}
    await page.evaluate(()=>{state.pending=[];state.profile_searches=[];testPanel._navigate('sib');});
    console.log('PASS inferred-profile offer: one acknowledgement for readings/controls and non-Protocol-4 finish');

    for (const kind of ['reference','unknown','must']) {
      const id={reference:'modbus_protocol_4',unknown:'smg_4',must:'must_pv3300'}[kind];
      await page.evaluate(({kind,id,fields}) => {
        state.devices[0].profile_layers=structuredClone(profileLayerFixtures[kind]);
        state.devices[0].profile_id=id;
        state.devices[0].parameters=fields;
        testPanel._navigate('sib/device/test-device/settings');
      },{kind,id,fields:profileParameters[id]});
      await refresh();
      const layers=page.locator('.profile-layers');
      const text=await layers.innerText();
      assert(text.includes('Common map') && text.includes('Selection basis'));
      if (kind==='reference') assert(text.includes('None — common map only') && text.includes('Reference read checks for native 4/32771'));
      if (kind==='unknown') assert(text.includes('None — common map only') && text.includes('45678'));
      if (kind==='must') assert(text.includes('Model extension') && text.includes('whole percent') && text.includes('cannot be disabled'));
      assert.equal(await layers.locator('input,select,button').count(),0);
      for(const width of [360,390,768,1440]) {
        await page.setViewportSize({width,height:1000});
        await overflow();
        assert(await layers.isVisible());
      }
      await page.screenshot({path:path.join(out,`profile-${kind}-1440.png`),fullPage:true});
      await page.evaluate(() => {state.devices[0].profile_layers.evidence_state='saved';});
      await refresh();
      assert((await layers.innerText()).includes('waiting for current readings'));
      await page.evaluate(() => testPanel._navigate('sib/device/test-device/connection'));
      assert((await page.locator('.profile-layers').innerText()).includes('Common map'));
    }
    await page.evaluate(fields => {
      state.devices[0].profile_id='modbus_protocol_4';
      state.devices[0].parameters=fields;
      state.devices[0].profile_layers=structuredClone(profileLayerFixtures.reference);
      state.devices[0].profile_layers.qualification='<img src=x onerror="window.injected=true">';
      testPanel._navigate('sib/device/test-device/settings');
    },parameters);
    await refresh();
    assert.equal(await page.locator('.profile-layers img').count(),0);
    assert.equal(await page.evaluate(() => Boolean(window.injected)),false);
    await page.evaluate(() => {state.devices[0].profile_layers=structuredClone(profileLayerFixtures.reference);});
    console.log('PASS profile layers: reference/common-only/mandatory variant, saved evidence, four widths and escaped descriptions');

    await page.evaluate(() => {
      window.beforeDialectTest=structuredClone(state.devices);
      Object.assign(state.devices[0],{profile_id:'pi30',profile_acceptance:{fingerprint:'accepted'},profile_layers:structuredClone(profileLayerFixtures.pi30)});
      state.devices[0].parameters=structuredClone(state.parameters);
      state.devices[0].parameters.find(p=>p.key==='maximum_charging_current').allowed_values=[20,30,60];
      testPanel._navigate('sib/device/test-device/settings');
    });
    await refresh();
    await page.locator('#profile-variant').selectOption('pi30_max');
    await refresh();
    assert.equal(await page.locator('#profile-variant').inputValue(),'pi30_max');
    await page.getByRole('button',{name:'Recheck this profile',exact:true}).click();
    await page.waitForFunction(()=>calls.some(c=>c.action==='recheck' && c.variant_id==='pi30_max'));
    const constrained=await edit('maximum_charging_current');
    await constrained.fill('55');
    assert.equal(await constrained.evaluate(e=>e.checkValidity()),false);
    const beforeInvalid=await page.evaluate(()=>calls.filter(c=>c.type.endsWith('/apply')).length);
    assert(await page.locator('[data-parameter="maximum_charging_current"] [data-action="apply"]').isHidden());
    await page.locator('[data-parameter="maximum_charging_current"] [data-action="apply"]').evaluate(button=>button.click());
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.type.endsWith('/apply')).length),beforeInvalid);
    await constrained.fill('60');
    assert.equal(await constrained.evaluate(e=>e.checkValidity()),true);
    await page.locator('[data-parameter="maximum_charging_current"] [data-action="discard"]').click();
    await page.evaluate(()=>{state.devices=beforeDialectTest;testPanel._drafts={};testPanel._error=null;});
    await refresh();
    console.log('PASS explicit PI30 dialect recheck preserves selection; unsupported numeric choices never reach Apply');

    await page.evaluate(() => {window.originalTestDevices=structuredClone(state.devices);state.devices[0].capabilities={inverter_write:false,module_reset:false};state.devices[0].transport='binary';state.devices[0].capability_reason='Binary monitoring only';testPanel._navigate('sib/device/test-device/settings');});
    await refresh();
    assert.equal(await page.locator('[data-action="edit"]').count(),0);
    assert((await panel().innerText()).includes('Binary monitoring only'));
    await page.evaluate(() => testPanel._navigate('sib/device/test-device/connection'));
    assert(await page.locator('[data-action="reset-module"]').isDisabled());
    await page.evaluate(() => {state.devices=[];testPanel._navigate('sib');});
    await refresh();
    await page.locator('[data-disclosure="home-help"] > summary').click();
    await page.getByRole('button',{name:'Collect compatibility report',exact:true}).click();
    await page.locator('#report-inverter_model').fill('Unknown variant');
    await page.getByRole('button',{name:'Start collection',exact:true}).click();
    await page.waitForFunction(() => calls.some(call=>call.type.endsWith('/compatibility') && call.action==='start'));
    assert.equal(await page.evaluate(() => calls.find(call=>call.type.endsWith('/compatibility') && call.action==='start').metadata.inverter_model),'Unknown variant');
    assert((await panel().innerText()).includes('Check DNS and reconnect.'));
    for (const width of [360,390,768,1440]) {
      await page.setViewportSize({width,height:1000});
      await overflow();
      assert(await page.locator('#report-inverter_model').isVisible());
    }
    assert.equal(await page.locator('#report-raw').isChecked(),false);
    let zip = page.waitForEvent('download');
    await page.getByRole('button',{name:'Download compatibility ZIP',exact:true}).click();
    assert.equal((await zip).suggestedFilename(),'compatibility-report-test.zip');
    assert.equal(await page.evaluate(() => calls.filter(call=>call.type.endsWith('/compatibility') && call.action==='download').at(-1).include_raw),false);
    await page.locator('#report-raw').check();
    zip = page.waitForEvent('download');
    await page.getByRole('button',{name:'Download compatibility ZIP',exact:true}).click();
    await zip;
    assert.equal(await page.evaluate(() => calls.filter(call=>call.type.endsWith('/compatibility') && call.action==='download').at(-1).include_raw),true);
    await page.getByRole('button',{name:'Stop collection',exact:true}).click();
    await page.locator('summary').filter({hasText:'Advanced: silent collector bootstrap'}).click();
    await page.locator('#bootstrap-preference').selectOption('binary');
    await page.getByRole('button',{name:'Save bootstrap preference',exact:true}).click();
    assert.equal(await page.evaluate(() => state.bootstrap_preference),'binary');
    await page.evaluate(() => {testPanel._reportOpen=false;state.devices=structuredClone(window.originalTestDevices);testPanel._navigate('sib');});
    console.log('PASS binary capability locks and zero-device report workflow: metadata, coverage, ZIP, explicit raw opt-in, stop and override');

    await page.evaluate(() => {state.devices[0].connected=false; state.devices[0].stale=true; window.testPanel._navigate('sib');});
    await refresh();
    assert.match(await panel().innerText(), /Offline/);
    assert.match(await page.locator('.device-card').first().innerText(), /—/);
    await page.evaluate(() => {state.devices[0].name='<img src=x onerror="window.injected=true">';});
    await refresh();
    assert.equal(await page.evaluate(() => Boolean(window.injected)), false);
    assert.equal(await panel().locator('img:not(.brand-logo)').count(), 0);
    assert(await panel().locator('.brand-logo').evaluate(image=>image.complete && image.naturalWidth>0));
    const buttons = await page.locator('.sib button:visible').evaluateAll(elements => elements.map(element => element.getBoundingClientRect().height));
    assert(buttons.every(height => height >= 44));
    assert.deepEqual(errors, []);
    console.log("PASS offline state, escaping, 44px controls, no browser exceptions");
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
