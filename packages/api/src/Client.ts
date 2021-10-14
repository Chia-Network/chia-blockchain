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

export default class Client extends EventEmitter {
  private options: Required<Options>;
  private ws: any;

  private connected: boolean = false;
  private requests: Map<string, {
    resolve: (value: Response) => void;
    reject: (reason: Error) => void;
  }> = new Map();

  private services: Set<Service> = new Set();
  private registered: Set<Service> = new Set();
  private connectedPromise: Promise<void> | null = null;

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

  isRegistered(service: Service) {
    return this.registered.has(service);
  }

  addService(service: Service) {
    if (!this.services.has(service)) {
      this.services.add(service);

      this.registerServices();
    }
  }

  async removeService(service: Service) {
    if (this.services.has(service)) {
      this.services.delete(service);

      await this.daemon.stopService(service.destination);
    }
  }

  async connect() {
    if (this.connectedPromise) {
      return this.connectedPromise;
    }

    const { url, key, cert, WebSocket } = this.options;

    const ws = new WebSocket(url, {
      key,
      cert,
      rejectUnauthorized: false,
    });

    this.connectedPromise = new Promise((resolve, reject) => {
      let fullfiled = false;

      ws.once('open', () => {
        if (fullfiled) {
          return;
        }

        fullfiled = true;

        resolve();
      });

      ws.once('error', (error) => {
        if (fullfiled) {
          return;
        }

        fullfiled = true;

        reject(error);
      });
    });

    ws.on('open', this.handleOpen);
    ws.on('close', this.handleClose);
    ws.on('error', this.handleError);
    ws.on('message', this.handleMessage);

    this.ws = ws;

    return this.connectedPromise;
  }

  private async registerServices() {
    if (!this.connected) {
      return;
    }

    this.services.forEach((service) => {
      if (!this.registered.has(service)) {
        console.log('registering', service.destination, service);
        this.daemon.registerService(service.destination);
        
        this.registered.add(service);
      }
    });
  }

  private handleOpen = () => {
    this.connected = true;

    this.registered.clear();
    this.registerServices();
  }

  private handleClose = () => {
    this.connected = false;
    this.connectedPromise = null;

    this.requests.forEach((request) => {
      request.reject(new Error(`Connection closed`));
    });
  }

  private handleError = (error: any) => {
    console.log('api ws error', error);
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

      console.log('SENDING MESSAGE API', message.toJSON(camelCase));

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
