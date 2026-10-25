# Homey Energy Dongle met ESPHome voor de Belgische digitale meter

ESPHome firmware voor de Homey Energy Dongle, afgestemd op de digitale meter van Fluvius. De dongle leest de P1 poort volledig lokaal uit en stuurt alles rechtstreeks naar Home Assistant via de native ESPHome API. Geen cloud, geen Homey nodig.

Vereist ESPHome 2026.9.0 of nieuwer (versleutelde OTA updates bestaan pas sinds die versie). Werk in Home Assistant de ESPHome Device Builder bij als je een oudere versie hebt.

Getest met ESPHome 2026.9.1: alle ESP32 firmwares compileren foutloos en beide integratietests slagen volledig (33/33 en 15/15), zie [Testen](#testen).

Geen kabel mogelijk tussen de digitale meter en een Growatt omvormer? Zie [Growatt meter emulator](#growatt-meter-emulator): de dongle stuurt de waarden dan draadloos naar een ESP32 bij de omvormer die zich voordoet als Eastron SDM630.

## Snelheid

De Fluvius meter stuurt elke seconde een telegram. Elk telegram komt gemiddeld 6 à 9 ms na de laatste byte in Home Assistant aan (gemeten, maximum 16 ms).

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

## Growatt meter emulator

Voor installaties waar geen RS485 kabel kan liggen tussen de digitale meter en de Growatt omvormer.

```
Fluvius meter --P1--> Homey dongle --WiFi (UDP, versleuteld)--> ESP32 + RS485 --RS485--> Growatt
```

De ESP32 bij de omvormer doet zich voor als een Eastron SDM630 v2 op slave adres 2, zoals Growatt verwacht. De link gaat rechtstreeks van ESP naar ESP: Home Assistant mag uitvallen.

> Enkel voor eigenverbruik en batterijsturing. Niet gebruiken als wettelijk verplichte injectiebegrenzing: Fluvius eist daar een begrenzer van de Synergrid C10/25 lijst, ingesteld door een erkend keuringsorganisme.

### Bestanden

| Bestand | Op welk toestel |
|---|---|
| `homey-p1-be-growatt-link.yaml` | De dongle aan de digitale meter. Gebruikt `homey-p1-be.yaml` en voegt de link toe, beide in dezelfde map zetten |
| `growatt-meter-emulator.yaml` | De ESP32 bij de omvormer. Gegenereerd door `tools/genereer_emulator.py` |

### Hardware bij de omvormer

| Onderdeel | Keuze |
|---|---|
| Bord | Waveshare ESP32-S3-RS485-CAN: DIN rail, geïsoleerde RS485, 120 Ω afsluitweerstand via jumper |
| Voeding | 7 tot 36 V DC, bv. een kleine 12 V DIN rail voeding |
| RS485 pinnen | TX GPIO17, RX GPIO18, richting GPIO21 |
| Aansluiting Growatt | A en B naar de meteringang, bij de MIN TL-XH op SYS COM pin 5 (A) en 6 (B). Kijk de pinout van jouw model na in de handleiding |

### Stappenplan

1. **Secrets aanvullen.** Voeg `api_key_emulator` en `p1_link_key` toe (zie `secrets.example.yaml`). `p1_link_key` moet op beide toestellen identiek zijn. Maak hem met `openssl rand -hex 16`.
2. **Dongle opnieuw flashen** met `homey-p1-be-growatt-link.yaml` in plaats van `homey-p1-be.yaml`. Dat mag draadloos.
3. **Emulator flashen** met `growatt-meter-emulator.yaml`, de eerste keer via USB-C.
4. **In Home Assistant nakijken** of het toestel Growatt meter de binaire sensor *Data van dongle* op Verbonden zet en of *Totaal vermogen naar omvormer* klopt met *Netto vermogen* van de dongle.
5. **RS485 aansluiten** op de omvormer. Bij een lange kabel aan beide uiteinden een afsluitweerstand van 120 Ω (jumper op het Waveshare bord).
6. **In de Growatt de meter activeren** (exportbeperking of meter aan, type Eastron) en de omvormer volledig herstarten.
7. **Eerste controle.** Zet `logger: level: DEBUG` op de emulator en kijk in de logs welke registers de omvormer opvraagt. Antwoorden met `ILLEGAL_DATA_ADDRESS` of een ander slave adres: laat het weten, dan breiden we de registerkaart uit.

### Instellingen

| Substitution | Standaard | Betekenis |
|---|---|---|
| `meter_adres` | 2 | 2 = SDM630 v2 (3 fasen), 1 = SDM230 (1 fase), 3 = SDM630 v3 |
| `failsafe_ms` | 5000 | Na zoveel ms zonder nieuw telegram stuurt de emulator een foutmelding |
| `p1_dongle` | homey-p1 | Naam van de dongle |
| `emulator_adres` (op de dongle) | 255.255.255.255 | Broadcast. Vul het vaste IP van de emulator in als het netwerk broadcast filtert (bv. UniFi Multicast and Broadcast Control) |

### Hoe het werkt

| Onderdeel | Werking |
|---|---|
| Registers | 25 SDM630 input registers (spanning, stroom, vermogen per fase, VA, arbeidsfactor, totalen, energie), IEEE754 float, hoogste woord eerst. Afname positief, injectie negatief. Andere registers tot 0x17F geven 0, zoals een echte SDM630 |
| Functiecodes | 04 (zoals SDM630) en ook 03 |
| Frequentie | Zit niet in het P1 telegram, de emulator meldt vast 50 Hz |
| Snelheid | Elk telegram wordt meteen doorgestuurd. Gemeten: gemiddeld 85 ms van laatste P1 byte tot nieuwe waarde in het Modbus antwoord |
| Failsafe | Komt er 5 s geen nieuw telegram binnen (P1 kabel los, dongle of WiFi weg), dan antwoordt de emulator met een Modbus foutmelding in plaats van een oude waarde. De omvormer valt dan terug op zijn eigen gedrag bij een meterfout. Pakketten die de dongle elke 5 s herhaalt tellen niet als nieuw |
| Beveiliging | Link versleuteld met `p1_link_key` en rolling code tegen herhaalde pakketten |

### Nog niet getest

Alles is getest met de echte firmware op Linux, met een gesimuleerde meter en een gesimuleerde Growatt. Op een echte Growatt is het nog niet getest. Growatt documenteert niet welke registers de omvormer precies opvraagt; de registerkaart volgt de officiële Eastron documentatie en wat gebruikers met een Growatt MIN TL-XH melden.

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
| 10 telegrammen aan 1 Hz | 10/10 verwerkt, gemiddeld 6 à 9 ms vertraging, max 16 ms |
| Alle sensoren (dag/nacht, injectie, fases, kwartierpiek, 13 maanden, gas) | Correct |
| Injectie en nachttarief | Netto vermogen negatief, tarief Nacht |
| Telegram met foute CRC | Genegeerd, volgend telegram terug correct |
| Telegram zonder gasmeter | Elektriciteit wordt verwerkt |
| Stresstest 4 Hz aan echte lijnsnelheid | 40/40 verwerkt |

De tweede test (`run_growatt_test.py`) draait de dongle en de emulator allebei als echte firmware, met een gesimuleerde Fluvius meter aan de ene kant en een gesimuleerde Growatt (Modbus master aan 9600 baud) aan de andere kant.

| Test | Resultaat |
|---|---|
| Foutmelding zolang er nog geen data is | Correct |
| Alle 25 registers bij 3 fasen, met injectie op 1 fase | 25/25 juist, injectie negatief |
| Functiecode 03, ander slave adres | Antwoord op 03, geen antwoord op ander adres |
| Vertraging laatste P1 byte tot Modbus antwoord | Gemiddeld 85 ms, max 92 ms |
| Omvormer vraagt 10 keer per seconde gedurende 10 s | Elke vraag correct beantwoord |
| P1 telegrammen stoppen, dongle blijft herhalen | Foutmelding na 5,1 s en blijft in foutmelding |
| Herstel na nieuw telegram | Meteen terug juiste waarden |
| Monofasige meter | 25/25 juist, L2 en L3 op 0 |
| Dongle valt volledig uit | Foutmelding na 5,1 s |

Uitvoeren op Linux (vereist `libmbedtls-dev`):

```
pip install esphome
cd test && python run_test.py
cd test && python run_growatt_test.py
```

## Terug naar de originele Homey firmware
Ga in Chrome naar usb.homey.app en volg de stappen. Doe dit ook altijd voor je een dongle terugstuurt of doorverkoopt.

## Bronnen
* Handleiding van Athom en ervaringen van gebruikers: [Home Assistant Community](https://community.home-assistant.io/t/how-to-connecting-the-homey-energy-dongle-to-home-assistant-with-esphome/878962)
* DSMR component en Belgische sensoren: [ESPHome documentatie](https://esphome.io/components/sensor/dsmr/)
* P1 poort activeren bij Fluvius: [Eniris integraties](https://integrations.eniris.be/Devices/Energy-meter/Fluvius)
* OTA versleuteling nieuw in 2026.9.0: [ESPHome changelog](https://esphome.io/changelog/2026.9.0/)
* API batch_delay standaard 100 ms: [ESPHome API documentatie](https://esphome.io/components/api/)
* SDM630 registerkaart: Eastron SDM630 Modbus Protocol (opgenomen in [esphome-fake-eastron-SDM630](https://github.com/hankipanky/esphome-fake-eastron-SDM630))
* Growatt verwacht SDM630 v2 op slave adres 2: [esphome-fake-eastron-SDM630](https://github.com/hankipanky/esphome-fake-eastron-SDM630)
* Pinnen Waveshare ESP32-S3-RS485-CAN: [esphome-yambms #89](https://github.com/Sleeper85/esphome-yambms/issues/89), bord: [Waveshare](https://www.waveshare.com/esp32-s3-rs485-can.htm)
* Injectiebegrenzing via C10/25 begrenzer: [Fluvius lastenboek exportbegrenzing](https://www.fluvius.be/sites/fluvius/files/2020-03/bijlage_lastenboek-export-vermogen-begrenzing_v2.1.pdf)
* Belgische OBIS codes (tarief 1 is dag, tarief 2 is nacht, gas op 0-1:24.2.3): [jensd.be](https://jensd.be/1183/linux/read-data-from-the-belgian-digital-meter-through-the-p1-port)
