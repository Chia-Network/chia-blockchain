import type { PlotNFT } from '@chia/api';
import { useGetPlotNFTsQuery } from '@chia/api-react';
import PlotNFTExternal from 'types/PlotNFTExternal';

export default function usePlotNFTs(): {
  loading: boolean;
  nfts?: PlotNFT[];
  external?: PlotNFTExternal[];
} {
  const { data, isLoading } = useGetPlotNFTsQuery(undefined, {
    pollingInterval: 10000,
  });

  return {
    loading: isLoading,
    nfts: data?.nfts,
    external: data?.external,
  };
}
