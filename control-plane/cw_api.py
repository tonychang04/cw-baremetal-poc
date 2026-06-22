#!/usr/bin/env python3
"""Cloneable Worlds PoC control plane: spawn / clone / exec / kill Firecracker microVMs."""
import json, subprocess, threading, time, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CW = "/opt/cw"
GUEST_KEY = f"{CW}/base/guest_key"
STATE = {}            # id -> {n, ip, tap, status, cold_boot, clone_s}
LOCK = threading.Lock()
NEXT_N = [20]         # subnet index allocator (172.16.<n>.0/24); 10-11 used by manual forks

def sh(cmd, timeout=120):
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr

def grab(pat, text):
    m = re.search(pat, text)
    return m.group(1) if m else None

def spawn(from_clone=True):
    with LOCK:
        n = NEXT_N[0]; NEXT_N[0] += 1
    fid = f"m{n}"
    ip = f"172.16.{n}.2"
    rc, out, err = sh(f"bash {CW}/clone.sh {fid} {n}")
    rec = {"id": fid, "n": n, "ip": ip, "tap": f"tap{n}", "status": "running" if rc == 0 else "failed",
           "pid": grab(r"FCPID=(\d+)", out),
           "clone_s": grab(r"CLONE_SECONDS=([\d.]+)", out),
           "cold_boot_s": grab(r"COLD_BOOT_SECONDS=([\d.]+)", out),
           "log": (out + err)[-600:]}
    with LOCK:
        STATE[fid] = rec
    return rec

def gexec(ip, command):
    c = (f"ssh -i {GUEST_KEY} -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
         f"-o ConnectTimeout=5 root@{ip} {json.dumps(command)}")
    rc, out, err = sh(c, timeout=30)
    return {"rc": rc, "out": out, "err": err}

def kill(fid):
    rec = STATE.get(fid)
    if not rec: return False
    pid = rec.get("pid")
    cmds = []
    if pid:
        cmds.append(f"sudo kill {pid} 2>/dev/null")          # exact firecracker pid, no pkill -f self-match
    else:
        cmds.append(f"sudo fuser -k {CW}/run/{fid}.sock 2>/dev/null || true")
    cmds.append("sleep 1")                                    # let firecracker release the rootfs
    cmds.append(f"sudo ip link del {rec['tap']} 2>/dev/null || true")
    cmds.append(f"sudo zfs destroy -r cwpool/{fid} 2>/dev/null || true")
    sh("; ".join(cmds), timeout=30)
    with LOCK:
        rec["status"] = "killed"
    return True

TOKEN = os.environ.get("CW_TOKEN", "")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-CW-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _auth(self):
        # token required only for /api/* (the static page is open)
        if TOKEN and self.path.startswith("/api") and self.headers.get("X-CW-Token") != TOKEN:
            self._send(403, '{"error":"forbidden"}'); return False
        return True

    def do_OPTIONS(self):
        self._send(204, "")

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            return self._send(200, PAGE, "text/html")
        if not self._auth(): return
        if self.path == "/api/machines":
            return self._send(200, json.dumps(list(STATE.values())))
        self._send(404, "{}")

    def do_POST(self):
        if not self._auth(): return
        ln = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(ln) or "{}") if ln else {}
        if self.path == "/api/machines":
            return self._send(200, json.dumps(spawn()))
        m = re.match(r"/api/machines/([^/]+)/clone", self.path)
        if m:   # clone == spawn another CoW fork from golden
            return self._send(200, json.dumps(spawn()))
        m = re.match(r"/api/machines/([^/]+)/exec", self.path)
        if m:
            rec = STATE.get(m.group(1))
            if not rec: return self._send(404, "{}")
            return self._send(200, json.dumps(gexec(rec["ip"], body.get("cmd", "uname -a; hostname"))))
        self._send(404, "{}")

    def do_DELETE(self):
        if not self._auth(): return
        m = re.match(r"/api/machines/([^/]+)", self.path)
        if m and kill(m.group(1)):
            return self._send(200, '{"ok":true}')
        self._send(404, "{}")

PAGE = """<!doctype html><meta charset=utf-8><title>Cloneable Worlds — microVM PoC</title>
<style>
 body{font:14px/1.5 ui-monospace,Menlo,monospace;background:#0b0d12;color:#d7dbe3;margin:0;padding:28px;max-width:980px}
 h1{font-size:18px;color:#fff;font-weight:600;letter-spacing:.3px}
 .sub{color:#7d8694;margin:-8px 0 20px}
 button{background:#1b2330;color:#cfe3ff;border:1px solid #2b3a4f;border-radius:7px;padding:7px 13px;cursor:pointer;font:inherit}
 button:hover{background:#243044}
 button.k{color:#ffb4b4;border-color:#4f2b2b}
 table{border-collapse:collapse;width:100%;margin-top:18px}
 th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #1c2330;font-size:13px}
 th{color:#7d8694;font-weight:500}
 .pill{padding:2px 8px;border-radius:20px;font-size:12px}
 .running{background:#13311f;color:#76e0a0}.killed{background:#332;color:#caa}.failed{background:#3a1c1c;color:#ff9b9b}
 .ms{color:#8fd0ff} input{background:#10151e;border:1px solid #28313f;color:#d7dbe3;border-radius:6px;padding:6px;font:inherit;width:260px}
 pre{background:#10151e;border:1px solid #1c2330;border-radius:8px;padding:12px;white-space:pre-wrap;max-height:220px;overflow:auto}
</style>
<h1>Cloneable Worlds — Firecracker microVM PoC</h1>
<div class=sub>a1.metal · aarch64 · ZFS copy-on-write forks · live on bare metal</div>
<button onclick=spawn()>+ Spawn microVM (CoW fork)</button>
<span id=stat style=color:#7d8694;margin-left:12px></span>
<table id=t><thead><tr><th>id<th>guest ip<th>status<th>cold boot<th>clone (CoW)<th>actions</tr></thead><tbody></tbody></table>
<h3 style=margin-top:26px;font-size:14px>exec in guest</h3>
<input id=cmd value="hostname; uname -m; cat /proc/uptime"> <button onclick=ex()>run on last machine</button>
<pre id=out>—</pre>
<script>
let last=null;
function cwkey(){let k=localStorage.getItem('cwkey');if(!k){k=prompt('Enter access key:')||'';if(k)localStorage.setItem('cwkey',k);}return k;}
async function F(path,opts){opts=opts||{};opts.headers=Object.assign({'X-CW-Token':cwkey()},opts.headers||{});
 let r=await fetch(path,opts);
 if(r.status===403){localStorage.removeItem('cwkey');alert('access key rejected — reload the page to re-enter it.');}
 return r;}
async function load(){let r=await F('/api/machines');if(!r.ok)return;let d=await r.json();
 let b=d.map(m=>`<tr><td>${m.id}<td>${m.ip}<td><span class="pill ${m.status}">${m.status}</span>
 <td class=ms>${m.cold_boot_s?(+m.cold_boot_s).toFixed(3)+'s':'—'}<td class=ms>${m.clone_s?(+m.clone_s*1000).toFixed(1)+'ms':'—'}
 <td><button onclick="clone('${m.id}')">clone</button> <button class=k onclick="kill('${m.id}')">kill</button></tr>`).join('');
 document.querySelector('#t tbody').innerHTML=b; if(d.length)last=d[d.length-1].id;}
async function spawn(){stat.textContent='spawning…';await F('/api/machines',{method:'POST'});stat.textContent='';load();}
async function clone(id){stat.textContent='cloning…';await F('/api/machines/'+id+'/clone',{method:'POST'});stat.textContent='';load();}
async function kill(id){await F('/api/machines/'+id,{method:'DELETE'});load();}
async function ex(){out.textContent='…';let r=await F('/api/machines/'+last+'/exec',{method:'POST',body:JSON.stringify({cmd:cmd.value})});
 if(!r.ok){out.textContent='unauthorized';return}let d=await r.json();out.textContent=(d.out||'')+(d.err||'');}
load();setInterval(load,3000);
</script>"""

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), H).serve_forever()
