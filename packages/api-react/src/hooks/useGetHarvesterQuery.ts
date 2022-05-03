import { useMemo } from 'react';
import { useGetHarvestersSummaryQuery } from '../services/farmer';

export default function useGetHarvesterQuery({
  nodeId,
}: {
  nodeId: string
}): {
  isLoading: boolean;
  error?: Error;
  plots?: number;
  noKeyFilenames?: number;
  failedToOpenFilenames?: number;
  duplicates?: number;
  totalPlotSize?: number;
  connection?: {
    nodeId: string;
    host: string;
    port: number;
  },
  initialized: boolean;
} {
  const { data, isLoading: isLoadingHarvesterSummary, error } = useGetHarvestersSummaryQuery();

  const harvester = useMemo(() => {
    return data?.find((harvester) => harvester.connection.nodeId === nodeId);
  }, [data, nodeId]);

  const isLoading = isLoadingHarvesterSummary;

  return {
    isLoading,
    error,
    connection: harvester?.connection,
    plots: harvester?.plots,
    noKeyFilenames: harvester?.noKeyFilenames,
    failedToOpenFilenames: harvester?.failedToOpenFilenames,
    duplicates: harvester?.duplicates,
    totalPlotSize: harvester?.totalPlotSize,
    initialized: harvester?.syncing?.initial !== true,
  };
}
