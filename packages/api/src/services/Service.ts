import EventEmitter from 'events';
import { isUndefined, omitBy } from 'lodash';
import type Client from '../Client';
import ServiceName from '../constants/ServiceName';
import Message from '../Message';
import sleep from '../utils/sleep';

export type Options = {
  origin?: ServiceName;
  skipAddService?: boolean;
};

export default class Service extends EventEmitter {
  private _client: Client;
  private _name: ServiceName;
  private _origin: ServiceName;
  private _readyPromise: Promise<null> | undefined;

  constructor(
    name: ServiceName,
    client: Client,
    options: Options = {},
    onInit?: () => Promise<void>,
  ) {
    super();

    const { origin, skipAddService } = options;

    this._client = client;
    this._name = name;
    this._origin = origin ?? client.origin;

    if (!skipAddService) {
      client.addService(this);
    }

    client.on('message', this.handleMessage);

    this._readyPromise = new Promise(async (resolve, reject) => {
      setTimeout(async () => {
        try {
          if (onInit) {
            await onInit();
          }
          resolve(null);
          return;
        } catch (error: any) {
          reject(error);
        }
      });
    });
  }

  async whenReady(callback?: () => Promise<any>) {
    await this._readyPromise;
    if (callback) {
      return callback();
    }
  }

  get name() {
    return this._name;
  }

  get client() {
    return this._client;
  }

  get origin() {
    return this._origin;
  }

  register() {
    return this._client.registerService(this.name);
  }

  handleMessage = (message: Message) => {
    if (message.origin !== this.name) {
      return;
    }

    this.processMessage(message);
  };

  processMessage(message: Message) {
    if (message.command) {
      this.emit(message.command, message.data, message);
    }
  }

  async command(
    command: string,
    data: Object = {},
    ack = false,
    timeout?: number,
    disableFormat?: boolean
  ): Promise<any> {
    const { client, origin, name } = this;

    if (!command) {
      throw new Error('Command is required parameter');
    }

    // remove undefined values from root data
    const updatedData = omitBy(data, isUndefined);

    const response = await client.send(
      new Message({
        origin,
        destination: name,
        command,
        data: updatedData,
        ack,
      }),
      timeout,
      disableFormat
    );

    return response?.data;
  }

  async ping(): Promise<{
    success: boolean;
  }> {
    return this.command('ping', undefined, undefined, 1000);
  }

  onCommand(
    command: string,
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any
  ): () => void {
    function handleCommand(data: any, message: Message) {
      const updatedData = processData ? processData(data, message) : data;
      callback(updatedData, message);
    }

    this.on(command, handleCommand);

    return () => {
      this.off(command, handleCommand);
    };
  }

  onStateChanged(
    state: string,
    callback: (data: any, message: Message) => void,
    processData?: (data: any) => any
  ) {
    return this.onCommand(
      'state_changed',
      (data, message) => {
        if (data.state === state) {
          callback(data, message);
        }
      },
      processData
    );
  }
}
