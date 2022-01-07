import EventEmitter from 'events';
import debug from 'debug';
import ServiceName from './constants/ServiceName';
import Message from './Message';
import Daemon from './services/Daemon';
import sleep from './utils/sleep';
import type Service from './services/Service';
import ErrorData from './utils/ErrorData';
import ConnectionState from './constants/ConnectionState';

const log = debug('chia-api:client');

type Options = {
  url: string;
  cert: string;
  key: string;
  webSocket: any;
  services?: ServiceName[];
  timeout?: number;
  camelCase?: boolean;
  backupHost?: string;
  debug?: boolean;
};

export default class Client extends EventEmitter {
  private options: Required<Options>;
  private ws: any;

  private connected = false;
  private requests: Map<string, {
    resolve: (value: Response) => void;
    reject: (reason: Error) => void;
  }> = new Map();

  private services: Set<ServiceName> = new Set();
  private started: Set<ServiceName> = new Set();
  private connectedPromise: Promise<void> | null = null;

  private daemon: Daemon;

  private closed = false;
  private state: ConnectionState = ConnectionState.DISCONNECTED;
  private reconnectAttempt = 0;
  private startingService?: ServiceName;

  constructor(options: Options) {
    super();

    this.options = {
      timeout: 60 * 1000 * 10, // 10 minutes
      camelCase: true,
      backupHost: 'https://backup.chia.net',
      debug: false,
      services: [],
      ...options,
    };

    const { url } = this.options;
    if (!url.startsWith('wss://')) {
      throw new Error('You need to use wss (WebSocket Secure) protocol');
    }

    this.daemon = new Daemon(this);

    this.options.services.forEach((service) => {
      this.services.add(service);
    });

    if (this.options.services.length) {
      this.connect();
    } 
  }

  getState(): {
    state: ConnectionState,
    attempt: number;
    startingService?: string;
  } {
    return {
      state: this.state,
      attempt: this.reconnectAttempt,
      startingService: this.startingService,
    };
  }

  changeState(state: ConnectionState) {
    log(`Connection state changed: ${state}`);
    if (state === ConnectionState.CONNECTING && state === this.state) {
      this.reconnectAttempt += 1;
      log(`Reconnect attempt ${this.reconnectAttempt}`);
    } else {
      this.reconnectAttempt = 0;
    }

    if (state !== ConnectionState.CONNECTING) {
      this.startingService = undefined;
    }

    this.state = state;
    this.emit('state', this.getState());
  }

  onStateChange(callback: (state: { state: ConnectionState, attempt: number }) => void) {
    this.on('state', callback);

    return () => {
      this.off('state', callback);
    };
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
    if (!this.services.has(service.name)) {
      this.services.add(service.name);
    }
  }

  async stopService(service: Service) {
    if (this.services.has(service.name)) {
      this.services.delete(service.name);
      this.started.delete(service.name);

      await this.daemon.stopService(service.name);
    }
  }

  async connect(reconnect?: boolean) {
    if (this.closed) {
      log('Client is permanently closed');
      return;
    }

    if (this.connectedPromise && !reconnect) {
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

    this.changeState(ConnectionState.CONNECTING);

    log(`Connecting to ${url}`);

    const ws = new WebSocket(url, {
      key,
      cert,
      rejectUnauthorized: false,
    });

    if (!reconnect) {
      this.connectedPromise = new Promise((resolve, reject) => {
        this.connectedPromiseResponse = {
          resolve,
          reject,
        };
      });
    }

    ws.on('open', this.handleOpen);
    ws.on('close', this.handleClose);
    ws.on('error', this.handleError);
    ws.on('message', this.handleMessage);

    this.ws = ws;

    return this.connectedPromise;
  }

  async startService(serviceName: ServiceName, disableWait?: boolean) {
    if (this.started.has(serviceName)) {
      return;
    }

    const response = await this.daemon.isRunning(serviceName);
    if (!response.isRunning) {
      log(`Starting service: ${serviceName}`);
      await this.daemon.startService(serviceName);
    }

    // wait for service initialisation
    log(`Waiting for ping from service: ${serviceName}`);
    if (!disableWait) {
      while(true) {
        try {
          const { data: pingResponse } = await this.send(new Message({
            command: 'ping',
            origin: this.origin,
            destination: serviceName,
          }), 1000);
          
          if (pingResponse.success) {
            break;
          }
        } catch (error) {
          await sleep(1000);
        }
      }

      log(`Service: ${serviceName} started`);
    }

    this.started.add(serviceName);
  }

  private async startServices() {
    if (!this.connected) {
      return;
    }

    const services = Array.from(this.services);

    await Promise.all(services.map(async (serviceName) => {
      return this.startService(serviceName);
    }));
  }

  private handleOpen = async () => {
    this.connected = true;

    this.started.clear();

    this.changeState(ConnectionState.CONNECTED);

    await this.registerService(ServiceName.EVENTS);
    await this.startServices();

    if (this.connectedPromiseResponse) {
      this.connectedPromiseResponse.resolve();
      this.connectedPromiseResponse = null;
    }
  }

  registerService(service: ServiceName) {
    return this.daemon.registerService(service);
  }

  private handleClose = () => {
    this.connected = false;
    this.connectedPromise = null;

    this.requests.forEach((request) => {
      request.reject(new Error(`Connection closed`));
    });
  }

  private handleError = async (error: any) => {
    if (this.connectedPromiseResponse) {
      await sleep(1000);
      this.connect(true);
      return;
      // this.connectedPromiseResponse.reject(error);
      // this.connectedPromiseResponse = null;
    }
  }

  private handleMessage = (data: string) => {
    const { options: { camelCase } } = this;

    log('Received message', data.toString());
    const message = Message.fromJSON(data, camelCase);

    const { requestId } = message;

    if (this.requests.has(requestId)) {
      const { resolve, reject } = this.requests.get(requestId);
      this.requests.delete(requestId);

      if (message.data?.error) {
        let errorMessage = message.data.error;

        if (errorMessage == '13') {
          errorMessage = '[Error 13] Permission denied. You are trying to access a file/directory without having the necessary permissions. Most likely one of the plot folders in your config.yaml has an issue.';
        } else if (errorMessage == '22') {
          errorMessage = '[Error 22] File not found. Most likely one of the plot folders in your config.yaml has an issue.';
        }

        log(`Request ${requestId} rejected`, errorMessage);

        reject(new ErrorData(errorMessage, message.data));
        return;
      }

      if (message.data?.success === false) {
        log(`Request ${requestId} rejected`, 'Unknown error message');
        reject(new ErrorData(`Request ${requestId} failed: ${JSON.stringify(message.data)}`, message.data));
        return;
      }

      resolve(message);
    } else {
      // other messages can be events like get_harvesters
      this.emit('message', message);
    }
  }

  async send(message: Message, timeout?: number, disableFormat?: boolean): Promise<Response> {
    const { 
      connected,
      options: {
        timeout: defaultTimeout,
        camelCase,
      },
    } = this;

    const currentTimeout = timeout ?? defaultTimeout;

    if (!connected) {
      log('API is not connected trying to connect');
      await this.connect();
    }

    return new Promise((resolve, reject) => {
      const { requestId } = message;

      this.requests.set(requestId, { resolve, reject });
      const value = message.toJSON(camelCase && !disableFormat);
      log('Sending message', value);

      this.ws.send(value);

      if (currentTimeout) {
        setTimeout(() => {
          if (this.requests.has(requestId)) {
            this.requests.delete(requestId);
  
            reject(new ErrorData(`The request ${requestId} has timed out ${currentTimeout / 1000} seconds.`));
          }
        }, currentTimeout);
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

    await Promise.all(Array.from(this.started).map(async (serviceName) => {
      return await this.daemon.stopService(serviceName);
    }));

    await this.daemon.exit();

    this.ws.close();
    // this.changeState(ConnectionState.DISCONNECTED);
  }
}
