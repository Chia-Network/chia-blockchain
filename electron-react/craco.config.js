const CracoAlias = require("craco-alias");
const path = require('path');

console.log(path.resolve(__dirname, './src/components/core/'),);

module.exports = {
  plugins: [{
    plugin: CracoAlias,
    options: {
      // source: "options",
      // baseUrl: "./src",
      aliases: {
        '@chia/core': './src/components/core',
        '@chia/icons': './src/components/icons',
      },
    },
  }],
};
