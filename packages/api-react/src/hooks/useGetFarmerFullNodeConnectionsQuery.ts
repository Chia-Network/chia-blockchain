import { useMemo } from 'react';
import { useGetFarmerConnectionsQuery } from '../services/farmer';

export default function useGetFarmerFullNodeConnectionsQuery() {
  const { data: connections, ...rest } = useGetFarmerConnectionsQuery({}, {
    pollingInterval: 10000,
  });
  const data = useMemo(() => {
    return connections?.filter((connection) => connection.type === 1);
  }, [connections]);

  return {
    data,
    ...rest,
  };
}
