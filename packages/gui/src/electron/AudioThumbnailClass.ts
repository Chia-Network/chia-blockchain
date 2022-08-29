import fs from 'fs';
import path from 'path';
import ffmpegStatic from 'ffmpeg-static';
import ffprobeStatic from 'ffprobe-static';
import ffmpeg from 'fluent-ffmpeg';

/* ffmpeg library should not be packed into app.asar in production! */
let pathToFfmpeg = ffmpegStatic.replace('app.asar', 'app.asar.unpacked');
let pathToFfprobe = ffprobeStatic.path.replace('app.asar', 'app.asar.unpacked');

const DEV = process.env.NODE_ENV !== 'production';
/* ffmpeg binary remains in node_modules (development) */

pathToFfmpeg = DEV
  ? pathToFfmpeg.replace(
      'build' + path.sep + 'electron',
      'node_modules' + path.sep + 'ffmpeg-static',
    )
  : pathToFfmpeg;

pathToFfprobe = DEV
  ? pathToFfprobe.replace(
      'build' + path.sep + 'electron',
      'node_modules' + path.sep + 'ffprobe-static',
    )
  : pathToFfprobe;

ffmpeg.setFfmpegPath(pathToFfmpeg);
ffmpeg.setFfprobePath(pathToFfprobe);

export default class AudioThumbnail {
  private uri: string;
  private filePath: string;

  constructor(uri: string, cacheFolder: string, appName: string) {
    this.uri = uri;
    this.filePath =
      cacheFolder +
      path.sep +
      appName +
      path.sep +
      Buffer.from(uri).toString('base64');
  }

  async createAudioThumbnail() {
    if (fs.existsSync(this.filePath + '.json')) {
      const json = fs.readFileSync(this.filePath + '.json', 'utf8');
      return JSON.parse(json);
    }
    const responseObject: any = {
      uri: this.uri,
      type: 'audio',
    };
    const audioData: any = await this.probeUri();
    const stream = Array.isArray(audioData.streams) && audioData.streams[0];
    if (stream) {
      responseObject.codec_name = stream.codec_name;
      responseObject.sample_rate = stream.sample_rate;
      responseObject.duration = stream.duration;
      responseObject.channel_layout = stream.channel_layout;
    }
    const format = audioData.format;
    if (format) {
      responseObject.bit_rate = format.bit_rate;
      responseObject.size = format.size;
      if (format.tags) {
        responseObject.title = format.tags.title;
        responseObject.artist = format.tags.artist;
        responseObject.album = format.tags.album;
      }
    }
    fs.writeFileSync(this.filePath + '.json', JSON.stringify(responseObject));
    return responseObject;
  }

  probeUri() {
    return new Promise((resolve, reject) => {
      ffmpeg.ffprobe(this.uri, (err: any, probeObj: any) => {
        if (err) {
          reject(err);
        } else {
          resolve(probeObj);
        }
      });
    });
  }
}
