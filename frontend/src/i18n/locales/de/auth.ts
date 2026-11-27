export const auth = {
  accountMenu: "Kontomenü",
  username: "Benutzername",
  password: "Passwort",
  enterUsername: "Benutzernamen eingeben",
  enterPassword: "Passwort eingeben",
  signInDescription: "Anmelden, um das Mikroskop zu steuern.",
  signIn: "Anmelden",
  localSignIn: "Lokale Anmeldung",
  onlineSignIn: "Online-Anmeldung",
  checkingOnlineSignIn: "Verbindung zu openUC2 wird geprüft …",
  keycloakSignIn: "Mit openUC2-Konto anmelden",
  localAccount: "Lokales Konto",
  openUC2Account: "openUC2-Konto",
  linkOpenUC2: "openUC2-Konto verknüpfen",
  openUC2AlreadyLinked:
    "Dieses lokale Konto ist bereits mit einem openUC2-Konto verknüpft.",
  openUC2LinkDescription:
    "Bestätige dein lokales Passwort und melde dich danach bei openUC2 an.",
  openUC2LinkConfirmDescription:
    "Prüfe die Kontonamen. Mit der Verknüpfung kannst du dich an diesem Mikroskop auch über openUC2 anmelden.",
  openUC2LinkConfirm: "Verknüpfung bestätigen",
  openUC2LinkSuccess: "openUC2-Konto verknüpft.",
  openUC2LinkConflict:
    "Eines der Konten ist bereits verknüpft. Der Geräteadmin kann die Verknüpfung prüfen.",
  openUC2LinkFailed:
    "Die Verknüpfung konnte nicht abgeschlossen werden. Bitte starte sie erneut im Kontomenü.",
  keycloakUnavailable:
    "Die Anmeldung mit dem openUC2-Konto ist gerade nicht verfügbar. Du kannst dich lokal anmelden.",
  keycloakFailed:
    "Die Anmeldung mit dem openUC2-Konto ist fehlgeschlagen. Bitte versuche es erneut.",
  keycloakUnlinked:
    "Dieses openUC2-Konto ist an diesem Mikroskop keinem aktiven lokalen Konto zugeordnet.",
  signingIn: "Anmeldung läuft...",
  invalidCredentials: "Benutzername oder Passwort ist ungültig.",
  backendUnavailable: "Das Mikroskop-Backend ist nicht erreichbar.",
  changePassword: "Passwort ändern",
  changingPassword: "Wird geändert...",
  currentPassword: "Aktuelles Passwort",
  newPassword: "Neues Passwort",
  confirmPassword: "Neues Passwort bestätigen",
  passwordsMismatch: "Die neuen Passwörter stimmen nicht überein.",
  currentPasswordIncorrect: "Das aktuelle Passwort ist falsch.",
  passwordChangeFailed: "Das Passwort konnte nicht geändert werden.",
  passwordChanged: "Passwort geändert.",
  passwordChangeDescription:
    "Du bleibst auf diesem Gerät angemeldet; alle anderen Sitzungen werden abgemeldet.",
  logOut: "Abmelden",
} as const;
