import React, { useState, ReactNode } from 'react';
import { useHistory } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { t, Trans } from '@lingui/macro';
import { Button, Typography } from '@material-ui/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm } from 'react-hook-form';
import { Flex, Form, Loading } from '@chia/core';
import GroupAddCreate from './GroupAddCreate';
import { createPoolNFT } from '../../../modules/group';
import type { RootState } from '../../../modules/rootReducer';
import PlotNFTState from '../../../constants/PlotNFTState';
import getPoolInfo from '../../../util/getPoolInfo';

type FormData = {
  self: boolean;
  poolUrl?: string;
  fee?: string | number;
};

type Props = {
  headerTag?: ReactNode;
}

export default function GroupAdd(props: Props) {
  const { headerTag: HeaderTag } = props;

  const dispatch = useDispatch();
  const history = useHistory();
  const [loading, setLoading] = useState<boolean>(false);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      self: true,
      poolUrl: 'http://127.0.0.1',
    },
  });

  async function handleSubmit(data: FormData) {
    try {
      setLoading(true);

      const { self, fee, poolUrl } = data;
      const initialTargetState = {
        state: self ? PlotNFTState.SELF_POOLING : PlotNFTState.FARMING_TO_POOL,
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

      /*
      "initial_target_state": {
        "target_puzzle_hash": target_puzzlehash.hex(),
        "relative_lock_height": relative_lock_height,
        "pool_url": pool_url,
        "state": state,
      */

      const { success, transaction } = await dispatch(createPoolNFT(initialTargetState, fee));
      if (success) {
        setTransaction
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
        {loading ? (
          <Flex flexDirection="column" gap={3} alignItems="center">
            <Typography variant="h6">
              <Trans>
                Waiting on transaction to hit the memory pool...
              </Trans>
            </Typography>
            <Loading />
          </Flex>
        ) : (
          <>
            <GroupAddCreate />
            <Flex gap={1}>
              <Button color="primary" type="submit" variant="contained">
                <Trans>
                  Create
                </Trans>
              </Button>
            </Flex>
          </>
        )}
      </Flex>
    </Form>
  );
}
