import React, { useEffect } from 'react';
import { Trans, t } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { SyncingStatus } from '@chia/api';
import {
  useExtendDerivationIndexMutation,
  useGetCurrentDerivationIndexQuery,
} from '@chia/api-react';
import {
  AlertDialog,
  ButtonLoading,
  Flex,
  Form,
  TextField,
  useOpenDialog,
} from '@chia/core';
import { useWalletState } from '@chia/wallets';

type FormData = {
  index: string;
};

export default function SettingsDerivationIndex() {
  const { state, isLoading: isLoadingWalletState } = useWalletState();
  const { data, isLoading: isLoadingCurrentDerivationIndex } =
    useGetCurrentDerivationIndexQuery();
  const [extendDerivationIndex] = useExtendDerivationIndexMutation();
  const openDialog = useOpenDialog();

  const index = data?.index;

  const methods = useForm<FormData>({
    defaultValues: {
      index: index ?? '',
    },
  });

  useEffect(() => {
    if (index !== null && index !== undefined) {
      methods.setValue('index', index);
    }
  }, [index]);

  const { isSubmitting } = methods.formState;
  const isLoading =
    isLoadingCurrentDerivationIndex || isLoadingWalletState || isSubmitting;
  const canSubmit = !isLoading && state === SyncingStatus.SYNCED;

  async function handleSubmit(values: FormData) {
    if (isSubmitting) {
      return;
    }

    const { index: newIndex } = values;
    const numberIndex = Number(newIndex);
    if (numberIndex <= index) {
      throw new Error(t`Derivation index must be greater than ${index}`);
    }

    await extendDerivationIndex({
      index: numberIndex,
    }).unwrap();

    await openDialog(
      <AlertDialog>
        <Trans>
          Successfully updated the derivation index. Your balances may take a
          while to update.
        </Trans>
      </AlertDialog>,
    );
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit} noValidate>
      <Flex gap={2}>
        <TextField
          name="index"
          type="number"
          size="small"
          disabled={!canSubmit}
          InputProps={{
            inputProps: {
              min: index,
              step: 100,
            },
          }}
          data-testid="SettingsDerivationIndex-index"
          fullWidth
        />
        <ButtonLoading
          size="small"
          disabled={!canSubmit}
          type="submit"
          loading={!canSubmit}
          variant="outlined"
          color="secondary"
          data-testid="SettingsDerivationIndex-save"
        >
          <Trans>Save</Trans>
        </ButtonLoading>
      </Flex>
    </Form>
  );
}
