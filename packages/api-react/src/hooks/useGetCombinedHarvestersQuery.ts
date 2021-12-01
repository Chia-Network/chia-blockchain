import { useMemo } from 'react';
import { useGetHarvestersQuery } from "../services/farmer";
import combineHarvesters from '../utils/combineHarvesters';

export default function useGetCombinedHarvestersQuery() {
  const { data: harvesters, ...rest } = useGetHarvestersQuery();

  const combinedData = useMemo(() => {
    if (!harvesters) {
      return harvesters;
    }

    return combineHarvesters(harvesters);
  }, [harvesters]);

  return {
    data: combinedData,
    ...rest,
  };
}