import { net, ipcMain, IncomingMessage, BrowserWindow } from 'electron';
import http from 'http';
import https from 'https';
import fs from 'fs';
import path from 'path';
import { MAX_FILE_SIZE } from '../hooks/useVerifyURIHash';
const crypto = require('crypto');

function getChecksum(path) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash('sha256');
    const input = fs.createReadStream(path);
    input.on('error', reject);
    input.on('data', (chunk) => {
      hash.update(chunk);
    });
    input.on('close', () => {
      resolve(hash.digest('hex'));
    });
  });
}

export default function validateSha256(
  cacheFolder: string,
  mainWindow: BrowserWindow,
  uri: string,
  force: boolean,
  validatingInProgress: (uri: string, action: string) => void,
) {
  let tempSize = 0;
  const fileOnDisk = cacheFolder + path + Buffer.from(uri).toString('base64');
  const fileStream = fs.createWriteStream(fileOnDisk);
  validatingInProgress(uri, 'start');
  (uri.match(/^https/) ? https : http).get(uri, (res) => {
    if (res.statusCode !== 200) {
      res.resume();
      mainWindow.webContents.send('sha256FileGetError');
      return;
    }
    let fileSize = parseInt(res.headers['content-length'] || '0');

    if (force || fileSize < MAX_FILE_SIZE) {
      mainWindow.webContents.send('sha256FileContentLength', fileSize);

      res.on('data', (chunk) => {
        tempSize += chunk.length;
        mainWindow.webContents.send('sha256DownloadProgress', {
          uri,
          progress: tempSize / fileSize || 1,
        });
        fileStream.write(chunk);
      });

      res.on('end', () => {
        validatingInProgress(uri, 'stop');
        mainWindow.webContents.send('sha256FileFinishedDownloading');
        getChecksum(fileOnDisk)
          .then((checksum) => {
            mainWindow.webContents.send('sha256hash', checksum);
          })
          .catch((err) => console.log(err));
      });
    } else {
      validatingInProgress(uri, 'stop');
      res.on('end', () => {});
    }
  });
}
