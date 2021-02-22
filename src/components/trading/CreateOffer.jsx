import { useDispatch, useSelector } from 'react-redux';
import React, { useMemo } from 'react';
import { Trans } from '@lingui/macro';
import { useHistory } from 'react-router';
import {
  Box,
  Grid,
  FormControl,
  MenuItem,
  Select,
  TextField,
  Button,
  InputLabel,
} from '@material-ui/core';
import { AlertDialog, Card, Flex } from '@chia/core';
import isElectron from 'is-electron';
import { newBuy, newSell, addTrade, resetTrades } from '../../modules/trade';
import {
  chia_to_mojo,
  colouredcoin_to_mojo,
} from '../../util/chia';
import { openDialog } from '../../modules/dialog';
import { create_trade_action } from '../../modules/trade_messages';
import { COLOURED_COIN } from '../../util/wallet_types';
import TradesTable from './TradesTable';

const TradeList = () => {
  const trades = useSelector((state) => state.trade_state.trades ?? []);
  const wallets = useSelector((state) => state.wallet_state.wallets);

  const tradeRows = useMemo(() => {
    return trades.map((trade) => ({
      amount: trade.side === 'sell'
        ? -trade.amount
        : trade.amount,
      name: wallets[trade.wallet_id].name,
    }));
  }, [trades]);

  if (!trades.length) {
    return null;
  }

  return (
    <TradesTable rows={tradeRows} />
  );
};

export default function CreateOffer() {
  const wallets = useSelector((state) => state.wallet_state.wallets);
  const dispatch = useDispatch();
  const history = useHistory();
  let amount_input = null;
  let buy_or_sell = null;
  let wallet_id = null;
  const trades = useSelector((state) => state.trade_state.trades);

  function handleAdd() {
    if (!wallet_id.value) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Please select coin colour
            </Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    if (amount_input.value === '') {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please select amount</Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    if (!buy_or_sell.value) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Please select buy or sell
            </Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    const mojo = wallets[wallet_id.value].type === COLOURED_COIN
      ? colouredcoin_to_mojo(amount_input.value)
      : chia_to_mojo(amount_input.value);

    const trade = buy_or_sell.value === 1
      ? newBuy(mojo, wallet_id.value)
      : newSell(mojo, wallet_id.value);

    dispatch(addTrade(trade));
  }

  async function handleSave() {
    if (trades.length === 0) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please add a trade pair</Trans>
          </AlertDialog>
        ),
      );
      return;
    }
    if (isElectron()) {
      const dialogOptions = {};
      const result = await window.remote.dialog.showSaveDialog(dialogOptions);
      const { filePath } = result;
      const offer = {};
      for (const trade of trades) {
        if (trade.side === 'buy') {
          offer[trade.wallet_id] = trade.amount;
        } else {
          offer[trade.wallet_id] = -trade.amount;
        }
      }
      dispatch(create_trade_action(offer, filePath, history));
    } else {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              This feature is available only from the GUI.
            </Trans>
          </AlertDialog>
        ),
      );
    }
  }
  function handleCancel() {
    dispatch(resetTrades());
  }

  return (
    <Card
      title={<Trans>Create Trade Offer</Trans>}
      actions={(
        <>
          <Button
            onClick={handleCancel}
            variant="contained"
          >
            <Trans>Cancel</Trans>
          </Button>
          <Button
            onClick={handleSave}
            variant="contained"
            color="primary"
          >
            <Trans>Save</Trans>
          </Button>
        </>
      )}
    >
      <Flex flexDirection="column" gap={3}>
        <TradeList />
        <Grid spacing={2} container>
          <Grid item xs={6}>
            <FormControl
              fullWidth
              variant="outlined"
            >
              <InputLabel required>
                <Trans>Side</Trans>
              </InputLabel>
              <Select
                inputRef={(input) => {
                  buy_or_sell = input;
                }}
              >
                <MenuItem value={1}><Trans>Buy</Trans></MenuItem>
                <MenuItem value={2}><Trans>Sell</Trans></MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={6}>
            <FormControl
              fullWidth
              variant="outlined"
            >
              <InputLabel required>
                <Trans>Colour</Trans>
              </InputLabel>
              <Select
                inputRef={(input) => {
                  wallet_id = input;
                }}
              >
                {wallets.map((wallet) => (
                  <MenuItem value={wallet.id} key={wallet.id}>{wallet.name}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12}>
            <Flex alignItems="stretch">
              <Box flexGrow={1}>
                <TextField
                  fullWidth
                  inputRef={(input) => {
                    amount_input = input;
                  }}
                  label={<Trans>Amount</Trans>}
                  variant="outlined"
                />
              </Box>
              <Button
                onClick={handleAdd}
                variant="contained"
                disableElevation
              >
                <Trans>Add</Trans>
              </Button>
            </Flex>
          </Grid>
        </Grid>
      </Flex>
    </Card>
  );
}
