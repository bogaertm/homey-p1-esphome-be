# Homey Energy Dongle met ESPHome voor de Belgische digitale meter

ESPHome firmware voor de Homey Energy Dongle, afgestemd op de digitale meter van Fluvius. De dongle leest de P1 poort volledig lokaal uit en stuurt alles rechtstreeks naar Home Assistant via de native ESPHome API. Geen cloud, geen Homey nodig.

Vereist ESPHome 2026.9.0 of nieuwer (versleutelde OTA updates bestaan pas sinds die versie). Werk in Home Assistant de ESPHome Device Builder bij als je een oudere versie hebt.

Getest met ESPHome 2026.9.1: ESP32 firmware compileert foutloos en de integratietest slaagt volledig (32/32), zie [Testen](#testen).

## Snelheid

De Fluvius meter stuurt elke seconde een telegram. Elk telegram komt binnen ongeveer 5 ms na de laatste byte in Home Assistant aan.

| Instelling | Waarom |
|---|---|
| `api: batch_delay: 0ms` | ESPHome bundelt updates standaard 100 ms, nu gaan ze meteen weg |
| `wifi: power_save_mode: none` | Geen vertraging door WiFi energiebesparing |
| Netto vermogen op telegram | Berekend bij elk telegram in plaats van op een timer |
| `logger: level: INFO` | Niet elke sensor elke seconde loggen. Zet op `DEBUG` bij foutzoeken |

Sneller dan de meter kan niet: de P1 poort zelf bepaalt het ritme van één telegram per seconde.

## Wat je krijgt in Home Assistant

| Groep | Sensoren |
|---|---|
| Energie | Afname dag, Afname nacht, Injectie dag, Injectie nacht (kWh) |
| Vermogen | Vermogen afname en injectie, per fase L1 L2 L3, Netto vermogen in W |
| Net | Spanning en stroom per fase |
| Capaciteitstarief | Kwartiervermogen lopend, Maandpiek, Gemiddelde maandpiek 13 maanden |
| Gas en water | Gasverbruik (m³), Waterverbruik (enkel met gekoppelde watermeter) |
| Info | Actief tarief (Dag/Nacht), P1 versie, serienummers, WiFi signaal, uptime |

Plus een bedienbare led en een herstartknop.

## Hardware van de dongle

| Functie | Pin |
|---|---|
| Chip | ESP32-C6, 4 MB flash |
| P1 data (RX) | GPIO4, geïnverteerd |
| P1 enable | GPIO23 |
| RGB led (WS2812) | GPIO2 |
| Flashknop | Naast de USB-C poort |

## Stappenplan

### 1. P1 poort activeren bij Fluvius
Log in op mijn.fluvius.be en ga naar Producten & Diensten, Verbruik, Beheer poorten. Zet de P1 poort aan. Op het scherm van de meter verschijnt een pijltje boven P1 zodra de poort actief is. Gebruik de P1 poort (gele rubberen klep), niet de S1 poort.

### 2. Secrets invullen
Kopieer `secrets.example.yaml` naar `secrets.yaml` (of zet de waarden in de secrets van ESPHome Builder in Home Assistant). Een API sleutel maak je in Terminal op de Mac met:

```
openssl rand -base64 32
```

### 3. Eerste keer flashen via USB
1. Hou het knopje naast de USB-C poort ingedrukt met een simkaartpinnetje en steek dan de USB-C kabel in. De led blijft uit, dat is normaal.
2. Open ESPHome Builder in Home Assistant, maak een nieuw toestel aan en plak de inhoud van `homey-p1-be.yaml`.
3. Kies Install, dan Plug into this computer (Chrome of Edge) of rechtstreeks via de USB poort van de Home Assistant server.
4. Na het flashen de kabel uittrekken en opnieuw insteken. De led brandt blauw.

Daarna gaan alle updates draadloos.

### 4. Toevoegen in Home Assistant
Home Assistant ontdekt het toestel automatisch. Klik op Configureren en geef de API sleutel in.

### 5. Energiedashboard
Ga naar Instellingen, Dashboards, Energie.

| Onderdeel | Sensor |
|---|---|
| Netverbruik | Afname dag en Afname nacht |
| Teruglevering | Injectie dag en Injectie nacht |
| Gasverbruik | Gasverbruik |

## Problemen oplossen

| Probleem | Oplossing |
|---|---|
| Geen data | Controleer of de P1 poort actief is (pijltje op de meter) |
| Flashen lukt niet, Improv niet gevonden | Knopje ingedrukt houden tijdens het insteken van de kabel, andere USB-C datakabel proberen |
| CRC fouten in de logs | Af en toe is normaal, het telegram wordt dan genegeerd. Vaak: kabel of contact van de dongle in de P1 poort nakijken |
| Geen gasverbruik | Gasmeter niet gekoppeld aan de digitale meter, of ander M-Bus kanaal: pas `gas_mbus_id` aan |

## Testen

De map `test` bevat een integratietest die de echte ESPHome DSMR code op Linux draait, er een gesimuleerde Fluvius meter (met geldige CRC, aan 115200 baud) op aansluit en de waarden uitleest via de native API, net zoals Home Assistant.

| Test | Resultaat |
|---|---|
| 10 telegrammen aan 1 Hz | 10/10 verwerkt, gemiddeld 5 ms vertraging |
| Alle sensoren (dag/nacht, injectie, fases, kwartierpiek, 13 maanden, gas) | Correct |
| Injectie en nachttarief | Netto vermogen negatief, tarief Nacht |
| Telegram met foute CRC | Genegeerd, volgend telegram terug correct |
| Telegram zonder gasmeter | Elektriciteit wordt verwerkt |
| Stresstest 4 Hz aan echte lijnsnelheid | 40/40 verwerkt |

Uitvoeren op Linux (vereist `libmbedtls-dev`):

```
pip install esphome
cd test && python run_test.py
```

## Terug naar de originele Homey firmware
Ga in Chrome naar usb.homey.app en volg de stappen. Doe dit ook altijd voor je een dongle terugstuurt of doorverkoopt.

## Bronnen
* Handleiding van Athom en ervaringen van gebruikers: [Home Assistant Community](https://community.home-assistant.io/t/how-to-connecting-the-homey-energy-dongle-to-home-assistant-with-esphome/878962)
* DSMR component en Belgische sensoren: [ESPHome documentatie](https://esphome.io/components/sensor/dsmr/)
* P1 poort activeren bij Fluvius: [Eniris integraties](https://integrations.eniris.be/Devices/Energy-meter/Fluvius)
* OTA versleuteling nieuw in 2026.9.0: [ESPHome changelog](https://esphome.io/changelog/2026.9.0/)
* API batch_delay standaard 100 ms: [ESPHome API documentatie](https://esphome.io/components/api/)
* Belgische OBIS codes (tarief 1 is dag, tarief 2 is nacht, gas op 0-1:24.2.3): [jensd.be](https://jensd.be/1183/linux/read-data-from-the-belgian-digital-meter-through-the-p1-port)
