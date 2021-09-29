import React, { ReactNode } from 'react';
import Grid from '@material-ui/core/Grid';
import { makeStyles } from '@material-ui/core/styles';
import { Alert } from '@material-ui/lab';
import { useDispatch, useSelector } from 'react-redux';
import { Trans } from '@lingui/macro';
import { AlertDialog, Card, CopyToClipboard, Flex, Loading } from '@chia/core';
import { InputAdornment, Typography } from '@material-ui/core';
import { 
  ExpandMore as ExpandMoreIcon,
  Edit as RenameIcon,
} from '@material-ui/icons';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Box,
  Button,
  TextField,
  ListItemIcon,
  MenuItem,
} from '@material-ui/core';
import {
  cc_spend,
  farm_block,
  rename_cc_wallet,
} from '../../../modules/message';
import {
  mojo_to_colouredcoin_string,
  colouredcoin_to_mojo,
} from '../../../util/chia';
import { openDialog } from '../../../modules/dialog';
import { get_transaction_result } from '../../../util/transaction_result';
import config from '../../../config/config';
import type { RootState } from '../../../modules/rootReducer';
import WalletHistory from '../WalletHistory';
import useCurrencyCode from '../../../hooks/useCurrencyCode';
import useOpenDialog from '../../../hooks/useOpenDialog';
import useWallet from '../../../hooks/useWallet';
import WalletReceiveAddress from '../WalletReceiveAddress';
import WalletCards from '../standard/WalletCards';
import WalletCATSend from './WalletCATSend';
import WalletHeader from '../WalletHeader';
import WalletRenameDialog from '../WalletRenameDialog';


const drawerWidth = 240;

const useStyles = makeStyles((theme) => ({
  root: {
    display: 'flex',
    paddingLeft: '0px',
  },
  resultSuccess: {
    color: '#3AAC59',
  },
  resultFailure: {
    color: 'red',
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
    padding: theme.spacing(1),
    margin: theme.spacing(1),
    marginBottom: theme.spacing(2),
    marginTop: theme.spacing(2),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
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
  balancePaper: {
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
    padding: theme.spacing(1),
    margin: theme.spacing(1),
    marginBottom: theme.spacing(2),
    marginTop: theme.spacing(2),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
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
  colourCard: {
    overflowWrap: 'break-word',
    marginTop: theme.spacing(2),
    paddingBottom: 20,
  },
  amountField: {
    paddingRight: 20,
  },
}));

type ColourCardProps = {
  wallet_id: number;
};

function ColourCard(props: ColourCardProps) {
  const { wallet_id } = props;

  const dispatch = useDispatch();

  const wallet = useSelector((state: RootState) =>
    state.wallet_state.wallets?.find((item) => item.id === wallet_id),
  );

  if (!wallet) {
    return null;
  }

  const { name, colour } = wallet;

  let name_input: HTMLInputElement;

  function rename() {
    dispatch(rename_cc_wallet(wallet_id, name_input.value));
  }

  const classes = useStyles();
  return (
    <Card title={<Trans>Token and Asset Issuance Limitations</Trans>}>
      <Grid item xs={12}>
        <Box display="flex">
          <Box flexGrow={1}>
            <TextField
              value={colour}
              variant="filled"
              InputProps={{
                readOnly: true,
                endAdornment: (
                  <InputAdornment position="end">
                    <CopyToClipboard value={colour} />
                  </InputAdornment>
                ),
              }}
              fullWidth
              multiline
            />
          </Box>
        </Box>
      </Grid>
    </Card>
  );
}

// comment
function get_cc_unit(name: string): string {
  let cc_unit = name;
  if (cc_unit.length > 10) {
    cc_unit = `${cc_unit.slice(0, 10)}...`;
  }
  return cc_unit;
}

type Props = {
  walletId: number;
};

export default function WalletCAT(props: Props) {
  const { walletId } = props;
  const { wallet, loading } = useWallet(walletId);
  const openDialog = useOpenDialog();
  const dispatch = useDispatch();

  function handleRename() {
    if (!wallet) {
      return;
    }

    const { id, name } = wallet;

    openDialog((
      <WalletRenameDialog
        name={name}
        onSave={() => dispatch(rename_cc_wallet(id, newName))}
      />
    ));
  }

  if (loading) {
    return (
      <Loading />
    );
  }

  if (!wallet) {
    return (
      <Alert severity="error">
        <Trans>Wallet does not exists</Trans>
      </Alert>
    );
  }

  return (
    <Flex flexDirection="column" gap={1}>
      <WalletHeader 
        wallet_id={walletId}
        title={<Trans>CAT Wallet</Trans>}
        actions={({ onClose }) => (
          <MenuItem
            onClick={() => {
              onClose();
              handleRename();
            }}
          >
            <ListItemIcon>
              <RenameIcon />
            </ListItemIcon>
            <Typography variant="inherit" noWrap>
              <Trans>Rename Wallet</Trans>
            </Typography>
          </MenuItem>
        )}
      />
      <Flex flexDirection="column" gap={3}>
        <WalletCards wallet_id={walletId} />
        <ColourCard wallet_id={walletId} />
        <WalletReceiveAddress walletId={walletId} />
        <WalletCATSend wallet_id={walletId} currency={wallet.name} />
        <WalletHistory walletId={walletId} />
      </Flex>
    </Flex>
  );
}
