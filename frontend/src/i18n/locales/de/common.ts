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
  latestChanges: "Letzte Änderungen",
  timelinePosition: "Position auf der Zeitachse",
  revision: "Rev.",
  noTimeline: "Es sind keine aktiven Sitzungszeiträume verfügbar.",
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
