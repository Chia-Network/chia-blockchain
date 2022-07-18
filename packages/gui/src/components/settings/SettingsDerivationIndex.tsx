import React, { useEffect } from 'react';
import { Trans, t } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { SyncingStatus } from '@chia/api';
import { useExtendDerivationIndexMutation, useGetCurrentDerivationIndexQuery } from '@chia/api-react';
import { Flex, ButtonLoading, Form, TextField } from '@chia/core';
import { useWalletState } from '@chia/wallets';

type FormData = {
  index: string;
};

export default function SettingsDerivationIndex() {
  const { state, isLoading: isLoadingWalletState } = useWalletState();
  const { data, isLoading: isLoadingCurrentDerivationIndex } = useGetCurrentDerivationIndexQuery();
  const [extendDerivationIndex] = useExtendDerivationIndexMutation();

  const methods = useForm<FormData>({
    defaultValues: {
      index: '',
    },
  });

  useEffect(() => {
    if (data !== null && data !== undefined) {
      methods.setValue('index', data);
    }
  }, [data]);

  const { isSubmitting } = methods.formState;
  const isLoading = isLoadingCurrentDerivationIndex || isLoadingWalletState || isSubmitting;
  const canSubmit = !isLoading && state === SyncingStatus.SYNCED;

  async function handleSubmit(values: FormData) {
    if (isSubmitting) {
      return;
    }

    const { index } = values;
    const numberIndex = Number(index);
    if (numberIndex <= data) {
      throw new Error(t`Detivation index must be greater than ${data}`);
   }

    await extendDerivationIndex({
      index: Number(index),
    }).unwrap();
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex gap={2} row>
        <TextField
          name="index"
          type="number"
          size="small"
          disabled={!canSubmit}
          InputProps={{
            inputProps: { min: data },
          }}
        />
        <ButtonLoading size="small" disabled={!canSubmit} type="submit" loading={!canSubmit} variant="outlined" color="secondary">
          <Trans>Save</Trans>
        </ButtonLoading>
      </Flex>
    </Form>
  );
}
