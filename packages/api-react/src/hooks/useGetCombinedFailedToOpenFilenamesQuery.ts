import useGetCombinedHarvestersQuery from './useGetCombinedHarvestersQuery';

export default function useGetCombinedFailedToOpenFilenamesQuery() {
  const { data, ...rest } = useGetCombinedHarvestersQuery();

  return {
    data: data?.failedToOpenFilenames,
    ...rest,
  };
}
