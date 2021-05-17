type PoolGroup = {
  id: string;
  self: boolean;
  name: string;
  poolUrl?: string;
  poolName?: string;
  poolDescription?: string;
  state: 'NOT_CREATED' | 'FREE' | 'POOLING' | 'ESCAPING';
  targetState?: 'FREE' | 'POOLING' | 'ESCAPING';
  balance: number;
  address: string;
};

export default PoolGroup;
