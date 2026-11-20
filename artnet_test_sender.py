#!/usr/bin/env python3
"""
Art-Net test sender for the Amstel 1 ALF Simulator.

Sends ArtDMX to the bridge so you can check the setup and the patch without a console.
Patch (wiring diagram R1 / MADRIX ALF.msz): two lines of 51 F12, 4 ch each (R G B W),
left line on universe 1, right line on universe 2, start address 1.

    python artnet_test_sender.py chase         # colour chase along both lines
    python artnet_test_sender.py walk          # one fixture at a time per line, in address order
    python artnet_test_sender.py full --rgbw 0 0 255 0
    python artnet_test_sender.py off           # blackout
    python artnet_test_sender.py chase --ip 2.255.255.255 --left 0 --right 1
"""
import argparse, colorsys, socket, struct, time

FIXTURES_PER_LINE = 51


def artdmx(universe, data, seq):
    return (b"Art-Net\x00" + struct.pack("<H", 0x5000) + struct.pack(">H", 14)
            + bytes([seq, 0, universe & 0xFF, (universe >> 8) & 0x7F]) + struct.pack(">H", len(data)) + bytes(data))


def line_frame(mode, t, a, offset):
    dmx = bytearray(512)
    for i in range(FIXTURES_PER_LINE):
        base = a.start - 1 + i * 4                  # fixture i+1 starts at start + 4 * i
        if base + 4 > 512:
            break
        if mode == "walk":
            val = [0, 0, 0, 255] if int(t * a.rate) % FIXTURES_PER_LINE == i else [0, 0, 0, 0]
        elif mode == "chase":
            r, g, b = colorsys.hsv_to_rgb((i / FIXTURES_PER_LINE - t * 0.1 + offset) % 1.0, 1, 1)
            val = [int(r * 255), int(g * 255), int(b * 255), 0]
        elif mode == "full":
            val = a.rgbw
        else:
            val = [0, 0, 0, 0]
        dmx[base:base + 4] = bytes(val)
    return dmx


def main():
    ap = argparse.ArgumentParser(description="Art-Net test patterns for the Amstel 1 ALF Simulator")
    ap.add_argument("mode", choices=["walk", "chase", "full", "off"])
    ap.add_argument("--ip", default="127.0.0.1", help="destination (127.0.0.1, a node IP or a broadcast address)")
    ap.add_argument("--left", type=int, default=1, help="Art-Net universe of the left line (default 1)")
    ap.add_argument("--right", type=int, default=2, help="Art-Net universe of the right line (default 2)")
    ap.add_argument("--start", type=int, default=1, help="start address (default 1)")
    ap.add_argument("--rate", type=float, default=4, help="walk steps per second")
    ap.add_argument("--rgbw", type=int, nargs=4, default=[255, 255, 255, 255])
    a = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    seq, t0 = 1, time.time()
    print("sending %s to %s:6454, left universe %d, right universe %d, Ctrl+C to stop" % (a.mode, a.ip, a.left, a.right))
    try:
        while True:
            t = time.time() - t0
            s.sendto(artdmx(a.left, line_frame(a.mode, t, a, 0.0), seq), (a.ip, 6454))
            s.sendto(artdmx(a.right, line_frame(a.mode, t, a, 0.5), seq), (a.ip, 6454))
            seq = seq % 255 + 1
            time.sleep(1 / 40)
    except KeyboardInterrupt:
        for u in (a.left, a.right):
            s.sendto(artdmx(u, bytearray(512), seq), (a.ip, 6454))
        print("\nstopped, sent blackout")


if __name__ == "__main__":
    main()
