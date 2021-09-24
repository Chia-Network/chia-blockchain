import EventEmitter from 'events';
import type Connection from '../Connection';
import Message from '../Message';

export type Options = {
  origin?: string;
};

export default class Service extends EventEmitter {
  connection: Connection;
  destination: string;
  origin: string;
  registered: boolean = false;

  constructor(name: string, connection: Connection, options: Options = {}) {
    super();

    const { origin } = options;

    this.connection = connection;
    this.destination = name;
    this.origin = origin ?? connection.origin ?? 'service';

    connection.addService(this);
    connection.on('message', this.handleMessage);
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
      this.registered = true;
    }

    if (message.command) {
      this.emit(message.command, message.data, message);
    }    
  }

  async command(command: string, data: Object = {}, ack: boolean = false): Promise<any> {
    const { connection, origin, destination } = this;

    if (!command) {
      throw new Error('Command is required parameter');
    }

    const response = await connection.send(new Message({
      origin,
      destination,
      command,
      data,
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
