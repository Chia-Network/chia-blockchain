module.exports = function babel(api) {
  api.cache(true);

  return {
    presets: [
      ['@babel/preset-env', {
        targets: {
          node: true,
        },
        useBuiltIns: 'entry',
        corejs: 3,
      }],
      '@babel/preset-typescript',
      ["@babel/preset-react", {
        "runtime": "automatic"
      }]
    ],
    plugins: [
      'macros',
      '@loadable/babel-plugin',
      ['babel-plugin-styled-components'],
    ],
  };
};
