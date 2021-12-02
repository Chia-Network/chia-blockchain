import { useMemo } from 'react';
import { useGetConnectionsQuery } from '../services/farmer';

export default function useGetHarvesterConnectionsQuery() {
  const { data: connections, ...rest } = useGetConnectionsQuery();
  const data = useMemo(() => {
    return connections?.filter((connection) => connection.type === 2);
  }, [connections]);

  return {
    data,
    ...rest,
  };
}
