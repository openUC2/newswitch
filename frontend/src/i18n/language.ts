export const LANGUAGE_STORAGE_KEY = "newswitch.language";

export const supportedLanguages = ["en", "de"] as const;

export type SupportedLanguage = (typeof supportedLanguages)[number];
export type LanguagePreference = SupportedLanguage | "system";

export function normalizeLanguage(
  language: string | null | undefined,
): SupportedLanguage | null {
  const baseLanguage = language?.trim().toLowerCase().split("-")[0];
  return (
    supportedLanguages.find((candidate) => candidate === baseLanguage) ?? null
  );
}

export function detectBrowserLanguage(
  languages: readonly string[] = typeof navigator === "undefined"
    ? []
    : navigator.languages.length > 0
      ? navigator.languages
      : [navigator.language],
): SupportedLanguage {
  for (const language of languages) {
    const normalized = normalizeLanguage(language);
    if (normalized) return normalized;
  }
  return "en";
}

export function readLanguagePreference(): LanguagePreference {
  if (typeof window === "undefined") return "system";
  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
  return stored === "de" || stored === "en" ? stored : "system";
}

export function resolveLanguage(
  preference: LanguagePreference = readLanguagePreference(),
): SupportedLanguage {
  return preference === "system" ? detectBrowserLanguage() : preference;
}
