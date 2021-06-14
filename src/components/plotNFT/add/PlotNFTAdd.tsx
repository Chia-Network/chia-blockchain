import React, { useState, ReactNode } from 'react';
import { useHistory } from 'react-router';
import { useDispatch } from 'react-redux';
import { t, Trans } from '@lingui/macro';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm } from 'react-hook-form';
import { ButtonLoading, Flex, Form, FormBackButton } from '@chia/core';
import GroupAddCreate from './PlotNFTAddCreate';
import { createPlotNFT } from '../../../modules/plotNFT';
import PlotNFTState from '../../../constants/PlotNFTState';
import getPoolInfo from '../../../util/getPoolInfo';
import useUnconfirmedPlotNFTs from '../../../hooks/useUnconfirmedPlotNFTs';
import { chia_to_mojo } from '../../../util/chia';

type FormData = {
  self: boolean;
  poolUrl?: string;
  fee?: string | number;
};

type Props = {
  headerTag?: ReactNode;
  step?: number;
  onCancel?: boolean;
}

export default function PlotNFTAdd(props: Props) {
  const { headerTag: HeaderTag, step, onCancel } = props;

  const dispatch = useDispatch();
  const history = useHistory();
  const [loading, setLoading] = useState<boolean>(false);
  const unconfirmedNFTs = useUnconfirmedPlotNFTs();

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      fee: '',
      self: true,
      poolUrl: '',
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

      const { success, transaction } = await dispatch(createPlotNFT(initialTargetState, feeMojos));
      if (success) {
        unconfirmedNFTs.add({
          transactionId: transaction.name,
          state: self ? PlotNFTState.SELF_POOLING : PlotNFTState.FARMING_TO_POOL,
          poolUrl,
        });
      }

      history.push('/dashboard/pool');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Form
      methods={methods}
      onSubmit={handleSubmit}
    >
      {HeaderTag && (
        <HeaderTag>
          <Flex alignItems="center">
            <ChevronRightIcon color="secondary" />
            <Trans>
              Add a Plot NFT
            </Trans>
          </Flex>
        </HeaderTag>
      )}
      <Flex flexDirection="column" gap={3}>
        <GroupAddCreate step={step} onCancel={onCancel} />
        {!onCancel && (
          <Flex gap={1}>
            <FormBackButton variant="contained" />
            <ButtonLoading loading={loading} color="primary" type="submit" variant="contained">
              <Trans>
                Create
              </Trans>
            </ButtonLoading>
          </Flex>
        )}
      </Flex>
    </Form>
  );
}

PlotNFTAdd.defaultProps = {
  step: undefined,
  onCancel: undefined,
};
