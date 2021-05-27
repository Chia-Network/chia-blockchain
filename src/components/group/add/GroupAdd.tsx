import React, { useState, ReactNode } from 'react';
import { useHistory } from 'react-router';
import { useDispatch, useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { Button, Typography } from '@material-ui/core';
import { ChevronRight as ChevronRightIcon } from '@material-ui/icons';
import { useForm } from 'react-hook-form';
import { Flex, Form, Loading } from '@chia/core';
import GroupAddCreate from './GroupAddCreate';
import type { RootState } from '../../../modules/rootReducer';

type JoinPoolFormData = {
  type: 'SELF_POOLING' | 'FARMING_TO_POOL';
  pool?: string;
};

type Props = {
  headerTag?: ReactNode;
}

export default function GroupAdd(props: Props) {
  const { headerTag: HeaderTag } = props;

  const dispatch = useDispatch();
  const history = useHistory();
  const [loading, setLoading] = useState<boolean>(false);
  const fingerprint = useSelector((state: RootState) => state.wallet_state.selected_fingerprint);

  const methods = useForm<FormData>({
    shouldUnregister: false,
    defaultValues: {
      self: true,
      poolUrl: 'test',
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
