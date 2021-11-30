import React from 'react';
import { Trans } from '@lingui/macro';
import { ConfirmDialog, useOpenDialog } from '@chia/core';
import { useCloseFullNodeConnectionMutation } from '@chia/api-react';

type Props = {
  nodeId: string;
  children: (props: { onClose: () => void }) => JSX.Element;
};

export default function FullNodeCloseConnection(props: Props): JSX.Element {
  const { nodeId, children } = props;
  const openDialog = useOpenDialog();
  const [closeConnection] = useCloseFullNodeConnectionMutation();

  async function handleClose() {
    await openDialog(
      <ConfirmDialog
        title={<Trans>Confirm Disconnect</Trans>}
        confirmTitle={<Trans>Disconnect</Trans>}
        confirmColor="danger"
        onConfirm={() => closeConnection({
          nodeId,
        }).unwrap()}
      >
        <Trans>Are you sure you want to disconnect?</Trans>
      </ConfirmDialog>,
    );
  }

  return children({
    onClose: handleClose,
  });
}
