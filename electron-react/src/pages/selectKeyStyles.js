import { makeStyles } from "@material-ui/core/styles";

export const useStyles = makeStyles(theme => ({
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
  centeredSpan: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
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
  bottomButtonRed: {
    width: 400,
    height: 45,
    marginTop: theme.spacing(2),
    marginBottom: theme.spacing(1),
    color: "red"
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
  whiteP: {
    color: "white",
    fontSize: "18px"
  },
  demo: {
    backgroundColor: theme.palette.background.paper
  },
  rightPadding: {
    paddingRight: theme.spacing(3)
  },
  buttonColor: {
    color: "white"
  },
  input: {
    backgroundColor: "white",
    borderRadius: 6,
    width: "100%"
  }
}));
