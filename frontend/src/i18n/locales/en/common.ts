export const common = {
  appName: "Newswitch",
  cancel: "Cancel",
  close: "Close",
  create: "Create",
  delete: "Delete",
  loading: "Loading...",
  refresh: "Refresh",
  save: "Save",
  slot: "Slot {{slot}}",
} as const;

export const language = {
  label: "Language",
  menu: "Language menu",
  system: "Browser language",
  english: "English",
  german: "Deutsch",
} as const;

export const navigation = {
  manageUsers: "Manage users",
  auditLog: "Audit log",
  backToMicroscope: "Back to microscope",
  index: "Microscope",
  replay: "Replay",
  latestChanges: "Latest changes",
  timelinePosition: "Timeline position",
  revision: "rev",
  noTimeline: "No active session boundaries were available.",
  timelineFailed: "Failed to prepare timeline",
  liveFailed: "Failed to return to live mode",
  checkoutFailed: "Failed to load timeline state",
} as const;

export const roles = {
  admin: "Administrator",
  operator: "Operator",
  viewer: "Viewer",
  analyst: "Analyst",
} as const;

export const taskStatus = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  submitted: "Submitted",
  failed: "Failed",
  cancelled: "Cancelled",
  paused: "Paused",
  interrupted: "Interrupted",
} as const;
