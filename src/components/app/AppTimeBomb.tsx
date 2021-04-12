import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { t } from '@lingui/macro';
import { RootState } from '../../modules/rootReducer';

const RESET_TIMEOUT = 4 * 60 * 60 * 1000; // 4 hours
const INFO_HEIGHT = 166000; // 32 days

export default function AppTimeBomb() {
  const [showed, setShowed] = useState<boolean>(false);
  const [timeoutId, setTimeoutId] = useState<number | undefined>();

  const peakHeight = useSelector(
    (state: RootState) => state.full_node_state.blockchain_state?.peak?.height ?? 0,
  );

  async function informUser() {
    if (showed || peakHeight < INFO_HEIGHT) {
      return;
    }

    setShowed(true);

    // @ts-ignore
    await window.remote.dialog.showMessageBox(window.remote.getCurrentWindow(), {
      type: 'warning',
      message: t`The application will stop working at block height 193536.`,
    });

    const newTimeoutId = setTimeout(() => {
      setShowed(false);
    }, RESET_TIMEOUT);

    // @ts-ignore
    setTimeoutId(newTimeoutId);
  }

  useEffect(() => {
    informUser();

    return () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    }
  }, [peakHeight, showed, timeoutId]);

  return null;
}
