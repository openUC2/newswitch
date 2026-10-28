import { configureBlokPlatform } from "@arkitektio/bsx/runtime";
import { toast as sonner } from "sonner";
import appTheme from "@/theme.css?raw";
import { defaultBlokCatalog } from "./catalog";
import { describeError } from "./notify";

/**
 * What the bloks get from newswitch (`@arkitektio/bsx` asks once, before the
 * first render): toasts through the app's sonner `Toaster`, errors as one
 * sentence, the Tailwind theme a blok's classes are compiled against (so
 * `bg-muted`, `dark:` and `locked:` mean what they mean in the app), and the
 * standard catalog. Imported first by `main.tsx`.
 */
configureBlokPlatform({
  toast: Object.assign(
    (message: string, options?: { description?: string }) =>
      sonner(message, options),
    {
      success: (message: string, options?: { description?: string }) =>
        sonner.success(message, options),
      info: (message: string, options?: { description?: string }) =>
        sonner.info(message, options),
      warning: (message: string, options?: { description?: string }) =>
        sonner.warning(message, options),
      error: (message: string, options?: { description?: string }) =>
        sonner.error(message, options),
    },
  ),
  describeError,
  tailwindTheme: appTheme,
  catalog: defaultBlokCatalog,
});
