import { useCloseFarmerConnectionMutation } from '@chia/api-react';

type Props = {
  nodeId: string;
  children: (props: { onClose: () => void }) => JSX.Element;
};

export default function FarmCloseConnection(props: Props): JSX.Element {
  const { nodeId, children } = props;
  const [closeFarmerConnection] = useCloseFarmerConnectionMutation();

  async function handleClose() {
    await closeFarmerConnection(nodeId).unwrap();
  }

  return children({
    onClose: handleClose,
  });
}
