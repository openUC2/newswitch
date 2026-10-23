# Bestandsaufnahme: Hardware aus Controller-Mappings starten

> Historische Bestandsaufnahme vom 20.10.2026. Auf `feat/controller-mapping-runtime`
> ist die unten geplante Anbindung inzwischen für lineare Achsen, PWM-Licht und
> eine RGB-Matrix über Master-Serial oder direktes CAN umgesetzt. Aktueller Vertrag,
> Startbefehle und Grenzen: `backend/configs/demos/README.md`. Die folgenden Punkte
> beschreiben die damalige Ausgangsbasis, nicht durchgehend den aktuellen Branch.

Stand: 20.10.2026. Basis: `main` / `89ef2ca`, Merge von PR #4 am 17.10.2026.
Vergleich: bisheriger Integrationsbranch `feat/yaml-hardware-startup` / `81d00d8`.
Umfang: Bewegungsachsen, Laser, einzelne LED-PWM-Ausgänge und LED-Matrix; keine
neue Kamera-, Filterrad- oder Objektivwechsler-Implementierung.

## Ergebnis

Die neue Config-Struktur ist in main angekommen. Parser, Schema, Referenzprüfung,
physikalische Werte und statische/persistente Dateien sind vorhanden. Die neuen
Controller-Mappings sind noch nicht an die realen Hardwareaufrufe angeschlossen.
Ein erfolgreiches Laden der YAML ist deshalb noch kein Nachweis dafür, dass ihre
Hardwareadressen und Betriebsparameter verwendet werden.

Die bestehenden UC2RestBus-/UC2CanBus-Treiber und Manager bleiben die Grundlage.
Unser alter Integrationscommit wird nicht vollständig übernommen: Seine Config-
Klassen und Beispiele passen nicht zum jetzt maßgeblichen Controller-Mapping.

## Tatsächlicher Startpfad und Lücken

- `backend/main.py`: NEWSWITCH_CONFIG erwartet weiterhin JSON mit flachen
  ImswitchConfig-Overrides; die eigentliche Geräte-YAML wird separat geladen.
- `app.py:provide_managers`: open_config lädt static/persistent. Ein explizites
  config_file dient dort aber nur als Ein/Aus-Schalter, nicht als geladener Pfad.
- Realbetrieb wählt einen globalen Bus anhand uc2_transport und der alten
  uc2_can/uc2_rest-Dictionaries. Mehrere Controller werden nicht geroutet.
- Serial übernimmt höchstens Port/Baudrate des ersten passenden Controllers.
  Kein Match kann in die alte automatische Auswahl zurückfallen; mehrere Matches
  werden nicht als Mehrdeutigkeit behandelt.
- Stage-Limits kommen in StageState an. Kalibrierung, Invertierung, homing_required,
  Achszuordnung und Geschwindigkeit werden aber nicht vollständig in die realen
  Bewegungsaufrufe übernommen. Manager verwenden alte uc2_stage-Overrides/Defaults.
- Lichtmetadaten werden aufgebaut, für die reale Illumination jedoch weiterhin die
  alten uc2_illumination-Overrides/Defaults verwendet. Mapping-pwm_max und
  Node-/Ausgangsadressen bestimmen die Befehle noch nicht.
- adapters.illuminations verwendet source.channels als channel. channels ist die
  Anzahl der Farb-/Spektralkanäle, keine Hardwareadresse. Außerdem startet dort die
  erste Quelle im Modell mit 100 Prozent; das ist keine geeignete Startvorgabe für
  den Hardwarepfad. Derzeit ist dies keine Aussage, dass schon 100 Prozent an eine
  reale Quelle gesendet werden.
- Serial-Positionsfehler werden im vorhandenen RestBus teilweise als Position 0
  interpretiert. Die zuvor ergänzten strikteren Fehler-/Completion-Prüfungen fehlen.

## Zielarchitektur

stage.axes[direction] -> Axis-Geräteschlüssel -> config.controller_of(key)
-> ControllerConfig.connection + MappingEntry -> gemeinsamer Busclient
-> Motor-/Lichtaufruf mit konkreter Hardwareadresse.

Wichtig: Routing pro Achse, nicht pro Stage. Die neue Beispiel-Stage enthält schon
Achsen an unterschiedlichen Controllern. Lichtquellen werden separat pro Gerät
aufgelöst. Clients werden pro physischer Verbindung geteilt, Einstellungen auf
Widersprüche geprüft und Ereignisse zum logischen Gerät zurückübersetzt.

## Vor der Hardwareintegration festzulegender Adressvertrag

| Verbindung / Typ | Interpretation im Adapter |
| --- | --- |
| direkt CAN / canopen-motor | id = Node-ID; subid = nullbasierter Motorindex |
| direkt CAN / canopen-laser | id = Node-ID; subid = nullbasierter Ausgang |
| direkt CAN / LED-Matrix | eigener, dokumentierter Mapping-Typ; id = Node-ID |
| Serial / serial-laser | id = UC2-Master-Laserkanal; subid für diesen Aufruf nicht frei interpretieren |
| Serial / Motor | UC2-Master-Stepperadresse ausdrücklich definieren; logische x/y/z-Richtung davon unabhängig halten |
| Serial / LED-Matrix | eigener Mapping-Typ; aktueller Matrixaufruf hat keine frei wählbare Ausgangsadresse |
| Serial / canopen-* | Bridge-Semantik klären, bevor Node-/Subadressen umgesetzt werden |

subid ist dabei ein logischer Treiberkanal, kein beliebiger CANopen-Subindex. Der
Treiber kennt Parameterindizes und setzt bei entsprechenden UC2-Parametern
subindex = Kanal + 1 um. Diese Bedeutung muss mit Christian festgelegt werden;
MappingEntry beschreibt sie gegenwärtig nur allgemein als CAN sub id.

Die Beispiel-YAML enthält canopen-* hinter uc2-rest mit id 0 und subid 1/2.
Das ist kein verifiziertes Routing über den bisherigen Mastertreiber. Es darf
nicht ungeprüft als direkte CAN-Node-Adresse oder als Stepper-ID behandelt werden.

## Modell-/Validierungsarbeit

1. Mapping-Typen und erlaubte Kombinationen aus Typ und Protokoll explizit prüfen.
   Momentan ist type ein freier String. Unknown extras ersetzen keine Runtime-
   Validierung für Hardwareparameter.
2. Adressgrenzen und Eindeutigkeit passend zum Adressraum prüfen. Aktuell kollidieren
   gleiche id/subid auch zwischen Serial-Motor und Serial-Laser, obwohl getrennte
   Befehle sie adressieren. Umgekehrt können Controller am gleichen physischen Bus
   gleiche reale Ausgänge belegen, ohne dass die Mappingprüfung sie zusammenführt.
3. Nullbasiertes subid dokumentieren; direkte CAN-Node-ID 1..127 und Motorindices
   entsprechend dem Treiber prüfen. Sonderfälle von Bridges getrennt definieren.
4. Wieder aufnehmen: Homing-Geschwindigkeit/-Richtung/-Timeout und Bewegungstimeout.
   homing_order=null bedeutet im neuen Modell paralleles Homing; unser bisheriger
   Manager arbeitet sequenziell. Verhalten ausdrücklich entscheiden/implementieren.
5. Für Drehachse A gegebenenfalls steps_per_deg und Winkel-Einheiten ergänzen;
   die aktuelle AxisConfig behandelt Werte in um und hat nur steps_per_um.
6. Licht-Startzustand explizit festlegen: zunächst aus. Optionaler Startwert kann
   später ergänzt werden. PWM-Skalierung pro Mapping anhand pwm_max, derzeit kein
   ungeprüftes automatisches Auslesen aus der Firmware voraussetzen.
7. Matrix-Adressierung und RGB-Wertebereich dokumentieren. Mehrere Matrizen benötigen
   eine adressierbare öffentliche API; der bisherige Convenience-Aufruf hat keine
   Geräteauswahl. Erste Integration kann ausdrücklich eine Matrix unterstützen.
8. Bewegungsstage von zusätzlichen Wheel-Stages unterscheiden; nicht pauschal
   jede Config mit mehreren Stages ablehnen. Unsupported Hardware explizit melden,
   statt ungeprüft Standard-Objektiv-/Filterradadressen zu aktivieren.

## Umsetzung in abgegrenzten Schritten

1. Neuer Feature-Branch von diesem main; Mappingvertrag und Hardwarebeispiele zuerst.
   Beispiele für nur Serial, nur direkt CAN und gemischten Betrieb, zunächst ohne
   Kamera/Wheels. Nur configs/ (kleingeschrieben) verwenden, auch in Tests/Docs.
2. Runtime-Plan aus Controller-Mappings erstellen: Achsen, Lichtquellen,
   Verbindungen, Skalierung und Parameter auflösen; fehlende Zuordnungen ablehnen.
3. Busrouter/Client-Pool und Event-Rückweg aus unserem alten Branch adaptieren.
   Nicht den alten Parser und keine alten Binding-Klassen wieder einführen.
4. Realen App-Start vollständig auf diesen Plan umstellen; JSON-Overrides nicht
   mehr als zweite Hardwarequelle verwenden. Config-Auswahl über einen eindeutigen
   YAML-Pfad ermöglichen, statischen Input niemals überschreiben und Christians
   persistenten Speicherweg erhalten. Simulation ausdrücklich separat halten.
5. Alte Stage-/Illumination-Erweiterungen selektiv portieren: pro Achse Kalibrierung,
   Grenzen, Geschwindigkeit/Beschleunigung, Invertierung, Homingpflicht, achsweise
   Serialisierung; logische Lichtslots, individuelle PWM-Bereiche und CAN-Nodes.
6. Treiberkorrekturen portieren und mit den tatsächlich installierten UC2-Libraries
   erneut prüfen: Serial-Homing/Done-Ereignisse, keine erfundenen Nullpositionen,
   Timeouts als äußere Frist, Completion-Fehler, CAN-Eventfilter für konfigurierte
   Achsen. Timeout/Abbruch muss Stop auslösen; Reconnect invalidiert Homingstatus.
7. Tests und Geräteabnahme: geänderte IDs müssen nachweislich die Treiberaufrufe
   ändern, unbekannte/mehrdeutige Zuordnungen dürfen keine Hardware ansprechen.

## Wiederverwendbare Arbeit aus 81d00d8

- yaml_runtime.py: Pooling, Routing, Lichtskalierung, Grenzen, Homingstatus,
  Ereignisaggregation und Reconnect-Grundstruktur. Konstruktion auf neue Modelle
  umschreiben; Verbindung pro Axis-Gerät statt pro Stage auswählen.
- canopen_bus.py/rest_bus.py: zusätzliche Adressparameter und Treiberkorrekturen.
- stage_manager.py: pro Achse Geschwindigkeit/Beschleunigung und Fehler bei nicht
  konfigurierten Achsen.
- illumination_manager.py: logische Slots unabhängig vom Hardwarekanal und PWM
  pro Lichtquelle.
- test_yaml_hardware.py: Tests auf das neue Schema übertragen und um die neuen
  per-axis Controller-Routen sowie Adressraumkollisionen ergänzen.

## Verifikation dieser Bestandsaufnahme

Auf main 89ef2ca: 167 Tests erfolgreich
(tests/config_io, test_app_config.py, test_uc2_bus.py, test_uc2_wave1.py).
Vorhandene virtuelle Umgebung verwendet; kein neuer Dependency-Sync vorgenommen.
Diese Tests ersetzen keine Abnahme der neuen YAML-zu-Hardware-Integration.
Keine physische Hardware verbunden/getestet; keine Hardwarebefehle ausgeführt.
In diesem Schritt wurde Hardwarecode nicht geändert.
