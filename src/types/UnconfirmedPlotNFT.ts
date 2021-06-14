import PlotNFTState from '../constants/PlotNFTState';

type UnconfirmedPlotNFT = {
  transactionId: string;
  state: PlotNFTState;
  poolUrl?: string;
};

export default UnconfirmedPlotNFT;
