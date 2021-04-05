import { useDispatch, useSelector } from 'react-redux';
import React, { useMemo } from 'react';
import { Dropzone } from '@chia/core';
import { Trans } from '@lingui/macro';
import {
  CssBaseline, 
  Container,
  Typography,
  Paper,
  Grid,
  Button,
  Box,
  TextField,
  Backdrop,
  CircularProgress,
} from '@material-ui/core';
import { makeStyles } from '@material-ui/core/styles';
import { Card } from '@chia/core';

import {
  createState,
  changeCreateWallet,
  CREATE_DID_WALLET_OPTIONS,
} from '../../../modules/createWallet';
import ArrowBackIosIcon from '@material-ui/icons/ArrowBackIos';
import { recover_did_action } from '../../../modules/message';
import { chia_to_mojo } from '../../../util/chia';
import { openDialog } from '../../../modules/dialog';
import { useForm, Controller, useFieldArray } from 'react-hook-form';

const useStyles = makeStyles((theme) => ({
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
  paper: {
    margin: theme.spacing(3),
    padding: theme.spacing(0),
    display: 'flex',
    overflow: 'auto',
    flexDirection: 'column',
  },
  balancePaper: {
    margin: theme.spacing(3),
  },
  copyButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(0),
    width: 50,
    height: 56,
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(4),
  },
  cardSubSection: {
    paddingLeft: theme.spacing(3),
    paddingRight: theme.spacing(3),
    paddingTop: theme.spacing(1),
  },
  tradeSubSection: {
    color: '#cccccc',
    borderRadius: 4,
    backgroundColor: '#555555',
    marginLeft: theme.spacing(3),
    marginRight: theme.spacing(3),
    marginTop: theme.spacing(1),
    padding: 15,
    overflowWrap: 'break-word',
  },
  formControl: {
    widht: '100%',
  },
  input: {
    height: 56,
    width: '100%',
  },
  send: {
    marginLeft: theme.spacing(2),
    paddingLeft: '0px',
    height: 56,
    width: 150,
  },
  card: {
    paddingTop: theme.spacing(10),
    height: 200,
  },
  saveButton: {
    width: '100%',
    marginTop: theme.spacing(4),
    marginRight: theme.spacing(1),
    marginBottom: theme.spacing(2),
    height: 56,
  },
  cancelButton: {
    width: '100%',
    marginTop: theme.spacing(4),
    marginLeft: theme.spacing(1),
    marginBottom: theme.spacing(2),
    height: 56,
  },
  drag: {
    backgroundColor: '#888888',
    height: 300,
    width: '100%',
  },
  dragText: {
    margin: 0,
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
  },
  circle: {
    height: '100%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
}));

/*

export const customStyles = makeStyles((theme) => ({
  input: {
    marginLeft: theme.spacing(3),
    height: 56,
  },
  inputLeft: {
    marginLeft: theme.spacing(3),
    width: '75%',
    height: 56,
  },
  inputDIDs: {
    paddingTop: theme.spacing(3),
    marginLeft: theme.spacing(0),
  },
  inputDID: {
    marginLeft: theme.spacing(0),
    marginBottom: theme.spacing(2),
    width: '50%',
    height: 56,
  },
  inputRight: {
    marginRight: theme.spacing(3),
    marginLeft: theme.spacing(6),
    height: 56,
  },
  sendButton: {
    marginLeft: theme.spacing(6),
    marginRight: theme.spacing(2),
    height: 56,
    width: 150,
  },
  addButton: {
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(2),
    height: 56,
    width: 50,
  },
  card: {
    paddingTop: theme.spacing(10),
    height: 200,
  },
  topCard: {
    height: 100,
  },
  subCard: {
    height: 100,
  },
  topTitleCard: {
    paddingTop: theme.spacing(6),
    paddingBottom: theme.spacing(1),
  },
  titleCard: {
    paddingBottom: theme.spacing(1),
  },
  inputTitleLeft: {
    paddingTop: theme.spacing(3),
    marginLeft: theme.spacing(3),
    width: '50%',
  },
  inputTitleRight: {
    marginLeft: theme.spacing(3),
    width: '50%',
  },
  ul: {
    listStyle: 'none',
  },
  sideButton: {
    marginTop: theme.spacing(0),
    marginBottom: theme.spacing(2),
    width: 50,
    height: 56,
  },
  root: {
    display: 'flex',
    paddingLeft: '0px',
  },
  content: {
    flexGrow: 1,
    height: 'calc(100vh - 64px)',
    overflowX: 'hidden',
  },
  container: {
    paddingTop: theme.spacing(0),
    paddingBottom: theme.spacing(0),
    paddingRight: theme.spacing(0),
    paddingLeft: theme.spacing(0),
  },
  balancePaper: {
    margin: theme.spacing(3),
  },
  cardTitle: {
    paddingLeft: theme.spacing(1),
    paddingTop: theme.spacing(1),
    marginBottom: theme.spacing(4),
  },
  dragContainer: {
    paddingLeft: 20,
    paddingRight: 20,
    paddingBottom: 20,
  },
  dragBox: {
    height: 300,
    width: '100%',
    margin: theme.spacing(3),
  },
  drag: {
    backgroundColor: '#888888',
    height: 300,
    width: '100%',
  },
  dragText: {
    margin: 0,
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
  },
}));

*/

export const RecoverDIDWallet = () => {
  const classes = useStyles();
  const dispatch = useDispatch();

  function handleDrop(acceptedFiles) {
    const recovery_file_path = acceptedFiles[0].path;
    const recovery_name = recovery_file_path.replace(/^.*[\\/]/, '');
    dispatch(recover_did_action(recovery_file_path));
  };

  function goBack() {
    dispatch(changeCreateWallet(CREATE_DID_WALLET_OPTIONS));
  }
  
  return (
    <div>
      <div className={classes.cardTitle}>
        <Box display="flex">
          <Box>
            <Button onClick={goBack}>
              <ArrowBackIosIcon> </ArrowBackIosIcon>
            </Button>
          </Box>
          <Box flexGrow={1} style={{ verticalAlign: 'bottom' }}>
            <Typography component="h6" variant="h6">
              Recover Distributed Identity Wallet
            </Typography>
          </Box>
        </Box>
      </div>
      <Dropzone onDrop={handleDrop}>
        <Trans>
          Drag and drop offer file
        </Trans>
      </Dropzone>
    </div>
  );
};

/*

<div>
  <div className={classes.cardTitle}>
    <Box display="flex">
      <Box>
        <Button onClick={goBack}>
          <ArrowBackIosIcon> </ArrowBackIosIcon>
        </Button>
      </Box>
      <Box flexGrow={1} className={classes.title}>
        <Typography component="h6" variant="h6">
          View DID Recovery File
        </Typography>
      </Box>
    </Box>
  </div>
  <div>
    <Box flexGrow={1} className={classes.dragBox}>
      <div
        onDrop={(e) => handleDrop(e)}
        onDragOver={(e) => handleDragOver(e)}
        onDragEnter={(e) => handleDragEnter(e)}
        onDragLeave={(e) => handleDragLeave(e)}
        className={classes.dragContainer}
      >
        <Paper className={classes.drag}>
          <div className={classes.dragText}>Drag and drop offer file</div>
        </Paper>
      </div>
    </Box>
  </div>
</div>

*/
