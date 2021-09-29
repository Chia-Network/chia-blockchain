import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Amount,
  Fee,
  Form,
  TextField as ChiaTextField,
  AlertDialog,
  Flex,
  Card,
} from '@chia/core';
import { useDispatch, useSelector } from 'react-redux';
import isNumeric from 'validator/es/lib/isNumeric';
import { useForm, useWatch } from 'react-hook-form';
import {
  Button,
  Grid,
} from '@material-ui/core';
import {
  send_transaction,
  farm_block,
} from '../../modules/message';
import { /* mojo_to_chia_string, */ chia_to_mojo } from '../../util/chia';
import { openDialog } from '../../modules/dialog';
import { get_transaction_result } from '../../util/transaction_result';
import config from '../../config/config';
import type { RootState } from '../../modules/rootReducer';
import { makeStyles } from '@material-ui/core/styles';

const drawerWidth = 240;

const useStyles = makeStyles((theme) => ({
  front: {
    zIndex: 100,
  },
  resultSuccess: {
    color: '#3AAC59',
  },
  resultFailure: {
    color: 'red',
  },
  root: {
    display: 'flex',
    paddingLeft: '0px',
  },
  toolbar: {
    paddingRight: 24, // keep right padding when drawer closed
  },
  toolbarIcon: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    padding: '0 8px',
    ...theme.mixins.toolbar,
  },
  appBar: {
    zIndex: theme.zIndex.drawer + 1,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen,
    }),
  },
  appBarShift: {
    marginLeft: drawerWidth,
    width: `calc(100% - ${drawerWidth}px)`,
    transition: theme.transitions.create(['width', 'margin'], {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  menuButton: {
    marginRight: 36,
  },
  menuButtonHidden: {
    display: 'none',
  },
  title: {
    flexGrow: 1,
  },
  drawerPaper: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  drawerPaperClose: {
    overflowX: 'hidden',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.leavingScreen,
    }),
    width: theme.spacing(7),
    [theme.breakpoints.up('sm')]: {
      width: theme.spacing(9),
    },
  },
  appBarSpacer: theme.mixins.toolbar,
  content: {
    flexGrow: 1,
    height: '100vh',
    overflow: 'auto',
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
  },
  paper: {
    marginTop: theme.spacing(2),
    padding: theme.spacing(2),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
  },
  fixedHeight: {
    height: 240,
  },
  heading: {
    fontSize: theme.typography.pxToRem(15),
    fontWeight: theme.typography.fontWeightRegular,
  },
  drawerWallet: {
    position: 'relative',
    whiteSpace: 'nowrap',
    width: drawerWidth,
    height: '100%',
    transition: theme.transitions.create('width', {
      easing: theme.transitions.easing.sharp,
      duration: theme.transitions.duration.enteringScreen,
    }),
  },
  sendCard: {
    marginTop: theme.spacing(2),
  },
  sendButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    width: 150,
    height: 50,
  },
  copyButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(0),
    height: 56,
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(1),
  },
  cardSubSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(1),
  },
  walletContainer: {
    marginBottom: theme.spacing(5),
  },
  table_root: {
    width: '100%',
    maxHeight: 600,
    overflowY: 'scroll',
  },
  table: {
    height: '100%',
    overflowY: 'scroll',
  },
  tableBody: {
    height: '100%',
    overflowY: 'scroll',
  },
  row: {
    width: 700,
  },
  cell_short: {
    fontSize: '14px',
    width: 50,
    overflowWrap: 'break-word' /* Renamed property in CSS3 draft spec */,
  },
  amountField: {
    paddingRight: 20,
  },
}));

type SendCardProps = {
  wallet_id: number;
};

type SendTransactionData = {
  address: string;
  amount: string;
  fee: string;
};

export default function WalletSend(props: SendCardProps) {
  const { wallet_id } = props;
  const classes = useStyles();
  const dispatch = useDispatch();

  const methods = useForm<SendTransactionData>({
    shouldUnregister: false,
    defaultValues: {
      address: '',
      amount: '',
      fee: '',
    },
  });

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

  const { sending_transaction, send_transaction_result } = wallet;

  const result = get_transaction_result(send_transaction_result);

  const result_message = result.message;
  const result_class = result.success
    ? classes.resultSuccess
    : classes.resultFailure;

  function farm() {
    if (addressValue) {
      dispatch(farm_block(addressValue));
    }
  }

  function handleSubmit(data: SendTransactionData) {
    if (sending_transaction) {
      return;
    }

    if (syncing) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please finish syncing before making a transaction</Trans>
          </AlertDialog>,
        ),
      );
      return;
    }

    const amount = data.amount.trim();
    if (!isNumeric(amount)) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a valid numeric amount</Trans>
          </AlertDialog>,
        ),
      );
      return;
    }

    const fee = data.fee.trim();
    if (!isNumeric(fee)) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>Please enter a valid numeric fee</Trans>
          </AlertDialog>,
        ),
      );
      return;
    }

    let address = data.address;
    if (address.includes('colour')) {
      dispatch(
        openDialog(
          <AlertDialog>
            <Trans>
              Error: Cannot send chia to coloured address. Please enter a chia
              address.
            </Trans>
          </AlertDialog>,
        ),
      );
      return;
    }

    if (address.slice(0, 12) === 'chia_addr://') {
      address = address.slice(12);
    }
    if (address.startsWith('0x') || address.startsWith('0X')) {
      address = address.slice(2);
    }

    const amountValue = Number.parseFloat(chia_to_mojo(amount));
    const feeValue = Number.parseFloat(chia_to_mojo(fee));

    dispatch(send_transaction(wallet_id, amountValue, feeValue, address));

    methods.reset();
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
      {result_message && <p className={result_class}>{result_message}</p>}

      <Form methods={methods} onSubmit={handleSubmit}>
        <Grid spacing={2} container>
          <Grid xs={12} item>
            <ChiaTextField
              name="address"
              variant="filled"
              color="secondary"
              fullWidth
              disabled={sending_transaction}
              label={<Trans>Address / Puzzle hash</Trans>}
            />
          </Grid>
          <Grid xs={12} md={6} item>
            <Amount
              id="filled-secondary"
              variant="filled"
              color="secondary"
              name="amount"
              disabled={sending_transaction}
              label={<Trans>Amount</Trans>}
              fullWidth
            />
          </Grid>
          <Grid xs={12} md={6} item>
            <Fee
              id="filled-secondary"
              variant="filled"
              name="fee"
              color="secondary"
              disabled={sending_transaction}
              label={<Trans>Fee</Trans>}
              fullWidth
            />
          </Grid>
          <Grid xs={12} item>
            <Flex justifyContent="flex-end" gap={1}>
              {!!config.local_test && (
                <Button onClick={farm} variant="outlined">
                  <Trans>Farm</Trans>
                </Button>
              )}

              <Button
                variant="contained"
                color="primary"
                type="submit"
                disabled={sending_transaction}
              >
                <Trans>Send</Trans>
              </Button>
            </Flex>
          </Grid>
        </Grid>
      </Form>
    </Card>
  );
}
