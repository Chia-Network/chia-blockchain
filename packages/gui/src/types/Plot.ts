type Plot = {
  plot_id: string;
  filename: string;
  file_size: number;
  size: number;
  local_sk: string;
  farmer_public_key: string;
  plot_public_key: string;
  pool_public_key: string;
  pool_contract_puzzle_hash: string;
  duplicates?: Plot[];
};

export default Plot;
