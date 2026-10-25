#!/usr/bin/env python3
"""Genereert growatt-meter-emulator.yaml.

De registerkaart volgt het Eastron SDM630 Modbus protocol (input registers 3xxxx,
IEEE754 float, hoogste woord eerst, functiecode 04). Alle waarden worden 1 keer per
nieuw telegram berekend. Elk Modbus register leest daarna enkel zijn plaats in een
tabel, met dezelfde failsafe: zijn de gegevens ouder dan failsafe_ms, dan krijgt de
omvormer een Modbus foutmelding in plaats van een verouderde waarde.

Uitvoeren:  python tools/genereer_emulator.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOEL = REPO / "growatt-meter-emulator.yaml"

# (adres, omschrijving volgens het Eastron SDM630 protocol, C++ expressie)
REGISTERS = [
    (0x00, "30001 Spanning L1 (V)", "w(u_l1)"),
    (0x02, "30003 Spanning L2 (V)", "w(u_l2)"),
    (0x04, "30005 Spanning L3 (V)", "w(u_l3)"),
    (0x06, "30007 Stroom L1 (A)", "w(i_l1)"),
    (0x08, "30009 Stroom L2 (A)", "w(i_l2)"),
    (0x0A, "30011 Stroom L3 (A)", "w(i_l3)"),
    (0x0C, "30013 Vermogen L1 (W), afname positief, injectie negatief", "w(p_l1)"),
    (0x0E, "30015 Vermogen L2 (W)", "w(p_l2)"),
    (0x10, "30017 Vermogen L3 (W)", "w(p_l3)"),
    (0x12, "30019 Schijnbaar vermogen L1 (VA)", "va(u_l1, i_l1)"),
    (0x14, "30021 Schijnbaar vermogen L2 (VA)", "va(u_l2, i_l2)"),
    (0x16, "30023 Schijnbaar vermogen L3 (VA)", "va(u_l3, i_l3)"),
    (0x1E, "30031 Arbeidsfactor L1", "pf(w(p_l1), va(u_l1, i_l1))"),
    (0x20, "30033 Arbeidsfactor L2", "pf(w(p_l2), va(u_l2, i_l2))"),
    (0x22, "30035 Arbeidsfactor L3", "pf(w(p_l3), va(u_l3, i_l3))"),
    (0x2A, "30043 Gemiddelde spanning (V)", "(w(u_l1) + w(u_l2) + w(u_l3)) / fasen"),
    (0x2E, "30047 Gemiddelde stroom (A)", "(w(i_l1) + w(i_l2) + w(i_l3)) / fasen"),
    (0x30, "30049 Som van de stromen (A)", "w(i_l1) + w(i_l2) + w(i_l3)"),
    (0x34, "30053 Totaal vermogen (W), afname positief", "p_tot"),
    (0x38, "30057 Totaal schijnbaar vermogen (VA)", "va_tot"),
    (0x3E, "30063 Totale arbeidsfactor", "pf(p_tot, va_tot)"),
    (0x46, "30071 Frequentie (Hz), zit niet in P1, nominaal 50 Hz", "50.0f"),
    (0x48, "30073 Afname totaal (kWh)", "w(e_import)"),
    (0x4A, "30075 Injectie totaal (kWh)", "w(e_export)"),
    (0x156, "30343 Totale actieve energie (kWh)", "w(e_import) + w(e_export)"),
]

# remote_id op de dongle, lokale naam, weergavenaam, eenheid, device_class, decimalen
ZICHTBAAR = [
    ("link_p_l1", "p_l1", "Vermogen L1", "W", "power", 0),
    ("link_p_l2", "p_l2", "Vermogen L2", "W", "power", 0),
    ("link_p_l3", "p_l3", "Vermogen L3", "W", "power", 0),
    ("link_import", "e_import", "Afname totaal", "kWh", "energy", 3),
    ("link_export", "e_export", "Injectie totaal", "kWh", "energy", 3),
    ("p1_u_l1", "u_l1", "Spanning L1", "V", "voltage", 1),
    ("p1_u_l2", "u_l2", "Spanning L2", "V", "voltage", 1),
    ("p1_u_l3", "u_l3", "Spanning L3", "V", "voltage", 1),
    ("p1_i_l1", "i_l1", "Stroom L1", "A", "current", 2),
    ("p1_i_l2", "i_l2", "Stroom L2", "A", "current", 2),
    ("p1_i_l3", "i_l3", "Stroom L3", "A", "current", 2),
]

KOP = """# Growatt meter emulator: ESP32 met RS485 bij de omvormer die zich voordoet als
# Eastron SDM630 (3 fasen) of SDM230 (1 fase). De meetwaarden komen draadloos van de
# Homey Energy Dongle aan de digitale meter (homey-p1-be-growatt-link.yaml).
#
# GEGENEREERD door tools/genereer_emulator.py: pas registers daar aan, niet hier.
#
# Hardware: Waveshare ESP32-S3-RS485-CAN (DIN rail, geisoleerde RS485, 7 tot 36 V DC)
#   RS485 A en B naar de meteringang van de Growatt (bv. SYS COM pin 5 = A, pin 6 = B)
#
# Enkel voor eigenverbruik en batterijsturing. NIET gebruiken als wettelijk verplichte
# injectiebegrenzing: daarvoor eist Fluvius een begrenzer van de Synergrid C10/25 lijst.

substitutions:
  name: growatt-meter
  friendly_name: Growatt meter
  # 2 = SDM630 v2 (3 fasen, standaard bij Growatt), 1 = SDM230 (1 fase), 3 = SDM630 v3
  meter_adres: "2"
  # Na zoveel ms zonder nieuw telegram stopt de emulator met antwoorden (failsafe)
  failsafe_ms: "5000"
  # Naam van de dongle (esphome name in homey-p1-be.yaml)
  p1_dongle: homey-p1
  rs485_tx: GPIO17
  rs485_rx: GPIO18
  rs485_de: GPIO21

esphome:
  name: ${name}
  friendly_name: ${friendly_name}
  min_version: 2026.9.0
  project:
    name: btechnics.growatt-meter-emulator
    version: "1.0.0"

esp32:
  board: esp32-s3-devkitc-1
  variant: esp32s3
  flash_size: 16MB
  framework:
    type: esp-idf

logger:
  level: INFO

api:
  batch_delay: 0ms
  encryption:
    key: !secret api_key_emulator

ota:
  - platform: esphome
    encryption:
      key: !secret api_key_emulator

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  power_save_mode: none
  ap:
    ssid: "${name} fallback"
    password: !secret ap_password

captive_portal:

web_server:
  port: 80
  version: 3
  ota: false

globals:
  # Berekende registerwaarden, in dezelfde volgorde als de registers hieronder
  - id: reg
    type: std::array<float, @AANTAL@>
    restore_value: false
  - id: laatste_seq
    type: float
    restore_value: false
    initial_value: "-1"
  - id: laatste_ontvangst
    type: uint32_t
    restore_value: false
    initial_value: "0"
  - id: telegrammen
    type: uint32_t
    restore_value: false
    initial_value: "0"

# ---------------------------------------------------------------- link met de dongle --
udp:
  id: p1_udp
  port: 18511

packet_transport:
  - platform: udp
    udp_id: p1_udp
    providers:
      - name: ${p1_dongle}
        encryption:
          key: !secret p1_link_key

# --------------------------------------------------------------------------- RS485 --
uart:
  - id: uart_rs485
    tx_pin: ${rs485_tx}
    rx_pin: ${rs485_rx}
    baud_rate: 9600
    data_bits: 8
    parity: NONE
    stop_bits: 1
    # Zet logger op DEBUG om alle vragen van de omvormer te zien (handig bij de eerste installatie)
    debug:
      direction: BOTH
      dummy_receiver: false

modbus:
  - id: rs485
    uart_id: uart_rs485
    role: server
    flow_control_pin: ${rs485_de}

modbus_server:
  - id: sdm
    modbus_id: rs485
    address: ${meter_adres}
    # Niet ingevulde registers geven 0 terug, zoals een echte SDM630
    courtesy_response:
      enabled: true
      register_last_address: 0x017F
      register_value: 0
    # Elk register: geen verse data van de dongle = foutmelding naar de omvormer
    registers:
"""

BEREKEN = """
script:
  # Rekent alle registerwaarden 1 keer uit per nieuw telegram
  - id: bereken
    then:
      - lambda: |-
          auto w = [](sensor::Sensor *s) -> float {
            return (s->has_state() && !std::isnan(s->state)) ? s->state : 0.0f;
          };
          auto va = [&](sensor::Sensor *u, sensor::Sensor *i) -> float { return w(u) * w(i); };
          auto pf = [](float p, float s) -> float {
            if (s < 1.0f) return 1.0f;
            float f = p / s;
            return f > 1.0f ? 1.0f : (f < -1.0f ? -1.0f : f);
          };
          sensor::Sensor *u_l1 = id(s_u_l1), *u_l2 = id(s_u_l2), *u_l3 = id(s_u_l3);
          sensor::Sensor *i_l1 = id(s_i_l1), *i_l2 = id(s_i_l2), *i_l3 = id(s_i_l3);
          sensor::Sensor *p_l1 = id(s_p_l1), *p_l2 = id(s_p_l2), *p_l3 = id(s_p_l3);
          sensor::Sensor *e_import = id(s_e_import), *e_export = id(s_e_export);
          int n = (w(u_l1) > 1.0f) + (w(u_l2) > 1.0f) + (w(u_l3) > 1.0f);
          float fasen = n > 0 ? (float) n : 1.0f;
          float p_tot = w(p_l1) + w(p_l2) + w(p_l3);
          float va_tot = va(u_l1, i_l1) + va(u_l2, i_l2) + va(u_l3, i_l3);
          auto &r = id(reg);
"""

HARTSLAG = """
sensor:
  # Hartslag van de dongle, komt als laatste in elk pakket
  - platform: packet_transport
    provider: ${p1_dongle}
    remote_id: link_seq
    id: seq
    internal: true
    on_value:
      - lambda: |-
          // De dongle stuurt alles om de 5 s opnieuw. Enkel een NIEUWE hartslag betekent
          // een nieuw telegram. Anders zou de failsafe nooit afgaan als de P1 kabel los
          // is terwijl de dongle zelf nog draait. Een lege hartslag (NaN, nog geen
          // telegram gezien) telt nooit.
          if (!std::isnan(x) && x != id(laatste_seq)) {
            id(laatste_seq) = x;
            id(laatste_ontvangst) = millis();
            id(telegrammen) += 1;
            id(bereken).execute();
          }
"""

STAART = """
  - platform: template
    name: "Totaal vermogen naar omvormer"
    unit_of_measurement: W
    device_class: power
    state_class: measurement
    accuracy_decimals: 0
    update_interval: 2s
    lambda: return id(reg)[@P_TOT@];

  - platform: template
    name: "Telegrammen ontvangen"
    accuracy_decimals: 0
    state_class: total_increasing
    entity_category: diagnostic
    update_interval: 10s
    lambda: return id(telegrammen);

  - platform: wifi_signal
    id: wifi_rssi
    name: "WiFi signaal"
    update_interval: 60s
    entity_category: diagnostic

binary_sensor:
  - platform: template
    name: "Data van dongle"
    device_class: connectivity
    lambda: |-
      return id(laatste_ontvangst) != 0 && (millis() - id(laatste_ontvangst)) <= ${failsafe_ms};

button:
  - platform: restart
    name: "Herstarten"
    entity_category: config
"""


def main():
    uit = [KOP.replace("@AANTAL@", str(len(REGISTERS)))]
    for k, (adres, omschrijving, _) in enumerate(REGISTERS):
        uit.append(
            f"      # {omschrijving}\n"
            f"      - address: 0x{adres:04X}\n"
            f"        value_type: FP32\n"
            f"        read_lambda: |-\n"
            f"          if (id(laatste_ontvangst) == 0 || millis() - id(laatste_ontvangst) > ${{failsafe_ms}}) return {{}};\n"
            f"          return id(reg)[{k}];\n"
        )
    uit.append(BEREKEN)
    for k, (adres, omschrijving, expr) in enumerate(REGISTERS):
        uit.append(f"          r[{k}] = {expr};  // 0x{adres:04X} {omschrijving.split(' ', 1)[1]}\n")
    uit.append(HARTSLAG)
    for remote, ident, naam, unit, dc, dec in ZICHTBAAR:
        sc = "total_increasing" if dc == "energy" else "measurement"
        uit.append(
            f"  - platform: packet_transport\n"
            f"    provider: ${{p1_dongle}}\n"
            f"    remote_id: {remote}\n"
            f"    id: s_{ident}\n"
            f"    name: \"{naam}\"\n"
            f"    internal: false\n"
            f"    unit_of_measurement: {unit}\n"
            f"    device_class: {dc}\n"
            f"    state_class: {sc}\n"
            f"    accuracy_decimals: {dec}\n"
        )
    p_tot = next(k for k, r in enumerate(REGISTERS) if r[0] == 0x34)
    uit.append(STAART.replace("@P_TOT@", str(p_tot)))
    DOEL.write_text("".join(uit))
    print(f"Geschreven: {DOEL} ({len(REGISTERS)} registers)")


if __name__ == "__main__":
    main()
