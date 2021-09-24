type Connection = {
  bytes_read: number;
  bytes_written: number;
  creation_time: number;
  last_message_time: number;
  local_host: string;
  local_port: number;
  node_id: string;
  peer_host: string;
  peer_port: number;
  peer_server_port: number;
  type: number;
};

export default Connection;
