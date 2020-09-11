import React from "react";
import Button from "@material-ui/core/Button";
import CssBaseline from "@material-ui/core/CssBaseline";
import Link from "@material-ui/core/Link";
import Grid from "@material-ui/core/Grid";
import { withTheme } from "@material-ui/styles";
import Container from "@material-ui/core/Container";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { useSelector } from "react-redux";
import { withRouter } from "react-router-dom";
import CssTextField from "../components/cssTextField";
import { useDispatch } from "react-redux";
import { mnemonic_word_added, resetMnemonic } from "../modules/mnemonic_input";
import { unselectFingerprint } from "../modules/message";
import {
  changeEntranceMenu,
  presentSelectKeys,
  presentRestoreBackup
} from "../modules/entranceMenu";
import logo from "../assets/img/chia_logo.svg";
import myStyle from "./style";

const MnemonicField = props => {
  return (
    <Grid item xs={2}>
      <CssTextField
        autoComplete="off"
        variant="outlined"
        margin="normal"
        fullWidth
        color="primary"
        id={props.id}
        label={props.index}
        error={props.error}
        autoFocus={props.autofocus}
        defaultValue={props.value}
        onChange={props.onChange}
      />
    </Grid>
  );
};

const Iterator = props => {
  const dispatch = useDispatch();
  const mnemonic_state = useSelector(state => state.mnemonic_state);
  const incorrect_word = useSelector(
    state => state.mnemonic_state.incorrect_word
  );

  function handleTextFieldChange(e) {
    var id = e.target.id + "";
    var clean_id = id.replace("id_", "");
    var int_val = parseInt(clean_id) - 1;
    var data = { word: e.target.value, id: int_val };
    dispatch(mnemonic_word_added(data));
  }
  var indents = [];
  for (var i = 0; i < 24; i++) {
    var focus = i === 0;
    indents.push(
      <MnemonicField
        onChange={handleTextFieldChange}
        key={i}
        error={
          (props.submitted && mnemonic_state.mnemonic_input[i] === "") ||
          mnemonic_state.mnemonic_input[i] === incorrect_word
        }
        value={mnemonic_state.mnemonic_input[i]}
        autofocus={focus}
        id={"id_" + (i + 1)}
        index={i + 1}
      />
    );
  }
  return indents;
};

const UIPart = () => {
  function goBack() {
    dispatch(resetMnemonic());
    dispatch(changeEntranceMenu(presentSelectKeys));
  }
  const dispatch = useDispatch();
  const [submitted, setSubmitted] = React.useState(false);
  const mnemonic = useSelector(state => state.mnemonic_state.mnemonic_input);
  const classes = myStyle();

  function enterMnemonic() {
    setSubmitted(true);
    for (var i = 0; i < mnemonic.length; i++) {
      if (mnemonic[i] === "") {
        return;
      }
    }
    dispatch(unselectFingerprint());
    dispatch(changeEntranceMenu(presentRestoreBackup));
  }

  return (
    <div className={classes.root}>
      <Link onClick={goBack} href="#">
        <ArrowBackIosIcon className={classes.navigator}> </ArrowBackIosIcon>
      </Link>
      <div className={classes.grid_wrap}>
        <img className={classes.logo} src={logo} alt="Logo" />
        <Container className={classes.grid} maxWidth="lg">
          <h1 className={classes.titleSmallMargin}>
            Import Wallet from Mnemonics
          </h1>
          <p className={classes.whiteP}>
            Enter the 24 word mmemonic that you have saved in order to restore
            your Chia wallet.
          </p>
          <Grid container spacing={2}>
            <Iterator submitted={submitted}></Iterator>
          </Grid>
        </Container>
      </div>
      <Container component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <Button
            onClick={enterMnemonic}
            type="submit"
            fullWidth
            variant="contained"
            color="primary"
            className={classes.submit}
          >
            Next
          </Button>
        </div>
      </Container>
    </div>
  );
};

const OldWallet = props => {
  return <UIPart props={props}></UIPart>;
};

export default withTheme(withRouter(OldWallet));
