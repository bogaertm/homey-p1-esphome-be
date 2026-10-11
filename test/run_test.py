#!/usr/bin/env python3
"""
Integratietest voor homey-p1-be.yaml.

Draait de echte ESPHome DSMR code op het Linux host platform, koppelt er een
gesimuleerde Fluvius meter aan via een virtuele seriele poort, en leest de
waarden uit via de native ESPHome API, net zoals Home Assistant dat doet.

Gebruik:  python run_test.py [--esphome /pad/naar/esphome] [--no-compile]
Vereist:  esphome, aioesphomeapi, libmbedtls-dev (Linux)
"""
import argparse
import asyncio
import os
import pty
import re
import shutil
import statistics
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

from aioesphomeapi import APIClient, SensorState, TextSensorState

HIER = Path(__file__).resolve().parent
REPO = HIER.parent
PROD = REPO / "homey-p1-be.yaml"
BUILD = HIER / "build"
PORT_LINK = "/tmp/p1-sim"
BINARY = HIER / ".esphome/build/homey-p1/.pioenvs/homey-p1/program"


# ---------------------------------------------------------------- telegram ---

def crc16(data: bytes) -> int:
    """CRC16/ARC zoals vereist door DSMR 5 en Fluvius e-MUCS."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def telegram(v: dict, gas=True, corrupt=False) -> bytes:
    """Bouwt een Fluvius telegram (e-MUCS formaat) met geldige CRC."""
    regels = [
        "/FLU5\\253769484_A",
        "",
        "0-0:96.1.4(50217)",
        "0-0:96.1.1(3153414731313030303037313930)",
        f"0-0:1.0.0({v['ts']}W)",
        f"1-0:1.8.1({v['a_dag']:010.3f}*kWh)",
        f"1-0:1.8.2({v['a_nacht']:010.3f}*kWh)",
        f"1-0:2.8.1({v['i_dag']:010.3f}*kWh)",
        f"1-0:2.8.2({v['i_nacht']:010.3f}*kWh)",
        f"0-0:96.14.0({v['tarief']})",
        f"1-0:1.4.0({v['kwartier']:06.3f}*kW)",
        f"1-0:1.6.0(261001084500S)({v['maandpiek']:06.3f}*kW)",
        "0-0:98.1.0(3)(1-0:1.6.0)(1-0:1.6.0)"
        "(260801000000S)(260712183000S)(03.456*kW)"
        "(260901000000S)(260815190000S)(04.321*kW)"
        "(261001000000S)(260918073000S)(02.987*kW)",
        f"1-0:1.7.0({v['p_af']:06.3f}*kW)",
        f"1-0:2.7.0({v['p_in']:06.3f}*kW)",
        f"1-0:21.7.0({v['p_af']/3:06.3f}*kW)",
        f"1-0:41.7.0({v['p_af']/3:06.3f}*kW)",
        f"1-0:61.7.0({v['p_af']/3:06.3f}*kW)",
        f"1-0:22.7.0({v['p_in']/3:06.3f}*kW)",
        f"1-0:42.7.0({v['p_in']/3:06.3f}*kW)",
        f"1-0:62.7.0({v['p_in']/3:06.3f}*kW)",
        "1-0:32.7.0(230.1*V)",
        "1-0:52.7.0(229.8*V)",
        "1-0:72.7.0(231.0*V)",
        f"1-0:31.7.0({v['i_l1']:06.2f}*A)",
        "1-0:51.7.0(001.71*A)",
        "1-0:71.7.0(001.73*A)",
        "0-0:96.3.10(1)",
        "0-0:17.0.0(999.9*kW)",
        "1-0:31.4.0(999*A)",
        "0-0:96.13.0()",
    ]
    if gas:
        regels += [
            "0-1:24.1.0(003)",
            "0-1:96.1.1(37464C4F32313139303333373333)",
            "0-1:24.4.0(1)",
            f"0-1:24.2.3({v['ts']}W)({v['gas']:09.3f}*m3)",
        ]
    body = ("\r\n".join(regels) + "\r\n!").encode()
    crc = crc16(body)
    if corrupt:
        crc ^= 0xFFFF
    return body + f"{crc:04X}\r\n".encode()


def waarden(i: int, injectie=False, nacht=False) -> dict:
    p_af = 0.0 if injectie else round(1.000 + i * 0.111, 3)
    p_in = round(2.400 + i * 0.010, 3) if injectie else 0.0
    return dict(
        ts=f"261011{14 + i // 3600:02d}{(i // 60) % 60:02d}{i % 60:02d}",
        a_dag=12345.678 + i * 0.001, a_nacht=23456.789,
        i_dag=3456.789 + (i * 0.001 if injectie else 0), i_nacht=1234.567,
        tarief="0002" if nacht else "0001",
        kwartier=2.351, maandpiek=4.012,
        p_af=p_af, p_in=p_in, i_l1=round(1.74 + i * 0.01, 2), gas=1234.567 + i * 0.001,
    )


# ------------------------------------------------------------------ helpers --

def maak_host_config():
    """Productieconfig zonder het timestamp tekstveld.

    glibc definieert een globale 'struct timestamp' (netinet/ip.h) die enkel op
    de Linux host botst met het DSMR veld 'timestamp'. Op de ESP32 speelt dit niet.
    """
    BUILD.mkdir(exist_ok=True)
    tekst = PROD.read_text()
    tekst, n = re.subn(r"\n    timestamp:\n(      .*\n)+", "\n", tekst)
    assert n == 1, "timestamp blok niet gevonden in productieconfig"
    (BUILD / "productie-host.yaml").write_text(tekst)
    for f in ("secrets.yaml",):
        bron = REPO / f
        if bron.exists():
            shutil.copy(bron, HIER / f)
            shutil.copy(bron, BUILD / f)


def api_key() -> str:
    for regel in (REPO / "secrets.yaml").read_text().splitlines():
        if regel.startswith("api_key:"):
            return regel.split(":", 1)[1].strip().strip('"')
    raise SystemExit("api_key niet gevonden in secrets.yaml")


class Resultaten:
    def __init__(self):
        self.rijen = []

    def check(self, naam, ok, detail=""):
        self.rijen.append((naam, ok, detail))
        print(f"  {'OK  ' if ok else 'FOUT'}  {naam}  {detail}")

    @property
    def geslaagd(self):
        return all(ok for _, ok, _ in self.rijen)


# --------------------------------------------------------------------- test --

async def test(master_fd: int, res: Resultaten):
    client = APIClient("127.0.0.1", 6053, None, noise_psk=api_key())
    for _ in range(50):
        try:
            await client.connect(login=True)
            break
        except Exception:
            await asyncio.sleep(0.2)
    else:
        raise SystemExit("Kan niet verbinden met de API")

    entiteiten, _ = await client.list_entities_services()
    naam_van = {e.key: e.name for e in entiteiten}
    res.check("API verbinding met encryptie", True, f"{len(entiteiten)} entiteiten")

    staat = {}           # naam -> laatste waarde
    log = []             # (tijd, naam, waarde)

    def on_state(s):
        if isinstance(s, (SensorState, TextSensorState)) and not getattr(s, "missing_state", False):
            n = naam_van.get(s.key)
            staat[n] = s.state
            log.append((time.perf_counter(), n, s.state))

    client.subscribe_states(on_state)
    await asyncio.sleep(1.0)

    async def stuur(data: bytes):
        os.write(master_fd, data)
        return time.perf_counter()

    async def stuur_baud(data: bytes):
        """Verstuurt zoals een echte P1 lijn: 115200 baud 8N1 = 11520 bytes/s."""
        t_begin = time.perf_counter()
        for k in range(0, len(data), 64):
            os.write(master_fd, data[k:k + 64])
            await asyncio.sleep(max(0, t_begin + (k + 64) / 11520 - time.perf_counter()))
        return t_begin

    def updates_na(t0, naam):
        return [(t, v) for t, n, v in log if t >= t0 and n == naam]

    # 1. Waardes en snelheid aan 1 Hz (echte meter) --------------------------
    print("\n[1] 10 telegrammen aan 1 Hz, zoals de Fluvius meter")
    latenties, t_start = [], time.perf_counter()
    for i in range(10):
        v = waarden(i)
        data = telegram(v)
        t_begin = await stuur_baud(data)
        t0 = time.perf_counter()  # laatste byte verzonden
        doel = round(v["p_af"] * 1000)
        for _ in range(100):
            await asyncio.sleep(0.002)
            hit = [t for t, val in updates_na(t0, "Netto vermogen") if round(val) == doel]
            if hit:
                latenties.append((hit[0] - t0) * 1000)
                break
        await asyncio.sleep(max(0, t_begin + 1.0 - time.perf_counter()))
    netto_updates = len(updates_na(t_start, "Netto vermogen"))
    res.check("Netto vermogen bij elk telegram", netto_updates == 10, f"{netto_updates}/10 updates")
    res.check("Vermogen afname bij elk telegram",
              len(updates_na(t_start, "Vermogen afname")) == 10,
              f"{len(updates_na(t_start, 'Vermogen afname'))}/10 updates")
    if latenties:
        res.check("Vertraging laatste byte tot Home Assistant", max(latenties) < 30,
                  f"gem {statistics.mean(latenties):.1f} ms, max {max(latenties):.1f} ms")
    else:
        res.check("Vertraging telegram tot Home Assistant", False, "geen updates ontvangen")

    v = waarden(9)
    verwacht = {
        "Afname dag": v["a_dag"], "Afname nacht": v["a_nacht"],
        "Injectie dag": v["i_dag"], "Injectie nacht": v["i_nacht"],
        "Vermogen afname": v["p_af"], "Vermogen injectie": 0.0,
        "Vermogen afname L1": round(v["p_af"] / 3, 3),
        "Spanning L1": 230.1, "Spanning L2": 229.8, "Spanning L3": 231.0,
        "Stroom L1": v["i_l1"], "Stroom L2": 1.71, "Stroom L3": 1.73,
        "Kwartiervermogen lopend": 2.351, "Maandpiek": 4.012,
        "Gemiddelde maandpiek 13 maanden": round((3.456 + 4.321 + 2.987) / 3, 3),
        "Gasverbruik": v["gas"],
        "Netto vermogen": round(v["p_af"] * 1000),
    }
    print("\n[2] Inhoud van de sensoren")
    for naam, doel in verwacht.items():
        echt = staat.get(naam)
        ok = echt is not None and abs(float(echt) - doel) < 0.0015 * max(1, abs(doel))
        res.check(naam, ok, f"verwacht {doel}, kreeg {echt}")
    for naam, doel in {"Actief tarief": "Dag", "P1 versie": "50217",
                       "Meter identificatie": "FLU5\\253769484_A"}.items():
        res.check(naam, staat.get(naam) == doel, f"verwacht {doel}, kreeg {staat.get(naam)}")

    # 3. Injectie en nachttarief ---------------------------------------------
    print("\n[3] Injectie (zonnepanelen) en nachttarief")
    v = waarden(20, injectie=True, nacht=True)
    t0 = await stuur(telegram(v))
    await asyncio.sleep(0.3)
    res.check("Netto vermogen negatief bij injectie",
              round(staat.get("Netto vermogen", 0)) == -round(v["p_in"] * 1000),
              f"{staat.get('Netto vermogen')} W")
    res.check("Actief tarief Nacht", staat.get("Actief tarief") == "Nacht", str(staat.get("Actief tarief")))

    # 4. Foute CRC moet genegeerd worden -------------------------------------
    print("\n[4] Telegram met foute CRC")
    await asyncio.sleep(0.8)
    t0 = await stuur(telegram(waarden(30), corrupt=True))
    await asyncio.sleep(0.5)
    res.check("Foute CRC genegeerd", not updates_na(t0, "Netto vermogen"),
              f"{len(updates_na(t0, 'Netto vermogen'))} updates")
    t0 = await stuur(telegram(waarden(31)))
    await asyncio.sleep(0.3)
    res.check("Volgend goed telegram terug verwerkt", bool(updates_na(t0, "Netto vermogen")))

    # 5. Telegram zonder gas --------------------------------------------------
    print("\n[5] Telegram zonder gasmeter")
    await asyncio.sleep(0.8)
    t0 = await stuur(telegram(waarden(40), gas=False))
    await asyncio.sleep(0.3)
    res.check("Elektriciteit verwerkt zonder gasblok", bool(updates_na(t0, "Vermogen afname")))

    # 6. Stresstest aan echte lijnsnelheid ------------------------------------
    print("\n[6] Stresstest: 40 telegrammen aan 4 Hz, verzonden aan 115200 baud (4x sneller dan de meter)")
    t_start = time.perf_counter()
    for i in range(40):
        t0 = await stuur_baud(telegram(waarden(100 + i)))
        await asyncio.sleep(max(0, t0 + 0.25 - time.perf_counter()))
    await asyncio.sleep(0.5)
    n = len(updates_na(t_start, "Netto vermogen"))
    res.check("Geen telegram verloren aan 4 Hz", n == 40, f"{n}/40 verwerkt")

    await client.disconnect()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--esphome", default=shutil.which("esphome") or "esphome")
    ap.add_argument("--no-compile", action="store_true")
    args = ap.parse_args()

    maak_host_config()
    if not args.no_compile:
        print("Compileren voor Linux host ...")
        r = subprocess.run([args.esphome, "compile", str(HIER / "host-test.yaml")],
                           capture_output=True, text=True)
        if r.returncode:
            print(r.stdout[-3000:], r.stderr[-3000:])
            raise SystemExit("Compileren mislukt")

    # Virtuele seriele poort
    master, slave = pty.openpty()
    tty.setraw(slave)
    if os.path.lexists(PORT_LINK):
        os.remove(PORT_LINK)
    os.symlink(os.ttyname(slave), PORT_LINK)

    proc = subprocess.Popen([str(BINARY)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    res = Resultaten()
    try:
        asyncio.run(test(master, res))
    finally:
        proc.terminate()
        uitvoer = proc.communicate(timeout=5)[0]
        os.remove(PORT_LINK)

    fouten = [l for l in uitvoer.splitlines() if "[E]" in l]
    crc_fout = [l for l in fouten if "CRC" in l or "Failed to parse" in l or "checksum" in l.lower()]
    andere = [l for l in fouten if l not in crc_fout]
    res.check("Geen onverwachte fouten in de device log", not andere,
              f"{len(crc_fout)} verwachte CRC fout(en), {len(andere)} andere")
    for l in andere[:5]:
        print("    ", l)

    totaal = len(res.rijen)
    ok = sum(1 for _, g, _ in res.rijen if g)
    print(f"\nResultaat: {ok}/{totaal} geslaagd")
    sys.exit(0 if res.geslaagd else 1)


if __name__ == "__main__":
    main()
