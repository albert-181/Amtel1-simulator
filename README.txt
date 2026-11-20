AMSTEL 1 ALF SIMULATOR
======================

What it is
  3D simulator of the glass street with 102 x Beam F12 Multi Color RGBW (25 deg),
  driven by Art-Net or sACN from your own console or media server on this computer.
  Light falloff uses the F12 LDT photometric files (R, G, B, W per optic).

Start
  1. Install Python 3.8 or newer (no extra packages needed).
  2. In this folder run:   python amstel1_alf_bridge.py --open
     (Windows: py amstel1_alf_bridge.py --open)
  3. The simulator opens at http://localhost:8080
  4. Send Art-Net to 127.0.0.1, universe 0 (or sACN universe 1).
     The status pill top left turns green when DMX arrives.

Patch (default, change it in the panel)
  Universe 0, 4 ch per fixture (R G B W), 102 fixtures = 408 ch.
  Right line first: address 1 at frame 1, then along the street.
  Left line continues after it (205 to 408).
  The DMX plan tab shows every address; "Copy patch as CSV" gives the list.
  The F12 channel order R G B W is assumed. Check it on a real fixture.

Test without a console
  python artnet_test_sender.py walk     (lights fixtures one by one in address order)
  python artnet_test_sender.py chase

If nothing arrives
  Port 6454 can only be shared if the other program allows it. If the console
  also listens on 6454, try: python amstel1_alf_bridge.py --artnet-ip 127.0.0.1
  or send to a loopback/second network adapter. sACN multicast universes 1-4 are
  joined by default (--sacn-universes 1-8 for more).

Files
  amstel1_alf_bridge.py   Art-Net/sACN listener, web server and WebSocket (stdlib only)
  artnet_test_sender.py   test patterns
  web/index.html          the simulator
  web/lib/                three.js r128 (MIT licence)

Dimensions of the street are estimates from the 1:200 floor plan and photos.
