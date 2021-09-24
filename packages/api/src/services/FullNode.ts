import Connection from '../Connection';
import Service from './Service';
import type { Options } from './Service';
import ServiceName from '../constants/ServiceName';

export default class FullNode extends Service {
  constructor(connection: Connection, options?: Options) {
    super(ServiceName.FULL_NODE, connection, options);
  }

}
