/**
 * What the blok renderer reports to the person: toasts (through the app's
 * sonner `Toaster`) and errors turned into a sentence.
 */
import { toast as sonner } from "sonner";

type ToastOptions = { id?: string | number };

export const toast = {
  success: (message: string, options?: ToastOptions) =>
    sonner.success(message, options),
  info: (message: string, options?: ToastOptions) =>
    sonner.info(message, options),
  warning: (message: string, options?: ToastOptions) =>
    sonner.warning(message, options),
  error: (message: string, options?: ToastOptions) =>
    sonner.error(message, options),
};

export type DescribedError = {
  /** One sentence, no codes or paths. */
  message: string;
  /** The raw text behind it. */
  details: string;
};

/** Any failure (a thrown `Error`, a string, a rejection with nothing in it) as one sentence. */
export const describeError = (error: unknown): DescribedError => {
  const raw =
    error instanceof Error
      ? error.message
      : typeof error === "string"
        ? error
        : "";
  const message = raw.trim() || "Something went wrong, and nothing said why.";
  return { message, details: raw || String(error) };
};
