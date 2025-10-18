/** @type {import('prettier').Config} */
const prettierConfig = {
  plugins: ['prettier-plugin-embed', 'prettier-plugin-sql'],
  printWidth: 120,
  singleQuote: true,
  overrides: [
    {
      files: ['*.yaml', '*.yml', '*.toml', '*.json', '*.ini'],
      options: {
        tabWidth: 2,
        singleQuote: false,
        experimentalTernaries: true,
        useTabs: false,
      },
    },
    {
      files: ['*.md'],
      options: {
        singleQuote: false,
      },
    },
  ],
};

/** @type {import('prettier-plugin-embed').PrettierPluginEmbedOptions} */
const prettierPluginEmbedConfig = {
  embeddedSqlTags: ['sql'],
};

/** @type {import('prettier-plugin-sql').SqlBaseOptions} */
const prettierPluginSqlConfig = {
  language: 'postgresql',
  keywordCase: 'upper',
};

const config = {
  ...prettierConfig,
  ...prettierPluginEmbedConfig,
  ...prettierPluginSqlConfig,
};

export default config;
