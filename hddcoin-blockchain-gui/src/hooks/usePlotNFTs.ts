import { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useInterval } from 'react-use';
import type { RootState } from '../modules/rootReducer';
import type PlotNFT from '../types/PlotNFT';
import { getPlotNFTs } from '../modules/plotNFT';
import PlotNFTExternal from 'types/PlotNFTExternal';

export default function usePlotNFTs(): {
  loading: boolean;
  nfts?: PlotNFT[];
  external?: PlotNFTExternal[];
} {
  const dispatch = useDispatch();
  const nfts = useSelector((state: RootState) => state.plot_nft.items);
  const external = useSelector((state: RootState) => state.plot_nft.external);
  const loading = !nfts || !external;

  useInterval(() => {
    dispatch(getPlotNFTs());
  }, 10000);

  useEffect(() => {
    dispatch(getPlotNFTs());
  }, []);

  return {
    loading,
    nfts,
    external,
  };
}
