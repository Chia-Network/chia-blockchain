import webpack from 'webpack';
import path from 'path';
import ReactRefreshWebpackPlugin from '@pmmmwh/react-refresh-webpack-plugin';
import LoadablePlugin from '@loadable/webpack-plugin';
import TerserPlugin from 'terser-webpack-plugin';
import HtmlWebpackPlugin from 'html-webpack-plugin';
import LodashModuleReplacementPlugin from 'lodash-webpack-plugin';

const PORT = 3000;
const CONTEXT = __dirname;
const DEV = process.env.NODE_ENV !== 'production';
const LOOSE = false;

const babelQuery = {
  babelrc: false,
  presets: [
    ['@babel/preset-env', {
      useBuiltIns: 'entry',
      corejs: 3,
      loose: LOOSE,
    }],
    '@babel/preset-typescript',
    '@babel/preset-react',
  ],
  plugins: [
    'lodash',
    '@loadable/babel-plugin',
    'babel-plugin-styled-components',
    ['@babel/plugin-proposal-class-properties', { loose: LOOSE }],
    '@babel/plugin-proposal-export-default-from',
    ['babel-plugin-transform-imports', {
      '@material-ui/core': {
        // Use "transform: '@material-ui/core/${member}'," if your bundler does not support ES modules
        'transform': '@material-ui/core/${member}',
        'preventFullImport': true,
      },
      '@material-ui/icons': {
        // Use "transform: '@material-ui/icons/${member}'," if your bundler does not support ES modules
        'transform': '@material-ui/icons/${member}',
        'preventFullImport': true,
      },
    }],
    DEV && require.resolve('react-refresh/babel'),
  ].filter(Boolean),
};

export default {
  mode: DEV ? 'development' : 'production',
  context: CONTEXT,
  devtool: DEV ? 'inline-source-map' : 'source-map',
  entry: path.join(CONTEXT, '/src/index'),
  target: 'electron-renderer',
  stats: 'errors-only',
  devServer: DEV ? {
    contentBase: path.join(__dirname, '../dist/renderer'),
    historyApiFallback: true,
    compress: true,
    hot: true,
    port: PORT,
    publicPath: '/',
  } : undefined,
  output: {
    path: path.resolve(__dirname, './build/renderer'),
    filename: 'js/[name].js',
    publicPath: './',
  },
  externals: {
    electron: 'electron',
  },
  resolve: {
    extensions: ['.wasm', '.mjs', '.ts', '.tsx', '.js', '.jsx', '.json'],
    modules: [
      path.resolve(CONTEXT, 'node_modules'),
      path.resolve(CONTEXT, '../../node_modules'),
      'node_modules',
    ],
    alias: {
      "@chia/core": `${__dirname}/src/components/core`,
      "@chia/icons": `${__dirname}/src/components/icons`,
      crypto: 'crypto-browserify',
      stream: 'stream-browserify',
    },
  },
  optimization: {
    splitChunks: {
      chunks: 'all',
    },
    usedExports: true,
    minimize: !DEV,
    minimizer: [
      new TerserPlugin({
        terserOptions: {
          ecma: undefined,
          warnings: false,
          parse: {},
          compress: {
            // collapse_vars: false,
            // drop_console: true,
          },
          mangle: true, // Note `mangle.properties` is `false` by default.
          module: false,
          output: null,
          toplevel: false,
          nameCache: null,
          ie8: false,
          keep_classnames: undefined,
          keep_fnames: false,
          safari10: true,
        },
      }),
    ],
  },
  plugins: [
    new LoadablePlugin(),
    new LodashModuleReplacementPlugin({
      paths: true,
      flattening: true,
    }),
    new webpack.DefinePlugin({
      'process.env.NODE_ENV': JSON.stringify(DEV ? 'development' : 'production'),
      'process.env.BROWSER': true,
      IS_BROWSER: true,
    }),
    new HtmlWebpackPlugin({
      template: './src/index.html',
    }),
    DEV && new ReactRefreshWebpackPlugin(),
  ].filter(Boolean),
  module: {
    rules: [{
      test: /\.mjs$/,
      include: /node_modules/,
      type: 'javascript/auto',
    }, {
      test: /\.[jt]sx?$/,
      exclude: DEV ? /node_modules/ : undefined,
      use: [{
        loader: 'babel-loader',
        options: babelQuery,
      }],
    }, {
      test: /\.(woff|woff2?|ttf|eot)$/,
      use: [{
        loader: 'url-loader',
        options: {
          limit: 10000,
        },
      }],
    }, {
      test: /\.svg$/,
      use: ['@svgr/webpack', 'url-loader'],
    }, {
      test: /\.(gif|png|jpe?g)$/i,
      use: [{
        loader: 'file-loader',
      }],
    }],
  },
};
