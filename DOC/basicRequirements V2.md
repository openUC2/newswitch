# Software requirementes document for new swithc

## Header
Author: Christian Karras
Version 0.1
Date: 29.07.26

## Version Log
V2 -> Use case analysis with Armin and Dirk

## Use cases /Issues

- Anschalten -> Keine Betriebszustandsanzeige -> Woher weiß ich, dass es an ist? In welchem Zusatnd bin ich ? Wie wird es angezeig? -> in SW und an Gerät
- Wie werden verfügbare Geräte vom Frontend gefunden? -> Das Gerät taucht im WLan auf
- 

-> Homing 
  -> derzeit nicht standard?
  - Optionen Homing and Homing and go to last pos
  -> Optional Homing beim Start oder nicht?
  -> Wie stelle ich sicher, dass das gerät immer weiß wo es ist? 
  -> Gerät soll definierte Positionen wieder finden

Verbinugnen mit dem Geöt
-> WLan verbindung mit Gerät
    -> Das Remotegerät kann nicht mehr über Wifi ins Internet
    -> Manche Kunden wollen Kein WLAN -> Verbindugn über USB
    -> Web security: Jeder der die IP hat kann aufs Gerät zugreifen, es soll ersichtlich sein, wer auf dem Gerät eingeloggt ist
    -> Verschlüsselung der Daten (SHA256 oder ähnliches?)
-> Kabelgebundene Verbindung
  - USB3 und Ethernet

-> Nutzerrechte
  - Erlaubte Nutzer sind auf Gerät hinterlegt?
  - Rechtemanagment über sudoUser
  - Nur ein Nutzer darf steuern, alle anderern schauen zu
  - Wie werden Steuerungen übergeben?
    - Einfaches Beobachten vs. Messreihe?
    - Hauptnutzer meldet sich ab
    - Haupnutzer fliegt raus (ungewollt) und will sich wieder einloggen
    - Hauptnutzer möchte steuerung aktiv an nebennutzer übergeben
    - Der Hauptnutzer loggt sich mit verschiedenen Remotegeräten ein
    - Was passiert, wenn es ein nutzer eingeloggt ist, aber ein anderer Nutzer einen Hardwarekontroller steuern?
        - Hier Idee: In SWGUI -> Aktiv Controllersteuerung aktivieren, Bei Messreihen, immer deaktivert 
    - Wie können Messreihenreihen abgebrochen werden?  -> nur Hauptuser? 
    - Wie können Messreihen während des Betriebes verändert werden? -> Nur Haupuser
  - Welche einstellungen dürfen durch welchen nutzer geändert werden? -> Sollen Kritsiche einstellungn wirklich in einer Textdatei liegen?

-> Schnittstellen für Externe
  - Wie werden SW Schnittstellen dargestellt? (API) -> Mit Triggeroptionen
  - Wie kann das Mikroskop in Robotikenvironments eingebunden werden? -> was sind aktuelle standards?


-> GUI Fehlermeldungen
  - Müssen KLAR ersichtlich sein!

-> Derzeit stabilster Modus: Lan + Chrome Browser

-> Config structure:
  - Wo werden Configs gespeichert
  - Wo werden welche Informationen gespeichert -> Dokumentation
  - Wo werden Mikrsokopiemetadaten gespeichert (Preset z.B. -> linked zu Mikrsokopsetting) ? (json, csv, ...) -> in Imswitch wrid das im Browser gespeichert, -> sollte das
  - Trennung zwischen User und system properties in config strukture

-> Nutzerfreundliche GUI
  - Zur zeit sehe ich alle Funktionen auf einmal 
  - Benötigte Features:
    - Liveview Vollbild
    - Digitaler Zoom des Livebildes
    - Es sollen nur "Apps" verfügbar sein, die das Mikroskop auch unterstütz
    - Überlblicksbild -> extra Kamera oder stitch (QuickOverview)??



-> Datenspeicherung / verarbeitung
  - Wo werden die Daten gespeichert
  - Speicherpfade außerhalb des RPI festlegen
  - Wie sollen automatische Daten gespeichert werden? -> Sicher erst mal auf RPI
    -> Max. Datenmenge im bereich 1TB
  - Download (Format? OME TIFF oder OME ZARR)
  - Stitching
    - Stitching auf RPI?
    - soll es überhaupt möglich
    - overview stitching

-> APPs
  - Wie sollen Apps (Programmabläufe) definiert werden?
    - script
    - GUI
    - Fest vordefiniert

-> Inittests
  - Welche Initialen Testroutinen sollen umgesetzt werden? 
    - intiale Achskalibrierung
    - Bildgrößen kalibrierung















## General Document rule

points starting wiht /D/ are points that are subject of further discussion

## Scope and Context
This a software requirements document which is ment to define the requirements (wrt. performance, usability, interfaces, GUI, key architecture aspects) for the newswitch project.

The purpose of newswitch is to control an open UC2 microscope. The develeopment code base of open UC2 is found in the following github: https://github.com/openUC2

Audience of this requirement document shall be developers and alpha as well as beta testers

## General setup rule
 - splitting in backend and frontend
    - frontend: react / vite / typescript
    - backend: 
        - pyhton with dependency injection and protocoll setup
        - Layers:
            - Routines --> managers --> protocols (states) and devices
        - purely simualted devices are available
    - connection:
        - structure form rekuest_next 
        - FASTAPI for lightweihgt communication
   



## Requrired features on GUI

### General features
- Feedback of the connection status of the device
- Feedack of the connection stauts between frontend and backend
- Dualside synchronization between GUI elements and the controlled devices
- Only show GUI elements, which are really implemented and possible to use in the current version of the microscope
- Historical states of the microscope shall be available (in init version already impolemented)


### Devices
- Implement and start devices
- Multiple cameras should be able to be used (only one will be shown in the live view)

### Imaging
- Live imaging of a selcect camera
- Snapshot of a current view. Snapshot shall be immediately downloaded the the remote machine 

### Camera settings
- per camera: 
    - Name
    - as sliders and numerical I/O
        - exposure time /ms
        - gain /dB
        - framerate /1/s
        - channel weighting (only for live viewer)
    - only show these elements, which are really controllable (a camera without the option of setting the framerate shall not show tihs)

### Light sources
    - on off
    - power (sldier and numerical IO) - dont show if off

### Stages:
    - buttons for directions (pos and neg)
    - XYZ direciton
    - Nonusable directions off
    - home button -> shall not be in center between controll buttons but in an extra menue
    - show position (x,y,z) 
    - Stepsize, velocity, accelaration, Jerk settable (only show what is settable by the controller) via numerical IO (extra menu)
    - Switch between joggin and stepping
    - Numerical IO of positions -> if entering position and confirming -> respective axis shall move




### Algorthims / Procedures
- Z- Scan (Scan different positions and record images) -> synchronized movement 
- Autofocus -> options -> select measure
- Focuslock
- Record overview image (maybe a 2nd camera will be used)
- Calibration microscope:
    - procedure: move to several points and record land marks and calbirate stages (current method: affine Transform)
    - Manual and automatic mode
- XY stitching mode
    - Should apply focus lock
- time series
- initial determination of potential sample area (coarse boarders of xy stage shall be set manually while comissioning and stored in the devices settings.json), fine adjustment shall be optionally done at power up of the system

## Backend / Frontend interaction

### Logged in users
- multiple users shall be able to be logged in to the backend of one microscope
- only one is enabled to controll the devices (first come first serve)
- if conntecion from one user breaks:
    - the GUI of the user with the broken connection shall be disabled and show a clear statement that the conneciton is disabled
    - the next user in the user list gains controll over the microscope
    - If there is no further user, the microscope shall stop immediately
    - This rules are obsolete for a case of a running experiment (such as a currently running time series / Stitching / Z-Scan). If a connection fails or the user logs out the experiment shall be finished
- 

## Used devices

### Cameras
- HIKROBOTICS 
- DAHENG
- Max DataRate: 500 MB/sec

### STAGES:
- Controlled via CANBUS (openCAN)

### Further devices
- rotators flters and objective

### Fast device conglomarates
- If devives shall be synced together this is done via an ESP32 hat for the Raspberry PI


## Development and Debugging rulse
- Changes shall be logged in a changelog.md
- A logging of fatals, errors, warning, infos, and debugging information must be available for the backend. This logging shall be implemented as a tool in the top level structure of the backend and be capable of logging 
- c /C++ files of a given (sub)project shall be structured in <subprojectName>/core/src and ./include
- CMake shall be used for building C/C++
- pybind11 shall be used for binding C/C++ funcitions to python
- snake case shall be used in pyhton, camel case in C/C++development
- Python: getattr  is banned


## Base archicterual setup

The basic arhictectural template is given in the current veriosn from today (28.07.26)



### Backend
- Logic of controlling the devices of the microsocpe
- Shall run on an Raspberry PI5 (Docker Container)
- Written in mostly in Pyhton
- Image handling is written in C/C++

#### Image handling in the backend
- The package to be used for the HIK camera was developped already and is found in https://github.com/openUC2/UC2_HikPy
- Each camera shall have a ring buffer that serves as source for images for furhter pocessing (streaming to frontend, downloading to front end, or local drive)
- Ringbuffer:
    - Shall be written in C/C++ with pybind11 as external project
    - Interfaces (python) is a settings structure for the ring buffer as well as  readimage and read_latest_image (with or without meta data, settable via flag)
    - Image hand over from camera to ringbuffer shall happen on c/C++ level

- image stream flow to frontend
    Camera → RingBuffer → [decimate + downscale + Mono8→I420]
       → rtc.VideoSource.capture_frame()
       → LiveKit SDK (libvpx VP8 encode + GCC/transport-cc + pacer)
       → LiveKit Server (SFU, Fan-out)
       → Browser: livekit-client, <video srcObject=…>
#### Base Microcope settings 
- shall be defined in one json file on the device
- well structure in 


### Frontend
- React / Vite / Typescript app
- Shall run basically in browser (Chrome) 
- Operating systems: Linux(X86), Windows(X86), IOS (Macbook), ARM (Rasbperry py)


### Connection
- Rekuest_next
- FASTAPI for transfering easily to handle data
- Mutual watchdogs for surveiling the connections shall be implemented
