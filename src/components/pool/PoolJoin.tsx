import type { ReactNode } from 'react';
import usePoolJoin from '../../hooks/usePoolJoin';
import type PoolGroup from '../../types/PoolGroup';

type Props = {
  pool: PoolGroup;
  children: (join) => JSX.Element,
};

export default function PoolJoin(props: Props) {
  const { pool, children } = props;

  const [join] = usePoolJoin(pool);

  return children(join);
}
