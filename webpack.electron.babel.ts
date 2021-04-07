import path from 'path';
import CopyPlugin from 'copy-webpack-plugin';

export default {
  resolve: {
    extensions: ['.tsx', '.ts', '.js'],
  },
  devtool: 'source-map',
  entry: './src/electron/main.ts',
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
      test: /\.(gif|png|jpe?g)$/i,
      use: ['file-loader', {
        loader: 'image-webpack-loader',
        options: {
          mozjpeg: {
            progressive: true,
          },
          gifsicle: {
            interlaced: false,
          },
          optipng: {
            optimizationLevel: 4,
          },
          pngquant: {
            quality: [0.75, 0.9],
            speed: 3,
          },
        },
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