export const auth = {
  accountMenu: "Kontomenü",
  username: "Benutzername",
  password: "Passwort",
  enterUsername: "Benutzernamen eingeben",
  enterPassword: "Passwort eingeben",
  signInDescription: "Anmelden, um das Mikroskop zu steuern.",
  signIn: "Anmelden",
  keycloakSignIn: "Mit Keycloak anmelden",
  keycloakUnavailable:
    "Keycloak ist nicht erreichbar. Du kannst dich lokal anmelden.",
  keycloakFailed:
    "Die Keycloak-Anmeldung ist fehlgeschlagen. Bitte versuche es erneut.",
  keycloakUnlinked:
    "Dieses Keycloak-Konto ist hier keinem aktiven lokalen Konto zugeordnet.",
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
