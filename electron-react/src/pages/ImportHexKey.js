import React from "react";
import CssBaseline from "@material-ui/core/CssBaseline";
import { makeStyles } from "@material-ui/core/styles";
import Container from "@material-ui/core/Container";
import logo from "../assets/img/chia_logo.svg"; // Tell webpack this JS file uses this image
import { withRouter } from "react-router-dom";
import { connect, useDispatch } from "react-redux";
import Link from "@material-ui/core/Link";
import ArrowBackIosIcon from "@material-ui/icons/ArrowBackIos";
import Button from "@material-ui/core/Button";
import CssTextField from "../components/cssTextField";
import { changeEntranceMenu, presentSelectKeys } from "../modules/entranceMenu";

const useStyles = makeStyles(theme => ({
  root: {
    background: "linear-gradient(45deg, #181818 30%, #333333 90%)",
    height: "100%"
  },
  paper: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    height: "100%"
  },
  textField: {
    borderColor: "#ffffff"
  },
  topButton: {
    width: 400,
    height: 45,
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(1)
  },
  bottomButton: {
    width: 400,
    height: 45,
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(1)
  },
  logo: {
    marginTop: theme.spacing(8),
    marginBottom: theme.spacing(3)
  },
  main: {
    height: "100%"
  },
  whiteText: {
    color: "white"
  },
  demo: {
    backgroundColor: theme.palette.background.paper
  },
  navigator: {
    color: "#ffffff",
    marginTop: theme.spacing(4),
    marginLeft: theme.spacing(4),
    fontSize: 35
  }
}));

const ImportHexKey = () => {
  const dispatch = useDispatch();
  const classes = useStyles();

  function goBack() {
    dispatch(changeEntranceMenu(presentSelectKeys));
  }
  const [hexKey, setHexKey] = React.useState("");
  const [error, setError] = React.useState(false);

  const regexp = /^[0-9a-fA-F]+$/;

  const handleChange = event => {
    let newHexKey = event.target.value;
    if (newHexKey === "") {
      setHexKey(newHexKey);
      setError(false);
      return;
    }
    if (newHexKey.startsWith("0x")) {
      newHexKey = newHexKey.substring(2);
    }
    if (regexp.test(newHexKey)) {
      if (newHexKey.length === 154 || newHexKey.length === 64) {
        // Private key must be in hex and 32 bytes (int private key) or 77 bytes (extended)
        setHexKey(newHexKey);
        setError(false);
        return;
      }
    }
    setHexKey(newHexKey);
    setError(true);
  };

  function next() {
    if (!error && hexKey.length > 0) {
    }
  }

  return (
    <div className={classes.root}>
      <Link onClick={goBack} href="#">
        <ArrowBackIosIcon className={classes.navigator}> </ArrowBackIosIcon>
      </Link>
      <Container className={classes.main} component="main" maxWidth="xs">
        <CssBaseline />
        <div className={classes.paper}>
          <img className={classes.logo} src={logo} alt="Logo" />
          <h2 className={classes.whiteText}>Paste your key in hex format</h2>
          <CssTextField
            error={error}
            autoComplete="off"
            variant="outlined"
            margin="normal"
            fullWidth
            color="primary"
            label={"Hexadecimal private key"}
            autoFocus={true}
            defaultValue=""
            onChange={handleChange}
            helperText={
              error
                ? "The key must be 154 or 77 characters long and valid hex."
                : ""
            }
          />
          <Link onClick={() => {}}>
            <Button
              type="submit"
              fullWidth
              variant="contained"
              color="primary"
              className={classes.topButton}
              onClick={next}
            >
              Add Key
            </Button>
          </Link>
        </div>
      </Container>
    </div>
  );
};

export default withRouter(connect()(ImportHexKey));
