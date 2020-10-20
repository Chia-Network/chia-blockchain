import { createMuiTheme } from "@material-ui/core/styles";

const defaultTheme = createMuiTheme();

export default {
  palette: {
    primary: { 
      main: "#5DA962", 
      light: 'white',
      dark: 'orange',
      contrastText: "#ffffff",
    },
    secondary: { 
      main: "#000000", 
      contrastText: "#ffffff",
    },
    danger: {
      main: '#dc3545',
      contrastText: "#ffffff",
    },
  },
  root: {
    background: "linear-gradient(45deg, #333333 30%, #333333 90%)",
    height: "100%"
  },
  paper: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
  },
  avatar: {
    marginTop: defaultTheme.spacing(8),
    backgroundColor: defaultTheme.palette.secondary.main
  },
  form: {
    width: "100%",
    marginTop: defaultTheme.spacing(5)
  },
  textField: {
    borderColor: "#ffffff"
  },
  submit: {
    marginTop: defaultTheme.spacing(8),
    marginBottom: defaultTheme.spacing(3)
  },
  grid: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    paddingTop: defaultTheme.spacing(5)
  },
  grid_item: {
    paddingTop: 10,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    backgroundColor: "#444444",
    color: "#ffffff",
    height: 50,
    verticalAlign: "middle"
  },
  title: {
    color: "#ffffff",
    marginTop: defaultTheme.spacing(4),
    marginBottom: defaultTheme.spacing(8)
  },
  navigator: {
    color: "#ffffff",
    marginTop: defaultTheme.spacing(4),
    marginLeft: defaultTheme.spacing(4),
    fontSize: 35
  },
}
