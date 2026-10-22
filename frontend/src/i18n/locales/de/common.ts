export const common = {
  appName: "Newswitch",
  cancel: "Abbrechen",
  close: "Schließen",
  create: "Erstellen",
  delete: "Löschen",
  loading: "Wird geladen...",
  refresh: "Aktualisieren",
  save: "Speichern",
  slot: "Position {{slot}}",
} as const;

export const language = {
  label: "Sprache",
  menu: "Sprachauswahl",
  system: "Browsersprache",
  english: "English",
  german: "Deutsch",
} as const;

export const navigation = {
  manageUsers: "Benutzer verwalten",
  auditLog: "Audit-Protokoll",
  backToMicroscope: "Zurück zum Mikroskop",
  index: "Mikroskop",
  replay: "Wiedergabe",
  live: "Live",
  liveHint: "Das Mikroskop zeigen, wie es jetzt ist",
  replayHint: "Durch das zurückgehen, was in dieser Sitzung geschah",
  viewingPast: "Ansicht der Vergangenheit",
  pastPaused: "Während der Wiedergabe sind die Steuerungen pausiert",
  sessionStart: "Sitzungsbeginn",
  now: "Jetzt",
  latestChanges: "Letzte Änderungen",
  timelinePosition: "Position auf der Zeitachse",
  revision: "Pos.",
  noTimeline:
    "Der Agent hat noch nichts aufgezeichnet, das sich abspielen lässt.",
  timelineFailed: "Die Zeitachse konnte nicht vorbereitet werden",
  liveFailed: "Die Live-Ansicht konnte nicht wiederhergestellt werden",
  checkoutFailed: "Der Zustand der Zeitachse konnte nicht geladen werden",
} as const;

export const roles = {
  admin: "Administrator",
  operator: "Bediener",
  viewer: "Betrachter",
  analyst: "Analyst",
} as const;

export const taskStatus = {
  pending: "Ausstehend",
  running: "Läuft",
  completed: "Abgeschlossen",
  submitted: "Übermittelt",
  failed: "Fehlgeschlagen",
  cancelled: "Abgebrochen",
  paused: "Pausiert",
  interrupted: "Unterbrochen",
} as const;
