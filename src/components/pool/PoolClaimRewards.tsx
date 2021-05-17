import { ReactNode } from 'react';
import useClaimPoolRewards from '../../hooks/usePoolClaimRewards';
import type PoolGroup from '../../types/PoolGroup';

type Props = {
  pool: PoolGroup;
  children: (claimRewards) => JSX.Element,
};

export default function PoolClaimRewards(props: Props) {
  const { pool, children } = props;

  const [claimRewards] = useClaimPoolRewards(pool);

  return children(claimRewards);
}
