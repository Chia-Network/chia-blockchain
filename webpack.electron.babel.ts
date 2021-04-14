import path from 'path';
import CopyPlugin from 'copy-webpack-plugin';

export default {
  resolve: {
    extensions: ['.tsx', '.ts', '.js'],
  },
  devtool: 'source-map',
  entry: './src/electron/main.tsx',
  target: 'electron-main',
  stats: 'errors-only',
  module: {
    rules: [{
      test: /\.(js|ts|tsx)$/,
      exclude: /node_modules/,
      use: {
        loader: 'babel-loader',
      },
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
  output: {
    path: path.resolve(__dirname, './build/electron'),
    filename: '[name].js',
  },
  plugins: [
    new CopyPlugin({
      patterns: [{ 
        from: path.resolve(__dirname, './src/electron/preload.js'),
        to: path.resolve(__dirname, './build/electron'),
      }],
    }),
  ],
};