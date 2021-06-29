import React /* , { ReactNode } */ from 'react';
import { Trans } from '@lingui/macro';
import {
  More,
  Amount,
  Fee,
  Form,
  TextField as ChiaTextField,
  AlertDialog,
  CopyToClipboard,
  Flex,
  Card,
} from '@chia/core';
import { makeStyles } from '@material-ui/core/styles';
import { useDispatch, useSelector } from 'react-redux';
import isNumeric from 'validator/es/lib/isNumeric';
import { useForm, useWatch } from 'react-hook-form';
import {
  /*
  Tooltip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  */
  Box,
  Typography,
  Button,
  TextField,
  InputAdornment,
  Grid,
  ListItemIcon,
  MenuItem,
} from '@material-ui/core';
import {
  // ExpandMore as ExpandMoreIcon,
  // Help as HelpIcon,
  Delete as DeleteIcon,
} from '@material-ui/icons';
import {
  get_address,
  send_transaction,
  farm_block,
} from '../../../modules/message';
import { /* mojo_to_chia_string, */ chia_to_mojo } from '../../../util/chia';
import { openDialog } from '../../../modules/dialog';
import { get_transaction_result } from '../../../util/transaction_result';
import config from '../../../config/config';
import type { RootState } from '../../../modules/rootReducer';
import WalletHistory from '../WalletHistory';
// import useCurrencyCode from '../../../hooks/useCurrencyCode';
import { deleteUnconfirmedTransactions } from '../../../modules/incoming';
// import WalletGraph from '../WalletGraph';
import WalletCards from './WalletCards';
import WalletStatus from '../WalletStatus';

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

/*
type BalanceCardSubSectionProps = {
  title: ReactNode;
  tooltip?: ReactNode;
  balance: number;
};

function BalanceCardSubSection(props: BalanceCardSubSectionProps) {
  const currencyCode = useCurrencyCode();

  return (
    <Grid item xs={12}>
      <Box display="flex">
        <Box flexGrow={1}>
          <Typography variant="subtitle1">
            {props.title}
            {props.tooltip && (
              <Tooltip title={props.tooltip}>
                <HelpIcon style={{ color: '#c8c8c8', fontSize: 12 }} />
              </Tooltip>
            )}
          </Typography>
        </Box>
        <Box>
          <Typography variant="subtitle1">
            {mojo_to_chia_string(props.balance)} {currencyCode}
          </Typography>
        </Box>
      </Box>
    </Grid>
  );
}

type BalanceCardProps = {
  wallet_id: number;
};

function BalanceCard(props: BalanceCardProps) {
  const { wallet_id } = props;

  const wallet = useSelector((state: RootState) =>
    state.wallet_state.wallets?.find((item) => item.id === wallet_id),
  );

  const balance = wallet?.wallet_balance?.confirmed_wallet_balance;
  const balance_spendable = wallet?.wallet_balance?.spendable_balance;
  const balance_pending = wallet?.wallet_balance?.pending_balance;
  const pending_change = wallet?.wallet_balance?.pending_change;

  const balance_ptotal = balance + balance_pending;

  const classes = useStyles();

  return (
    <Card title={<Trans>Balance</Trans>}>
      <BalanceCardSubSection
        title={<Trans>Total Balance</Trans>}
        balance={balance}
        tooltip={
          <Trans>
            This is the total amount of chia in the blockchain at the current
            peak sub block that is controlled by your private keys. It includes
            frozen farming rewards, but not pending incoming and outgoing
            transactions.
          </Trans>
        }
      />
      <BalanceCardSubSection
        title={<Trans>Spendable Balance</Trans>}
        balance={balance_spendable}
        tooltip={
          <Trans>
            This is the amount of Chia that you can currently use to make
            transactions. It does not include pending farming rewards, pending
            incoming transactions, and Chia that you have just spent but is not
            yet in the blockchain.
          </Trans>
        }
      />
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <Accordion className={classes.front}>
              <AccordionSummary
                expandIcon={<ExpandMoreIcon />}
                aria-controls="panel1a-content"
                id="panel1a-header"
              >
                <Typography className={classes.heading}>
                  <Trans>View pending balances</Trans>
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Grid container spacing={0}>
                  <BalanceCardSubSection
                    title={<Trans>Pending Total Balance</Trans>}
                    balance={balance_ptotal}
                    tooltip={
                      <Trans>
                        This is the total balance + pending balance: it is what
                        your balance will be after all pending transactions are
                        confirmed.
                      </Trans>
                    }
                  />
                  <BalanceCardSubSection
                    title={<Trans>Pending Balance</Trans>}
                    balance={balance_pending}
                    tooltip={
                      <Trans>
                        This is the sum of the incoming and outgoing pending
                        transactions (not yet included into the blockchain).
                        This does not include farming rewards.
                      </Trans>
                    }
                  />
                  <BalanceCardSubSection
                    title={<Trans>Pending Change</Trans>}
                    balance={pending_change}
                    tooltip={
                      <Trans>
                        This is the pending change, which are change coins which
                        you have sent to yourself, but have not been confirmed
                        yet.
                      </Trans>
                    }
                  />
                </Grid>
              </AccordionDetails>
            </Accordion>
          </Box>
        </Box>
      </Grid>
      <WalletGraph walletId={wallet_id} />
    </Card>
  );
}
*/

type SendCardProps = {
  wallet_id: number;
};

type SendTransactionData = {
  address: string;
  amount: string;
  fee: string;
};

function SendCard(props: SendCardProps) {
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

type AddressCardProps = {
  wallet_id: number;
};

function AddressCard(props: AddressCardProps) {
  const { wallet_id } = props;

  const dispatch = useDispatch();
  const wallet = useSelector((state: RootState) =>
    state.wallet_state.wallets?.find((item) => item.id === wallet_id),
  );

  if (!wallet) {
    return null;
  }

  const { address } = wallet;

  function newAddress() {
    dispatch(get_address(wallet_id, true));
  }

  return (
    <Card
      title={<Trans>Receive Address</Trans>}
      action={
        <Button onClick={newAddress} variant="outlined">
          <Trans>New Address</Trans>
        </Button>
      }
      tooltip={
        <Trans>
          HD or Hierarchical Deterministic keys are a type of public key/private
          key scheme where one private key can have a nearly infinite number of
          different public keys (and therefor wallet receive addresses) that
          will all ultimately come back to and be spendable by a single private
          key.
        </Trans>
      }
    >
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              label={<Trans>Address</Trans>}
              value={address}
              variant="filled"
              InputProps={{
                readOnly: true,
                endAdornment: (
                  <InputAdornment position="end">
                    <CopyToClipboard value={address} />
                  </InputAdornment>
                ),
              }}
              fullWidth
            />
          </Box>
        </Box>
      </Grid>
    </Card>
  );
}

type StandardWalletProps = {
  wallet_id: number;
};

export default function StandardWallet(props: StandardWalletProps) {
  const { wallet_id } = props;
  const dispatch = useDispatch();

  function handleDeleteUnconfirmedTransactions() {
    dispatch(deleteUnconfirmedTransactions(wallet_id));
  }

  return (
    <Flex flexDirection="column" gap={1}>
      <Flex gap={1} alignItems="center">
        <Flex flexGrow={1}>
          <Typography variant="h5" gutterBottom>
            <Trans>Chia Wallet</Trans>
          </Typography>
        </Flex>
        <More>
          {({ onClose }) => (
            <Box>
              <MenuItem
                onClick={() => {
                  onClose();
                  handleDeleteUnconfirmedTransactions();
                }}
              >
                <ListItemIcon>
                  <DeleteIcon />
                </ListItemIcon>
                <Typography variant="inherit" noWrap>
                  <Trans>Delete Unconfirmed Transactions</Trans>
                </Typography>
              </MenuItem>
            </Box>
          )}
        </More>
      </Flex>

      <Flex flexDirection="column" gap={2}>
        <Flex gap={1} justifyContent="flex-end">
          <Typography variant="body1" color="textSecondary">
            <Trans>Wallet Status:</Trans>
          </Typography>
          <WalletStatus height />
        </Flex>
        <Flex flexDirection="column" gap={3}>
          <WalletCards wallet_id={wallet_id} />
          <SendCard wallet_id={wallet_id} />
          <AddressCard wallet_id={wallet_id} />
          <WalletHistory walletId={wallet_id} />
        </Flex>
      </Flex>
    </Flex>
  );
}
