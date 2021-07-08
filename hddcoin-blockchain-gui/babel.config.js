const LOOSE = false;

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
        loose: LOOSE,
      }],
      '@babel/preset-typescript',
      '@babel/preset-react',
    ],
    plugins: [
      'macros',
      '@loadable/babel-plugin',
      ['babel-plugin-styled-components'],
      ['@babel/plugin-proposal-class-properties', { loose: LOOSE }],
      '@babel/plugin-proposal-export-default-from',
    ],
  };
};
