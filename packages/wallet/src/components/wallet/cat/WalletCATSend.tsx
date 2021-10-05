import React from 'react';
import { Trans, t } from '@lingui/macro';
import {
  Fee,
  Form,
  AlertDialog,
  Flex,
  Card,
  ButtonLoading,
  TextFieldNumber,
  TextField,
} from '@chia/core';
import { useDispatch, useSelector } from 'react-redux';
import isNumeric from 'validator/es/lib/isNumeric';
import { useForm, useWatch } from 'react-hook-form';
import { Button, Grid } from '@material-ui/core';
import { cc_spend, farm_block } from '../../../modules/message';
import { chia_to_mojo, colouredcoin_to_mojo } from '../../../util/chia';
import useOpenDialog from '../../../hooks/useOpenDialog';
import { get_transaction_result } from '../../../util/transaction_result';
import config from '../../../config/config';
import type { RootState } from '../../../modules/rootReducer';

type Props = {
  wallet_id: number;
  currency?: string;
};

type SendTransactionData = {
  address: string;
  amount: string;
  fee: string;
  memo: string;
};

export default function WalletSend(props: Props) {
  const { wallet_id, currency } = props;
  const dispatch = useDispatch();
  const openDialog = useOpenDialog();

  const methods = useForm<SendTransactionData>({
    shouldUnregister: false,
    defaultValues: {
      address: '',
      amount: '',
      fee: '',
      memo: '',
    },
  });

  const { formState: { isSubmitting }} = methods;

  const addressValue = useWatch<string>({
    control: methods.control,
    name: 'address',
  });

  const syncing = useSelector(
    (state: RootState) => state.wallet_state.status.syncing,
  );

  const wallet = useSelector((state: RootState) =>
    state.wallet_state.wallets?.find((item) => item.id === wallet_id),
  );

  if (!wallet) {
    return null;
  }

  const { colour, id } = wallet;

  function farm() {
    if (addressValue) {
      dispatch(farm_block(addressValue));
    }
  }

  async function handleSubmit(data: SendTransactionData) {
    if (isSubmitting) {
      return;
    }

    try {
      if (syncing) {
        throw new Error(t`Please finish syncing before making a transaction`);
      }

      const amount = data.amount.trim();
      if (!isNumeric(amount)) {
        throw new Error(t`Please enter a valid numeric amount`);
      }

      const fee = data.fee.trim() || '0';
      if (!isNumeric(fee)) {
        throw new Error(t`Please enter a valid numeric fee`);
      }

      let address = data.address;
      if (address.includes('colour')) {
        throw new Error(t`Cannot send chia to coloured address. Please enter a chia address.`);
      }

      if (address.includes('chia_addr') || address.includes('colour_desc')) {
        throw new Error(t`Recipient address is not a coloured wallet address. Please enter a coloured wallet address`);
      }
      if (address.slice(0, 14) === 'colour_addr://') {
        const colour_id = address.slice(14, 78);
        address = address.slice(79);
        if (colour_id !== colour) {
          throw new Error(t`Error the entered address appears to be for a different colour.`);
        }
      }

      if (address.slice(0, 12) === 'chia_addr://') {
        address = address.slice(12);
      }
      if (address.startsWith('0x') || address.startsWith('0X')) {
        address = address.slice(2);
      }

      const amountValue = Number.parseFloat(colouredcoin_to_mojo(amount));
      const feeValue = Number.parseFloat(chia_to_mojo(fee));

      const memo = data.memo.trim();
      const memos = memo ? [memo] : undefined;

      const response = await dispatch(cc_spend(id, address, amountValue, feeValue, memos));
      if (response && response.data && response.data.success === true) {
        const result = get_transaction_result(response.data);
        if (result.success) {
            openDialog(
              <AlertDialog title={<Trans>Success</Trans>}>
                {result.message ?? <Trans>Transaction has successfully been sent to a full node and included in the mempool.</Trans>}
              </AlertDialog>,
            );
        } else {
          throw new Error(result.message ?? 'Something went wrong');
        }
      } else {
        throw new Error(response?.data?.error ?? 'Something went wrong');
      }
      methods.reset();
    } catch (error: Error) {
      openDialog(
        <AlertDialog title={<Trans>Error</Trans>}>
          {error.message}
        </AlertDialog>,
      );
    }
  }

  return (
    <Card
      title={<Trans>Create Transaction</Trans>}
      tooltip={
        <Trans>
          On average there is one minute between each transaction block. Unless
          there is congestion you can expect your transaction to be included in
          less than a minute.
        </Trans>
      }
    >
      <Form methods={methods} onSubmit={handleSubmit}>
        <Grid spacing={2} container>
          <Grid xs={12} item>
            <TextField
              name="address"
              variant="filled"
              color="secondary"
              fullWidth
              disabled={isSubmitting}
              label={<Trans>Address / Puzzle hash</Trans>}
              required
            />
          </Grid>
          <Grid xs={12} md={6} item>
            <TextFieldNumber
              id="filled-secondary"
              variant="filled"
              color="secondary"
              name="amount"
              disabled={isSubmitting}
              label={<Trans>Amount</Trans>}
              currency={currency}
              fullWidth
              required
            />
          </Grid>
          <Grid xs={12} md={6} item>
            <Fee
              id="filled-secondary"
              variant="filled"
              name="fee"
              color="secondary"
              disabled={isSubmitting}
              label={<Trans>Fee</Trans>}
              fullWidth
            />
          </Grid>
          <Grid xs={12} item>
            <TextField
              name="memo"
              variant="filled"
              color="secondary"
              fullWidth
              disabled={isSubmitting}
              label={<Trans>Memo</Trans>}
            />
          </Grid>
          <Grid xs={12} item>
            <Flex justifyContent="flex-end" gap={1}>
              {!!config.local_test && (
                <Button onClick={farm} variant="outlined">
                  <Trans>Farm</Trans>
                </Button>
              )}
              <ButtonLoading
                variant="contained"
                color="primary"
                type="submit"
                disabled={isSubmitting}
                loading={isSubmitting}
              >
                <Trans>Send</Trans>
              </ButtonLoading>
            </Flex>
          </Grid>
        </Grid>
      </Form>
    </Card>
  );
}
