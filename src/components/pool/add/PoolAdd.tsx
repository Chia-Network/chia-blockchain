import React, { useState } from 'react';
import { useHistory } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Button, Typography } from '@material-ui/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm } from 'react-hook-form';
import { Flex, Form, Loading } from '@chia/core';
import { PoolHeaderSource } from '../PoolHeader';
import PoolAddCreate from './PoolAddCreate';
import type { RootState } from '../../../modules/rootReducer';

type JoinPoolFormData = {
  type: 'SELF_POOL' | 'JOIN_POOL';
  pool?: string;
};

export default function PlotAdd() {
  const dispatch = useDispatch();
  const history = useHistory();
  const [loading, setLoading] = useState<boolean>(false);
  const fingerprint = useSelector((state: RootState) => state.wallet_state.selected_fingerprint);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      self: true,
    },
  });

  async function handleSubmit(data: JoinPoolFormData) {
    try {
      setLoading(true);
      /*
      dispatch(createPoolGroup({
        ...data,
        fingerprint,
      }));
      */

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
      <PoolHeaderSource>
        <Flex alignItems="center">
          <ChevronRightIcon color="secondary" />
          <Trans>
            Add a Group
          </Trans>
        </Flex>
      </PoolHeaderSource>
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
            <PoolAddCreate />
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
