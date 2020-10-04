import React from 'react';
import { useForm } from "react-hook-form";
import { useDispatch, useSelector } from "react-redux";
import { Card, CardContent, Button, Box, Grid, Typography, TextField } from "@material-ui/core";
import { chia_to_mojo } from "../../util/chia";
import { addRateLimitedFunds } from '../../modules/message';
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

    const { amount, fee } = values;

    if (amount === '' || !Number(amount) || isNaN(Number(amount))) {
      dispatch(openDialog("Please enter a valid numeric amount"));
      return;
    } else if (fee === '' || isNaN(Number(fee))) {
      dispatch(openDialog("Please enter a valid numeric fee"));
      return;
    }

    const amountValue = parseFloat(Number(chia_to_mojo(amount)));
    const feeValue = parseFloat(Number(chia_to_mojo(fee)));

    dispatch(addRateLimitedFunds(walletId, amountValue, feeValue));
    reset();
  }

  return (
    <form onSubmit={handleSubmit(handleSubmitForm)}>
      <Card>
        <CardContent>
          <Typography component="h6" variant="h6" gutterBottom>
            Add Funds
          </Typography>

          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <TextField
                name="amount"
                variant="filled"
                color="secondary"
                margin="normal"
                inputRef={register}
                label="Amount"
                fullWidth
              />
            </Grid>
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
              Add
            </Button>
          </Box>
        </CardContent>
      </Card>
    </form>
  );
}
