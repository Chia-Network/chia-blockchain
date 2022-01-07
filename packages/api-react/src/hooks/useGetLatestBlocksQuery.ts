import { get } from 'lodash';
import { useGetBlockchainStateQuery, useGetBlockRecordsQuery } from "../services/fullNode";

export default function useGetLatestBlocksQuery(count = 10) {
  const { data: state, isLoading: isLoadingBlockchainState, ...rest } = useGetBlockchainStateQuery();
  const peakHeight = get(state, 'peak.height');
  const end = peakHeight ? peakHeight + 1 : 1;
  const start = Math.max(0, end - count);
  const { data: blocks, isLoading: isLoadingBlocks } = useGetBlockRecordsQuery({
    start,
    end,
  }, {
    skip: !peakHeight,
  });

  const isLoading = isLoadingBlockchainState || isLoadingBlocks;

  return {
    isLoading,
    data: blocks ? [...blocks].reverse() : blocks,
    ...rest,
  };
}
