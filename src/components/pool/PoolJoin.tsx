import type { ReactNode } from 'react';
import usePoolJoin from '../../hooks/usePoolJoin';
import type Group from '../../types/Group';

type Props = {
  group: Group;
  children: (join) => JSX.Element,
};

export default function PoolJoin(props: Props) {
  const { group, children } = props;

  const [join] = usePoolJoin(group);

  return children(join);
}
