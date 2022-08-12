import React from 'react';
import { t, plural, Trans } from '@lingui/macro';
import { useGetKeyringStatusQuery } from '@chia/api-react';
import AlertDialog from '../components/AlertDialog';
import ConfirmDialog from '../components/ConfirmDialog';
import useOpenDialog from './useOpenDialog';

export default function useValidateChangePassphraseParams() {
  const { data: keyringState, isLoading, error } = useGetKeyringStatusQuery();
  const openDialog = useOpenDialog();

  async function validateChangePassphraseParams(
    currentPassphrase: string | null,
    newPassphrase: string,
    confirmationPassphrase: string
  ): Promise<boolean> {
    try {
      if (isLoading) {
        throw new Error('Keyring state is loading please wait');
      } else if (!keyringState) {
        throw new Error('Keyring state is not defined');
      }

      const {
        isOptional: allowEmptyPassphrase,
        minLength: minPassphraseLength,
      } = keyringState.passphraseRequirements;

      if (newPassphrase != confirmationPassphrase) {
        throw new Error(
          t`The provided passphrase and confirmation do not match`
        );
      } else if (
        (newPassphrase.length == 0 && !allowEmptyPassphrase) || // Passphrase required, no passphrase provided
        (newPassphrase.length > 0 && newPassphrase.length < minPassphraseLength)
      ) {
        // Passphrase provided, not long enough
        throw new Error(
          plural(minPassphraseLength, {
            one: 'Passphrases must be at least # character in length',
            other: 'Passphrases must be at least # characters in length',
          })
        );
      } else if (
        currentPassphrase !== null &&
        currentPassphrase == newPassphrase
      ) {
        throw new Error(
          t`New passphrase is the same as your current passphrase`
        );
      } else if (newPassphrase.length == 0) {
        // Warn about using an empty passphrase
        let alertTitle: React.ReactElement | string;
        let buttonTitle: React.ReactElement | string;
        let message: React.ReactElement | string;

        if (currentPassphrase === null) {
          alertTitle = <Trans>Skip Passphrase Protection</Trans>;
          buttonTitle = <Trans>Skip</Trans>;
          message = (
            <Trans>
              Setting a passphrase is strongly recommended to protect your keys.
              Are you sure you want to skip setting a passphrase?
            </Trans>
          );
        } else {
          alertTitle = <Trans>Disable Passphrase Protection</Trans>;
          buttonTitle = <Trans>Disable</Trans>;
          message = (
            <Trans>
              Using a passphrase is strongly recommended to protect your keys.
              Are you sure you want to disable passphrase protection?
            </Trans>
          );
        }

        const useEmptyPassphrase = await openDialog(
          <ConfirmDialog
            title={alertTitle}
            confirmTitle={buttonTitle}
            confirmColor="danger"
            // @ts-ignore
            maxWidth="xs"
          >
            {message}
          </ConfirmDialog>
        );

        // @ts-ignore
        if (!useEmptyPassphrase) {
          return false;
        }
      }

      return true;
    } catch (error: any) {
      await openDialog(<AlertDialog>{error.message}</AlertDialog>);
      return false;
    }
  }

  return [validateChangePassphraseParams, { isLoading, error }];
}
