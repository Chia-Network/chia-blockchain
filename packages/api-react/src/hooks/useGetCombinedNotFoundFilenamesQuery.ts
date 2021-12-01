import useGetCombinedHarvestersQuery from './useGetCombinedHarvestersQuery';

export default function useGetCombinedNotFoundFilenamesQuery() {
  const { data, ...rest } = useGetCombinedHarvestersQuery();

  return {
    data: data?.notFoundFilenames,
    ...rest,
  };
}
