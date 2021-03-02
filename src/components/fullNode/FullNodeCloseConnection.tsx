import { useDispatch } from 'react-redux';
import { closeConnection } from '../../modules/fullnodeMessages';

type Props = {
  nodeId: string;
  children: (props: { onClose: () => void }) => JSX.Element;
};

export default function FullNodeCloseConnection(props: Props): JSX.Element {
  const { nodeId, children } = props;
  const dispatch = useDispatch();

  function handleClose() {
    dispatch(closeConnection(nodeId));
  }

  return children({
    onClose: handleClose,
  });
}
