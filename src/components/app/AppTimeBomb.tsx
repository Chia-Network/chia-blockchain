import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { t } from '@lingui/macro';
import { RootState } from '../../modules/rootReducer';

const CRITICAL_HEIGHT = 4608*42;

export default function AppTimeBomb() {
  const [showed, setShowed] = useState<boolean>(false);

  const peakHeight = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state?.peak?.height ?? 0,
  );

  useEffect(() => {
    if (showed || peakHeight < CRITICAL_HEIGHT) {
      return;
    }

    setShowed(true);

    // @ts-ignore
    window.remote.dialog.showMessageBox({
      type: 'warning',
      message: t`You need to upgrade the Chia application as this version will stop working soon!`,
    });
  }, [peakHeight, showed]);

  return null;
}
