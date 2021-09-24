export default interface MessageInterface {
  command: string;
  data: Object;
  origin: string;
  destination: string;
  ack: boolean; 
  requestId?: string;
}
