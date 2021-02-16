type Plot = {
  filename: string;
  file_size: number;
  size: number;
  local_sk: string;
  farmer_public_key: string;
  'plot-seed': string;
  plot_public_key: string;
  pool_public_key: string;
  duplicates?: Plot[];
};

export default Plot;
