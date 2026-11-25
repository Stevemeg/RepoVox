import js from "@eslint/js";
import ts from "typescript-eslint";
import hooks from "eslint-plugin-react-hooks";

// Browser security policy, enforced with ESLint core rules only (no extra plugins).
// Repository strings are untrusted: no HTML injection, no code evaluation, no browser
// dialogs, and external links only through <ExternalLink> (which pins rel=noopener).
const htmlAndDialogs = [
  {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: "Render untrusted strings as React text only.",
  },
  {
    selector: "MemberExpression[property.name=/^(innerHTML|outerHTML)$/]",
    message: "Never write HTML strings into the DOM.",
  },
  {
    selector: "CallExpression[callee.property.name='insertAdjacentHTML']",
    message: "Never write HTML strings into the DOM.",
  },
  {
    selector: "MemberExpression[object.name='window'][property.name=/^(confirm|alert|prompt|open)$/]",
    message: "Use <ConfirmDialog> or <ExternalLink> instead of browser dialogs and window.open.",
  },
  {
    selector: "CallExpression[callee.name=/^(confirm|alert|prompt)$/]",
    message: "Use <ConfirmDialog> instead of browser dialogs.",
  },
  {
    selector: "MemberExpression[object.object.name='process'][object.property.name='env'][property.name=/^NEXT_PUBLIC_/]",
    message: "No NEXT_PUBLIC_ variables: nothing from the server environment reaches the bundle.",
  },
];
const externalLinks = {
  selector: "JSXAttribute[name.name='target']",
  message: "Open other sites only through <ExternalLink>, which sets rel=\"noopener noreferrer\".",
};

export default ts.config(
  {
    ignores: [
      ".next/**",
      "next-env.d.ts",
      "playwright-report/**",
      "test-results/**",
    ],
  },
  js.configs.recommended,
  ...ts.configs.recommended,
  {
    files: ["**/*.ts", "**/*.tsx"],
    plugins: { "react-hooks": hooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
    },
  },
  {
    // Shipped code only: tests deliberately feed hostile `javascript:` URLs to validators.
    files: ["src/**/*.ts", "src/**/*.tsx"],
    rules: {
      "no-script-url": "error",
      "no-restricted-syntax": ["error", ...htmlAndDialogs, externalLinks],
    },
  },
  {
    // The single audited place allowed to set `target`.
    files: ["src/components/ui/external-link.tsx"],
    rules: { "no-script-url": "error", "no-restricted-syntax": ["error", ...htmlAndDialogs] },
  },
);
