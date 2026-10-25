#!/usr/bin/env python3
"""
End to end test van de Growatt meter emulator.

  gesimuleerde Fluvius meter --P1--> dongle firmware --UDP--> emulator firmware --RS485--> "Growatt"

Beide firmwares zijn de echte ESPHome builds voor het Linux host platform. Python speelt
de digitale meter (P1 telegrammen met geldige CRC) en de Growatt omvormer (Modbus RTU
master aan 9600 baud, zoals op de SYS COM poort).

Gebruik:  python run_growatt_test.py [--esphome /pad/naar/esphome] [--no-compile]
"""
import argparse
import os
import pty
import re
import select
import shutil
import statistics
import struct
import subprocess
import sys
import time
import tty
from pathlib import Path

HIER = Path(__file__).resolve().parent
REPO = HIER.parent
BUILD = HIER / "build"
P1_PORT = "/tmp/p1-sim-link"
RS485_PORT = "/tmp/rs485-sim"
BIN_LINK = HIER / ".esphome/.esphome/build/link-host/.pioenvs/homey-p1/program"
BIN_EMU = HIER / ".esphome/.esphome/build/emulator-host/.pioenvs/growatt-meter/program"
ADRES = 2  # SDM630 v2, zoals Growatt verwacht


# ------------------------------------------------------------------ helpers --

def crc16_dsmr(data: bytes) -> int:
    """CRC16/ARC (start 0) zoals in het P1 telegram."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc16(data: bytes) -> int:
    """CRC16/MODBUS (start 0xFFFF) voor de RS485 frames."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def telegram(v: dict, fasen=3) -> bytes:
    """Fluvius telegram (e-MUCS) met afzonderlijke waarden per fase."""
    r = [
        "/FLU5\\253769484_A", "",
        "0-0:96.1.4(50217)",
        "0-0:96.1.1(3153414731313030303037313930)",
        "0-0:1.0.0(261025090000W)",
        f"1-0:1.8.1({v['a_dag']:010.3f}*kWh)",
        f"1-0:1.8.2({v['a_nacht']:010.3f}*kWh)",
        f"1-0:2.8.1({v['i_dag']:010.3f}*kWh)",
        f"1-0:2.8.2({v['i_nacht']:010.3f}*kWh)",
        "0-0:96.14.0(0001)",
        "1-0:1.4.0(02.351*kW)",
        f"1-0:1.7.0({sum(max(p, 0) for p in v['p']):06.3f}*kW)",
        f"1-0:2.7.0({sum(max(-p, 0) for p in v['p']):06.3f}*kW)",
    ]
    for k in range(fasen):
        p = v["p"][k]
        r.append(f"1-0:{21 + 20 * k}.7.0({max(p, 0):06.3f}*kW)")
        r.append(f"1-0:{22 + 20 * k}.7.0({max(-p, 0):06.3f}*kW)")
    for k in range(fasen):
        r.append(f"1-0:{32 + 20 * k}.7.0({v['u'][k]:05.1f}*V)")
    for k in range(fasen):
        r.append(f"1-0:{31 + 20 * k}.7.0({v['i'][k]:06.2f}*A)")
    r += ["0-0:96.3.10(1)", "0-0:17.0.0(999.9*kW)", "1-0:31.4.0(999*A)", "0-0:96.13.0()"]
    body = ("\r\n".join(r) + "\r\n!").encode()
    return body + f"{crc16_dsmr(body):04X}\r\n".encode()


def waarden(k=0, fasen=3):
    # L1 afname, L2 injectie, L3 kleine afname: elke fase verschillend om verwisselingen te vangen
    p = [round(1.234 + k * 0.010, 3), -0.567, 0.200][:fasen] + [0.0] * (3 - fasen)
    return dict(
        a_dag=12345.678 + k * 0.001, a_nacht=23456.789, i_dag=3456.789, i_nacht=1234.567,
        p=p, u=[230.1, 229.8, 231.0], i=[5.40, 2.50, 0.90],
    )


def verwacht(v, fasen=3):
    u = v["u"][:fasen] + [0.0] * (3 - fasen)
    i = v["i"][:fasen] + [0.0] * (3 - fasen)
    p = [x * 1000 for x in v["p"]]
    imp = v["a_dag"] + v["a_nacht"]
    exp = v["i_dag"] + v["i_nacht"]
    va = [u[k] * i[k] for k in range(3)]
    pf = lambda pp, s: 1.0 if s < 1 else max(-1.0, min(1.0, pp / s))  # noqa: E731
    return {
        0x00: u[0], 0x02: u[1], 0x04: u[2],
        0x06: i[0], 0x08: i[1], 0x0A: i[2],
        0x0C: p[0], 0x0E: p[1], 0x10: p[2],
        0x12: va[0], 0x14: va[1], 0x16: va[2],
        0x1E: pf(p[0], va[0]), 0x20: pf(p[1], va[1]), 0x22: pf(p[2], va[2]),
        0x2A: sum(u) / fasen, 0x2E: sum(i) / fasen, 0x30: sum(i),
        0x34: sum(p), 0x38: sum(va), 0x3E: pf(sum(p), sum(va)),
        0x46: 50.0, 0x48: imp, 0x4A: exp, 0x156: imp + exp,
    }


class Bus:
    """Growatt als Modbus RTU master op de virtuele RS485 lijn."""

    def __init__(self, fd):
        self.fd = fd

    def lees(self, start, aantal, fc=4, adres=ADRES, timeout=0.5):
        req = bytes([adres, fc]) + struct.pack(">HH", start, aantal)
        req += struct.pack("<H", crc16(req))
        while select.select([self.fd], [], [], 0)[0]:
            os.read(self.fd, 4096)  # oude rommel weg
        os.write(self.fd, req)
        buf, t_end = b"", time.perf_counter() + timeout
        while time.perf_counter() < t_end:
            if select.select([self.fd], [], [], 0.01)[0]:
                buf += os.read(self.fd, 4096)
                if len(buf) >= 5 and buf[1] & 0x80:
                    return ("fout", buf[2]) if crc16(buf[:5]) == 0 else ("crc", None)
                if len(buf) >= 3 and len(buf) >= 5 + buf[2]:
                    n = 5 + buf[2]
                    if crc16(buf[:n]) != 0:
                        return ("crc", None)
                    return ("ok", struct.unpack(f">{buf[2] // 2}H", buf[3:3 + buf[2]]))
        return ("geen", None)

    def floats(self, start, aantal, **kw):
        st, regs = self.lees(start, aantal, **kw)
        if st != "ok":
            return st, regs
        out = {}
        for k in range(0, len(regs) - 1, 2):
            out[start + k] = struct.unpack(">f", struct.pack(">HH", regs[k], regs[k + 1]))[0]
        return "ok", out


class Res:
    def __init__(self):
        self.rijen = []

    def check(self, naam, ok, detail=""):
        self.rijen.append(ok)
        print(f"  {'OK  ' if ok else 'FOUT'}  {naam}  {detail}")


def vergelijk(res, label, gekregen, doel):
    fouten = [f"0x{a:04X}: {gekregen.get(a)} i.p.v. {round(w, 3)}" for a, w in doel.items()
              if a not in gekregen or abs(gekregen[a] - w) > 0.002 * max(1.0, abs(w))]
    res.check(label, not fouten, f"{len(doel) - len(fouten)}/{len(doel)} registers juist"
              + ("" if not fouten else "; " + "; ".join(fouten[:4])))


def pty_link(pad):
    m, s = pty.openpty()
    tty.setraw(s)
    tty.setraw(m)
    if os.path.lexists(pad):
        os.remove(pad)
    os.symlink(os.ttyname(s), pad)
    return m


LAATSTE_TELEGRAM = [0.0]


def stuur(fd, data):
    """Aan echte P1 snelheid (115200 baud), geeft het tijdstip van de laatste byte."""
    t0 = time.perf_counter()
    for k in range(0, len(data), 64):
        if k:
            time.sleep(max(0, t0 + k / 11520 - time.perf_counter()))
        os.write(fd, data[k:k + 64])
    LAATSTE_TELEGRAM[0] = time.perf_counter()  # direct na de laatste byte
    return LAATSTE_TELEGRAM[0]


# --------------------------------------------------------------------- test --

def test(p1, bus: Bus, res: Res, start_link):
    print("\n[1] Opstart: nog geen telegram ontvangen")
    st, code = bus.lees(0x0C, 2)
    res.check("Foutmelding zolang er geen data is", st == "fout" and code == 4,
              f"{st}, code {code} (4 = SERVICE_DEVICE_FAILURE)")

    print("\n[2] Telegram 3 fasen, uitlezen zoals Growatt (blok 0x00 tot 0x4F)")
    v = waarden(0)
    stuur(p1, telegram(v))
    time.sleep(0.3)
    st, regs = bus.floats(0x00, 0x4C)
    st2, regs2 = bus.floats(0x156, 2)
    if st == "ok" and st2 == "ok":
        regs.update(regs2)
        vergelijk(res, "Alle 25 SDM630 registers", regs, verwacht(v))
        res.check("Injectie op L2 is negatief", regs[0x0E] < 0, f"{regs[0x0E]:.0f} W")
        res.check("Lege registers geven 0 (bv. 30025 VAr L1)", regs.get(0x18) == 0.0, str(regs.get(0x18)))
    else:
        res.check("Alle 25 SDM630 registers", False, f"{st} {st2}")
    st, r3 = bus.floats(0x34, 2, fc=3)
    res.check("Ook antwoord op functiecode 03", st == "ok" and abs(r3[0x34] - verwacht(v)[0x34]) < 1,
              f"{st} {r3 if st == 'ok' else ''}")
    st, _ = bus.lees(0x0C, 2, adres=1)
    res.check("Geen antwoord op ander slave adres", st == "geen", st)

    print("\n[3] Vertraging: laatste P1 byte tot nieuwe waarde op de RS485 bus (10 telegrammen)")
    lat = []
    for k in range(1, 11):
        v = waarden(k)
        doel = v["p"][0] * 1000
        t_laatste = stuur(p1, telegram(v))
        while time.perf_counter() - t_laatste < 1.0:
            st, r = bus.floats(0x0C, 2, timeout=0.2)
            if st == "ok" and abs(r[0x0C] - doel) < 0.5:
                lat.append((time.perf_counter() - t_laatste) * 1000)
                break
        time.sleep(max(0, t_laatste + 1.0 - time.perf_counter()))
    res.check("Elk telegram komt door", len(lat) == 10, f"{len(lat)}/10")
    if lat:
        res.check("Vertraging inclusief Modbus antwoord", max(lat) < 150,
                  f"gem {statistics.mean(lat):.0f} ms, max {max(lat):.0f} ms")

    print("\n[4] Growatt vraagt 10 keer per seconde, 10 s lang (telegram 1 per seconde)")
    goed = fout = 0
    t_eind, volgende_tel, k = time.perf_counter() + 10, 0.0, 20
    while time.perf_counter() < t_eind:
        if time.perf_counter() >= volgende_tel:
            stuur(p1, telegram(waarden(k)))
            k += 1
            volgende_tel = time.perf_counter() + 1.0
        st, _ = bus.floats(0x00, 0x12, timeout=0.2)
        goed += st == "ok"
        fout += st != "ok"
        time.sleep(0.1)
    res.check("Elke vraag correct beantwoord", fout == 0, f"{goed} goed, {fout} fout")

    print("\n[5] Failsafe: P1 telegrammen stoppen, dongle blijft draaien en zendt om de 5 s alles opnieuw")
    t_stop = LAATSTE_TELEGRAM[0]  # gemeten vanaf het laatste telegram
    t_fail = None
    while time.perf_counter() - t_stop < 12:
        st, code = bus.lees(0x0C, 2, timeout=0.2)
        if st == "fout":
            t_fail = time.perf_counter() - t_stop
            break
        time.sleep(0.1)
    res.check("Foutmelding 5 s na het laatste telegram", t_fail is not None and 4.8 < t_fail < 5.8,
              f"na {t_fail:.2f} s" if t_fail else "nooit")
    time.sleep(6)  # over een herhaling van de dongle heen
    st, code = bus.lees(0x0C, 2)
    res.check("Blijft in failsafe ondanks herhaalde pakketten", st == "fout", st)

    print("\n[6] Herstel na nieuw telegram")
    v = waarden(50)
    t_laatste = stuur(p1, telegram(v))
    time.sleep(0.2)
    st, r = bus.floats(0x0C, 2)
    res.check("Meteen terug juiste waarde", st == "ok" and abs(r[0x0C] - v["p"][0] * 1000) < 0.5,
              f"{st} {r.get(0x0C) if st == 'ok' else ''}")

    print("\n[7] Monofasige meter (enkel L1 in het telegram)")
    # Nieuwe dongle start zodat L2 en L3 van vorige telegrammen niet blijven hangen
    link = start_link(herstart=True)
    time.sleep(1.5)
    v = waarden(60, fasen=1)
    stuur(p1, telegram(v, fasen=1))
    time.sleep(0.3)
    st, regs = bus.floats(0x00, 0x4C)
    st2, regs2 = bus.floats(0x156, 2)
    if st == "ok" and st2 == "ok":
        regs.update(regs2)
        vergelijk(res, "Registers bij 1 fase (L2, L3 = 0, gemiddelde = L1)", regs, verwacht(v, fasen=1))
    else:
        res.check("Registers bij 1 fase", False, f"{st} {st2}")

    print("\n[8] Failsafe: dongle valt volledig uit")
    link.kill()
    link.wait()
    t_stop = LAATSTE_TELEGRAM[0]
    t_fail = None
    while time.perf_counter() - t_stop < 10:
        st, _ = bus.lees(0x0C, 2, timeout=0.2)
        if st == "fout":
            t_fail = time.perf_counter() - t_stop
            break
        time.sleep(0.1)
    res.check("Foutmelding 5 s na het laatste telegram", t_fail is not None and 4.8 < t_fail < 5.8,
              f"na {t_fail:.2f} s" if t_fail else "nooit")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--esphome", default=shutil.which("esphome") or "esphome")
    ap.add_argument("--no-compile", action="store_true")
    args = ap.parse_args()

    BUILD.mkdir(exist_ok=True)
    t = (REPO / "homey-p1-be.yaml").read_text()
    t, n = re.subn(r"\n    timestamp:\n(      .*\n)+", "\n", t)
    assert n == 1
    (BUILD / "productie-host.yaml").write_text(t)
    (BUILD / "link-host.yaml").write_text((REPO / "homey-p1-be-growatt-link.yaml").read_text()
                                          .replace("!include homey-p1-be.yaml", "!include productie-host.yaml"))
    for d in (HIER, BUILD):
        shutil.copy(REPO / "secrets.yaml", d / "secrets.yaml")

    if not args.no_compile:
        for f in ("host-link.yaml", "host-emulator.yaml"):
            print(f"Compileren {f} ...")
            r = subprocess.run([args.esphome, "compile", str(HIER / f)], capture_output=True, text=True)
            if r.returncode:
                print(r.stdout[-3000:], r.stderr[-2000:])
                raise SystemExit("Compileren mislukt")

    p1 = pty_link(P1_PORT)
    rs = pty_link(RS485_PORT)
    procs = {}

    def start_link(herstart=False):
        if herstart and procs.get("link"):
            procs["link"].kill()
            procs["link"].wait()
        procs["link"] = subprocess.Popen([str(BIN_LINK)], stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True)
        return procs["link"]

    procs["emu"] = subprocess.Popen([str(BIN_EMU)], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
    start_link()
    time.sleep(2)
    res = Res()
    try:
        test(p1, Bus(rs), res, start_link)
    finally:
        uit = {}
        for k, p in procs.items():
            if p.poll() is None:
                p.terminate()
            try:
                uit[k] = p.communicate(timeout=5)[0]
            except Exception:
                p.kill()
                uit[k] = p.communicate()[0]
        for pad in (P1_PORT, RS485_PORT):
            if os.path.lexists(pad):
                os.remove(pad)

    andere = [l for l in uit.get("emu", "").splitlines() if "[E]" in l]
    res.check("Geen onverwachte fouten in de log van de emulator", not andere, f"{len(andere)} fout(en)")
    for l in andere[:5]:
        print("    ", l)
    print(f"\nResultaat: {sum(res.rijen)}/{len(res.rijen)} geslaagd")
    sys.exit(0 if all(res.rijen) else 1)


if __name__ == "__main__":
    main()
