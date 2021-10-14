import Client from '../Client';
import Service from './Service';
import type { Options } from './Service';
import ServiceName from '../constants/ServiceName';

export default class Events extends Service {
  constructor(client: Client, options?: Options) {
    super(ServiceName.EVENTS, client, {
      skipAddService: true,
      ...options,
    });
  }
}
