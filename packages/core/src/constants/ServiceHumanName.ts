import { ServiceName } from '@chia/api';

const ServiceHumanName = {
  [ServiceName.WALLET]: 'Wallet',
  [ServiceName.FULL_NODE]: 'Full Node',
  [ServiceName.FARMER]: 'Farmer',
  [ServiceName.HARVESTER]: 'Harvester',
  [ServiceName.SIMULATOR]: 'Full Node Simulator',
  [ServiceName.DAEMON]: 'Daemon',
  [ServiceName.PLOTTER]: 'Plotter',
  [ServiceName.EVENTS]: 'Events',
}

export default ServiceHumanName;