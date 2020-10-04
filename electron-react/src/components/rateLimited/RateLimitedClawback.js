import React from 'react';
import { useForm } from "react-hook-form";
import { useDispatch, useSelector } from "react-redux";
import { Card, CardContent, Button, Box, Grid, Typography, TextField } from "@material-ui/core";
import { chia_to_mojo } from "../../util/chia";
import { sendClawbackTransaction } from '../../modules/message';
import { openDialog } from "../../modules/dialogReducer";

export default function RateLimitedAddFunds(props) {
  const { walletId } = props;
  const dispatch = useDispatch();
  const { register, handleSubmit, reset } = useForm();

  const syncing = useSelector(state => state.wallet_state.status.syncing);

  function handleSubmitForm(values) {
    if (syncing) {
      dispatch(openDialog("Please finish syncing before making a transaction"));
      return;
    }

    const { fee } = values;
    if (fee === '' || isNaN(Number(fee))) {
      dispatch(openDialog("Please enter a valid numeric fee"));
      return;
    }

    const feeValue = parseFloat(Number(chia_to_mojo(fee)));

    dispatch(sendClawbackTransaction(walletId, feeValue));

    reset();
  }

  return (
    <form onSubmit={handleSubmit(handleSubmitForm)}>
      <Card>
        <CardContent>
          <Typography component="h6" variant="h6" gutterBottom>
            Clawback Coin
          </Typography>

          <Typography variant="subtitle1" gutterBottom>
            You may use the clawback feature to retrieve your coin at any time. 
            If you do so, your Rate Limited User will no longer be able to spend the coin.
          </Typography>

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <TextField
                name="fee"
                variant="filled"
                color="secondary"
                margin="normal"
                inputRef={register}
                label="Fee"
                fullWidth
              />
            </Grid>
          </Grid>

          <Box>
            <Button
              variant="contained"
              color="primary"
              type="submit"
            >
              Clawback Coin
            </Button>
          </Box>
        </CardContent>
      </Card>
    </form>
  );
}
