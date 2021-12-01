import useGetCombinedHarvestersQuery from './useGetCombinedHarvestersQuery';

export default function useGetCombinedPlotsQuery() {
  const { data, ...rest } = useGetCombinedHarvestersQuery();

  return {
    data: data?.plots,
    ...rest,
  };
}