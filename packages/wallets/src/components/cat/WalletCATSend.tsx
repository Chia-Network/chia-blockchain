import React, { useMemo } from 'react';
import { Trans, t } from '@lingui/macro';
import {
  AdvancedOptions,
  Button,
  Fee,
  Form,
  Flex,
  Card,
  ButtonLoading,
  TextFieldNumber,
  TextField,
  useOpenDialog,
  chiaToMojo,
  catToMojo,
  useIsSimulator,
  useCurrencyCode,
  getTransactionResult,
  TooltipIcon,
} from '@chia/core';
import {
  useSpendCATMutation,
  useFarmBlockMutation,
} from '@chia/api-react';
import { SyncingStatus, toBech32m } from '@chia/api';
import isNumeric from 'validator/es/lib/isNumeric';
import { useForm, useWatch } from 'react-hook-form';
import { Grid, Typography } from '@mui/material';
import useWallet from '../../hooks/useWallet';
import useWalletState from '../../hooks/useWalletState';
import CreateWalletSendTransactionResultDialog from '../WalletSendTransactionResultDialog';

type Props = {
  walletId: number;
};

type SendTransactionData = {
  address: string;
  amount: string;
  fee: string;
  memo: string;
};

export default function WalletCATSend(props: Props) {
  const { walletId } = props;
  const openDialog = useOpenDialog();
  const [farmBlock] = useFarmBlockMutation();
  const [spendCAT, { isLoading: isSpendCatLoading }] = useSpendCATMutation();
  const { state } = useWalletState();
  const currencyCode = useCurrencyCode();
  const isSimulator = useIsSimulator();

  const retireAddress = useMemo(() => {
    if (!currencyCode) {
      return undefined;
    }
    return toBech32m(
      '0000000000000000000000000000000000000000000000000000000000000000',
      currencyCode
    );
  }, [currencyCode]);

  const methods = useForm<SendTransactionData>({
    defaultValues: {
      address: '',
      amount: '',
      fee: '',
      memo: '',
    },
  });

  const { formState: { isSubmitting } } = methods;

  const addressValue = useWatch<string>({
    control: methods.control,
    name: 'address',
  });

  const { wallet, unit, loading } = useWallet(walletId);

  async function farm() {
    if (addressValue) {
      await farmBlock({
        address: addressValue,
      }).unwrap();
    }
  }

  const canSubmit = wallet && !isSpendCatLoading && !loading;

  async function handleSubmit(data: SendTransactionData) {
    const assetId = wallet?.meta?.assetId;

    if (state !== SyncingStatus.SYNCED) {
      throw new Error(t`Please finish syncing before making a transaction`);
    }

    if (!canSubmit) {
      return;
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
    if (address === 'retire' && retireAddress) {
      address = retireAddress;
    }

    if (address.includes('colour')) {
      throw new Error(t`Cannot send chia to coloured address. Please enter a chia address.`);
    }

    if (address.includes('chia_addr') || address.includes('colour_desc')) {
      throw new Error(t`Recipient address is not a coloured wallet address. Please enter a coloured wallet address`);
    }
    if (address.slice(0, 14) === 'colour_addr://') {
      const colour_id = address.slice(14, 78);
      address = address.slice(79);
      if (colour_id !== assetId) {
        throw new Error(t`Error the entered address appears to be for a different colour.`);
      }
    }

    if (address.slice(0, 12) === 'chia_addr://') {
      address = address.slice(12);
    }
    if (address.startsWith('0x') || address.startsWith('0X')) {
      address = address.slice(2);
    }

    const amountValue = catToMojo(amount);
    const feeValue = chiaToMojo(fee);

    const memo = data.memo.trim();
    const memos = memo ? [memo] : undefined;

    const queryData = {
      walletId,
      address,
      amount: amountValue,
      fee: feeValue,
      waitForConfirmation: true,
    };

    if (memos) {
      queryData.memos = memos;
    }

    const response = await spendCAT(queryData).unwrap();

    const result = getTransactionResult(response.transaction);
    const resultDialog = CreateWalletSendTransactionResultDialog({success: result.success, message: result.message});

    if (resultDialog) {
      await openDialog(resultDialog);
    }
    else {
      throw new Error(result.message ?? 'Something went wrong');
    }

    methods.reset();
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex gap={2} flexDirection="column">
        <Typography variant="h6">
          <Trans>Create Transaction</Trans>
          &nbsp;
          <TooltipIcon>
            <Trans>
              On average there is one minute between each transaction block. Unless
              there is congestion you can expect your transaction to be included in
              less than a minute.
            </Trans>
          </TooltipIcon>
        </Typography>
        <Card>
          <Grid spacing={2} container>
            <Grid xs={12} item>
              <TextField
                name="address"
                variant="filled"
                color="secondary"
                fullWidth
                disabled={isSubmitting}
                label={<Trans>Address / Puzzle hash</Trans>}
                data-testid="WalletCATSend-address"
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
                currency={unit}
                data-testid="WalletCATSend-amount"
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
                data-testid="WalletCATSend-fee"
                fullWidth
              />
            </Grid>
            <Grid xs={12} item>
              <AdvancedOptions>
                <TextField
                  name="memo"
                  variant="filled"
                  color="secondary"
                  fullWidth
                  disabled={isSubmitting}
                  label={<Trans>Memo</Trans>}
                  data-testid="WalletCATSend-memo"
                />
              </AdvancedOptions>
            </Grid>
          </Grid>
        </Card>
        <Flex justifyContent="flex-end" gap={1}>
          {isSimulator && (
            <Button onClick={farm} variant="outlined" data-testid="WalletCATSend-farm">
              <Trans>Farm</Trans>
            </Button>
          )}
          <ButtonLoading
            variant="contained"
            color="primary"
            type="submit"
            disabled={!canSubmit}
            loading={isSpendCatLoading}
            data-testid="WalletCATSend-send"
          >
            <Trans>Send</Trans>
          </ButtonLoading>
        </Flex>
      </Flex>
    </Form>
  );
}
