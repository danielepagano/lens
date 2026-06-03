import { defineConfig } from "eslint/config";
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import svelte from "eslint-plugin-svelte";
import globals from "globals";

export default defineConfig([
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...svelte.configs["flat/recommended"],
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: ["**/*.svelte"],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
    rules: {
      "svelte/infinite-reactive-loop": "off",
      "svelte/prefer-svelte-reactivity": "off",
    },
  },
  {
    files: ["src/features/cli/**/*.svelte"],
    rules: {
      "max-lines": ["warn", { max: 320, skipBlankLines: true, skipComments: true }],
    },
  },
  {
    ignores: ["dist/", "node_modules/"],
  },
]);
