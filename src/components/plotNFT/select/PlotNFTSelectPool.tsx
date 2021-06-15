import React, { useState, ReactNode } from 'react';
import { t, Trans } from '@lingui/macro';
import { useForm } from 'react-hook-form';
import { ButtonLoading, Flex, Form, FormBackButton } from '@chia/core';
import PlotNFTSelectBase from './PlotNFTSelectBase';
import getPoolInfo from '../../../util/getPoolInfo';
import InitialTargetState from '../../../types/InitialTargetState';
import { chia_to_mojo } from '../../../util/chia';

export type SubmitData = {
  initialTargetState: InitialTargetState;
  fee?: string;
};

type FormData = {
  self: boolean;
  poolUrl?: string;
  fee?: string | number;
};

type Props = {
  step?: number;
  onCancel?: () => void;
  title: ReactNode;
  description?: ReactNode;
  submitTitle?: ReactNode;
  hideFee?: boolean;
  onSubmit: (data: SubmitData) => Promise<void>;
  defaultValues?: {
    fee?: string;
    self?: boolean;
    poolUrl?: string;
  };
}

export default function PlotNFTSelectPool(props: Props) {
  const { step, onCancel, defaultValues, onSubmit, title, description, submitTitle, hideFee } = props;
  const [loading, setLoading] = useState<boolean>(false);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      fee: '',
      self: true,
      poolUrl: '',
      ...defaultValues,
    },
  });

  async function handleSubmit(data: FormData) {
    try {
      setLoading(true);

      const { self, fee, poolUrl } = data;
      const initialTargetState = {
        state: self ? 'SELF_POOLING' : 'FARMING_TO_POOL',
      };

      if (!self && poolUrl) {
        const { target_puzzle_hash, relative_lock_height } = await getPoolInfo(poolUrl);
        if (!target_puzzle_hash) {
          throw new Error(t`Pool does not provide target_puzzle_hash.`);
        }
        if (relative_lock_height === undefined) {
          throw new Error(t`Pool does not provide relative_lock_height.`);
        }

        initialTargetState.pool_url = poolUrl;
        initialTargetState.target_puzzle_hash = target_puzzle_hash;
        initialTargetState.relative_lock_height = relative_lock_height;
      }

      const feeMojos = chia_to_mojo(fee);

      await onSubmit({
        fee: feeMojos,
        initialTargetState,
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <Form
      methods={methods}
      onSubmit={handleSubmit}
    >
      <Flex flexDirection="column" gap={3}>
        <PlotNFTSelectBase
          step={step}
          onCancel={onCancel}
          title={title}
          description={description}
          hideFee={hideFee}
        />
        {!onCancel && (
          <Flex gap={1}>
            <FormBackButton variant="contained" />
            <ButtonLoading loading={loading} color="primary" type="submit" variant="contained">
              {submitTitle}
            </ButtonLoading>
          </Flex>
        )}
      </Flex>
    </Form>
  );
}

PlotNFTSelectPool.defaultProps = {
  step: undefined,
  onCancel: undefined,
  defaultValues: undefined,
  title: undefined,
  description: undefined,
  hideFee: false,
  submitTitle: <Trans>Create</Trans>,
};
