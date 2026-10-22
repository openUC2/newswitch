/**
 * Tailwind for the bloks the backend serves, compiled in the browser.
 *
 * The app's own classes are compiled at build time, from its sources. A blok's
 * classes arrive at run time (`/schemas/bloks`, or a design's own UI), so the
 * build never sees them: `@tailwindcss/browser` compiles whatever classes appear
 * in the page instead. It is given the app's tokens and variants (`theme.css`,
 * which the build imports too), so `bg-muted`, `dark:`, `past:`, `live:` and
 * `locked:` mean the same in a blok as in the app.
 */
import theme from "@/theme.css?raw";

const style = document.createElement("style");
style.setAttribute("type", "text/tailwindcss");
style.setAttribute("data-blok-runtime-tailwind", "");
style.textContent = theme;
document.head.appendChild(style);

// Loaded after the theme is in place; it watches the page from then on.
void import("@tailwindcss/browser");
