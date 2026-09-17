import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import {
  LANGUAGE_STORAGE_KEY,
  type LanguagePreference,
  readLanguagePreference,
  resolveLanguage,
} from "./language";
import { resources } from "./resources";

const initialPreference = readLanguagePreference();

void i18n.use(initReactI18next).init({
  resources,
  lng: resolveLanguage(initialPreference),
  fallbackLng: "en",
  supportedLngs: ["en", "de"],
  interpolation: { escapeValue: false },
  react: { useSuspense: false },
});

function updateDocumentLanguage(language: string) {
  if (typeof document !== "undefined") {
    document.documentElement.lang = language;
  }
}

updateDocumentLanguage(i18n.resolvedLanguage ?? i18n.language);
i18n.on("languageChanged", updateDocumentLanguage);

export async function setLanguagePreference(preference: LanguagePreference) {
  if (typeof window !== "undefined") {
    if (preference === "system") {
      window.localStorage.removeItem(LANGUAGE_STORAGE_KEY);
    } else {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, preference);
    }
  }
  await i18n.changeLanguage(resolveLanguage(preference));
}

export { i18n };
export * from "./language";
