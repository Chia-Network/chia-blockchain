const CracoAlias = require("craco-alias");

module.exports = {
  webpack: {
    configure: {
      target: 'electron-renderer'
    },
  },
  plugins: [{
    plugin: CracoAlias,
    options: {
      source: "tsconfig",
      baseUrl: "./src",
      tsConfigPath: "./tsconfig.paths.json"
    },
  }],
};
