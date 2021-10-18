import ServiceName from "../constants/ServiceName";

export default interface MessageInterface {
  command: string;
  data: Object;
  origin: ServiceName;
  destination: ServiceName;
  ack: boolean; 
  requestId?: string;
}
