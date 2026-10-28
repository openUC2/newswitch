# Bugreport: H.264-Livebild zwischen `FrameBroadcaster` und Frontend

Stand: 2026-10-28, Branch `KC/CamAdapter` (Commit `6343890`).

## Symptome

Simulierte Kamera aus uc2_cam_py (`use_virtual_microscope: false`,
`static_config_path: camTest_config.yaml`), Frontend über `just dev`. Die Frames kommen in
`FrameBroadcaster._schedule_encoder_frames` an. Mit aktivem Livestream im Frontend:

- es wird nur ein Ausschnitt des Bildes dargestellt,
- die Bildrate ist sehr niedrig,
- nach einiger Zeit friert das Bild ein.

## Kurzfassung

| Symptom | Ursache | Bug |
|---|---|---|
| Einfrieren | Der H.264-Bytestrom wird im Backend zerstückelt (ein Drittel der Bytes und praktisch alle Keyframes gehen verloren). Der Browser-Decoder bricht beim ersten beschädigten Frame ab, und das Frontend erholt sich davon nicht. | 1, 2 |
| Ausschnitt | Die Live-Ebene ist ≈ 328 Szeneneinheiten groß, die 2D-Kamera zeigt bei `zoom={5}` aber nur Canvas-Pixel / 5 Einheiten. | 3 |
| niedrige Bildrate | `koil.sleep(0.01)` dauert ≈ 100 ms: Die Live-Loop schafft 10–13 fps statt der 20 fps der Kamera. Dazu kommen beschädigte Frames und die feste Annahme von 30 fps im Player. | 4, 1, 5 |

Das Backend selbst friert nicht ein: In 3 Minuten Messung lief der Strom mit konstant ≈ 13 fps
bis zum WebSocket.

## Messungen

Aufbau: Backend in-process mit camTest (Auth aus, `camera_debug_window: false`), Live-View per
`POST /start_live_view`, ein Python-WebSocket-Client an `/stream/h264/1`. An jeder Stufe wurde
mitgezählt, und der empfangene sowie der vollständige ffmpeg-Strom wurden mitgeschnitten. Die
Mitschnitte wurden anschließend in headless Chromium (Playwright) über JMuxer 2.1.0 abgespielt,
mit denselben Optionen wie in `useH264LiveTexture`. Die Skripte lagen im Session-Scratchpad und
sind nicht im Repository.

| Stufe | Messwert (Lauf über 180 s) |
|---|---|
| Kamera (konfiguriert) | 20 fps, 640×480, `uint16` |
| `broadcast_sync` ohne Client | 10,0 fps (Median-Abstand 100 ms) |
| `broadcast_sync` mit Client | 13,3 fps (Median-Abstand 88 ms) |
| `H264Encoder.encode_frame` | Median 2,3 ms, max. 107 ms, läuft im Detektor-Thread |
| ffmpeg-Ausgabe | 10,0 MB in 3200 Chunks; 80 Keyframes, jeder mit SPS/PPS; 7 Slices pro Bild |
| in `EncoderSubscription` verworfen | 812 Chunks = 3,3 MB (33 %) |
| WebSocket empfangen | 2387 Chunks (genau 1 pro Frame), 6,7 MB |
| davon SPS/PPS | 1 von 80 (nur der allererste) |
| davon IDR-Slices | 81 von 560 |
| Bilder ohne ersten Slice | 733 von 2388 (31 %) |

Abspielen im Browser (Mitschnitt über 25 s):

- **Vollständiger ffmpeg-Strom:** 327 von 327 Frames decodiert, kein Fehler.
- **Beim Client angekommener Strom:** `video.error` Code 3,
  `PIPELINE_ERROR_DECODE: Failed to send video packet for decoding` bei Medienzeit 0,627 s.
  JMuxer meldet danach `InvalidStateError` und setzt sich zurück, ohne dass bis zum Ende des
  Mitschnitts noch ein Frame decodiert wird.

---

## 1 · H.264-Bytestrom wird in der Subscription-Queue zerstückelt (Hauptursache)

**Beschreibung.**
[`EncoderSubscription`](../backend/newswitch/broadcasters/encoders/subscription.py#L29-L31)
hält genau einen Chunk (`asyncio.Queue(maxsize=1)`). Ist die Queue voll, verwirft
[`push_chunk`](../backend/newswitch/broadcasters/encoders/subscription.py#L56) den ältesten.
Für Zstd ist das vertretbar, weil dort ein Chunk ein ganzes Frame ist. Für H.264 sind es
4096-Byte-Stücke eines fortlaufenden Bytestroms
([`_read_output`](../backend/newswitch/broadcasters/encoders/h264_encoder.py#L133-L138)).

Dass fast immer etwas verworfen wird, liegt an asyncio: `StreamReader.read(4096)` kehrt ohne
Rückgabe an den Event-Loop zurück, solange sein Puffer Daten enthält. Die Reader-Task schiebt
deshalb alle Chunks eines ffmpeg-Ausgabeblocks direkt hintereinander in die Queue, und der
WebSocket-Handler ([`liveview.py:185`](../backend/newswitch/routes/ws/liveview.py#L185)) kommt
erst danach wieder an die Reihe. Pro Frame überleben so nur die letzten ≤ 4096 Bytes, gemessen:
genau ein WebSocket-Chunk pro Frame.

Folgen:

- Keyframes (IDR mit SPS/PPS, meist deutlich größer als 4 KB) kommen praktisch nie an: 1 von 80.
  Damit gibt es keinen Punkt, an dem sich der Decoder erholen kann.
- `-tune zerolatency` lässt x264 jedes Bild in 7 Slices aufteilen (sliced threads). Fehlt der
  erste Slice eines Bildes (31 % der Bilder), hängt JMuxer die restlichen Slices an das
  vorherige Sample. Es entstehen ungültige Samples, und der Decoder bricht ab (siehe Bug 2).
  Ein fehlertoleranterer Decoder würde stattdessen nur Teile des Bildes (einzelne Streifen)
  aktualisieren, was ebenfalls wie ein Ausschnitt aussehen kann.

Bereits als Risiko in OP #30 und
[`LIVE-IMAGE-PIPELINE.md`](../backend/docs/LIVE-IMAGE-PIPELINE.md) §8 erwähnt. Hiermit ist
bestätigt, dass dies die Hauptursache ist.

**Fixvorschlag.**

1. Sofortmaßnahme: Der H.264-Pfad darf keine Bytes verwerfen. Eine Queue ohne Größenlimit
   (oder ein großes Limit) für H.264-Subscriptions, z. B. über einen Parameter `maxsize` von
   `EncoderSubscription`, den der H.264-Encoder anders setzt als der Zstd-Encoder. Zusätzlich
   in größeren Blöcken lesen (`read(65536)`), das spart WebSocket-Nachrichten.
2. Robuste Lösung: ganze Frames (Access Units) statt 4096-Byte-Stücken verteilen. Dazu z. B.
   ffmpeg mit `-x264-params aud=1` starten und am Access Unit Delimiter trennen. Läuft die Queue
   eines langsamen Clients über, alles bis zum nächsten IDR (mit SPS/PPS) verwerfen. Der Client
   verliert dann ganze Frames, aber nie Teile davon. Ein neuer Client bekommt erst ab dem
   nächsten Keyframe Daten. Alternativ SPS/PPS und den letzten IDR zwischenspeichern und beim
   Subscribe zuerst senden.
3. Test: einen Ausgabeblock > 4096 Bytes einspeisen und prüfen, dass alle Bytes vollständig und
   in Reihenfolge beim Subscriber ankommen.

Die Zstd-Route verwendet `use_delta=True`
([`liveview.py:125`](../backend/newswitch/routes/ws/liveview.py#L125)). Dort zerstört ein
verworfenes Delta-Frame die Rekonstruktion ebenfalls. Das betrifft das Frontend derzeit nicht,
weil der Zstd-Pfad dort nicht genutzt wird.

## 2 · Frontend erholt sich nicht von einem Decoder-Fehler (dauerhaftes Einfrieren)

**Beschreibung.**
[`useH264LiveTexture`](../frontend/src/components/stage/hooks/useH264LiveTexture.tsx#L66-L98)
setzt weder JMuxers `onError` noch einen Listener für `error` am `<video>`-Element. Nach dem
ersten Decoder-Fehler (gemessen: `PIPELINE_ERROR_DECODE`, danach `InvalidStateError`) setzt
JMuxer seine MediaSource zurück und wartet auf ein neues SPS/PPS. Wegen Bug 1 kommt keines
mehr. Die `VideoTexture` zeigt das letzte Bild weiter an, für den Nutzer friert der Stream ein.
Der WebSocket bleibt offen und liefert weiter Daten, deshalb ist im Netzwerk-Tab nichts
Auffälliges zu sehen.

Wann das passiert, hängt davon ab, wann das erste beschädigte Frame kommt. Im Test war das
nach 0,6 s Medienzeit, beim Nutzer „nach einiger Zeit“.

Nebenbefund aus dem Test: Wird JMuxer gefüttert, bevor die MediaSource offen ist
(`sourceopen`), geht das Init-Segment verloren und es erscheint nie ein Bild. In der App ist das
Zeitfenster klein, weil der WebSocket-Handshake dazwischenliegt. Bei einem Client, der sich an
einen schon laufenden Encoder hängt, ist es aber denkbar.

**Fixvorschlag.**

1. `onError` an JMuxer und `error` am Video-Element abfangen: JMuxer neu erzeugen und den
   WebSocket neu verbinden, mit Backoff. ffmpeg wiederholt SPS/PPS mit jedem IDR, nach höchstens
   einer GOP ist wieder ein Bild da, sofern Bug 1 behoben ist.
2. Den WebSocket erst nach JMuxers `onReady` öffnen, oder Chunks bis dahin puffern.
3. Mittelfristig WebCodecs `VideoDecoder` statt JMuxer und MSE erwägen. Fehler betreffen dort
   einzelne Frames: `reset()` aufrufen und auf den nächsten Keyframe warten. Das gibt außerdem
   weniger Latenz und entfernt die Zeitstempel-Probleme aus Bug 5. Voraussetzung ist ein Secure
   Context (localhost genügt).
4. Den Verbindungs- und Decoderzustand im UI anzeigen. `connectionState` wird heute von
   `LivePlane` nicht genutzt.

## 3 · Live-Ebene größer als der sichtbare Bereich, Seitenverhältnis falsch (Ausschnitt)

**Beschreibung.**
[`LivePlane`](../frontend/src/components/stage/planes/stream/LivePlane.tsx#L41-L48) zeichnet
das Bild auf eine quadratische Ebene mit fest eingestellten 1024 µm Kantenlänge. Diese wird mit
der Standard-Affinen aus `useCurrentAffineTransform` (Faktor 0,32) multipliziert, ergibt also
≈ 328 Szeneneinheiten. Die Standardansicht ist 2D (`modeStore`: `displayMode: "2D"`) mit
[`OrthographicCamera zoom={5}`](../frontend/src/components/stage/cameras/CameraController.tsx#L27-L29),
sichtbar sind also Canvas-Pixel / 5 Einheiten. Bei einer Canvas von 1200 × 700 px sind das
240 × 140 Einheiten: etwa 73 % der Bildbreite und 43 % der Bildhöhe, um die Bildmitte herum.
Damit das ganze Bild hineinpasst, müsste die Canvas in beiden Richtungen ≥ 1640 px groß sein.

Außerdem ist die Ebene quadratisch, das Bild aber 640 × 480 (4:3): Es wird vertikal um den
Faktor 1,33 gestreckt. Zusätzlich skaliert `H264EncoderConfig` jedes Frame fest auf 640 × 480
([`config.py:19-21`](../backend/newswitch/broadcasters/encoders/config.py#L19-L21)). Andere
Sensorformate werden schon im Backend verzerrt (OP #30).

Am Code abgeleitet, nicht im echten Frontend angesehen. Schnelle Prüfung: in der 2D-Ansicht
mit dem Mausrad herauszoomen. Erscheint dann das ganze Bild, ist das die Ursache.

**Fixvorschlag.**

1. Die Größe der Ebene aus dem Detektor ableiten: `detector.width` × `detector.height` mal µm
   pro Pixel (aus Kalibrierung bzw. Affiner), statt fest 1024 µm im Quadrat. Damit stimmt auch
   das Seitenverhältnis.
2. Die Kamera beim Start auf das Live-Bild einpassen: `zoom = min(canvasW / planeW,
   canvasH / planeH)`, z. B. mit drei `<Bounds fit observe>`. Zusätzlich einen Knopf „auf Bild
   einpassen“.
3. Backend: Encodergröße aus der Detektorgröße ableiten, oder mit erhaltenem Seitenverhältnis
   skalieren. Höhe und Breite müssen für yuv420p gerade sein.

## 4 · `koil.sleep` begrenzt die Live-Loop auf ≈ 10 fps (OP #3)

**Beschreibung.**
Die Live-Loop pausiert nach jeder Runde mit `koil.sleep(LIVE_INTERVAL_S)` = 10 ms
([`uc2_detector.py:628`](../backend/newswitch/managers/uc2/uc2_detector.py#L628)). koil plant
den Timer mit `loop.call_later` aus dem Worker-Thread ein. Das ist nicht thread-sicher und weckt
den Event-Loop nicht auf, der Timer läuft also erst beim nächsten Aufwachen aus einem anderen
Grund ab. Unter uvicorn ist das dessen 100-ms-Takt (`Server.main_loop`). Gemessen:

- ohne Client exakt 100 ms pro Runde, also 10 fps statt 20 fps;
- mit Client 88 ms im Median (13 fps), weil der Loop durch WebSocket und Reader-Task öfter
  aufwacht.

Die Bildrate hängt damit von der Last des Event-Loops ab, nicht von der Kamera.

**Zur Frage, ob das mit dem aktuellen Problem zusammenhängt:** Ja, für die niedrige Bildrate:
Es halbiert sie ungefähr. Für den Ausschnitt und das Einfrieren ist es nicht verantwortlich.
Dass die Frames in `_schedule_encoder_frames` „zügig“ ankommen, passt dazu: Es sind gemessen
10–13 pro Sekunde, nicht die 20 der Kamera.

**Fixvorschlag.**
Wie in OP #3: In der Live-Loop einen eigenen Helfer statt `koil.sleep` verwenden, der mit
`threading.Event.wait` in kurzen Scheiben wartet und dazwischen `koil.check_cancelled()` prüft.
Besser noch: blockierend auf das nächste Bild der Kamera warten (uc2_cam_py `wait_for_frame`,
OP #12), dann läuft die Loop im Takt der Kamera. Alternativ upstream in koil:
`loop.call_soon_threadsafe(loop.call_later, …)`.

## 5 · Feste Bildraten-Annahmen in Encoder und Player

**Beschreibung.**

- **Player:** JMuxer läuft mit `fps: 30` und bekommt keine `duration`
  ([`useH264LiveTexture.tsx:66-73`](../frontend/src/components/stage/hooks/useH264LiveTexture.tsx#L66-L73)).
  Bei realen 10–13 fps läuft die Medienzeit der Wanduhr voraus: Nach 25 s Wanduhr standen 10,8 s
  Medienzeit. Das Video läuft nach fast jedem Frame leer (302 `waiting`-Events bei 327 Frames).
  Mit `fps: 13` folgte die Medienzeit der Wanduhr (24,8 s), die `waiting`-Events gingen auf 239
  zurück. Chromium meldete im Headless-Test außerdem einen großen Teil der Frames als
  `droppedVideoFrames`. Ob das in einem echten Browser genauso ist, wurde nicht geprüft. Da
  `duration` fehlt, hält JMuxer zudem das letzte Frame jedes Chunks zurück, bis der nächste
  Chunk kommt: ein Frame zusätzliche Latenz.
- **Encoder:** ffmpeg läuft mit `-r 30` und `-g 30`
  ([`h264_encoder.py:91-104`](../backend/newswitch/broadcasters/encoders/h264_encoder.py#L91-L104)).
  Bei 10–13 fps kommt ein Keyframe deshalb nur alle 2,3–3 s. Nach einem Fehler dauert die
  Erholung entsprechend lange.

**Fixvorschlag.**
Wenn Bug 1 ganze Frames pro Nachricht liefert, jedem `feed` die tatsächliche Dauer seit dem
vorigen Frame mitgeben (`duration` in ms). Mit WebCodecs (Bug 2, Punkt 3) entfällt das, weil
jedes decodierte Frame sofort gezeichnet wird. Im Encoder `-r` aus der Kamera-Bildrate
(`CameraState`) setzen und die GOP auf etwa 1 s legen (`-g` = Bildrate).

## 6 · `encode_frame` läuft im Detektor-Thread (latentes Risiko)

**Beschreibung.**
[`H264Encoder.encode_frame`](../backend/newswitch/broadcasters/encoders/h264_encoder.py#L187-L188)
wird aus dem Detektor-Thread aufgerufen. `StreamWriter.write` auf dem Pipe-Transport ist nicht
thread-sicher (`_add_writer` und Pufferzugriffe aus einem fremden Thread). Danach blockiert
`unkoil(drain)` den Thread, bis ffmpeg das ganze Rohbild (921.600 Bytes) gelesen hat. Ein
Belastungstest mit dem echten Encoder (16.500 Frames ohne Pause aus einem Worker-Thread) hing
nicht: Weil nach jedem `write` auf `drain` gewartet wird, sind die Zugriffe praktisch
serialisiert. Für die beobachteten Symptome ist das daher nicht die Ursache. Es bleibt aber ein
Risiko: Hängt ffmpeg, steht die Live-Loop für alle Detektoren still (gemessen max. 107 ms pro
Frame). Mit mehreren Detektoren oder Encodern summieren sich die Zeiten. Der Zstd-Encoder ruft
`asyncio.Queue.put_nowait` ebenfalls aus dem fremden Thread auf. Bereits in OP #30 erfasst.

**Fixvorschlag.**
Detektor-Thread und Encoder entkoppeln: `encode_frame` legt nur das neueste Rohbild in einen
thread-sicheren Ein-Platz-Briefkasten (z. B. per `loop.call_soon_threadsafe`). Eine
asyncio-Task des Encoders schreibt es mit `write` und `await drain()` auf dem Loop an ffmpeg.
Rohbilder vor ffmpeg zu verwerfen ist unschädlich, anders als codierte Bytes. Für Zstd
`push_chunk` über `call_soon_threadsafe` aufrufen.

---

## Vergleich mit Commit `77aefcf`

Seit `77aefcf` (in `6343890`) geändert:

- `liveview.py`: `await_broadcaster` statt des nicht existierenden `get_context_for_type`. Erst
  damit entsteht überhaupt ein Encoder.
- `h264_encoder.py`: ffmpeg mit `-hide_banner -loglevel error -nostats`, stderr nach DEVNULL.
- `base_config.yaml`: auf camTest umgestellt.
- Doku und Test angepasst.

Keine dieser Änderungen verursacht die beschriebenen Symptome. Der stderr-Fix hat das
serverseitige Einfrieren nach einigen Minuten (volle stderr-Pipe) behoben: 3 Minuten Messung
ohne Stillstand. Das jetzt sichtbare Einfrieren ist ein anderes und entsteht im Browser
(Bugs 1 und 2). Es war vorher nur nicht zu sehen, weil die Route gar keine Daten lieferte.

## Empfohlene Reihenfolge

1. Bug 1, Sofortmaßnahme (verlustfreie H.264-Queue): behebt das Einfrieren, erhöht die Zahl
   decodierbarer Frames.
2. Bug 3 prüfen (herauszoomen) und die Ebene bzw. Kamera einpassen.
3. Bug 4: verdoppelt etwa die Bildrate.
4. Bug 2: Wiederanlauf im Frontend, damit Fehler künftig nicht dauerhaft einfrieren.
5. Bug 1, robuste Lösung, sowie Bugs 5 und 6.
