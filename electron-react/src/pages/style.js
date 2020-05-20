import { makeStyles } from "@material-ui/styles";

const myStyle = makeStyles(theme => ({
  root: {
    background: "linear-gradient(45deg, #181818 30%, #333333 90%)",
    height: "100%"
  },
  paper: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: theme.spacing(0)
  },
  avatar: {
    marginTop: theme.spacing(8),
    backgroundColor: theme.palette.secondary.main
  },
  form: {
    width: "100%", // Fix IE 11 issue.
    marginTop: theme.spacing(5)
  },
  textField: {
    borderColor: "#ffffff"
  },
  submit: {
    marginTop: theme.spacing(8),
    marginBottom: theme.spacing(3)
  },
  grid_wrap: {
    paddingLeft: theme.spacing(10),
    paddingRight: theme.spacing(10)
  },
  grid: {
    display: "flex",
    flexDirection: "column",
    alignItems: "center"
  },
  grid_item: {
    padding: theme.spacing(2),
    paddingTop: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    backgroundColor: "#444444",
    color: "#ffffff",
    height: 60
  },
  title: {
    color: "#ffffff",
    marginTop: theme.spacing(4),
    marginBottom: theme.spacing(8)
  },
  navigator: {
    color: "#ffffff",
    marginTop: theme.spacing(4),
    marginLeft: theme.spacing(4),
    fontSize: 35,
    flex: 1,
    align: "right"
  },
  instructions: {
    color: "#ffffff",
    fontSize: 18
  }
}));

export default myStyle;
