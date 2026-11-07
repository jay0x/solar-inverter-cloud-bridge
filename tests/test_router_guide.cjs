// Router recipes are generated and syntax-checked, never run against a router.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const {execFileSync} = require("node:child_process");
const {chromium} = require("playwright");
const frontend = path.resolve(__dirname, "../custom_components/solar_inverter_bridge/frontend");
const {generate, KNOWN_DOMAINS} = require(path.join(frontend, "router-guide.js"));
const base = {router:"mikrotik", ha_ip:"192.168.10.77", router_ip:"192.168.10.1", dns_ip:"192.168.10.1", method:"dns", scope:"network", subnet:"192.168.10.0/24", collector_ip:"", selected:["iot3.eybond.com","dtu_ess.eybond.com","*.eybond.com"], extra_domains:"", lan_interface:"bridge", ha_interface:"bridge", dns_interface:"bridge", intercept_dns:false, hairpin:true};
const commands = result => result.blocks.map(item => item.code).join("\n");
const dnsOnly = commands(generate(base));
assert(dnsOnly.includes("match-subdomain=yes"));
assert(!dnsOnly.includes("add chain="));
assert.equal((dnsOnly.match(/^add name=/gm) || []).length, 1);
assert(!dnsOnly.includes("192.0.2."));
assert(commands(generate({...base, subnet:""})).includes("address=192.168.10.77"));
const single = commands(generate({...base, scope:"single", subnet:"invalid hidden input", collector_ip:"192.168.10.58", method:"redirect", intercept_dns:true}));
assert(single.includes("src-address=192.168.10.58 "));
assert(!single.includes("SIB_GUIDE_SOURCES"));
assert(single.includes("make-static [find where address=192.168.10.58]"));
assert.equal((single.match(/add chain=dstnat/g)||[]).length, 3);
for (const line of single.split("\n").filter(line => line.startsWith("add chain=dstnat"))) assert(line.includes("src-address=192.168.10.58 "));
const sharedMikrotik = commands(generate({...base,method:"redirect",intercept_dns:false,lan_interface:"",ha_interface:""}));
assert(sharedMikrotik.includes('src-address=192.168.10.0/24 protocol=tcp dst-port=502,18899,38899'));
assert(!sharedMikrotik.includes('address-list'));
const externalMikrotik = commands(generate({...base,method:"redirect",intercept_dns:true,dns_ip:"192.168.10.20"}));
assert(!externalMikrotik.includes('address-list'));
assert(externalMikrotik.includes('src-address=192.168.10.20 protocol=udp dst-port=53 action=accept place-before=0'));
assert(externalMikrotik.includes('src-address=192.168.10.20 protocol=tcp dst-port=53 action=accept place-before=0'));
for (const change of [{method:"redirect",subnet:""}, {subnet:"0.0.0.0/0"}, {extra_domains:"bad.com;reboot"}, {ha_ip:"192.168.10.77;reboot"}, {lan_interface:'bridge"; reboot'}, {selected:[]}]) assert.throws(() => generate({...base,...change}));
const exact = commands(generate({...base, selected:["iot3.eybond.com"]}));
assert(!exact.includes("match-subdomain=yes"));
assert(!exact.includes("dtu_ess.eybond.com"));
const custom = commands(generate({...base,selected:[],extra_domains:"*.example.test example.test host.example.test"}));
assert.equal((custom.match(/^add name=/gm)||[]).length, 1);
const externalDomains = ["api.dessmonitor.com", "ios.shinemonitor.com", "dessmonitor.com", "www.dessmonitor.com", "www.shinemonitor.com"];
const allKnown = commands(generate({...base, selected:KNOWN_DOMAINS.map(domain => domain.name)}));
assert.equal(KNOWN_DOMAINS.length, 12);
assert.equal(KNOWN_DOMAINS.find(domain => domain.name === '*.eybond.com').defaultSelected, false);
for (const name of ['ess.eybond.com','m2m.eybond.com','iot.eybond.com','vip1.eybond.com']) {
  const individual = commands(generate({...base, selected:[name]}));
  assert(individual.includes(`add name=${name} type=A`));
  assert(!individual.includes('match-subdomain=yes'));
}
assert.equal((allKnown.match(/^add name=/gm)||[]).length, 6, "parent suffix should remove only covered collector names");
for (const name of externalDomains) {
  assert(allKnown.includes(`add name=${name} type=A address=${base.ha_ip}`));
  assert.equal(KNOWN_DOMAINS.find(domain => domain.name === name).defaultSelected, false);
}
for (const router of ["mikrotik","openwrt","pfsense","opnsense","linux"]) {
  const result=generate({...base,router,method:"redirect",intercept_dns:true,lan_interface:"",ha_interface:"",dns_interface:""});
  const text=commands(result);
  assert(text.includes("192.168.10.77"));
  assert(text.includes("502") && text.includes("18899") && text.includes("38899"));
  assert(!text.includes('SIB_GUIDE_SOURCES'));
  assert(!text.includes('firewall/alias/'));
  assert(!text.includes('aliases/alias'));
  assert(text.includes('192.168.10.0/24'));
  assert(!text.includes('192.168.10.0/26'), 'subnet must not be split into CIDR lists');
  const one = generate({...base,router,method:'redirect',scope:'single',collector_ip:'192.168.10.58',intercept_dns:false});
  assert.equal(one.settings.source,'192.168.10.58');
  assert(!commands(one).includes('SIB_GUIDE_SOURCES'));
  if (["mikrotik", "linux"].includes(router)) {
    assert(!text.includes('in-interface=""') && !text.includes('iifname ""'));
    assert(!text.includes('out-interface=""') && !text.includes('oifname ""'));
    assert.equal(result.settings.lan_interface, "");
  } else {
    assert.equal(result.settings.lan_interface, "lan");
    assert.equal(result.settings.ha_interface, "lan");
    assert.equal(result.settings.dns_interface, "lan");
  }
  if (router === "opnsense") {
    const code=result.blocks[0].code.split("\n").slice(1,-1).join("\n");
    execFileSync("python3",["-c","import ast,sys; ast.parse(sys.stdin.read())"],{input:code});
    assert(!code.includes("input("), "heredoc scripts must prompt through the terminal, not exhausted stdin");
    assert(!code.includes("verify=False"));
    assert(code.includes("'snat_mode':'hybrid'"));
  }
  if (router === "pfsense") execFileSync("php",["-l"],{input:"<?php\n"+result.blocks[1].code.replace(/\nexec$/, "")});
  if (["linux","openwrt"].includes(router)) for (const item of result.blocks) execFileSync("sh",["-n"],{input:item.code});
  const external=commands(generate({...base,router,method:"redirect",intercept_dns:true,dns_ip:"192.168.20.2",dns_interface:"iotdns"}));
  assert(external.includes("192.168.20.2"));
  assert(!external.includes('SIB_GUIDE_SOURCES'));
  if (router === 'openwrt') {
    assert(text.includes("uci set firewall.sib_tcp_18899.src_ip='192.168.10.0/24'"));
    assert(external.includes("uci add_list firewall.sib_dns.src_ip='!192.168.20.2'"));
    assert(!text.includes('uci add_list firewall.sib_tcp_'));
  }
  if (router === 'pfsense') {
    assert(text.includes("'source'=>['address'=>$sib['source']]"));
    assert(external.indexOf("'nordr'=>true") < external.indexOf('foreach ($flows as'));
  }
  if (router === 'opnsense') {
    assert(text.includes("'source':{'network':cfg['source']}"));
    assert(text.includes("'source_net':cfg['source']"));
    assert(external.includes("'nordr':'1'"));
    assert(external.includes('before_uuid = rule_uuid'));
  }
  if (router === 'linux') {
    assert(text.includes('ip saddr 192.168.10.0/24 tcp dport'));
    assert(external.includes('ip saddr 192.168.10.0/24 ip saddr != 192.168.20.2'));
  }
  const customized=generate({...base,router,method:"redirect",intercept_dns:true,lan_interface:"iot",ha_interface:"home",dns_interface:"dnsnet"});
  assert.equal(customized.settings.lan_interface,"iot");
  assert.equal(customized.settings.ha_interface,"home");
}
console.log("PASS router recipes: direct IP/subnet without aliases, external DNS bypass, DNS-only, domain selection, validation and syntax");

(async () => {
  const server = http.createServer((req,res) => {
    const file = req.url.includes("collector-domains.json") ? "collector-domains.json" : req.url.includes("router-guide.js") ? "router-guide.js" : "routers.html";
    res.setHeader("Content-Type", file.endsWith("json") ? "application/json" : file.endsWith("js") ? "text/javascript" : "text/html");
    res.end(fs.readFileSync(path.join(frontend,file)));
  });
  await new Promise(resolve => server.listen(0,"127.0.0.1",resolve));
  const url=`http://127.0.0.1:${server.address().port}/solar_inverter_bridge/routers.html`;
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage();
  const errors=[];
  page.on("pageerror", error => errors.push(error.message));
  try {
    await page.goto(url);
    await page.waitForFunction(() => Boolean(window.SIBRouterGuide));
    assert.equal(await page.locator("#intercept_dns").isChecked(), false);
    for (const name of externalDomains) assert.equal(await page.locator(`[name="domain"][value="${name}"]`).isChecked(), false);
    const wildcard = page.locator('[name="domain"][value="*.eybond.com"]');
    assert.equal(await wildcard.isChecked(), false);
    for (const domain of KNOWN_DOMAINS.filter(domain => !domain.suffix && domain.name.endsWith('.eybond.com'))) assert(await page.locator(`[name="domain"][value="${domain.name}"]`).isEnabled());
    assert.equal(await page.locator("#ha_ip").inputValue(), "", "browser host must not become a LAN hint");
    // Empty values saved by a direct visit must not suppress later HA discovery hints.
    const hints = new URLSearchParams({ha_ip:base.ha_ip,router_ip:base.router_ip,dns_ip:base.dns_ip,subnet:base.subnet});
    await page.goto(url+"#"+hints);
    await page.reload();
    await page.waitForFunction(() => Boolean(window.SIBRouterGuide));
    assert.equal(await page.locator("#ha_ip").inputValue(),base.ha_ip);
    assert.equal(await page.locator("#router_ip").inputValue(),base.router_ip);
    assert.equal(await page.locator("#collector-field").isHidden(),true);
    assert.equal(await page.locator("#output").isHidden(),true);
    await page.getByRole("button",{name:"Generate commands",exact:true}).click();
    assert(await page.locator("#output").isVisible());
    assert(!(await page.locator("#commands").innerText()).includes("add chain="));
    await page.getByRole("button",{name:"Clear selection"}).click();
    await page.locator('[name="domain"][value="iot3.eybond.com"]').check();
    await page.getByRole("button",{name:"Generate commands",exact:true}).click();
    assert(!(await page.locator("#commands").innerText()).includes("dtu_ess.eybond.com"));
    await page.getByRole("button",{name:"Select all",exact:true}).click();
    assert.equal(await page.locator('[name="domain"]:checked').count(),12);
    assert.equal(await page.locator('[name="domain"]:disabled').count(),6);
    await wildcard.uncheck();
    assert.equal(await page.locator('[name="domain"]:disabled').count(),0);
    assert(await page.locator('[name="domain"][value="m2m.eybond.com"]').isChecked());
    await wildcard.check();
    await page.getByRole("button",{name:"Generate commands",exact:true}).click();
    const allDomainCommands = await page.locator("#commands").innerText();
    for (const name of externalDomains) assert(allDomainCommands.includes(`add name=${name} type=A`));
    await page.locator("#method").selectOption("redirect");
    await page.locator("#intercept_dns").check();
    assert(await page.locator("#lan_interface").isHidden());
    await page.getByRole("button",{name:"Generate commands",exact:true}).click();
    assert((await page.locator("#commands").innerText()).includes("add chain=dstnat"));
    assert(!(await page.locator("#commands").innerText()).includes("in-interface="));
    assert((await page.locator("#dns-use-note").innerText()).includes("192.168.10.1"));
    await page.locator("#scope").selectOption("single");
    await page.locator("#collector_ip").fill("192.168.10.58");
    await page.getByRole("button",{name:"Generate commands",exact:true}).click();
    assert((await page.locator("#dhcp-note").innerText()).includes("Reserve"));
    assert((await page.locator("#commands").innerText()).includes("src-address=192.168.10.58 "));
    await page.locator("#scope").selectOption("network");
    await page.locator("#ha_ip").fill("192.168.10.88");
    await page.reload();
    await page.waitForFunction(() => Boolean(window.SIBRouterGuide));
    assert(await wildcard.isChecked());
    assert.equal(await page.locator('[name="domain"]:disabled').count(),6);
    await wildcard.uncheck();
    assert.equal(await page.locator('[name="domain"]:checked').count(),11);
    assert.equal(await page.locator("#ha_ip").inputValue(),"192.168.10.88", "user corrections must survive discovery hints");
    assert.equal(await page.locator("#intercept_dns").isChecked(), false, "DNS interception must not be restored from a previous visit");
    for (const router of ["mikrotik","openwrt","pfsense","opnsense","linux","other"]) {
      await page.locator("#router").selectOption(router);
      await page.getByRole("button",{name:"Generate commands",exact:true}).click();
      assert(await page.locator("#output").isVisible());
      assert.equal(await page.locator("#lan_interface").inputValue(), "");
      if (["openwrt", "pfsense", "opnsense"].includes(router)) {
        assert(await page.locator("#interface-note").isVisible());
        assert((await page.locator("#interface-note").innerText()).includes("lan"));
      }
      for (const width of [360,390,768,1440]) {
        await page.setViewportSize({width,height:900});
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1), `${router} overflow at ${width}`);
      }
    }
    await page.locator("#extra_domains").fill('<img src=x onerror="alert(1)">');
    await page.getByRole("button",{name:"Generate commands",exact:true}).click();
    assert(await page.locator("#form-error").isVisible());
    assert(await page.locator("#output").isHidden());
    await page.getByRole("button",{name:"Forget saved values"}).click();
    await page.waitForLoadState("load");
    await page.waitForFunction(() => Boolean(window.SIBRouterGuide));
    assert.equal(await page.locator("#ha_ip").inputValue(),base.ha_ip);
    assert.equal(await page.locator("#method").inputValue(),"dns");
    assert.equal(await wildcard.isChecked(),false);
    assert.deepEqual(errors,[]);
    console.log("PASS router form: prefill, no collector IP, individual/shared rules, all/single domains, persistence, and 24 responsive screens");
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {console.error(error);process.exitCode=1;});
