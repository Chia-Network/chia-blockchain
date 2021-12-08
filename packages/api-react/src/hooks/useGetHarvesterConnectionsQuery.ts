import { useMemo } from 'react';
import { useGetFarmerConnectionsQuery } from '../services/farmer';

export default function useGetHarvesterConnectionsQuery() {
  const { data: connections, ...rest } = useGetFarmerConnectionsQuery();
  const data = useMemo(() => {
    return connections?.filter((connection) => connection.type === 2);
  }, [connections]);

  return {
    data,
    ...rest,
  };
}
