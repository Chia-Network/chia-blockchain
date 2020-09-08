import React from "react";
import PropTypes from "prop-types";

import MuiCard from "@material-ui/core/Card";
import CardContent from "@material-ui/core/CardContent";
import CardActions from "@material-ui/core/CardActions";
import Typography from "@material-ui/core/Typography";
import Button from "@material-ui/core/Button";
import { makeStyles } from "@material-ui/core/styles";

const useStyles = makeStyles({
  root: {
    width: 440,
    padding: "27px 59px 27px 44px",
  },
  content: {
    padding: 0,
    marginBottom: "30px",
  },
  text: {
    fontWeight: 300,
    fontSize: "22px",
    lineHeight: "32px",
    color: "#66666B",
  },
});

function Card(props) {
  const { actionText, onAction, iconSrc } = props;

  const classes = useStyles();

  return (
    <MuiCard className={classes.root}>
      <CardContent className={classes.content}>
        {iconSrc && <img src={iconSrc} alt="Card Icon" />}
        <Typography className={classes.text} variant="body2" component="p">
          {props.children}
        </Typography>
      </CardContent>
      {actionText && onAction && (
        <CardActions>
          <Button
            color="primary"
            variant="contained"
            size="large"
            onClick={onAction}
          >
            {actionText}
          </Button>
        </CardActions>
      )}
    </MuiCard>
  );
}

Card.propTypes = {
  actionText: PropTypes.string,
  onAction: PropTypes.func,
  iconSrc: PropTypes.string,
};

export default Card;
