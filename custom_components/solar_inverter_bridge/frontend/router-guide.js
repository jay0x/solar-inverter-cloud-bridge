/* Local-only router instruction generator. No router credentials or requests. */
(() => {
  "use strict";
  const KNOWN_DOMAINS = typeof module !== "undefined" && module.exports ? require("./collector-domains.json") : [];
  const PRIVATE = [[0x0a000000, 0x0affffff], [0xac100000, 0xac1fffff], [0xc0a80000, 0xc0a8ffff]];
  const ipNumber = value => value.split(".").reduce((number, part) => number * 256 + Number(part), 0);
  const ipString = value => [24, 16, 8, 0].map(bits => Math.floor(value / 2 ** bits) % 256).join(".");
  function address(value, label) {
    value = String(value || "").trim();
    if (!/^(0|[1-9]\d{0,2})(\.(0|[1-9]\d{0,2})){3}$/.test(value) || value.split(".").some(part => Number(part) > 255)) throw new Error(`${label}: enter an IPv4 address.`);
    const number = ipNumber(value);
    if (!PRIVATE.some(([start, end]) => number >= start && number <= end)) throw new Error(`${label}: use a private LAN address (10.x, 172.16–31.x, or 192.168.x).`);
    return value;
  }
  function network(value) {
    const parts = String(value || "").trim().split("/");
    const ip = address(parts[0], "Collector network");
    if (parts.length !== 2 || !/^(?:[1-9]|[12]\d|3[0-2])$/.test(parts[1])) throw new Error("Collector network: include a CIDR prefix.");
    const prefix = Number(parts[1]), size = 2 ** (32 - prefix), start = Math.floor(ipNumber(ip) / size) * size;
    if (start !== ipNumber(ip)) throw new Error(`Collector network: use ${ipString(start)}/${prefix}, not a host address.`);
    if (!PRIVATE.some(([first, last]) => start >= first && start + size - 1 <= last)) throw new Error("Collector network must stay within one private LAN range.");
    return {text: `${ip}/${prefix}`, start, end: start + size - 1};
  }
  function domains(selected, extra) {
    const all = KNOWN_DOMAINS.filter(item => selected.includes(item.name)).map(item => ({...item, name:item.suffix ? item.name.replace(/^\*\./, "") : item.name}));
    for (let raw of String(extra || "").split(/[\s,]+/).filter(Boolean)) {
      const suffix = raw.startsWith("*.");
      raw = (suffix ? raw.slice(2) : raw).toLowerCase().replace(/\.$/, "");
      if (raw.length > 253 || !raw.includes(".") || raw.split(".").some(part => !/^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$/.test(part))) throw new Error("Additional domains: enter DNS names, not URLs or commands.");
      all.push({name: raw, suffix});
    }
    if (!all.length) throw new Error("Select at least one collector domain.");
    if (all.length > 32) throw new Error("Use at most 32 domain entries.");
    return all.filter((item, index) => !all.some((other, otherIndex) =>
      otherIndex !== index && ((other.name === item.name && (other.suffix && !item.suffix || other.suffix === item.suffix && otherIndex < index))
        || other.suffix && item.name.endsWith("." + other.name))));
  }
  function settings(raw) {
    const value = {...raw};
    for (const [key, label] of [["ha_ip", "Home Assistant"], ["router_ip", "Router"], ["dns_ip", "DNS resolver"]]) value[key] = address(value[key], label);
    if (value.ha_ip === value.router_ip) throw new Error("Home Assistant and the router must have different addresses.");
    if (!["mikrotik", "openwrt", "pfsense", "opnsense", "linux", "other"].includes(value.router)) throw new Error("Choose a router platform.");
    if (!["dns", "redirect"].includes(value.method) || !["single", "network"].includes(value.scope)) throw new Error("Choose a connection method and source scope.");
    value.intercept_dns = !!value.intercept_dns;
    value.hairpin = value.method === "redirect" && !!value.hairpin;
    value.nat = value.method === "redirect" || value.intercept_dns;
    value.subnet = value.scope === "network" && value.subnet ? network(value.subnet).text : "";
    value.collector_ip = value.scope === "single" ? address(value.collector_ip, "Collector") : "";
    if (value.nat && value.scope === "network" && !value.subnet) throw new Error("Enter the LAN/IoT subnet for shared interception rules. No individual inverter IP is needed.");
    value.source = value.scope === "single" ? value.collector_ip : value.subnet;
    if (value.collector_ip && [value.ha_ip, value.router_ip, value.dns_ip].includes(value.collector_ip)) throw new Error("The collector cannot be the HA host, router, or DNS resolver.");
    for (const key of ["lan_interface", "ha_interface", "dns_interface"]) {
      value[key] = String(value[key] || "").trim();
      if (value[key] && !/^[a-zA-Z0-9_.:-]{1,32}$/.test(value[key])) throw new Error("Interface/zone names may contain letters, digits, dots, underscores, colons, and hyphens.");
    }
    value.default_lan = ["openwrt", "pfsense", "opnsense"].includes(value.router) && !value.lan_interface;
    if (value.default_lan) value.lan_interface = "lan";
    if (["openwrt", "pfsense", "opnsense"].includes(value.router)) {
      value.ha_interface ||= value.lan_interface;
      value.dns_interface ||= value.lan_interface;
    }
    value.domains = domains(value.selected || [], value.extra_domains);
    return value;
  }
  const block = (title, code) => ({title, code: code.trim()});
  const shQuote = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
  function dnsmasqLines(s) {
    return s.domains.flatMap(domain => domain.suffix
      ? [`address=/${domain.name}/${s.ha_ip}`, `local=/${domain.name}/`]
      : [`host-record=${domain.name},${s.ha_ip},300`, `local=/${domain.name}/`]);
  }
  function externalDns(s) {
    return block(`DNS — run on the dnsmasq resolver at ${s.dns_ip}`, `set -e
sudo install -d /etc/dnsmasq.d
sudo tee /etc/dnsmasq.d/solar-inverter-bridge.conf >/dev/null <<'SIB_DNS'
${dnsmasqLines(s).join("\n")}
SIB_DNS
if ! sudo grep -Eq '^[[:space:]]*conf-dir=/etc/dnsmasq[.]d([,/[:space:]]|$)|^[[:space:]]*conf-file=/etc/dnsmasq[.]d/solar-inverter-bridge[.]conf$' /etc/dnsmasq.conf; then
  printf '\\nconf-file=/etc/dnsmasq.d/solar-inverter-bridge.conf\\n' | sudo tee -a /etc/dnsmasq.conf >/dev/null
fi
sudo dnsmasq --test
sudo systemctl restart dnsmasq
# Serve the collector LAN only; preserve normal upstream DNS for other names.`);
  }
  function mikrotik(s) {
    const incoming = s.lan_interface ? `in-interface="${s.lan_interface}" ` : "";
    const outgoing = s.ha_interface ? `out-interface="${s.ha_interface}" ` : "";
    const result = [block("1. Inspect RouterOS interfaces and existing rules", "/interface print\n/ip dns print\n/ip dns static print\n/ip firewall nat print\n/ip firewall filter print")];
    if (s.dns_ip === s.router_ip) result.push(block("2. Local DNS records — RouterOS terminal", `/ip dns static
${s.domains.map(d => `add name=${d.name} type=A address=${s.ha_ip} ttl=5m${d.suffix ? " match-subdomain=yes" : ""} comment="SolarInverterBridge DNS"`).join("\n")}
/ip dns set allow-remote-requests=yes
# Permit DNS from the trusted LAN in the input firewall; keep WAN DNS blocked.`));
    if (s.nat) {
      const lines = ["/ip firewall nat"];
      if (s.method === "redirect") lines.push(`add chain=dstnat ${incoming}src-address=${s.source} protocol=tcp dst-port=502,18899,38899 action=dst-nat to-addresses=${s.ha_ip} comment="SolarInverterBridge TCP"`);
      if (s.intercept_dns) for (const protocol of ["udp", "tcp"]) lines.push(`add chain=dstnat ${incoming}src-address=${s.source} protocol=${protocol} dst-port=53 action=${s.dns_ip === s.router_ip ? "redirect to-ports=53" : `dst-nat to-addresses=${s.dns_ip} to-ports=53`} comment="SolarInverterBridge DNS ${protocol}"`);
      if (s.hairpin) lines.push(`add chain=srcnat ${outgoing}src-address=${s.source} dst-address=${s.ha_ip} protocol=tcp dst-port=502,18899,38899 connection-nat-state=dstnat action=masquerade comment="SolarInverterBridge return TCP"`);
      if (s.intercept_dns && s.dns_ip !== s.router_ip) for (const protocol of ["udp", "tcp"]) lines.push(`add chain=srcnat src-address=${s.source} dst-address=${s.dns_ip} protocol=${protocol} dst-port=53 connection-nat-state=dstnat action=masquerade comment="SolarInverterBridge return DNS ${protocol}"`);
      lines.push("/ip firewall filter");
      if (s.method === "redirect") lines.push(`add chain=forward ${incoming}src-address=${s.source} dst-address=${s.ha_ip} protocol=tcp dst-port=502,18899,38899 action=accept comment="SolarInverterBridge allow TCP"`);
      if (s.intercept_dns) for (const protocol of ["udp", "tcp"]) lines.push(`add chain=${s.dns_ip === s.router_ip ? "input" : "forward"} ${incoming}src-address=${s.source} dst-address=${s.dns_ip} protocol=${protocol} dst-port=53 action=accept comment="SolarInverterBridge allow DNS ${protocol}"`);
      lines.push(':foreach rule in=[/ip firewall nat find where comment~"^SolarInverterBridge "] do={ /ip firewall nat move $rule destination=0 }', ':foreach rule in=[/ip firewall filter find where comment~"^SolarInverterBridge "] do={ /ip firewall filter move $rule destination=0 }');
      if (s.intercept_dns && s.dns_ip !== s.router_ip) {
        lines.push("# Keep the external resolver's own DNS queries out of interception.", "/ip firewall nat");
        for (const protocol of ["udp", "tcp"]) lines.push(`add chain=dstnat src-address=${s.dns_ip} protocol=${protocol} dst-port=53 action=accept place-before=0 comment="SolarInverterBridge resolver bypass ${protocol}"`);
      }
      result.push(block("3. Shared interception rules — RouterOS terminal", lines.join("\n")));
    }
    if (s.scope === "single") result.push(block("Reserve the active collector DHCP lease — RouterOS terminal", `/ip dhcp-server lease print where address=${s.collector_ip}
# Check that the displayed MAC belongs to your collector, then:
/ip dhcp-server lease make-static [find where address=${s.collector_ip}]`));
    result.push(block("Check DNS and counters — RouterOS terminal", `${s.domains.map(d => `:put [:resolve domain-name="${d.name}" server=${s.dns_ip}]`).join("\n")}
/ip firewall nat print stats where comment~"SolarInverterBridge"`));
    return result;
  }
  function openwrt(s) {
    const result = [block("1. Inspect zones — SSH shell on OpenWrt", "uci show firewall\nuci show dhcp\nip -4 address")];
    if (s.dns_ip === s.router_ip) result.push(block("2. DNS overrides — OpenWrt SSH shell", `set -e
${s.domains.flatMap(d => d.suffix
      ? [`uci add_list dhcp.@dnsmasq[0].address='/${d.name}/${s.ha_ip}'`, `uci add_list dhcp.@dnsmasq[0].server='/${d.name}/'`]
      : [`uci add_list dhcp.@dnsmasq[0].hostrecord='${d.name},${s.ha_ip},300'`, `uci add_list dhcp.@dnsmasq[0].server='/${d.name}/'`]).join("\n")}
uci commit dhcp
/etc/init.d/dnsmasq restart`));
    if (s.nat) {
      const lines = ["set -e"];
      const addRedirect = (name, protocol, port, target, zone) => {
        lines.push(`uci set firewall.${name}=redirect`, `uci set firewall.${name}.name='SolarInverterBridge ${name}'`, `uci set firewall.${name}.family='ipv4'`, `uci set firewall.${name}.src='${s.lan_interface}'`, `uci set firewall.${name}.proto='${protocol}'`, `uci set firewall.${name}.src_dport='${port}'`, `uci set firewall.${name}.dest_ip='${target}'`, `uci set firewall.${name}.dest_port='${port}'`, `uci set firewall.${name}.target='DNAT'`, `uci set firewall.${name}.src_ip='${s.source}'`);
        if (zone) lines.push(`uci set firewall.${name}.dest='${zone}'`);
        lines.push(`uci set firewall.${name}.reflection='0'`, `uci reorder firewall.${name}=0`);
      };
      if (s.method === "redirect") for (const port of [502, 18899, 38899]) addRedirect(`sib_tcp_${port}`, "tcp", port, s.ha_ip, s.ha_interface || s.lan_interface);
      if (s.intercept_dns) {
        addRedirect("sib_dns", "tcp udp", 53, s.dns_ip, s.dns_ip === s.router_ip ? "" : s.dns_interface);
        if (s.dns_ip !== s.router_ip) lines.push(`# Exclude only the external resolver's own DNS traffic.`, `uci add_list firewall.sib_dns.src_ip='!${s.dns_ip}'`);
        if (s.dns_ip === s.router_ip) lines.push("uci set firewall.sib_dns_input=rule", "uci set firewall.sib_dns_input.name='SolarInverterBridge DNS input'", `uci set firewall.sib_dns_input.src='${s.lan_interface}'`, "uci set firewall.sib_dns_input.proto='tcp udp'", "uci set firewall.sib_dns_input.dest_port='53'", "uci set firewall.sib_dns_input.target='ACCEPT'", `uci set firewall.sib_dns_input.src_ip='${s.source}'`, "uci reorder firewall.sib_dns_input=0");
      }
      const snat = (name, protocol, ports, destination, zone) => {
        lines.push(`uci set firewall.${name}=nat`, `uci set firewall.${name}.name='SolarInverterBridge ${name}'`, `uci set firewall.${name}.family='ipv4'`, `uci set firewall.${name}.src='${zone}'`, `uci set firewall.${name}.src_ip='${s.source}'`, `uci set firewall.${name}.dest_ip='${destination}'`, `uci set firewall.${name}.dest_port='${ports}'`, `uci set firewall.${name}.proto='${protocol}'`, `uci set firewall.${name}.target='MASQUERADE'`, `uci reorder firewall.${name}=0`);
      };
      if (s.hairpin) snat("sib_return_tcp", "tcp", "502 18899 38899", s.ha_ip, s.ha_interface);
      if (s.intercept_dns && s.dns_ip !== s.router_ip) snat("sib_return_dns", "tcp udp", "53", s.dns_ip, s.dns_interface);
      lines.push("uci commit firewall", "fw4 check", "/etc/init.d/firewall reload", "nft list ruleset", "# Verify these rules precede conflicting redirects or isolation drops.");
      result.push(block("3. NAT — OpenWrt SSH shell (named sib_* sections)", lines.join("\n")));
    }
    result.push(block("Check DNS — OpenWrt SSH shell", s.domains.map(d => `nslookup ${d.name} ${s.dns_ip}`).join("\n")));
    return result;
  }
  function unboundLines(s) {
    return s.domains.flatMap(d => [`local-zone: "${d.name}." ${d.suffix ? "redirect" : "static"}`, `local-data: "${d.name}. 300 IN A ${s.ha_ip}"`]);
  }
  function pfsense(s) {
    const data = {source: s.source, lan: s.lan_interface, out: s.ha_interface || s.lan_interface, dns_out: s.dns_interface, ha: s.ha_ip, dns: s.dns_ip, router: s.router_ip, tcp: s.method === "redirect", intercept: s.intercept_dns, hairpin: s.hairpin, zones: unboundLines(s)};
    const code = `require_once("filter.inc");
require_once("services.inc");
require_once("unbound.inc");
$sib = json_decode('${JSON.stringify(data)}', true);
if (!function_exists('config_get_path') || !function_exists('config_set_path')) { throw new Exception('Unsupported pfSense config API'); }
if (($sib['tcp'] || $sib['intercept']) && !config_get_path('interfaces/' . $sib['lan'])) { throw new Exception('Unknown collector interface'); }
if ($sib['dns'] === $sib['router'] && !config_path_enabled('unbound', 'enable')) { throw new Exception('Enable DNS Resolver on the LAN first'); }
$tag = 'SolarInverterBridge';
if ($sib['dns'] === $sib['router']) {
    $old = base64_decode(config_get_path('unbound/custom_options', ''));
    if (str_contains($old, '# SolarInverterBridge begin')) { throw new Exception('Guide DNS block already exists; edit it instead of adding another'); }
    $extra = "\n# SolarInverterBridge begin\nserver:\n" . implode("\n", $sib['zones']) . "\n# SolarInverterBridge end\n";
    config_set_path('unbound/custom_options', base64_encode($old . $extra));
}
if ($sib['tcp'] || $sib['intercept']) {
    $rules = config_get_path('nat/rule', []);
    foreach ($rules as $rule) { if (str_starts_with($rule['descr'] ?? '', $tag)) { throw new Exception('Guide NAT rules already exist; edit those rules instead of adding duplicates'); } }
    $flows = $sib['tcp'] ? [['tcp',502,$sib['ha']],['tcp',18899,$sib['ha']],['tcp',38899,$sib['ha']]] : [];
    if ($sib['intercept']) { $flows[]=['tcp',53,$sib['dns']]; $flows[]=['udp',53,$sib['dns']]; }
    $new = [];
    if ($sib['intercept'] && $sib['dns'] !== $sib['router']) {
        foreach (['tcp','udp'] as $proto) {
            $new[] = ['interface'=>$sib['lan'], 'ipprotocol'=>'inet', 'protocol'=>$proto,
              'source'=>['address'=>$sib['dns']], 'destination'=>['any'=>'', 'port'=>'53'],
              'nordr'=>true, 'descr'=>$tag . ' resolver bypass ' . $proto];
        }
    }
    foreach ($flows as [$proto,$port,$target]) {
        $new[] = ['interface'=>$sib['lan'], 'ipprotocol'=>'inet', 'protocol'=>$proto,
          'source'=>['address'=>$sib['source']], 'destination'=>['any'=>'', 'port'=>(string)$port],
          'target'=>$target, 'local-port'=>(string)$port, 'associated-rule-id'=>'pass',
          'natreflection'=>'disable', 'descr'=>$tag . ' ' . $proto . ' ' . $port];
    }
    config_set_path('nat/rule', array_merge($new, $rules));
    if ($sib['hairpin'] || ($sib['intercept'] && $sib['dns'] !== $sib['router'])) {
        $mode = config_get_path('nat/outbound/mode', 'automatic');
        if ($mode === 'disabled') { throw new Exception('Outbound NAT is disabled; review return-path routing first'); }
        if ($mode === 'automatic') { config_set_path('nat/outbound/mode', 'hybrid'); }
        $out = config_get_path('nat/outbound/rule', []);
        foreach ($flows as [$proto,$port,$target]) {
            if (($port !== 53 && !$sib['hairpin']) || ($port === 53 && $sib['dns'] === $sib['router'])) { continue; }
            array_unshift($out, ['interface'=>$port===53 ? $sib['dns_out'] : $sib['out'], 'ipprotocol'=>'inet', 'protocol'=>$proto,
              'source'=>['network'=>$sib['source']], 'destination'=>['network'=>$target.'/32'],
              'dstport'=>(string)$port, 'target'=>'', 'descr'=>$tag . ' return ' . $proto . ' ' . $port]);
        }
        config_set_path('nat/outbound/rule', $out);
    }
}
if ($sib['dns'] === $sib['router']) {
    $errors = [];
    if (test_unbound_config(config_get_path('unbound'), $errors) !== 0) { throw new Exception(implode("\\n", $errors)); }
}
write_config('SolarInverterBridge DNS and scoped NAT');
if ($sib['dns'] === $sib['router']) { services_unbound_configure(false); }
filter_configure();
exec`;
    return [block("1. Open the documented pfSense PHP shell — SSH shell", "pfSsh.php"), block("2. Paste into the PHP shell, including the final exec line", code), block("3. Exit PHP shell, then check from the SSH shell", `exit
${s.domains.map(d => `drill @${s.dns_ip} ${d.name} A`).join("\n")}
pfctl -sn` )];
  }
  function opnsense(s) {
    const hosts = s.domains.flatMap(d => d.suffix ? [{hostname: "", domain: d.name}, {hostname: "*", domain: d.name}] : [{hostname: d.name.split(".")[0], domain: d.name.split(".").slice(1).join(".")}]);
    const payload = {ha: s.ha_ip, router: s.router_ip, dns: s.dns_ip, interface: s.lan_interface, out: s.ha_interface || s.lan_interface, dns_out: s.dns_interface, source: s.source, hosts, tcp: s.method === "redirect", intercept: s.intercept_dns, hairpin: s.hairpin};
    const script = `python3 - <<'SIB_API'
import base64, getpass, json, ssl, urllib.request
cfg = json.loads(${JSON.stringify(JSON.stringify(payload))})
def prompt(message):
    with open('/dev/tty', 'r+') as tty:
        tty.write(message); tty.flush()
        return tty.readline().strip()
base = prompt('OPNsense HTTPS URL (certificate name must match): ').rstrip('/')
if not base.startswith('https://'): raise SystemExit('HTTPS is required')
ca = prompt('Trusted CA PEM path (empty for system trust): ')
tls = ssl.create_default_context(cafile=ca or None)
key = getpass.getpass('API key: ')
secret = getpass.getpass('API secret: ')
auth = 'Basic ' + base64.b64encode((key + ':' + secret).encode()).decode()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None
opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=tls))
def api(path, data=None):
    request = urllib.request.Request(base + '/api/' + path, data=None if data is None else json.dumps(data).encode(), headers={'Authorization': auth, 'Content-Type': 'application/json'})
    with opener.open(request, timeout=30) as response:
        result = json.load(response)
    if data is not None and (result.get('validations') or result.get('result') in ('failed','fail') or result.get('status') in ('failed','fail')):
        raise RuntimeError(json.dumps(result))
    return result
def add(path, data):
    result = api(path, data)
    if not result.get('uuid'): raise RuntimeError('Creation not confirmed: ' + json.dumps(result))
    print(path, result['uuid'])
    return result['uuid']
nat = cfg['tcp'] or cfg['intercept']
if nat:
    schema = api('firewall/d_nat/get_rule')['rule']
    if not all(k in schema for k in ('source','destination','target','local-port','pass')):
        raise SystemExit('This firmware does not expose the supported DNat schema')
    existing = api('firewall/d_nat/search_rule?rowCount=-1').get('rows', [])
    if any(row.get('descr','').startswith('SolarInverterBridge') for row in existing):
        raise SystemExit('Guide NAT rules already exist. Edit them instead of adding duplicates.')
    previous = api('firewall/d_nat/search_rule?rowCount=1').get('rows', [])
    before_uuid = previous[0].get('uuid') if previous else None
if cfg['dns'] == cfg['router']:
    existing = api('unbound/settings/search_host_override?rowCount=-1').get('rows', [])
    for host in cfg['hosts']:
        if any(row.get('hostname','') == host['hostname'] and row.get('domain') == host['domain'] for row in existing):
            raise SystemExit('A selected DNS override already exists; review it first')
    for host in cfg['hosts']:
        add('unbound/settings/add_host_override', {'host': dict(host, enabled='1', rr='A', server=cfg['ha'], ttl='300', addptr='0', description='SolarInverterBridge')})
if nat:
    flows = [('tcp',502,cfg['ha']),('tcp',18899,cfg['ha']),('tcp',38899,cfg['ha'])] if cfg['tcp'] else []
    if cfg['intercept']: flows += [('tcp',53,cfg['dns']),('udp',53,cfg['dns'])]
    for proto, port, target in flows:
        rule_uuid = add('firewall/d_nat/add_rule', {'rule': {'disabled':'0','interface':cfg['interface'],'ipprotocol':'inet','protocol':proto,'source':{'network':cfg['source']},'destination':{'network':'any','port':str(port)},'target':target,'local-port':str(port),'pass':'pass','natreflection':'disable','descr':'SolarInverterBridge ' + proto + ' ' + str(port)}})
        if before_uuid: api('firewall/d_nat/move_rule_before/' + rule_uuid + '/' + before_uuid)
        before_uuid = rule_uuid
    if cfg['intercept'] and cfg['dns'] != cfg['router']:
        for proto in ('tcp','udp'):
            rule_uuid = add('firewall/d_nat/add_rule', {'rule': {'disabled':'0','nordr':'1','interface':cfg['interface'],'ipprotocol':'inet','protocol':proto,'source':{'network':cfg['dns']},'destination':{'network':'any','port':'53'},'descr':'SolarInverterBridge resolver bypass ' + proto}})
            if before_uuid: api('firewall/d_nat/move_rule_before/' + rule_uuid + '/' + before_uuid)
            before_uuid = rule_uuid
    returns = [(p,n,t) for p,n,t in flows if n != 53 and cfg['hairpin'] or n == 53 and cfg['dns'] != cfg['router']]
    if returns:
        mode = api('firewall/source_nat/get')['filter']['settings']['nat']['snat_mode']
        if isinstance(mode, dict): mode = next((k for k,v in mode.items() if str(v.get('selected')) == '1'), None)
        if mode == 'automatic': api('firewall/source_nat/set', {'filter': {'settings': {'nat': {'snat_mode':'hybrid'}}}})
        elif mode not in ('hybrid', 'advanced'): raise RuntimeError('Review the existing outbound NAT mode before adding return rules')
        for proto, port, target in returns:
            add('firewall/source_nat/add_rule', {'rule': {'enabled':'1','interface':cfg['out'] if port != 53 else cfg['dns_out'],'ipprotocol':'inet','protocol':proto,'source_net':cfg['source'],'destination_net':target,'destination_port':str(port),'target':'','description':'SolarInverterBridge return ' + proto + ' ' + str(port)}})
    api('firewall/filter/apply', {})
if cfg['dns'] == cfg['router']: api('unbound/service/reconfigure', {})
print('Review rule order in the UI and verify the DNS answers and new collector session.')
SIB_API`;
    return [block("OPNsense API — run in a trusted Unix terminal with Python 3", script), block("Check DNS — OPNsense SSH shell", s.domains.map(d => `drill @${s.dns_ip} ${d.name} A`).join("\n"))];
  }
  function linux(s) {
    const incoming = s.lan_interface ? `iifname "${s.lan_interface}" ` : "";
    const outgoing = s.ha_interface ? `oifname "${s.ha_interface}" ` : "";
    const result = [];
    if (s.dns_ip === s.router_ip) result.push(externalDns(s));
    if (s.nat) {
      const sources = s.source;
      const pre = [];
      if (s.method === "redirect") pre.push(`${incoming}ip saddr ${sources} tcp dport { 502, 18899, 38899 } counter dnat to ${s.ha_ip}`);
      if (s.intercept_dns) pre.push(`${incoming}ip saddr ${sources} ${s.dns_ip !== s.router_ip ? `ip saddr != ${s.dns_ip} ` : ""}meta l4proto { tcp, udp } th dport 53 counter dnat to ${s.dns_ip}`);
      const post = [];
      if (s.hairpin) post.push(`${outgoing}ip saddr ${sources} ip daddr ${s.ha_ip} tcp dport { 502, 18899, 38899 } ct status dnat masquerade`);
      if (s.intercept_dns && s.dns_ip !== s.router_ip) post.push(`ip saddr ${sources} ip daddr ${s.dns_ip} meta l4proto { tcp, udp } th dport 53 ct status dnat masquerade`);
      const filter = [];
      if (s.method === "redirect") filter.push(`insert rule inet filter forward ${incoming}ip saddr ${sources} ip daddr ${s.ha_ip} tcp dport { 502, 18899, 38899 } accept comment "SolarInverterBridge TCP"`);
      if (s.intercept_dns) filter.push(`insert rule inet filter ${s.dns_ip === s.router_ip ? "input" : "forward"} ${incoming}ip saddr ${sources} ip daddr ${s.dns_ip} meta l4proto { tcp, udp } th dport 53 accept comment "SolarInverterBridge DNS"`);
      result.push(block("NAT — native nftables host, root shell", `set -e
# Requires nftables >= 1.0.9 and an existing inet filter input/forward policy.
# Use the system's firewall manager instead on firewalld/UFW hosts.
nft list chain inet filter input
nft list chain inet filter forward
install -d /etc/nftables.d
cat > /etc/nftables.d/solar-inverter-bridge.nft <<'SIB_NFT'
destroy table ip solar_inverter_bridge
table ip solar_inverter_bridge {
  chain prerouting {
    type nat hook prerouting priority -101; policy accept;
    ${pre.join(";\n    ")};
  }
  chain postrouting {
    type nat hook postrouting priority 99; policy accept;
    ${post.join(";\n    ")}${post.length ? ";" : ""}
  }
}
${filter.join("\n")}
SIB_NFT
# Include after your existing filter table declaration. Do not duplicate an existing wildcard include.
grep -Eq '^[[:space:]]*include "/etc/nftables.d/(solar-inverter-bridge[.]nft|[*][.]nft|[*])"' /etc/nftables.conf || printf '\\ninclude "/etc/nftables.d/solar-inverter-bridge.nft"\\n' >> /etc/nftables.conf
nft --check -f /etc/nftables.conf
nft -f /etc/nftables.conf
sysctl -w net.ipv4.ip_forward=1
printf 'net.ipv4.ip_forward=1\\n' > /etc/sysctl.d/90-solar-inverter-bridge.conf
nft list table ip solar_inverter_bridge`));
    }
    result.push(block("Check DNS — Linux shell", s.domains.map(d => `dig @${s.dns_ip} ${d.name} A +short`).join("\n")));
    return result;
  }
  function generate(raw) {
    const s = settings(raw);
    let blocks = ({mikrotik, openwrt, pfsense, opnsense, linux}[s.router] || (() => []))(s);
    if (s.dns_ip !== s.router_ip) blocks.unshift(externalDns(s));
    if (s.router === "other") blocks.push(block("Verify DNS from a computer on this LAN", s.domains.map(d => `nslookup ${d.name} ${s.dns_ip}`).join("\n")));
    const notes = {
      mikrotik: "Run once in a RouterOS 7 terminal. Inspect existing SolarInverterBridge rules before rerunning. Reorder generated NAT/pass rules before conflicting redirects or drops.",
      openwrt: "OpenWrt firewall4/dnsmasq recipe. Interface fields are firewall zone names. Named sib_* sections belong to this guide. Inspect rule order and avoid duplicate DNS lists when rerunning.",
      pfsense: "Use pfSense's documented PHP shell, not a FreeBSD shell for PHP lines. Requires the config_get_path/config_set_path API and an enabled LAN Unbound resolver when DNS is on the router. NAT Pass rules bypass interface rules for the narrowly matched flows; review ordering. Other pfSense versions require adaptation.",
      opnsense: "Requires the DNat API with nested source/destination fields and the Unbound API. Use an API user allowed to manage these settings and a trusted TLS certificate. Firmware without this schema is refused. Credentials are entered in your terminal, not this form. Review existing rule order before use.",
      linux: "For a native nftables-managed gateway with inet filter input/forward chains and dnsmasq. Confirm interface names and include order. This is not a firewalld/UFW recipe; use their native manager on those systems.",
      other: "There is no universal configuration command for Keenetic, ASUS, or ISP firmware. Supply the exact model/firmware to obtain its CLI recipe. Apply the displayed DNS rewrites in its DNS UI; a WAN-only port-forward screen cannot intercept LAN traffic.",
    };
    return {settings: s, blocks, note: notes[s.router]};
  }

  function init() {
    const form = document.querySelector("#router-form");
    if (!form) return;
    const storeKey = "solar_inverter_bridge:router-guide:v1";
    const ids = ["router", "ha_ip", "router_ip", "dns_ip", "lan_interface", "ha_interface", "dns_interface", "method", "scope", "subnet", "collector_ip", "extra_domains", "intercept_dns", "hairpin"];
    for (const domain of KNOWN_DOMAINS) {
      const label = document.createElement("label"); label.className = "check";
      if (!domain.suffix && domain.name.endsWith(".eybond.com")) label.classList.add("domain-child");
      const input = document.createElement("input"); input.type = "checkbox"; input.name = "domain"; input.value = domain.name; input.checked = domain.defaultSelected !== false;
      const text = document.createElement("span"), name = document.createElement("strong"), description = document.createElement("small");
      name.textContent = domain.label; description.textContent = domain.description; description.className = "help";
      text.append(name, description); label.append(input, text); document.querySelector("#known-domains").append(label);
    }
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(storeKey) || "{}"); } catch (_) { /* Manual entry remains available. */ }
    const hints = new URLSearchParams(location.hash.slice(1));
    for (const id of ids) {
      const input = document.getElementById(id);
      if (id === "intercept_dns") {
        input.checked = false;
        continue;
      }
      if (Object.hasOwn(saved, id) && (input.type === "checkbox" || saved[id] !== "")) input.type === "checkbox" ? input.checked = !!saved[id] : input.value = saved[id];
      else if (hints.has(id) && ["ha_ip", "router_ip", "dns_ip", "subnet", "collector_ip"].includes(id)) input.value = hints.get(id);
    }
    const rememberedDomains = saved.individual_domains || saved.selected;
    if (Array.isArray(rememberedDomains)) form.querySelectorAll('[name="domain"]').forEach(input => input.checked = rememberedDomains.includes(input.value));
    try {
      for (const item of JSON.parse(hints.get("addresses") || "[]")) {
        const option = document.createElement("option"); option.value = address(item.address, "HA"); option.label = item.network; document.querySelector("#ha-addresses").append(option);
      }
    } catch (_) { /* Invalid URL hints are never commands. */ }
    const read = () => ({...Object.fromEntries(ids.map(id => { const input = document.getElementById(id); return [id, input.type === "checkbox" ? input.checked : input.value]; })), selected: [...form.querySelectorAll('[name="domain"]:checked:not(:disabled)')].map(input => input.value), individual_domains: [...form.querySelectorAll('[name="domain"]:checked')].map(input => input.value)});
    const update = () => {
      const wildcard = form.querySelector('[name="domain"][value="*.eybond.com"]').checked;
      for (const input of form.querySelectorAll('[name="domain"]')) {
        input.disabled = wildcard && input.value.endsWith(".eybond.com") && input.value !== "*.eybond.com";
        input.closest("label").classList.toggle("covered-domain", input.disabled);
      }
      const s = read(), single = s.scope === "single", nat = s.method === "redirect" || s.intercept_dns;
      document.querySelector("#collector-field").hidden = !single;
      document.querySelector("#subnet-field").hidden = single;
      form.elements.collector_ip.required = single;
      form.elements.subnet.required = !single && nat;
      for (const name of ["lan_interface", "ha_interface", "dns_interface"]) form.elements[name].required = false;
      document.querySelector("#hairpin-field").hidden = s.method !== "redirect";
      document.querySelector("#scope-note").hidden = single || !nat;
      document.querySelector("#scope-note").textContent = "Shared rules match this subnet directly. Shared DNS interception also affects other clients; an external DNS resolver is bypassed to prevent a loop.";
      document.querySelector("#dhcp-note").textContent = single && nat
        ? "Reserve this collector IP in the DHCP server before using IP-specific rules. If the lease changes, both redirection and an exact-IP Bridge allowlist can stop matching."
        : "For DNS-only or shared subnet rules, changing collector IPs are less critical. Native DTUPN identity preserves the inverter; Bridge must still allow the new source.";
      document.querySelector("#interface-help").textContent = ({mikrotik: "Optional: RouterOS interface name, for example bridge. Empty means IP-scoped rules.", openwrt: "Defaults to the standard lan zone. Override for an IoT zone.", linux: "Optional: Linux interface name, for example br0. Empty means IP-scoped rules.", pfsense: "Defaults to logical interface lan. Override for opt1 or another LAN.", opnsense: "Defaults to logical interface lan. Override for opt1 or another LAN."}[s.router] || "Optional firmware-specific override.");
      document.querySelector("#output").hidden = true;
      document.querySelector("#form-error").hidden = true;
      try { localStorage.setItem(storeKey, JSON.stringify(s)); } catch (_) { /* Storage is optional. */ }
    };
    form.addEventListener("input", update);
    form.addEventListener("change", update);
    for (const [id, checked] of [["select-all", true], ["select-none", false]]) document.getElementById(id).onclick = () => { form.querySelectorAll('[name="domain"]').forEach(input => input.checked = checked); update(); };
    document.querySelector("#forget-values").onclick = () => { try { localStorage.removeItem(storeKey); } catch (_) { /* optional */ } location.reload(); };
    form.addEventListener("submit", event => {
      event.preventDefault();
      try {
        const {settings: s, blocks, note} = generate(read());
        const container = document.querySelector("#commands"); container.replaceChildren();
        document.querySelector("#summary").textContent = `${s.domains.map(d => (d.suffix ? "*." : "") + d.name).join(", ")} → ${s.ha_ip}. Resolver: ${s.dns_ip}. ${s.method === "dns" ? "DNS-only: no TCP port-redirection rules." : "TCP 502/18899/38899 → HA at the same ports."} ${s.intercept_dns ? "DNS interception source: " + s.source + "." : "Collector must use this resolver via DHCP or its network settings."}`;
        document.querySelector("#platform-note").textContent = note;
        document.querySelector("#dns-use-note").textContent = `Make sure the inverter sends DNS requests to ${s.dns_ip}, where these records must be configured.${s.intercept_dns ? " The generated DNS redirect sends matching requests there." : " Set this DNS server through DHCP or the inverter's network settings. Records on another device will not be used."}`;
        const interfaceNote = document.querySelector("#interface-note");
        interfaceNote.hidden = !s.nat || !["openwrt", "pfsense", "opnsense"].includes(s.router);
        interfaceNote.textContent = `These commands use ${s.lan_interface} as the collector LAN and ${s.ha_interface} toward HA. If your devices are in a different zone/VLAN, change Advanced settings first.`;
        for (const item of blocks) {
          const section = document.createElement("div"), heading = document.createElement("div"), title = document.createElement("h3"), button = document.createElement("button"), pre = document.createElement("pre");
          heading.className = "command-heading"; title.textContent = item.title; button.textContent = "Copy commands"; button.type = "button"; pre.textContent = item.code; pre.tabIndex = 0;
          button.onclick = async () => { try { await navigator.clipboard.writeText(item.code); button.textContent = "Copied"; } catch (_) { const selection = getSelection(), range = document.createRange(); range.selectNodeContents(pre); selection.removeAllRanges(); selection.addRange(range); button.textContent = "Selected — copy manually"; } };
          heading.append(title, button); section.append(heading, pre); container.append(section);
        }
        document.querySelector("#allowlist-note").textContent = `Bridge allowed sources: ${s.source || "the actual collector IP or its LAN/IoT subnet"}${s.method === "redirect" && s.hairpin ? " and " + s.router_ip + " if SNAT is used" : ""}. A router DNS override does not change source IPs. This guide does not edit the allowlist.`;
        const output = document.querySelector("#output"); output.hidden = false; document.querySelector("#form-error").hidden = true; output.focus(); output.scrollIntoView({behavior: "smooth", block: "start"});
      } catch (error) {
        document.querySelector("#output").hidden = true;
        const element = document.querySelector("#form-error"); element.textContent = error.message; element.hidden = false;
      }
    });
    update();
    form.querySelector('[type="submit"]').disabled = false;
  }
  const api = {KNOWN_DOMAINS, address, network, settings, generate};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") {
    fetch("/solar_inverter_bridge/collector-domains.json?v=0.10.0").then(response => {
      if (!response.ok) throw new Error("Domain catalogue unavailable");
      return response.json();
    }).then(catalogue => {
      KNOWN_DOMAINS.push(...catalogue);
      window.SIBRouterGuide = api;
      init();
    }).catch(() => {
      const error = document.querySelector("#form-error");
      error.textContent = "The domain list could not be loaded. Reload this page to generate commands.";
      error.hidden = false;
    });
  }
})();
