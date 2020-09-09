import { createMuiTheme } from "@material-ui/core/styles";

const defaultTheme = createMuiTheme();

const theme = createMuiTheme({
  palette: {
    primary: { main: "#5DA962", contrastText: "#ffffff" },
    secondary: { main: "#000000", contrastText: "#ffffff" },
  },
  root: {
    background: "linear-gradient(45deg, #333333 30%, #333333 90%)",
    height: "100%",
  },
  app_root: {
    background: "linear-gradient(45deg, #142229 30%, #112240 90%)",
    height: "100%",
  },
  paper: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
  },
  avatar: {
    marginTop: defaultTheme.spacing(8),
    backgroundColor: defaultTheme.palette.secondary.main,
  },
  form: {
    width: "100%",
    marginTop: defaultTheme.spacing(5),
  },
  textField: {
    borderColor: "#ffffff",
  },
  submit: {
    marginTop: defaultTheme.spacing(8),
    marginBottom: defaultTheme.spacing(3),
  },
  grid: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    paddingTop: defaultTheme.spacing(5),
  },
  grid_item: {
    paddingTop: 10,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    backgroundColor: "#444444",
    color: "#ffffff",
    height: 50,
    verticalAlign: "middle",
  },
  title: {
    color: "#ffffff",
    marginTop: defaultTheme.spacing(4),
    marginBottom: defaultTheme.spacing(8),
  },
  navigator: {
    color: "#ffffff",
    marginTop: defaultTheme.spacing(4),
    marginLeft: defaultTheme.spacing(4),
    fontSize: 35,
  },
  div: {
    height: "100%",
    background: "linear-gradient(45deg, #222222 30%, #333333 90%)",
    fontFamily: "Open Sans, sans-serif"
  },
  center: {
    textAlign: "center",
    height: "200px",
    width: "300px",
    position: "absolute",
    top: 0,
    bottom: 0,
    left: 0,
    right: 0,
    margin: "auto"
  },
  h3: {
    color: "white"
  }
});

export default theme;
