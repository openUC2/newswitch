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
