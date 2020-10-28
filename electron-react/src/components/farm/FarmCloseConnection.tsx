import { useDispatch } from 'react-redux';
import { closeConnection } from '../../modules/farmerMessages';

type Props = {
  nodeId: string;
  children: (props: { onClose: () => void }) => JSX.Element;
};

export default function FarmCloseConnection(props: Props): JSX.Element {
  const { nodeId, children } = props;
  const dispatch = useDispatch();

  function handleClose() {
    dispatch(closeConnection(nodeId));
  }

  return children({
    onClose: handleClose,
  });
}
