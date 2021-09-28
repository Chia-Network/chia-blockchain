import React, { useState } from 'react';
import { Trans } from '@lingui/macro';
import { AlertDialog, Fee, Back, ButtonLoading, Card, Flex, Form, TextField } from '@chia/core';
import { Box, Grid } from '@material-ui/core';
import { useDispatch } from 'react-redux';
import { useForm } from 'react-hook-form';
import { create_cc_for_colour_action } from '../../../modules/message';
import { chia_to_mojo } from '../../../util/chia';
import { openDialog } from '../../../modules/dialog';

type CreateExistingCATWalletData = {
  name: string;
  fee: string;
};

export default function WalletCATCreateExisting() {
  const methods = useForm<CreateExistingCATWalletData>({
    shouldUnregister: false,
    defaultValues: {
      name: '',
      fee: '',
    },
  });
  const [loading, setLoading] = useState<boolean>(false);
  const dispatch = useDispatch();

  async function handleSubmit(values: CreateExistingCATWalletData) {
    try {
      const { name, fee } = values;
      setLoading(true);

      if (!name) {
        dispatch(
          openDialog(
            <AlertDialog>
              <Trans>Please enter a valid CAT name</Trans>
            </AlertDialog>,
          ),
        );
        return;
      }
      if (fee === '' || isNaN(Number(fee))) {
        dispatch(
          openDialog(
            <AlertDialog>
              <Trans>Please enter a valid numeric fee</Trans>
            </AlertDialog>,
          ),
        );
        return;
      }

      const feeMojos = chia_to_mojo(fee);

      await dispatch(create_cc_for_colour_action(name, feeMojos));
    } finally {
      setLoading(false);
    }
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex flexDirection="column" gap={3}>
        <Back variant="h5">
          <Trans>Create Chia Asset Token Wallet</Trans>
        </Back>
        <Card>
          <Grid spacing={2} container>
            <Grid xs={12} md={6} item>
              <TextField
                name="name"
                variant="outlined"
                label={<Trans>Name</Trans>}
                fullWidth
              />
            </Grid>
            <Grid xs={12} md={6} item>
              <Fee
                variant="outlined"
                fullWidth
              />
            </Grid>
          </Grid>
        </Card>
        <Box>
          <ButtonLoading
            type="submit"
            variant="contained"
            color="primary"
            loading={loading}
          >
            <Trans>Create</Trans>
          </ButtonLoading>
        </Box>
      </Flex>
    </Form>
  );
}
