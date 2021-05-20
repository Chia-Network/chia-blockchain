import useGroupClaimRewards from '../../hooks/useGroupClaimRewards';
import type Group from '../../types/Group';

type Props = {
  group: Group;
  children: (claimRewards) => JSX.Element,
};

export default function GroupClaimRewards(props: Props) {
  const { group, children } = props;

  const [claimRewards] = useGroupClaimRewards(group);

  return children(claimRewards);
}
