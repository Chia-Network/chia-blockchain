import React, { Component, useEffect } from "react";
import Button from "@material-ui/core/Button";
import CssBaseline from "@material-ui/core/CssBaseline";
import Grid from "@material-ui/core/Grid";
import Typography from "@material-ui/core/Typography";
import { withTheme } from "@material-ui/styles";
import Container from "@material-ui/core/Container";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import { connect, useSelector, useDispatch } from "react-redux";
import { genereate_mnemonics, add_new_key_action } from "../modules/message";
import { withRouter } from "react-router-dom";
import CssTextField from "../components/cssTextField";
import myStyle from "./style";
import { changeEntranceMenu, presentSelectKeys } from "../modules/entranceMenu";
import { openDialog } from "../modules/dialogReducer";

const MnemonicField = props => {
  return (
    <Grid item xs={2}>
      <CssTextField
        variant="outlined"
        margin="normal"
        disabled
        fullWidth
        color="primary"
        id={props.id}
        label={props.index}
        name="email"
        autoComplete="email"
        autoFocus
        value={props.word}
        height="60"
      />
    </Grid>
  );
};
const Iterator = props => {
  return props.mnemonic.map((word, i) => (
    <MnemonicField key={i} word={word} id={"id_" + (i + 1)} index={i + 1} />
  ));
};

const UIPart = props => {
  var words = useSelector(state => state.wallet_state.mnemonic);
  const dispatch = useDispatch();
  const classes = myStyle();
  if (!words) {
    words = [];
  }

  useEffect(() => {
    dispatch(
      openDialog(
        "Welcome!",
        `The following words are used for your wallet backup.
        Without them, you will lose access to your wallet, keep them safe!!!
        Write down each word along with the order number next to them. (Order is important) `
      )
    );
  }, [dispatch]);

  function goBack() {
    dispatch(changeEntranceMenu(presentSelectKeys));
  }

  function next() {
    dispatch(add_new_key_action(words));
  }

  return (
    <div className={classes.root}>
      <ArrowBackIosIcon onClick={goBack} className={classes.navigator}>
        {" "}
      </ArrowBackIosIcon>
      <div className={classes.grid_wrap}>
        <Container className={classes.grid} maxWidth="lg">
          <Typography className={classes.title} component="h4" variant="h4">
            New Wallet
          </Typography>
          <Grid container spacing={2}>
            <Iterator mnemonic={words}></Iterator>
          </Grid>
        </Container>
      </div>
      <Container component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <Button
            onClick={next}
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

class NewWallet extends Component {
  constructor(props) {
    super(props);
    this.words = [];
    var get_mnemonics = genereate_mnemonics();
    props.dispatch(get_mnemonics);
    this.classes = props.theme;
  }

  componentDidMount(props) {}

  render() {
    return <UIPart props={this.props}></UIPart>;
  }
}

export default withTheme(withRouter(connect()(NewWallet)));
