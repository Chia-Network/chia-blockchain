import PlotNFTState from '../constants/PlotNFTState';

type UnconfirmedPlotNFT = {
  fingerprint: string;
  transactionId: string;
  state: PlotNFTState;
  poolUrl?: string;
};

export default UnconfirmedPlotNFT;
