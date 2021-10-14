import EventEmitter from 'events';
import { isUndefined, omitBy } from 'lodash';
import type Client from '../Client';
import Message from '../Message';

export type Options = {
  origin?: string;
};

export default class Service extends EventEmitter {
  private _client: Client;
  private _destination: string;
  private _origin: string;

  constructor(name: string, client: Client, options: Options = {}) {
    super();

    const { origin } = options;

    this._client = client;
    this._destination = name;
    this._origin = origin ?? client.origin;

    client.addService(this);
    client.on('message', this.handleMessage);
  }

  get destination() {
    return this._destination;
  }

  get client() {
    return this._client;
  }

  get origin() {
    return this._origin;
  }

  get registered() {
    return this.client.isRegistered(this);
  }

  handleMessage = (message: Message) => {
    if (message.destination !== this.destination) {
      return;
    }

    this.processMessage(message);
  }

  processMessage(message: Message) {
    if (message.command === 'register_service') {
      console.log('service was registered', this.destination);
      this._registered = true;
      this.emit('ready');
    }

    if (message.command) {
      this.emit(message.command, message.data, message);
    }    
  }

  async command(command: string, data: Object = {}, ack: boolean = false): Promise<any> {
    const { client, origin, destination } = this;

    if (!command) {
      throw new Error('Command is required parameter');
    }

    // remove undefined values from root data
    const updatedData = omitBy(data, isUndefined);

    const response = await client.send(new Message({
      origin,
      destination,
      command,
      data: updatedData,
      ack,
    }));

    console.log('response', response);

    return response?.data;
  }

  async ping() {
    return this.command('ping');
  }

  onCommand(
    command: string, 
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ): () => void {
    function handleCommand(currentCommand: string, data: any, message: Message) {
      if (currentCommand === command) {
        const updatedData = processData ? processData(data, message) : data;
        callback(updatedData, message);
      }
    }

    this.on('command', handleCommand);

    return () => {
      this.off('command', handleCommand);
    };
  }

  onStateChanged(
    state: string,
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any,
  ) {
    return this.onCommand('state_changed', (data, message) => {
      if (data.state === state) {
        callback(data, message);
      }
    }, processData);
  }
}
