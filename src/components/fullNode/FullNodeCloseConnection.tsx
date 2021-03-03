import React from 'react';
import { useDispatch } from 'react-redux';
import { Trans } from '@lingui/macro';
import { ConfirmDialog } from '@chia/core';
import { closeConnection } from '../../modules/fullnodeMessages';
import useOpenDialog from '../../hooks/useOpenDialog';

type Props = {
  nodeId: string;
  children: (props: { onClose: () => void }) => JSX.Element;
};

export default function FullNodeCloseConnection(props: Props): JSX.Element {
  const { nodeId, children } = props;
  const openDialog = useOpenDialog();
  const dispatch = useDispatch();

  async function handleClose() {
    const canDisconnect = await openDialog((
      <ConfirmDialog
        title={<Trans>Confirm Disconnect</Trans>}
        confirmTitle={<Trans>Disconnect</Trans>}
        confirmColor="danger"
      >
        <Trans>
          Are you sure you want to disconnect?
        </Trans>
      </ConfirmDialog>
    ));

    // @ts-ignore
    if (canDisconnect) {
      dispatch(closeConnection(nodeId));
    }
  }

  return children({
    onClose: handleClose,
  });
}
