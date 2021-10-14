import EventEmitter from 'events';
import ServiceName from './constants/ServiceName';
import Message from './Message';
import Daemon from './services/Daemon';
import Events from './services/Events';
import type Service from './services/Service';

type Options = {
  url: string;
  cert: string;
  key: string;
  WebSocket: any;
  origin?: string;
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
      origin: ServiceName.EVENTS,
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

      this.startServices();
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
      this.connectedPromiseResponse = {
        resolve,
        reject,
      };
    });

    ws.on('open', this.handleOpen);
    ws.on('close', this.handleClose);
    ws.on('error', this.handleError);
    ws.on('message', this.handleMessage);

    this.ws = ws;

    return this.connectedPromise;
  }

  private async startServices() {
    if (!this.connected) {
      return;
    }

    await Promise.all(Array.from(this.services).map(async (service) => {
      if (!this.registered.has(service)) {
        const response = await this.daemon.isRunning(service.destination);
        if (!response.isRunning) {
          // this.daemon.registerService(service.destination);
          await this.daemon.startService(service.destination);
        }

        // await service.ping();

        this.registered.add(service);
      }
    }));
  }

  private handleOpen = async () => {
    this.connected = true;

    this.registered.clear();

    await this.daemon.registerService(ServiceName.EVENTS);
    await this.startServices();

    if (this.connectedPromiseResponse) {
      this.connectedPromiseResponse.resolve();
      this.connectedPromiseResponse = null;
    }
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

    if (this.connectedPromiseResponse) {
      this.connectedPromiseResponse.reject(error);
      this.connectedPromiseResponse = null;
    }
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
