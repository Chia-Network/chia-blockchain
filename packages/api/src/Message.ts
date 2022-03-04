import { randomBytes } from 'crypto-browserify';
import JSONbig from 'json-bigint';
import type MessageInterface from './@types/MessageInterface';
import ServiceName from './constants/ServiceName';
import toCamelCase from './utils/toCamelCase';
import toSnakeCase from './utils/toSnakeCase';
import toSafeNumber from './utils/toSafeNumber';

export default class Message implements MessageInterface {
  command: string;
  data: Object;
  origin: ServiceName;
  destination: ServiceName;
  ack: boolean;
  requestId: string;

  constructor(options: MessageInterface) {
    const {
      command,
      origin,
      destination,
      data = {},
      ack = false,
      requestId = randomBytes(32).toString('hex'),
    } = options;
  
    this.command = command;
    this.origin = origin;
    this.destination = destination;
    this.data = data;
    this.ack = ack;
    this.requestId = requestId;
  }

  toJSON(useSnakeCase: boolean): string {
    const data = {
      command: this.command,
      data: this.data,
      origin: this.origin,
      destination: this.destination,
      ack: this.ack,
      request_id: this.requestId,
    };

    const formatedData = useSnakeCase
      ? toSnakeCase(data)
      : data;

    return JSONbig.stringify(formatedData);
  }

  static fromJSON(json: string, useCamelCase: boolean): Message {
    const {
      command,
      data,
      origin,
      destination,
      ack,
      request_id: requestId,
    } = toSafeNumber(JSONbig.parse(json));

    return new Message({
      command,
      data: useCamelCase ? toCamelCase(data): data,
      origin,
      destination,
      ack,
      requestId,
    });
  }
}
