export const auth = {
  accountMenu: "Account menu",
  username: "Username",
  password: "Password",
  enterUsername: "Enter a username",
  enterPassword: "Enter a password",
  signInDescription: "Sign in to control the microscope.",
  signIn: "Sign in",
  localSignIn: "Local sign-in",
  onlineSignIn: "Online sign-in",
  checkingOnlineSignIn: "Checking the connection to openUC2…",
  keycloakSignIn: "Sign in with openUC2",
  localAccount: "Local account",
  openUC2Account: "openUC2 account",
  linkOpenUC2: "Link an openUC2 account",
  openUC2AlreadyLinked: "This local account already has an openUC2 link.",
  openUC2LinkDescription:
    "Confirm your local password, then sign in with openUC2.",
  openUC2LinkConfirmDescription:
    "Check the account names. Linking them lets you sign in to this microscope with openUC2.",
  openUC2LinkConfirm: "Confirm link",
  openUC2LinkSuccess: "openUC2 account linked.",
  openUC2LinkConflict:
    "One of the accounts is already linked. Ask your microscope admin to check the link.",
  openUC2LinkFailed:
    "We could not finish linking the accounts. Start again from the account menu.",
  keycloakUnavailable:
    "Signing in with openUC2 is temporarily unavailable. You can still sign in locally.",
  keycloakFailed: "Sign-in with openUC2 failed. Please try again.",
  keycloakUnlinked:
    "This openUC2 account is not linked to an active local account on this microscope.",
  signingIn: "Signing in...",
  invalidCredentials: "Invalid username or password.",
  backendUnavailable: "Could not reach the microscope backend.",
  changePassword: "Change password",
  changingPassword: "Changing...",
  currentPassword: "Current password",
  newPassword: "New password",
  confirmPassword: "Confirm new password",
  passwordsMismatch: "The new passwords do not match.",
  currentPasswordIncorrect: "Current password is incorrect.",
  passwordChangeFailed: "Could not change the password.",
  passwordChanged: "Password changed.",
  passwordChangeDescription:
    "You will stay signed in on this device; every other session is signed out.",
  logOut: "Log out",
} as const;
