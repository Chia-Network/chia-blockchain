import EventEmitter from 'events';
import ServiceName from './constants/ServiceName';
import Message from './Message';
import Daemon from './services/Daemon';
import sleep from './utils/sleep';
import type Service from './services/Service';
import ErrorData from './utils/ErrorData';

type Options = {
  url: string;
  cert: string;
  key: string;
  webSocket: any;
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
  private started: Set<ServiceName> = new Set();
  private connectedPromise: Promise<void> | null = null;

  private daemon: Daemon;

  private startingServices: boolean = false;
  private closed: boolean = false;

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
    return ServiceName.EVENTS;
  }

  get backupHost() {
    return this.options.backupHost;
  }

  get debug(): boolean {
    return this.options.debug;
  }

  isStarted(serviceName: ServiceName) {
    return this.started.has(serviceName);
  }

  addService(service: Service) {
    if (!this.services.has(service)) {
      this.services.add(service);

      this.startServices();
    }
  }

  async stopService(service: Service) {
    if (this.services.has(service)) {
      this.services.delete(service);

      this.started.delete(service.name);

      await this.daemon.stopService(service.name);
    }
  }

  async connect() {
    if (this.closed) {
      console.log('Client is closed');
      return;
    }

    if (this.connectedPromise) {
      return this.connectedPromise;
    }

    const { url, key, cert, webSocket: WebSocket } = this.options;

    if (!url) {
      throw new Error('Url is not defined');
    } else if (!key) {
      throw new Error('Key is not defined');
    } else if (!cert) {
      throw new Error('Cert is not defined');
    } else if (!WebSocket) {
      throw new Error('WebSocket is not defined');
    }

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
    if (!this.connected || this.startingServices) {
      return;
    }

    this.startingServices = true;
    await Promise.all(Array.from(this.services).map(async (service) => {
      if (!this.started.has(service.name)) {
        const response = await this.daemon.isRunning(service.name);
        if (!response.isRunning) {
          await this.daemon.startService(service.name);
        }

        // wait for service initialisation
        while(true) {
          try {
            const pingResponse = await service.ping();
            if (pingResponse.success) {
              break;
            }
            
          } catch (error) {
            await sleep(1000);
          }
        }

        this.started.add(service.name);
      }
    }));
    this.startingServices = false;
  }

  private handleOpen = async () => {
    this.connected = true;

    this.started.clear();

    this.startingServices = true;
    await this.daemon.registerService(ServiceName.EVENTS);
    await this.startServices();
    this.startingServices = false;

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
    console.log('RESPONSE', data.toString());
    const { requestId } = message;

    if (this.requests.has(requestId)) {
      const { resolve, reject } = this.requests.get(requestId);
      this.requests.delete(requestId);

      if (message.data?.error) {
        reject(new ErrorData(message.data?.error, message.data));
        return;
      }

      if (message.data?.success === false) {
        reject(new ErrorData(`Request ${requestId} failed: ${JSON.stringify(message.data)}`, message.data));
        return;
      }

      resolve(message);
    }

    this.emit('message', message);
  }

  async send(message: Message): Promise<Response> {
    const { 
      startingServices,
      connected,
      options: {
        timeout,
        camelCase,
      },
    } = this;

    if (!connected) {
      console.log('API is not connected trying to connect');
      await this.connect();
    }

    if (!startingServices) {
      await this.startServices();
    }

    return new Promise((resolve, reject) => {
      const { requestId } = message;

      this.requests.set(requestId, { resolve, reject });
      this.ws.send(message.toJSON(camelCase));

      console.log('SEND', message.toJSON(camelCase));

      if (timeout) {
        setTimeout(() => {
          if (this.requests.has(requestId)) {
            this.requests.delete(requestId);
  
            reject(new ErrorData(`The request ${requestId} has timed out ${timeout / 1000} seconds.`));
          }
        }, timeout);
      }
    });
  }

  async close(force: true) {
    if (force) {
      this.closed = true;
    }

    if (!this.connected) {
      return;
    }

    this.startingServices = true;

    await Promise.all(Array.from(this.started).map(async (serviceName) => {
      return await this.daemon.stopService(serviceName);
    }));

    await this.daemon.exit();

    this.startingServices = false;

    this.ws.close();
  }
}
