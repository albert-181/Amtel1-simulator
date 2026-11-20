#!/usr/bin/env python3
"""
Art-Net test sender for the Amstel 1 ALF Simulator.

Sends ArtDMX to the bridge so you can check the patch without a console.

    python artnet_test_sender.py walk          # one fixture at a time in address order
    python artnet_test_sender.py chase         # colour chase over all fixtures
    python artnet_test_sender.py full --rgbw 0 0 255 0
    python artnet_test_sender.py walk --ip 2.255.255.255 --universe 0

Assumes the F12 4 ch mode R G B W, start address 1, 102 fixtures (408 ch).
"""
import argparse, colorsys, socket, struct, time


def artdmx(universe, data, seq):
    data = bytes(data) + (b"\x00" if len(data) % 2 else b"")
    return (b"Art-Net\x00" + struct.pack("<H", 0x5000) + struct.pack(">H", 14)
            + bytes([seq, 0, universe & 0xFF, (universe >> 8) & 0x7F]) + struct.pack(">H", len(data)) + data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["walk", "chase", "full", "off"])
    ap.add_argument("--ip", default="127.0.0.1", help="destination (127.0.0.1, a node IP or a broadcast address)")
    ap.add_argument("--universe", type=int, default=0)
    ap.add_argument("--fixtures", type=int, default=102)
    ap.add_argument("--start", type=int, default=1, help="start address")
    ap.add_argument("--rate", type=float, default=4, help="walk steps per second")
    ap.add_argument("--rgbw", type=int, nargs=4, default=[255, 255, 255, 255])
    a = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    seq, t0 = 1, time.time()
    print("sending %s to %s:6454 universe %d, Ctrl+C to stop" % (a.mode, a.ip, a.universe))
    try:
        while True:
            t = time.time() - t0
            dmx = bytearray(512)
            for i in range(a.fixtures):
                base = a.start - 1 + i * 4
                if base + 4 > 512:
                    break
                if a.mode == "walk":
                    on = int(t * a.rate) % a.fixtures == i
                    val = [0, 0, 0, 255] if on else [0, 0, 0, 0]
                elif a.mode == "chase":
                    r, g, b = colorsys.hsv_to_rgb((i / 51.0 - t * 0.1) % 1.0, 1, 1)
                    val = [int(r * 255), int(g * 255), int(b * 255), 0]
                elif a.mode == "full":
                    val = a.rgbw
                else:
                    val = [0, 0, 0, 0]
                dmx[base:base + 4] = bytes(val)
            s.sendto(artdmx(a.universe, dmx, seq), (a.ip, 6454))
            seq = seq % 255 + 1
            time.sleep(1 / 40)
    except KeyboardInterrupt:
        s.sendto(artdmx(a.universe, bytearray(512), seq), (a.ip, 6454))
        print("\nstopped, sent blackout")


if __name__ == "__main__":
    main()
