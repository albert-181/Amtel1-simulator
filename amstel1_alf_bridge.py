#!/usr/bin/env python3
"""
Amstel 1 ALF Simulator - Art-Net / sACN bridge

Listens for Art-Net (UDP 6454) and sACN / E1.31 (UDP 5568), serves the simulator
web page and pushes every DMX universe to it over a WebSocket.

Python 3.8+ and the standard library only. No pip install needed.

    python amstel1_alf_bridge.py                 # then open http://localhost:8080
    python amstel1_alf_bridge.py --open          # also opens the browser
    python amstel1_alf_bridge.py --artnet-ip 127.0.0.1 --http-port 8090

Universe numbering: Art-Net port-address as sent (0 = first universe).
sACN universe N is shown as Art-Net universe N-1 (sACN 1 = Art-Net 0).
"""
import argparse, asyncio, base64, hashlib, json, mimetypes, os, socket, struct, sys, time, webbrowser

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
ART_HEADER = b"Art-Net\x00"
OP_POLL, OP_POLLREPLY, OP_DMX = 0x2000, 0x2100, 0x5000
SACN_ID = b"ASC-E1.17\x00\x00\x00"

clients = set()                 # websocket writers
latest = {}                     # universe -> bytes(512)
dirty = set()
stats = {"artnet": 0, "sacn": 0}
listen_info = []


# ---------------------------------------------------------------- DMX input
def store(universe, data):
    buf = bytearray(512)
    buf[:len(data)] = data[:512]
    latest[universe] = bytes(buf)
    dirty.add(universe)


def local_ip_for(peer_ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((peer_ip, 6454))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def poll_reply(ip, name="Amstel1 ALF Sim"):
    """Basic ArtPollReply so consoles can discover the simulator (1 output port)."""
    p = bytearray(239)
    p[0:8] = ART_HEADER
    struct.pack_into("<H", p, 8, OP_POLLREPLY)
    p[10:14] = socket.inet_aton(ip)
    struct.pack_into("<H", p, 14, 6454)
    struct.pack_into(">H", p, 16, 1)            # firmware version
    p[18] = 0                                     # NetSwitch
    p[19] = 0                                     # SubSwitch
    p[23] = 0xD0                                  # Status1: indicators normal, port-address by network
    p[26:26 + 18] = name.encode()[:17].ljust(18, b"\x00")
    p[44:44 + 64] = b"Amstel 1 ALF Simulator bridge".ljust(64, b"\x00")
    p[108:108 + 64] = b"#0001 [0000] Simulator ready".ljust(64, b"\x00")
    struct.pack_into(">H", p, 172, 1)             # NumPorts
    p[174] = 0x80                                 # PortTypes[0]: output from Art-Net, DMX512
    p[182] = 0x80                                 # GoodOutput[0]: data being transmitted
    p[190] = 0                                    # SwOut[0]
    p[200] = 0x00                                 # Style: StNode
    p[207:211] = socket.inet_aton(ip)             # BindIp
    p[211] = 1                                    # BindIndex
    p[212] = 0x08                                 # Status2: supports 15-bit port-address
    return bytes(p)


class ArtNet(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.t = transport

    def datagram_received(self, d, addr):
        if len(d) < 12 or d[:8] != ART_HEADER:
            return
        op = struct.unpack_from("<H", d, 8)[0]
        if op == OP_DMX and len(d) >= 18:
            sub, net = d[14], d[15]
            length = struct.unpack_from(">H", d, 16)[0]
            store(((net & 0x7F) << 8) | sub, d[18:18 + length])
            stats["artnet"] += 1
        elif op == OP_POLL:
            try:
                self.t.sendto(poll_reply(local_ip_for(addr[0])), (addr[0], 6454))
            except OSError:
                pass


class SACN(asyncio.DatagramProtocol):
    def datagram_received(self, d, addr):
        if len(d) < 126 or d[4:16] != SACN_ID:
            return
        if struct.unpack_from(">I", d, 18)[0] != 0x00000004:      # root vector: E1.31 data
            return
        if struct.unpack_from(">I", d, 40)[0] != 0x00000002:      # framing vector: data packet
            return
        if d[125] != 0:                                             # start code must be 0 (dimmer data)
            return
        universe = struct.unpack_from(">H", d, 113)[0]
        count = struct.unpack_from(">H", d, 123)[0] - 1
        store(max(0, universe - 1), d[126:126 + count])
        stats["sacn"] += 1


def udp_socket(ip, port, multicast_unis=()):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind((ip, port))
    for u in multicast_unis:
        group = socket.inet_aton("239.255.%d.%d" % (u >> 8, u & 0xFF))
        iface = socket.inet_aton(ip if ip != "0.0.0.0" else "0.0.0.0")
        try:
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, group + iface)
        except OSError:
            pass
    s.setblocking(False)
    return s


# ---------------------------------------------------------------- WebSocket + HTTP
def ws_frame(payload, opcode=0x2):
    n = len(payload)
    if n < 126:
        head = struct.pack("!BB", 0x80 | opcode, n)
    elif n < 65536:
        head = struct.pack("!BBH", 0x80 | opcode, 126, n)
    else:
        head = struct.pack("!BBQ", 0x80 | opcode, 127, n)
    return head + payload


async def ws_session(reader, writer):
    clients.add(writer)
    writer.write(ws_frame(json.dumps({"type": "hello", "listen": listen_info}).encode(), 0x1))
    for uni, data in latest.items():
        writer.write(ws_frame(struct.pack(">H", uni) + data))
    try:
        while True:
            h = await reader.readexactly(2)
            op, ln = h[0] & 0x0F, h[1] & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", await reader.readexactly(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", await reader.readexactly(8))[0]
            mask = await reader.readexactly(4) if h[1] & 0x80 else b""
            data = await reader.readexactly(ln)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if op == 0x8:
                break
            if op == 0x9:
                writer.write(ws_frame(data, 0xA))
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        clients.discard(writer)
        try:
            writer.close()
        except Exception:
            pass


async def http_handler(reader, writer):
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
    except Exception:
        writer.close()
        return
    lines = raw.decode("latin-1").split("\r\n")
    try:
        method, path, _ = lines[0].split(" ", 2)
    except ValueError:
        writer.close()
        return
    headers = {}
    for l in lines[1:]:
        if ":" in l:
            k, v = l.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    path = path.split("?", 1)[0].split("#", 1)[0]

    if path == "/ws" and headers.get("upgrade", "").lower() == "websocket":
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        writer.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
        await writer.drain()
        await ws_session(reader, writer)
        return

    rel = "index.html" if path in ("/", "") else path.lstrip("/")
    full = os.path.normpath(os.path.join(WEB_DIR, rel))
    if method != "GET" or not full.startswith(WEB_DIR) or not os.path.isfile(full):
        body, status, ctype = b"Not found", "404 Not Found", "text/plain"
    else:
        with open(full, "rb") as f:
            body = f.read()
        status, ctype = "200 OK", mimetypes.guess_type(full)[0] or "application/octet-stream"
    writer.write(("HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nCache-Control: no-store\r\n"
                  "Connection: close\r\n\r\n" % (status, ctype, len(body))).encode() + body)
    try:
        await writer.drain()
    finally:
        writer.close()


async def pump(fps):
    """Send the newest frame of every changed universe to every page, max `fps` per second."""
    last_log = time.time()
    while True:
        await asyncio.sleep(1.0 / fps)
        if dirty and clients:
            frames = [ws_frame(struct.pack(">H", u) + latest[u]) for u in list(dirty)]
            dirty.clear()
            for w in list(clients):
                try:
                    for fr in frames:
                        w.write(fr)
                except Exception:
                    clients.discard(w)
        if time.time() - last_log >= 5:
            last_log = time.time()
            if stats["artnet"] or stats["sacn"]:
                print("  rx last 5 s: Art-Net %d, sACN %d packets, universes %s, pages %d"
                      % (stats["artnet"], stats["sacn"], sorted(latest)[:8], len(clients)))
            stats["artnet"] = stats["sacn"] = 0


async def main():
    ap = argparse.ArgumentParser(description="Amstel 1 ALF Simulator bridge (Art-Net / sACN to browser)")
    ap.add_argument("--artnet-ip", default="0.0.0.0", help="interface IP to listen on for Art-Net (default all)")
    ap.add_argument("--artnet-port", type=int, default=6454)
    ap.add_argument("--no-sacn", action="store_true", help="do not listen for sACN / E1.31")
    ap.add_argument("--sacn-universes", default="1-4", help="sACN multicast universes to join, e.g. 1-4 or 1,2,7")
    ap.add_argument("--http-host", default="127.0.0.1", help="web server address (use 0.0.0.0 to allow other devices)")
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--fps", type=float, default=60, help="max update rate to the page")
    ap.add_argument("--open", action="store_true", help="open the simulator in the default browser")
    a = ap.parse_args()

    loop = asyncio.get_running_loop()
    try:
        s = udp_socket(a.artnet_ip, a.artnet_port)
        await loop.create_datagram_endpoint(ArtNet, sock=s)
        listen_info.append("Art-Net %s:%d" % (a.artnet_ip, a.artnet_port))
    except OSError as e:
        print("! Art-Net port %d is busy or not allowed (%s)." % (a.artnet_port, e))
        print("  Close other Art-Net receivers, or listen on one interface with --artnet-ip 127.0.0.1")
    if not a.no_sacn:
        unis = set()
        for part in a.sacn_universes.split(","):
            if "-" in part:
                lo, hi = part.split("-")
                unis.update(range(int(lo), int(hi) + 1))
            elif part.strip():
                unis.add(int(part))
        try:
            s = udp_socket("0.0.0.0", 5568, sorted(unis))
            await loop.create_datagram_endpoint(SACN, sock=s)
            listen_info.append("sACN :5568 (universes %s)" % a.sacn_universes)
        except OSError as e:
            print("! sACN port 5568 not available (%s), continuing with Art-Net only." % e)

    server = await asyncio.start_server(http_handler, a.http_host, a.http_port)
    url = "http://%s:%d" % ("localhost" if a.http_host in ("127.0.0.1", "0.0.0.0") else a.http_host, a.http_port)
    print("Amstel 1 ALF Simulator bridge")
    print("  listening: " + ("; ".join(listen_info) or "nothing"))
    print("  simulator: " + url)
    print("  Ctrl+C to stop")
    if a.open:
        webbrowser.open(url)
    async with server:
        await asyncio.gather(server.serve_forever(), pump(a.fps))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")
