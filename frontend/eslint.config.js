import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import { defineConfig, globalIgnores } from "eslint/config";

export default defineConfig([
  globalIgnores(["dist"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
  {
    // Vendored shadcn/ui components. Exporting a cva variants const alongside the
    // component is the idiomatic shadcn shape, and these files are meant to be
    // re-synced from upstream - so relax the rules rather than edit them.
    files: ["src/components/ui/**"],
    rules: {
      "react-refresh/only-export-components": "off",
      "react-hooks/purity": "off",
    },
  },
  {
    // newswitch's own bloks (the renderer is @arkitektio/bsx). Its catalog modules
    // export blok component *definitions* (objects wrapping a render function)
    // and runtime hooks/contexts side by side, which is the point of a catalog -
    // fast refresh simply does a full reload for them.
    files: ["src/lib/blok/**"],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },
]);
