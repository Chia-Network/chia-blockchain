import { useMemo } from 'react';
import { useGetHarvestersSummaryQuery } from '../services/farmer';

export default function useGetHarvesterStats(nodeId: string): {
  isLoading: boolean;
  error?: Error;
  harvester: any;
} {
  const { data, isLoading, error } = useGetHarvestersSummaryQuery();

  const harvester = useMemo(() => {
    return data?.find((harvester) => harvester.connection.nodeId === nodeId);
  }, [data, nodeId]);

  return {
    isLoading,
    error,
    harvester,
  };
}
