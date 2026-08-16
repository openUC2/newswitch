-> VirtualDetectorManager
    -> Setzt offensichtlich Defaultdetektoren

1. wozu gibt es folgende States im VirtualDetectorManager
        stage_state
        objective_state
        illumination_state
        filter_bank_state
    Diese haben doch erst mal nichts mit den Detektoren zu tun?

**Antwort:**

Sie haben nichts mit *Detektoren* zu tun, aber alles mit *Bildentstehung*. Der `VirtualDetectorManager` ist kein Treiber, sondern ein **Simulator**: Er liest keine Pixel aus, er *berechnet* sie. Damit werden die vier States zu Eingangsgrößen des Bildentstehungsmodells:

| State | Verwendung | Fundstelle |
|---|---|---|
| `stage_state.x/y` | Verschiebung des Probenbilds | `virtual_detector.py:449-453` |
| `stage_state.z` | Defokus / PSF-Faltung | `virtual_detector.py:469-480` |
| `objective_state.magnification` | Zoom-Faktor | `virtual_detector.py:455-459` |
| `illumination_state.illuminations` | Helligkeit (Summe aktiver Quellen) | `virtual_detector.py:398-417` |
| `filter_bank_state` | spektrale Transmission (Gauß-Profil) | `virtual_detector.py:358-396` |

In der echten Anlage entsteht diese Kopplung über Physik (Photonen). In der Simulation muss sie explizit modelliert werden — deshalb die Injektion.

**Gegenprobe:** Der `Uc2DetectorManager` nimmt exakt dieselben Parameter entgegen, benutzt sie aber nicht (`uc2_detector_manager.py:57-61`, Kommentar: *"accepted for drop-in parity with VirtualDetectorManager (unused here)"*). Das bestätigt: Diese States sind reine Simulationsabhängigkeiten und gehören bewusst **nicht** ins `DetectorManager`-Protokoll, sondern nur in den Konstruktor. Das ist richtig so — das Protokoll bleibt sauber.

**Kritik / Empfehlung:**

a) Die States sind für den Detektor *lesend*, das wird aber nirgends erzwungen. Rekuest kennt dafür `Annotated[StageState, ReadOnly]` (`rekuest_next/state/predicate.py:22-35`). Die Konstruktorparameter sollten so typisiert werden.

b) Vier injizierte States sind ein Geruch für zu viele Kollaborateure. Sauberer wäre, die Bildentstehung komplett in eine eigene Klasse (`VirtualScene` / `SampleSimulator`) zu ziehen, die diese vier States kapselt. Der `VirtualDetectorManager` hinge dann nur noch an *einem* Kollaborateur und täte nur noch Detektor-Dinge (Slots, Belichtung, Gain, Aktivierung). Das löst gleichzeitig Frage 4.

c) Der Manager liest diese States, ohne deren Locks (`stage_position`, `illumination`, `filter_bank`, `objective`) zu halten. Im Hintergrund-Loop `acquire_live` (`virtual_detector.py:698-722`) kann parallel geschrieben werden → ein Frame kann aus inkonsistenten Zuständen entstehen (z. B. X schon neu, Y noch alt). Praktisch harmlos (nur ein Simulationsartefakt), sollte aber bewusst dokumentiert und nicht zufällig sein.

---

2 Warum trennt man VirtualDetectormanager und UC2Detectormanager auf und nutzt nicht einen allgemeinen Detektormanager, der generelle Detektorstrukturen verwaltet? Tatsächlich gibt es sowas auch schon unter Protocolls/DetecotroManager(Manager, Protocol)

**Antwort:**

Hier werden zwei Ebenen verwechselt:

- `protocols/detector.py:88` — `DetectorManager(Manager, Protocol)` **ist** der allgemeine Detektormanager. Aber nur als **Vertrag**: Er beschreibt, *was* jeder Detektormanager kann, ohne jede Implementierung.
- `VirtualDetectorManager` und `Uc2DetectorManager` sind die zwei **Implementierungen** dieses Vertrags — Simulation vs. echte Kameras.

Die beiden unterscheiden sich fundamental im *Wie*: Der eine rechnet Frames mit NumPy, der andere ruft `Uc2Camera.grab_frame()` auf einem SDK-Handle. Es gibt praktisch kein gemeinsames Verhalten, das man teilen könnte. Der Umschaltpunkt liegt an genau **einer** Stelle (`app.py:188-203`, `config.use_virtual_microscope`); der gesamte Rest der Anwendung sieht nur `DetectorManager`. Das ist genau das Muster, das man will.

**Aber der Instinkt ist teilweise richtig — es gibt tatsächlich vermeidbare Duplikation:**

`get_detector_state`, `list_available_detectors`, `list_active_detectors` sind reine State-Abfragen und in beiden Implementierungen bedeutungsgleich (`virtual_detector.py:583-611` vs. `uc2_detector_manager.py:184-197`).

**Empfehlung:** Diese Methoden gehören nicht in einen gemeinsamen Manager, sondern an den `CameraState` — wo sie zum Teil schon liegen (→ Frage 3). Beide Manager delegieren dann nur. Übrig bleibt in den Implementierungen genau das, was sich wirklich unterscheidet: `capture_image`, `acquire_live`, `activate/deactivate_detector`, `update_detector`, `_initialize_detectors`. Falls doch geteilter Code nötig wird, ist ein `DetectorManagerBase`-Mixin (ohne Protokolländerung) der leichtgewichtige Weg — keine Vereinigung der beiden Manager.

---

3. Warum werden folgende Funktionen implementiert (Es wirkt als werden die doppelt im CameraState und im Manager implementiert) -> Es wird ja sogar auf die States verwiesen?
    _get_active_detector()
    _get_dtector(slot)
    _get_active_detectors()

**Antwort:**

Das ist echte Duplikation und aus meiner Sicht ein **Mangel, keine Entwurfsentscheidung**.

`CameraState` bietet bereits (`protocols/detector.py:70-83`):
- `get_active_detectors() -> list[Detector]`
- `get_detector_for_slot(slot) -> Detector` (wirft `ValueError`)

Der `VirtualDetectorManager` implementiert dieselbe Schleife erneut (`virtual_detector.py:255-271`):
- `_get_detector(slot)` → identisch zu `get_detector_for_slot`, gibt aber `None` statt `ValueError`
- `_get_active_detectors()` → 1:1 identisch zu `state.get_active_detectors()`
- `_get_active_detector(slot|None)` → zusätzliche Semantik *„erster aktiver Detektor"* — diese existiert am State **nicht**

**Der eigentliche Befund ist die Inkonsistenz zwischen den beiden Implementierungen:** Der `Uc2DetectorManager` benutzt die State-Methoden (`state.get_detector_for_slot`, `state.get_active_detectors`), der `VirtualDetectorManager` seine eigenen. Damit haben zwei Implementierungen desselben Protokolls **unterschiedliches Fehlerverhalten** bei unbekanntem Slot: virtuell → `None`, Hardware → `ValueError` (in `get_detector_state` abgefangen, in `activate_detector` nicht). Das ist ein realer Verhaltensunterschied zwischen Simulations- und Hardwarebetrieb.

**Empfehlung:**
- `_get_detector` und `_get_active_detectors` im `VirtualDetectorManager` löschen, `self.state.*` verwenden.
- Falls die `None`-Semantik gebraucht wird: `CameraState.get_detector_for_slot_or_none(slot)` ergänzen — einmal, für beide.
- `_get_active_detector(slot=None)` ebenfalls an den State verschieben (`CameraState.get_active_detector(slot=None)`), da es eine reine Abfrage über eigene Daten ist.

**Faustregel für die Grenze State/Manager:** Reine Abfragen über die eigenen Daten des States gehören an den State. Alles, was Hardware, Zeit, Zufall oder Seiteneffekte berührt, gehört an den Manager.

---

4. Warum werden folgende FUnktionen nicht in der DetectorClass implementiert? (Ich weiß, es ist eigentlich eine Dataclass und hält deswegen eigenschaften, allerdings sind u.g. Funktionen auch Teil des Eigenschafts und Methodenraumes eines Detectors)
    _generate_frame(self, detector: Detector)
    _generate_astigmatism_frame(self, detector: Detector)
    activate_detector(self, slot: int, raise_on_active: bool = False)
    deactivate_detector(self, slot: int)
    update_detector(
        self, slot: int, exposure_time: Optional[float] = None, gain: Optional[float] = None
    ) -> Detector:

**Antwort:**

Die Frage zerfällt in zwei Gruppen mit unterschiedlicher Antwort.

**Gruppe A — `_generate_frame` / `_generate_astigmatism_frame`: gehören korrekterweise NICHT an `Detector`.**

Sie brauchen weit mehr als den Detektor selbst: Stage-/Objektiv-/Beleuchtungs-/Filter-States, das vorgenerierte Probenbild `self._sample_image`, den RNG `self._rng`, den Cache `self._cache` und die Config. `Detector` ist eine `@model`-Dataclass (`rekuest_next/structures/model.py:61`), die **serialisiert und ans Frontend geschickt** wird. Läge die Bildgenerierung dort, müsste das State-Modell NumPy-Arrays, einen RNG und einen Cache tragen — das zerstört die Serialisierbarkeit und vermischt Transportdaten mit Simulations-Engine.

Zusätzlich: Diese Methoden sind rein virtuell. Ein echter Detektor hat kein `_generate_frame`. Sie gehören damit weder an `Detector` noch — streng genommen — an den Manager, sondern in eine eigene Simulator-/Szenenklasse (siehe Frage 1b).

**Gruppe B — `activate_detector` / `deactivate_detector` / `update_detector`: der Instinkt ist richtig, aber nur zur Hälfte — und genau diese Hälfte ist der Grund, warum sie am Manager bleiben müssen.**

- Virtuell: `detector.is_active = True` — reine Datenmutation, funktionierte auch am `Detector`.
- UC2 (`uc2_detector_manager.py:150-182`): `cam.start()`, `cam.stop()`, `cam.set_exposure_time()`, `cam.set_gain()` — es muss **vor** der Datenmutation ein Hardwareaufruf stattfinden. Eine `Detector`-Dataclass hat kein Kamera-Handle und darf keines bekommen (sie wird serialisiert).

Die *Semantik* „Detektor aktivieren" ist also Gerätverhalten → Manager.

**Was sinnvoll an `Detector` wandern könnte, ist der reine Validierungsanteil:**

`Detector.clamp_exposure(value)` / `Detector.clamp_gain(value)` — anstelle des anonymen `_clamp` (`virtual_detector.py:506-509`), das heute nur im virtuellen Manager existiert. Denn: **`Uc2DetectorManager.update_detector` klemmt gar nicht** (`uc2_detector_manager.py:176-181`). Im Simulationsbetrieb wird eine zu große Belichtungszeit auf `max_exposure_time` begrenzt, im Hardwarebetrieb ungeprüft an die Kamera weitergereicht. Da `min_*`/`max_*` ohnehin am `Detector` liegen, würde ein `clamp_*` dort diesen Bug an einer Stelle für beide Implementierungen beheben.

---

5. Bei get_detecotr_state(slot: int) wird ein Detector zurück gegeben oder none. Aber nicht der State. Warum?

**Antwort:**

Weil `Detector` **der State ist** — die Benennung ist irreführend, nicht das Verhalten.

Es gibt zwei State-Ebenen:

- `CameraState` (`protocols/detector.py:59`) = der **aggregierte**, agent-sichtbare State, den Rekuest publiziert (`@state(required_locks=["camera_parameters"])`). Enthält `is_acquiring` und die Liste `detectors`.
- `Detector` (`protocols/detector.py:30`) = der **State-Datensatz pro Slot**. Der eigene Docstring sagt es wörtlich: *„Shared state for detector parameters."* Als `@model` ist er ein serialisierbares Kind des State-Baums, kein Geräteobjekt.

`get_detector_state(slot)` liefert also korrekt „den Zustand des Detektors in diesem Slot". Der Eindruck entsteht nur, weil das Wort `Detector` nach Gerät klingt und der Methodenname eine `*State`-Klasse suggeriert.

`Optional`, weil der Slot nicht existieren muss: Virtuell gibt `_get_detector` `None` zurück (`virtual_detector.py:260`); UC2 fängt das `ValueError` des States ab und wandelt es in `None` (`uc2_detector_manager.py:186-189`). Das Protokoll fixiert die `None`-Semantik damit bewusst.

**Empfehlung (reine Benennung, kein Verhaltenswechsel):** Entweder `get_detector_state` → `get_detector(slot)` umbenennen, oder das Modell `Detector` → `DetectorState` und den Methodennamen behalten.

Grundproblem: Das Wort „Detector" bezeichnet in diesem Modul aktuell drei verschiedene Dinge — das Protokoll `DetectorManager`, den State-Datensatz `Detector` und das Hardwareobjekt `Uc2Camera`. Diese Begriffe zu trennen ist der billigste Lesbarkeitsgewinn im ganzen Modul.

---

6. Mein generelles Verständniss: In Protocolls existieren Vorlagen für Geräteimplementationen. Das ist so ähnlich wie man es mit einer abstrakten Klassenstruktur umsetzen würde, aber eben ohne vererbung um harte Abhängigkeiten zu umgehen (Dependency injection). Dazu gehört z.b. der DetectorManager und der Detector. (Warum ist bei DetectoManager nichts implementiert? Weil es fehlt oder weil der Mechanismus nur einen Funktionsbeschreibung verlangt? dann könnte man aber auch wirklich gleich mit abstrakten Klassen arbeiten!)

**Antwort:**

Das Verständnis ist korrekt — mit einer entscheidenden Ergänzung.

**Was stimmt:** `protocols/` enthält strukturelle Verträge (PEP 544 `Protocol`). Eine Implementierung erbt *nicht*, sie muss nur strukturell passen („statisches Duck Typing"). `VirtualDetectorManager` (`virtual_detector.py:116`) und `Uc2DetectorManager` (`uc2_detector_manager.py:44`) erben von nichts. Vorteile gegenüber ABC: keine harte Importabhängigkeit Implementierung→Interface, Implementierungen dürfen aus Fremdpaketen kommen, mehrere Protokolle ohne Mehrfachvererbung erfüllbar.

**„Warum ist nichts implementiert?"** → Per Definition, es fehlt nichts. In einem Protocol *ist* der Rumpf `...` die Signaturdeklaration; der Typechecker prüft dagegen. Eine Implementierung im Protocol-Rumpf würde nur geerbt, wenn man erben würde — und genau das will man hier vermeiden. Der Mechanismus verlangt tatsächlich nur die Funktionsbeschreibung.

**„Dann könnte man auch gleich abstrakte Klassen nehmen"** — nein, und hier kommt der projektspezifische Grund:

`@context(locks=[...])` steht **auf dem Protokoll** (`protocols/detector.py:86`). Rekuest benutzt die Protokollklasse als **Injektions-Schlüssel und als Lock-Metadatum**. In `app.py:562` bewirkt der Parameter `detector: DetectorManager`, dass (a) der unter dem Context-Namen `detector_manager` registrierte Manager injiziert wird und (b) diese Funktion automatisch das Lock `camera_parameters` hält (`actify.py:56-62`, `auto_locks` ist standardmäßig `True`). Das Protokoll ist hier also nicht nur Typprüfhilfe, sondern **Laufzeit-Metadatum**. Eine ABC könnte das prinzipiell auch — würde die Implementierungen aber wieder in Vererbung zwingen, und `Uc2DetectorManager` will explizit ein Drop-in bleiben, ohne von der newswitch-Klassenhierarchie abzuhängen.

**Ehrliche Einschränkung — der Vertrag wird aktuell nur schwach durchgesetzt:**
- `Manager` (`protocols/base.py:6-12`) ist leer, fügt also nichts hinzu.
- Es gibt im gesamten Code **kein einziges** `isinstance(x, DetectorManager)` (geprüft).
- `shutdown()` und `background()` existieren in beiden Implementierungen, stehen aber in **keinem** Protokoll.

Heute prüft also nur der Typechecker (mypy/pyright). **Empfehlung:** (a) `shutdown()` in `Manager` oder ein `ClosableManager`-Protokoll aufnehmen, (b) in `provide_managers` je ein `assert isinstance(detector, DetectorManager)` — das ist der eigentliche Nutzen von `runtime_checkable` (→ Frage 7), der derzeit verschenkt wird.

---

7. was macht der Context-Decorator und der runtime_checkable decorator?

**Antwort:**

**`@context`** (`rekuest_next/agents/context.py:70-120`) — reines Metadatum, kein Wrapping. Er setzt zwei Attribute auf die Klasse:
- `__rekuest_context__` = snake_case-Klassenname (`DetectorManager` → `detector_manager`) — der Schlüssel, unter dem das Objekt registriert und injiziert wird.
- `__rekuest_context_locks__` = die Liste aus `locks=[...]`.

Ausgewertet wird das an zwei Stellen:

1. **Startup-Hook** (`app.py:107`): Das von `provide_managers` zurückgegebene Tupel wird anhand der **Rückgabe-Typannotation** klassifiziert — jede Position mit `@state` wandert in die State-Registry, jede mit `@context` in die Context-Registry (`agents/hooks/startup.py`, `WrappedStartupHook.arun`).
2. **Jede `@register`-Funktion**: Parameter mit Context-Typ bekommen das Objekt injiziert, und die Locks werden abgeleitet (`derive_implementation_details`, `actify.py:51-62`).

**`@runtime_checkable`** (stdlib `typing`) — erlaubt `isinstance(obj, DetectorManager)` zur Laufzeit für ein Protocol. Ohne den Dekorator wirft `isinstance` einen `TypeError`.

Wichtige Einschränkung: Er prüft **nur die Existenz der Member anhand ihrer Namen** — nicht Signaturen, nicht Typen. `isinstance(x, DetectorManager)` ist `True`, sobald `x` Attribute namens `capture_image`, `activate_detector`, … besitzt, egal mit welchen Parametern.

**Befund:** `runtime_checkable` steht auf allen 15 Protokollen dieses Projekts, es existiert aber kein einziger `isinstance()`-Aufruf dagegen. Aktuell ist der Dekorator also **totes Beiwerk**. Entweder nutzen (Assertions beim Startup, siehe Frage 6) oder entfernen — er ist billig, ich würde ihn nutzen.

**Zum Vergleich `@state`** (`state/decorator.py:120`) — tut deutlich mehr als `@context`: macht die Klasse zur Dataclass, baut ein Port-Schema, registriert sie in der `AppRegistry` und umhüllt `__init__`, damit `make_evented` die Instanzklasse austauscht. Erst dadurch erzeugen Mutationen JSON-Patches (RFC 6902) Richtung Frontend, und erst dadurch greift die Lock-Prüfung (`__check_if_has_required_locks`, `state/observable.py:119-125`).

---

8. auch die Einträge in DetectorConfig und in Detector scheinen sich zu doppeln warum?

**Antwort:**

Zwei unterschiedliche Rollen mit teilweiser Überlappung — plus ein echter Bug.

- **`DetectorConfig`** (`virtual_detector.py:89-113`): eine `@model @dataclass`, aber **kein** `@state`. Sie ist die **Simulationskonfiguration** des virtuellen Managers: Probentyp, Probengröße/-seed, Rauschparameter, Astigmatismusparameter — nichts davon existiert an einem echten Detektor. Zusätzlich enthält sie **Default- und Grenzwerte**, aus denen die `Detector`-Objekte gebaut werden.
- **`Detector`** (`protocols/detector.py:30-55`): der **Laufzeit-State pro Slot**, Teil des publizierten State-Baums, von beiden Managern benutzt.

Die überlappenden Felder (`width/height`, `min/max_exposure`, `min/max_gain`, `default_exposure/default_gain`) folgen dem Muster *„Werksvorgabe → Instanzwert"*: `_initialize_detectors` (`virtual_detector.py:181-230`) kopiert Config-Werte in jeden `Detector`, der danach individuell verstellbar ist. Das ist im Prinzip legitim.

**Drei reale Probleme dabei:**

1. **`width`/`height` ist keine Vorgabe, sondern wird parallel benutzt — und zwar inkonsistent.**
   `_initialize_detectors` schreibt `width=1024, height=1024` in jeden Detector (`virtual_detector.py:187-188` u. a.), während die Frame-Erzeugung `self.config.width/height` = **512** benutzt (`extract_roi`, `virtual_detector.py:462-466`; `_compose_rgb_frame`, `virtual_detector.py:645-648`). Der ans Frontend publizierte State behauptet also 1024×1024, die tatsächlichen Frames sind 512×512. **Das ist ein Bug, kein Doppelungsproblem.** Entweder benutzt `_generate_*` `detector.width/height`, oder der `Detector` bekommt die Config-Werte.

2. **`Detector.is_acquiring`** (`protocols/detector.py:50`) dupliziert `CameraState.is_acquiring` (`protocols/detector.py:67`). Benutzt wird ausschließlich das am `CameraState` (`app.py:545`/`557`, `acquire_live` `virtual_detector.py:708`). Das Feld pro Detektor ist tot und irreführend — entfernen oder tatsächlich pro Slot verwenden.

3. **`DetectorConfig` vermischt zwei Anliegen**: Detektor-Defaults (Belichtung/Gain/Größe) und Szenensimulation (`sample_*`, `astig_*`, Rauschen). Zieht man den Szenensimulator heraus (→ Frage 1b / 4A), zerfällt diese Config entlang derselben Naht, und die Überlappung mit `Detector` schrumpft auf die reinen Defaults zusammen.

**Nebenbefund:** Der `Uc2DetectorManager` hat gar keine Config — er liest `Uc2DevSettings` aus JSON (`uc2_detector_manager.py:66`) und baut die `Detector`-Objekte aus `cam.frame_format` (`uc2_detector_manager.py:107-118`). Er klemmt deshalb überhaupt nicht gegen `min/max` — siehe Frage 4, Gruppe B.

---

9. Wie sind states und managers miteinander verbunden?

**Antwort:**

In fünf Schichten, von unten nach oben:

**1. Konstruktion und Besitzverhältnis** (`app.py:150-264`)
States werden zuerst und eigenständig erzeugt (`CameraState()`, `StageState()`, …). Danach werden die Manager gebaut und bekommen den State **hineingereicht** (`VirtualDetectorManager(camera_state=…, stage_state=…, …)`, `app.py:189-196`).

> **Manager → hält Referenz → State. Niemals umgekehrt. Ein State kennt keinen Manager.**

Das ist die Kernregel und sie wird konsequent eingehalten (`LightPathManager` und `MetadataManager`, `app.py:233-250`, nehmen 5–6 States und keinen Manager).

**2. Registrierung über die Rückgabeannotation des Startup-Hooks** (`app.py:108-136`)
Das von `provide_managers` zurückgegebene Tupel wird **anhand der Typannotation** klassifiziert, nicht anhand der Werte: alles mit `@state` → State-Registry, alles mit `@context` → Context-Registry. Beide leben danach als Singletons im Agenten.

> **Fragilität:** Position im Rückgabetupel und Position in der Annotation müssen exakt übereinstimmen. Eine Vertauschung zweier Einträge gleichen Typs fällt nicht auf. Bei 26 Rückgabewerten ist das ein reales Risiko und sollte kommentiert werden.

**3. Injektion in registrierte Funktionen**
Eine `@register`-Funktion deklariert ihren Bedarf per Typ:
- `detector: DetectorManager` → Context → die Manager-Instanz (`app.py:562`)
- `camera_state: CameraState` → State → die State-Instanz (`app.py:537`)
- beides gemeinsam, wo nötig (`app.py:502-519`)

Aufgelöst wird das über `prepare_state_variables` / `prepare_context_variables` aus den Typhints.

**4. Locking wird aus *beiden* Seiten abgeleitet**
`@state(required_locks=["camera_parameters"])` (`protocols/detector.py:58`) und `@context(locks=["camera_parameters"])` (`protocols/detector.py:86`) deklarieren denselben Lock-Namen. `derive_implementation_details` (`actify.py:51-62`) bildet die Vereinigung über alle State- und Context-Parameter einer Funktion (`auto_locks=True` per Default). Eine Funktion, die nur `detector: DetectorManager` entgegennimmt, hält deshalb implizit `camera_parameters`. Explizite Übersteuerung ist möglich: `@register(locks=["stage_position"])` (`app.py:415`).

**5. Beobachtung und Publikation**
`@state` tauscht die Instanz in eine „evented" Klasse (`make_evented`, `state/decorator.py:89-95`). Jede Mutation — auch `detector.is_active = True` **im Manager** — erzeugt einen JSON-Patch ans Frontend und wird mit `RuntimeError` abgelehnt, wenn das nötige Lock fehlt (`state/observable.py:119-125`, `282-288`). **Manager sind nicht evented und werden nicht publiziert.**

**Das resultierende Denkmodell:**

| | State | Manager | Protocol |
|---|---|---|---|
| Rolle | beobachtbares, serialisierbares Datenabbild | serverseitiges Verhalten | Vertrag + Injektions-/Lock-Schlüssel |
| Frontend-sichtbar | ja | nein | — |
| enthält | nur reine Abfragen über eigene Daten | Hardware, Zeit, Zufall, Seiteneffekte | nur Signaturen |

Der State ist der **einzige** Kanal vom Manager zum Frontend. Daraus folgen zwei Regeln:
- Ein Manager darf keinen Gerätezustand privat halten, den das Frontend sehen muss — der muss in den State.
- Umgekehrt darf kein Simulationsinterna (`_cache`, `_rng`, `_sample_image`) in den State.

**Zwei Schwachstellen, die aus dieser Struktur folgen:**

a) **Keine Änderungsbenachrichtigung.** Die Richtung State → Manager existiert bewusst nicht. Der `VirtualDetectorManager` muss deshalb pollen (`acquire_live` liest jede Iteration alle States) und braucht manuelle Cache-Invalidierung. `invalidate_illumination_cache` (`virtual_detector.py:247-253`) wird allerdings **von nichts aufgerufen** — funktional gedeckt durch den Cache-Key-Vergleich in `_get_illumination_cache_key`, aber die Methode ist toter Code und suggeriert einen Mechanismus, den es nicht gibt.

b) **Manager-Lebenszyklus ist unvollständig verdrahtet.** Der `@shutdown`-Hook `release_managers` (`app.py:298-318`) nimmt `detector: DetectorManager` entgegen, ruft aber **nie** `detector.shutdown()` auf. Im Hardwarebetrieb ist genau `Uc2DetectorManager.shutdown()` (`uc2_detector_manager.py:125-141`) die Stelle, die die Kameras trennt — die Kameras werden also derzeit nie freigegeben. Konkreter Bug.
