module.exports = {
  extends: [
    "airbnb-typescript",
    "airbnb/hooks",
    "plugin:@typescript-eslint/recommended",
    "plugin:@typescript-eslint/recommended-requiring-type-checking",
    "plugin:eslint-comments/recommended",
    "plugin:jest/recommended",
    "plugin:promise/recommended",
    "plugin:unicorn/recommended",
    "prettier",
    "prettier/react",
    "prettier/@typescript-eslint",
  ],
  plugins: [
    "@typescript-eslint",
    "eslint-comments",
    "jest",
    "promise",
    "unicorn",
    "react",
    "jsx-a11y",
    "import",
    "prettier",
  ],
  env: {
    "browser": true,
    "es6": true,
    "jest": true,
  },
  parser: "@typescript-eslint/parser",
  parserOptions: {
    sourceType: "module",
    project: "./tsconfig.json",
    ecmaFeatures: {
      jsx: true,
    },
  },
  rules: {
    "unicorn/no-null": "off",
    "unicorn/prevent-abbreviations": "off",
    "unicorn/filename-case": ["error", {
      "cases": {
        "camelCase": true,
        "pascalCase": true,
      },
    }],
  },
};
