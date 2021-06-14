import { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useInterval } from 'react-use';
import type { RootState } from '../modules/rootReducer';
import type PlotNFT from '../types/PlotNFT';
import { getPlotNFTs } from '../modules/plotNFT';

export default function usePlotNFTs(): {
  loading: boolean;
  nfts?: PlotNFT[];
} {
  const dispatch = useDispatch();
  const nfts = useSelector((state: RootState) => state.plot_nft.items);
  const loading = !nfts;

  useInterval(() => {
    dispatch(getPlotNFTs());
  }, 10000);

  useEffect(() => {
    dispatch(getPlotNFTs());
  }, []);

  return {
    loading,
    nfts,
  };
}