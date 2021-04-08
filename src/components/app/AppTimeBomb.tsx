import React, { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { t, Trans } from '@lingui/macro';
import { Alert } from '@material-ui/lab';
import { RootState } from '../../modules/rootReducer';

const INFO_HEIGHT = 4608 * 32;
const CRITICAL_HEIGHT = 4608 * 42;

export default function AppTimeBomb() {
  const [showed, setShowed] = useState<boolean>(false);

  const peakHeight = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state?.peak?.height ?? 0,
  );

  useEffect(() => {
    if (showed || peakHeight < INFO_HEIGHT) {
      return;
    }

    setShowed(true);

    // @ts-ignore
    window.remote.dialog.showMessageBox({
      type: 'warning',
      message: t`You need to upgrade the Chia application as this version will stop working soon!`,
    });
  }, [peakHeight, showed]);

  if (peakHeight > CRITICAL_HEIGHT) {
    return (
      <Alert severity="warning">
        <Trans>You need to upgrade the Chia application as this version will stop working soon!</Trans>
      </Alert>
    );
  }

  return null;
}
