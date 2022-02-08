import React from 'react';
import { Trans } from '@lingui/macro';
import ConfirmDialog from '../components/ConfirmDialog';
import useSkipMigration from './useSkipMigration';
import useOpenDialog from './useOpenDialog';

export default function useKeyringMigrationPrompt() {
  const [_, setSkipMigration] = useSkipMigration();
  const openDialog = useOpenDialog();

  async function promptForKeyringMigration(): Promise<void> {

    const beginMigration = await openDialog(
      <ConfirmDialog
        title={<Trans>Migration required</Trans>}
        confirmTitle={<Trans>Migrate</Trans>}
        cancelTitle={<Trans>Cancel</Trans>}
        confirmColor="default"
      >
        <Trans>
          Your keys have not been migrated to a new keyring. You will be unable to create new keys or delete existing keys until migration completes. Would you like to migrate your keys now?
        </Trans>
      </ConfirmDialog>
    );

    if (beginMigration) {
      setSkipMigration(false);
    }
  }

  return [promptForKeyringMigration];
}