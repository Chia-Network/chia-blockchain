import { useMemo } from 'react';
import { useGetConnectionsQuery } from '../services/farmer';

export default function useGetFarmerFullNodeConnectionsQuery() {
  const { data: connections, ...rest } = useGetConnectionsQuery();
  const data = useMemo(() => {
    return connections?.filter((connection) => connection.type === 1);
  }, [connections]);

  return {
    data,
    ...rest,
  };
}