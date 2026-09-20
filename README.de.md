# Shelly Phase Netting für Home Assistant

🇬🇧 [English version](README.md)

Diese Custom Integration liest `EMData.GetData` vom Shelly Pro 3EM, saldiert jede gespeicherte Minute über alle drei Phasen und erzeugt zwei Energy-Dashboard-taugliche Zähler:

- Netzbezug saldiert (kWh)
- Netzeinspeisung saldiert (kWh)

Dazu kommt ein Diagnose-Sensor „Letzter verarbeiteter Datensatz“ (Zeitstempel, auf der Geräteseite unter „Diagnose“ aufgeführt; das Attribut `cursor` enthält die Position, ab der beim nächsten Abruf weitergelesen wird).

Der Cursor und beide Summen werden nach jeder erfolgreichen Datenübernahme in Home Assistant gespeichert. Ein HA-Ausfall wird aus der Shelly-Historie nachgeholt; auf dem Shelly entstehen keine zusätzlichen Schreibzugriffe.

Hinweis: „Netting“ meint hier das Saldieren von Bezug und Einspeisung über die Phasen pro Minute (saldierende Messung). Es ist nicht das Abrechnungsmodell, das im Englischen „net metering“ heißt.

## Warum diese Integration?

**Das Problem:** Die Energiezähler (kWh) des Shelly Pro 3EM addieren Bezug und Rückspeisung *pro Phase* getrennt. Speist zum Beispiel ein Balkonkraftwerk auf einer Phase ein, während eine andere Phase Strom bezieht, laufen beide Zähler gleichzeitig, und die Summen liegen über dem, was dein Stromzähler erfasst, denn dieser saldiert die Phasen. Nur die momentane Gesamtleistung (`total_act_power`) ist saldiert.

**Bestehende Ansätze** und ihre Grenzen:

| Ansatz | Funktionsweise | Nachteile |
|---|---|---|
| [Home-Assistant-Template-Sensoren + Integral-Helfer](https://www.simon42.com/shelly-pro-3em-saldierung-home-assistant/) | Die Gesamtleistung wird in einen Bezugs- und einen Einspeise-Sensor getrennt und beide werden über die Zeit integriert. | Es werden nur Stichproben der Leistung integriert, die Genauigkeit hängt also davon ab, wie oft der Shelly meldet. Solange Home Assistant aus ist oder neu startet, wird nichts aufsummiert, und die Lücke lässt sich nicht nachträglich füllen. Keine Historie vor dem Anlegen der Helfer. Zwei Template-Sensoren und zwei Helfer müssen von Hand eingerichtet und gepflegt werden. |
| [Skript auf dem Shelly](https://github.com/chackl1990/shelly-pro-3em-net-metering) oder [mit MQTT](https://gist.github.com/Davc0m/dc419aa3147ec3c3d6e7289f89dc0ed8) | Ein mJS-Skript auf dem Gerät integriert die Leistung alle 500 ms und hält die Zähler auf dem Gerät. | Verändert das Gerät: Ein Skript muss installiert und über Firmware-Updates hinweg funktionsfähig gehalten werden (ein Projekt ist nur mit Firmware 1.7.1 getestet). Die Zähler werden auf dem Gerät gespeichert, das bedeutet regelmäßige Flash-Schreibzugriffe (ein Autor schätzt die Lebensdauer auf etwa 5 Jahre bei einem Schreibvorgang alle 15 Minuten). Manche Varianten benötigen MQTT. |

**Was diese Integration anders macht:**

- **Sie nutzt die Energie, die der Shelly bereits aufgezeichnet hat.** Der Pro 3EM speichert die Energie pro Phase in Ein-Minuten-Datensätzen. Die Integration liest diese Datensätze (`EMData.GetData`) und saldiert jede Minute über die Phasen, statt abgetastete Leistung zu integrieren.
- **Ausfälle von Home Assistant oder des Netzwerks erzeugen keine Lücken.** Leseposition (Cursor) und Summen werden gespeichert. Ist Home Assistant wieder erreichbar, macht die Integration genau dort weiter, wo sie aufgehört hat, und holt die Zeit aus der Shelly-Historie nach (der Shelly speichert etwa 60 Tage). Neustarts, Updates und Netzwerkprobleme verlieren also keine Energie.
- **Historie ab dem ersten Tag.** Bei der Einrichtung können die Zähler aus bis zu 45 Tagen Shelly-Historie gefüllt werden und starten nicht bei null, und die stündliche Historie wird in die Langzeitstatistik geschrieben, sodass auch das Energie-Dashboard sie zeigt (siehe unten).
- **Der Shelly bleibt unangetastet.** Die Integration liest nur: kein Skript, kein MQTT, keine Konfigurationsänderung, damit auch kein zusätzlicher Flash-Verschleiß und keine Abhängigkeit von einer bestimmten Firmware-Version.
- **Sofort nutzbar.** Zwei Energie-Sensoren für das Energie-Dashboard, mit Reauth und Konfigurationsdialog, statt selbst gebauter Helfer.

**Abwägungen:**

- Die Saldierung erfolgt pro gespeicherter Minute. Gegenläufige Leistungsflüsse innerhalb derselben Minute können sich aufheben, während ein Skript mit 500-ms-Saldierung kurzzeitigen Änderungen genauer folgt.
- Die Werte folgen den Shelly-Datensätzen mit höchstens einem Abrufintervall (standardmäßig 60 Sekunden) Verzögerung, plus den wenigen Sekunden, die der Shelly zum Speichern einer abgeschlossenen Minute braucht. Live-Leistung liefert diese Integration nicht; dafür die native Shelly-Integration verwenden.
- Nach einem Ausfall wird die fehlende Energie ergänzt, sobald Home Assistant den Shelly wieder erreicht. Die Summen stimmen dann, aber das Energie-Dashboard bucht den Anstieg zum Zeitpunkt des Nachholens und nicht in den Stunden, in denen die Energie tatsächlich verbraucht wurde.
- Unterstützt werden nur Geräte mit der Komponente `EMData` (Pro 3EM im Triphase-Profil).

## Installation

### Über HACS (empfohlen)

[![Open your Home Assistant instance and open this repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gojux&repository=shelly_phase_netting&category=integration)

1. Auf den Button oben klicken (oder in HACS: ⋮ → **Benutzerdefinierte Repositories** → `https://github.com/gojux/shelly_phase_netting` mit der Kategorie **Integration** hinzufügen).
2. **Shelly Phase Netting** in HACS herunterladen und Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/shelly_phase_netting` nach `/config/custom_components/` kopieren und Home Assistant neu starten.

## Einrichtung

1. **Einstellungen → Geräte & Dienste → Integration hinzufügen → Shelly Phase Netting** öffnen.
2. IP/Hostname des Pro 3EM eingeben. Bei aktivierter Shelly-Authentifizierung das Passwort ergänzen (der Benutzername ist bei Shelly Gen2 immer `admin`). Die Authentifizierung nutzt SHA-256-Digest.
3. Den gewünschten Rückimport wählen (Standard: 24 Stunden, maximal 45 Tage).
4. Nach dem Import die beiden kWh-Sensoren im Energie-Dashboard als Netzbezug und Rückspeisung auswählen.

## Wie die Berechnung funktioniert

Der Pro 3EM speichert pro Minute einen Datensatz. Jeder Datensatz enthält für jede Phase (A, B, C) die in dieser Minute **bezogene** und die **zurückgespeiste** Energie in Wh. Für jeden Datensatz rechnet die Integration:

```
Saldo = (A_bezogen − A_zurück) + (B_bezogen − B_zurück) + (C_bezogen − C_zurück)

Saldo ≥ 0  →  Bezugssumme += Saldo
Saldo < 0  →  Einspeisesumme += −Saldo
```

Beispiel mit drei Minuten (alle Werte in Wh):

| Minute | A | B | C | Saldo | Bezugssumme | Einspeisesumme |
|---|---|---|---|---|---|---|
| 1 | 10 bezogen | 4 zurück | – | +6 | 6 | 0 |
| 2 | 2 bezogen | 5 zurück | 1 bezogen | −2 | 6 | 2 |
| 3 | 3 bezogen | – | – | +3 | 9 | 2 |

Die saldierten Summen sind 9 Wh Bezug und 2 Wh Einspeisung. Die phasenweisen Zähler des Shelly würden für dieselben drei Minuten 16 Wh Bezug und 9 Wh Rückspeisung anzeigen.

So werden die Datensätze verarbeitet:

- **Nur abgeschlossene Minuten werden gezählt.** Der Pro 3EM liefert die noch laufende Minute nicht aus: Eine Minute erschien wenige Sekunden nach ihrem Ende (an einem Pro 3EM beobachtet). Die Integration verbucht daher nie Teilwerte.
- **Jeder Datensatz wird genau einmal gezählt.** Die Integration führt eine Leseposition (Cursor), die auf das Ende des zuletzt verarbeiteten Datensatzes zeigt. Bei jedem Abruf fragt sie den Shelly nach den Datensätzen ab dem Cursor (`EMData.GetData`) und folgt dessen Seitenweiterschaltung (`next_record_ts`), bis alles gelesen ist.
- **Der Zustand wird nach jedem Abruf mit Fortschritt gespeichert:** beide Summen in Wh, der Cursor und der Zeitpunkt des letzten Datensatzes. Nach einem Neustart von Home Assistant macht die Integration dort weiter.
- **Ein fehlgeschlagener Abruf ändert nichts.** Ist der Shelly nicht erreichbar oder die Antwort unvollständig, bleiben Summen und Cursor unverändert. Der nächste erfolgreiche Abruf liest dieselben Datensätze erneut, es geht also nichts verloren und nichts wird doppelt gezählt.
- **Erster Start:** Der Cursor wird auf den gewählten Rückimport-Zeitpunkt gesetzt (auf volle Minuten abgerundet), ab dort werden die Datensätze wie alle anderen verarbeitet. Große Rückstände werden in Etappen gelesen, höchstens 20 Seiten pro Abruf, mit Folgeabrufen im 2-Sekunden-Takt.
- **Lücken in der Shelly-Historie** (zum Beispiel während der Shelly ausgeschaltet war) werden übersprungen: Der Cursor springt zum nächsten gespeicherten Datensatz. Ihre Energie lässt sich nicht wiederherstellen, die Lücken werden aber gemeldet: Der Diagnose-Sensor hat die Attribute `gaps`, `missing_minutes`, `last_gap_start` und `last_gap_end`, jede Lücke wird protokolliert, und ab 10 Minuten erscheint ein Hinweis unter **Einstellungen → System → Reparaturen** (den du ignorieren kannst).
- **Historie für das Energie-Dashboard:** Beim ersten Rückimport wird die Energie zusätzlich pro Stunde aufsummiert. Ist der Rückimport abgeschlossen, werden diese Stundenwerte in die Langzeitstatistik der beiden Energie-Sensoren des Recorders geschrieben, bis zur letzten vollen Stunde vor der aktuellen; den Rest berechnet Home Assistant aus den Live-Werten. Damit seine eigene laufende Summe genau dort fortsetzt, wo die importierte endet, wird eine 5-Minuten-Statistikzeile als Startpunkt dafür importiert; ohne sie würde die Summe um den importierten Gesamtwert zurückspringen. Die erste Stunde dient nur als Ausgangsbasis. Das geschieht einmalig, nur bei der Ersteinrichtung und nur, wenn der Recorder für die Sensoren noch keine Statistik hat (sonst würden vorhandene Werte überschrieben; es wird eine Warnung protokolliert). Für die Historie einer bestehenden Installation die Integration entfernen, die übrig gebliebenen Statistiken beider Sensoren löschen (Entwicklerwerkzeuge → Statistiken) und die Integration neu einrichten. Die eigene Zustandshistorie des Sensors beginnt erst zum Zeitpunkt der Einrichtung; davor zeigt das Verlaufs-Panel die importierten Stundenwerte als Stufen. Spätere Ausfälle werden beim Nachholen gebucht (siehe oben).
- **Ausgabe:** Die Sensoren zeigen die Summen in kWh (Wh ÷ 1000, bis zu sechs Nachkommastellen) und haben den Typ `total_increasing`, den das Energie-Dashboard erwartet.

## Verhalten und Grenzen

- Der Pro 3EM muss im **Triphase-Profil** (3 Phasen) laufen. Im Monophase-Profil gibt es `EMData` nicht (dort heißt die Komponente `EM1Data`); die Einrichtung meldet dann einen entsprechenden Fehler.
- Die Zähler starten beim gewählten Rückimport-Zeitpunkt, nicht beim historischen Zählerstand des Netzbetreibers.
- Die Saldierung erfolgt pro gespeichertem 60-Sekunden-Intervall. Kurzzeitiger Bezug und Einspeisung innerhalb derselben Minute können sich daher aufheben.
- Der Rückimport läuft in Etappen (höchstens 20 Seiten pro Abruf, Folgeabrufe im 2-Sekunden-Takt) und blockiert die Einrichtung nicht. Die beiden Energie-Sensoren bleiben bis zum Ende des Rückimports und des Historien-Imports `unavailable`; ihr erster Wert ist damit der vollständige Stand, und das Energie-Dashboard bucht die nachgeholte Energie nicht als Verbrauch der ersten Stunde. Das Attribut `catch_up_pending` des Diagnose-Sensors zeigt, ob noch nachgeholt wird.
- Daten, die bereits aus der internen Shelly-Historie herausgefallen sind, können nicht nachgeholt werden.
- Das Abrufintervall (30–3600 Sekunden, Standard 60) lässt sich in den Integrationsoptionen ändern; die Integration wird dabei automatisch neu geladen.
- Die Shelly-Firmware 2.x hat einen Schutz gegen Passwort-Raten, der einen steten Strom unauthentifizierter Anfragen mit HTTP 429 (Too Many Requests) beantwortet, und die Firmware 2.0.0 tut das gelegentlich sogar bei einem einzelnen Client (laut Berichten in 2.0.1 behoben, zuerst als Beta veröffentlicht). Um dem auszuweichen, verwendet die Integration die Digest-Challenge zwischen den Aufrufen wieder, statt bei jeder Anfrage eine neue zu provozieren. Antwortet der Shelly trotzdem mit 429, wird die Anfrage bis zu dreimal wiederholt (einem `Retry-After`-Header folgend, falls der Shelly einen sendet), bevor der Abruf als fehlgeschlagen gilt. Ein fehlgeschlagener Abruf macht die Sensoren bis zum nächsten erfolgreichen `unavailable`; Daten gehen nicht verloren, weil die Leseposition erst nach einem erfolgreichen Lesen weiterrückt.
- Lehnt der Shelly die Zugangsdaten ab (z. B. nach einer Passwortänderung), startet Home Assistant einen Reauth-Dialog.
- Bekommt der Shelly eine neue IP-Adresse oder einen neuen Hostnamen, lässt sie sich unter **Einstellungen → Geräte & Dienste → Shelly Phase Netting → ⋮ → Neu konfigurieren** ändern. Es muss dasselbe Gerät sein (Prüfung über die MAC-Adresse); ein leeres Passwortfeld behält das gespeicherte Passwort. Leseposition und Summen bleiben erhalten.
- Vor einem Löschen/Neueinrichten der Integration die HA-Daten sichern: Das Entfernen des Config-Eintrags löscht auch den zugehörigen Cursor-/Summenspeicher (`.storage/shelly_phase_netting.<entry_id>`); ein neu eingerichteter Eintrag beginnt wieder bei 0.

## Diagnose

Für Fehlermeldungen: **Einstellungen → Geräte & Dienste → Shelly Phase Netting → ⋮ → Diagnose herunterladen**. Die Datei enthält den Zustand (Summen, Leseposition, Lücken), den letzten Fehler sowie Modell und Firmware-Version des Shelly. Adresse, Zugangsdaten und Gerätekennungen sind geschwärzt. Für mehr Details lässt sich auf derselben Seite das Debug-Logging einschalten.

## Tests

Die Tests laufen in Docker gegen verschiedene Python- und Home-Assistant-Versionen (keine lokale Python-Einrichtung nötig):

```bash
docker compose run --rm tests        # aktuellstes Python + aktuellstes Home Assistant
docker compose run --rm tests-min    # älteste unterstützte Home-Assistant-Version (siehe hacs.json)
docker compose run --rm tests-beta   # aktuellste Home-Assistant-Vorabversion
```

Beliebige Kombinationen und zusätzliche pytest-Argumente sind ebenfalls möglich, zum Beispiel:

```bash
PYTHON_VERSION=3.14 HA_VERSION=2026.3.0 docker compose run --rm tests -k reauth -x
```

Ohne Docker: `pip install -r requirements_test.txt && pytest`.

## Lizenz

[MIT](LICENSE) © gojux
