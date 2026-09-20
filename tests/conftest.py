import hashlib, json, secrets, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import pytest

KEYS = ["a_total_act_energy","a_total_act_ret_energy","b_total_act_energy","b_total_act_ret_energy","c_total_act_energy","c_total_act_ret_energy"]

def h(s): return hashlib.sha256(s.encode()).hexdigest()

class FakeShelly:
    def __init__(self, password="secret", emdata=True, mac="AABBCCDDEEFF"):
        self.password, self.emdata, self.mac = password, emdata, mac
        self.busy = 0   # answer this many further requests with 429 Too Many Requests
        self.requests = []   # (path, authed)
        self.nonce = secrets.token_hex(8)
        # records: ts -> (a_act, a_ret, b_act, b_ret, c_act, c_ret)
        self.records = {}
        self.page_size = 3

    def check_auth(self, hdr, method, uri):
        if not self.password: return True
        if not hdr or not hdr.startswith("Digest "): return False
        f = {}
        for part in hdr[7:].split(","):
            k, _, v = part.strip().partition("=")
            f[k] = v.strip('"')
        if f.get("algorithm") != "SHA-256" or f.get("username") != "admin": return False
        if f.get("nonce") != self.nonce: return False   # unknown or expired nonce
        ha1 = h(f"admin:shellypro3em-test:{self.password}")
        ha2 = h(f"{method}:{f['uri']}")
        if f["uri"] != uri: return False
        exp = h(f"{ha1}:{f['nonce']}:{f['nc']}:{f['cnonce']}:{f['qop']}:{ha2}")
        return exp == f["response"]

def make_handler(fs):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        timeout = 1
        def log_message(self, *a): pass
        def do_GET(self):
            u = urlparse(self.path)
            authed = fs.check_auth(self.headers.get("Authorization"), "GET", self.path)
            fs.requests.append((u.path, authed))
            if not authed:
                self._send(401, b"", {"WWW-Authenticate": f'Digest qop="auth", realm="shellypro3em-test", nonce="{fs.nonce}", algorithm=SHA-256'})
                return
            if fs.busy > 0:
                fs.busy -= 1
                return self._send(429, b"Too many requests", {"Retry-After": "0"})
            if u.path == "/rpc/Shelly.GetDeviceInfo":
                return self._json({
                    "id": "shellypro3em-test", "mac": fs.mac, "model": "SPEM-003CEBEU", "gen": 2,
                    "fw_id": "20260710-101227/2.0.0-g87fbfa4", "ver": "2.0.0", "app": "Pro3EM",
                    "auth_en": bool(fs.password),
                })
            if u.path == "/rpc/EMData.GetData":
                if not fs.emdata: return self._send(404, b"No handler for EMData.GetData")
                q = parse_qs(u.query); ts = int(q["ts"][0])
                recs = sorted(t for t in fs.records if t >= ts)
                page, rest = recs[:fs.page_size], recs[fs.page_size:]
                data = [{"ts": t, "period": 60, "values": [list(fs.records[t])]} for t in page]
                out = {"keys": KEYS, "data": data}
                if rest: out["next_record_ts"] = rest[0]
                return self._json(out)
            self._send(404, b"nope")
        def _json(self, obj): self._send(200, json.dumps(obj).encode(), {"Content-Type": "application/json"})
        def _send(self, code, body, hdrs=None):
            self.send_response(code)
            for k, v in (hdrs or {}).items(): self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
    return H

def start_server(fs):
    ThreadingHTTPServer.daemon_threads = False
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(fs))
    fs.host = f"127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def fake_shelly(socket_enabled):
    fs = FakeShelly()
    srv = start_server(fs)
    yield fs
    srv.shutdown(); srv.server_close()


@pytest.fixture
def fake_shelly_factory(socket_enabled):
    """Start further simulated devices, e.g. one reachable under a new address."""
    servers = []

    def make(**kwargs):
        fs = FakeShelly(**kwargs)
        servers.append(start_server(fs))
        return fs

    yield make
    for srv in servers:
        srv.shutdown(); srv.server_close()
