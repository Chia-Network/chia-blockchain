import EventEmitter from 'events';
import Message from './Message';
import Daemon from './services/Daemon';
import type Service from './services/Service';

type Options = {
  url: string;
  cert: string;
  key: string;
  WebSocket: any;
  origin: string;
  timeout?: number;
  camelCase?: boolean;
  backupHost?: string;
  debug?: boolean;
};

export default class Connection extends EventEmitter {
  private options: Required<Options>;
  private ws: any;

  private connected: boolean = false;
  private requests: Map<string, {
    resolve: (value: Response) => void;
    reject: (reason: Error) => void;
  }> = new Map();

  private services: Set<Service> = new Set();

  private daemon: Daemon;

  constructor(options: Options) {
    super();

    this.options = {
      timeout: 60 * 1000, // 60 seconds
      camelCase: true,
      backupHost: 'https://backup.chia.net',
      debug: false,
      ...options,
    };

    const { url } = this.options;
    if (!url.startsWith('wss://')) {
      throw new Error('You need to use wss (WebSocket Secure) protocol');
    }

    this.daemon = new Daemon(this);
  }

  get origin() {
    return this.options.origin;
  }

  get backupHost() {
    return this.options.backupHost;
  }

  get debug(): boolean {
    return this.options.debug;
  }

  addService(service: Service) {
    this.services.add(service);

    return this.daemon.registerService(service.destination);
  }

  async connect() {
    const { url, key, cert, WebSocket } = this.options;

    const ws = new WebSocket(url, {
      key,
      cert,
      rejectUnauthorized: false,
    });

    ws.on('open', this.handleOpen);
    ws.on('close', this.handleClose);
    ws.on('error', this.handleError);
    ws.on('message', this.handleMessage);

    this.ws = ws;
  }

  private handleOpen = () => {
    this.connected = true;
  }

  private handleClose = () => {
    this.connected = false;
  }

  private handleError = (error: any) => {
    this.emit('error', error);
  }

  private handleMessage = (data: string) => {
    const { options: { camelCase } } = this;

    const message = Message.fromJSON(data, camelCase);
    const { requestId } = message;

    if (this.requests.has(requestId)) {
      const { resolve, reject } = this.requests.get(requestId);
      this.requests.delete(requestId);

      if (message.data?.error) {
        reject(new Error(message.data?.error));
        return;
      }

      if (message.data?.success === false) {
        reject(new Error(`Request ${requestId} failed: ${JSON.stringify(message.data)}`));
        return;
      }

      resolve(message);
    }

    this.emit('message', message);
  }

  async send(message: Message): Promise<Response> {
    const { 
      connected,
      options: {
        timeout,
        camelCase,
      },
      
    } = this;

    if (!connected) {
      throw new Error('You need to connect first');
    }

    return new Promise((resolve, reject) => {
      const { requestId } = message;

      this.requests.set(requestId, { resolve, reject });
      this.ws.send(message.toJSON(camelCase));

      if (timeout) {
        setTimeout(() => {
          if (this.requests.has(requestId)) {
            this.requests.delete(requestId);
  
            reject(new Error(`The request ${requestId} has timed out ${timeout / 1000} seconds.`));
          }
        }, timeout);
      }
    });
  }

  async close() {
    if (!this.connected) {
      return;
    }

    this.ws.close();
  }
}
