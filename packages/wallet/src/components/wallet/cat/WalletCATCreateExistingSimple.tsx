import React from 'react';
import { Trans, t } from '@lingui/macro';
import { Back, ButtonLoading, Card, Flex, Form, TextField } from '@chia/core';
import { Box, Grid } from '@material-ui/core';
import { useAddCATTokenMutation } from '@chia/api-react';
import { useForm } from 'react-hook-form';
import { useHistory } from 'react-router';

type CreateExistingCATWalletData = {
  name: string;
  tail: string;
  symbol?: string;
};

export default function WalletCATCreateExisting() {
  const methods = useForm<CreateExistingCATWalletData>({
    shouldUnregister: false,
    defaultValues: {
      tail: '',
      name: '',
      symbol: '',
    },
  });
  const history = useHistory();
  const [addCATToken, { isLoading: isAddCATTokenLoading }] = useAddCATTokenMutation();

  async function handleSubmit(values: CreateExistingCATWalletData) {
    const { name, tail } = values;

    if (isAddCATTokenLoading) {
      return;
    }

    if (!tail) {
      throw new Error(t`Please enter a valid TAIL`);
    }

    if (!name) {
      throw new Error(t`Please enter a valid token name`);
    }

    const walletId = await addCATToken({
      name,
      tail,
      fee: '0',
    }).unwrap();

    history.push(`/dashboard/wallets/${walletId}`);
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex flexDirection="column" gap={3}>
        <Back variant="h5">
          <Trans>Add Token</Trans>
        </Back>
        <Card>
        <Grid spacing={2} direction="column" container>
            <Grid xs={12} md={8} lg={6} item>
          <Grid spacing={2} container>
            <Grid xs={12} item>
              <TextField
                  name="name"
                  variant="outlined"
                  label={<Trans>Name</Trans>}
                  fullWidth
                  autoFocus
                />
            </Grid>
            <Grid xs={12} item>
              <TextField
                name="tail"
                variant="outlined"
                label={<Trans>Token and Asset Issuance Limitations</Trans>}
                multiline
                fullWidth
              />
            </Grid>
          </Grid>
          </Grid>
          </Grid>
        </Card>
        <Box>
          <ButtonLoading
            type="submit"
            variant="contained"
            color="primary"
            loading={isAddCATTokenLoading}
          >
            <Trans>Add</Trans>
          </ButtonLoading>
        </Box>
      </Flex>
    </Form>
  );
}
