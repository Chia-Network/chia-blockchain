import React from 'react';
import { Trans } from '@lingui/macro';
import {
  TextField,
  Typography,
  Grid,
  Container,
} from '@material-ui/core';
import { useGenerateMnemonicMutation, useAddKeyMutation, useLogInMutation } from '@chia/api-react';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useHistory } from 'react-router';
import { useEffectOnce } from 'react-use';
import { ButtonLoading, Flex, Loading, Link, Logo, useShowError } from '@chia/core';
import LayoutHero from '../layout/LayoutHero';

const MnemonicField = (props: any) => (
  <Grid item xs={2}>
    <TextField
      variant="filled"
      margin="normal"
      color="primary"
      id={props.id}
      label={props.index}
      name="email"
      autoComplete="email"
      value={props.word}
      inputProps={{
        readOnly: true,
      }}
      fullWidth
      autoFocus
    />
  </Grid>
);

export default function WalletAdd() {
  const history = useHistory();
  const [generateMnemonic, { data: words, isLoading }] = useGenerateMnemonicMutation();
  const [addKey, { isLoading: isAddKeyLoading }] = useAddKeyMutation();
  const [logIn, { isLoading: isLogInLoading }] = useLogInMutation();
  const showError = useShowError();

  useEffectOnce(() => {
    generateMnemonic();
  });

  const isProcessing = isAddKeyLoading || isLogInLoading;

  async function handleNext() {
    if (!words || isProcessing) {
      return;
    }

    try {
      const fingerprint = await addKey({
        mnemonic: words,
        type: 'new_wallet',
      }).unwrap();

      await logIn({
        fingerprint,
      }).unwrap();

      history.push('/dashboard/wallets/1');
    } catch (error) {
      showError(error);
    }
  }

  return (
    <LayoutHero
      header={
        <Link to="/">
          <ArrowBackIosIcon fontSize="large" color="secondary" />
        </Link>
      }
    >
      <Container maxWidth="lg">
        <Flex flexDirection="column" gap={3} alignItems="center">
          <Logo />
          <Typography variant="h4" component="h1" gutterBottom>
            <Trans>New Wallet</Trans>
          </Typography>
          <Typography variant="subtitle1" align="center">
            <Trans>
              Welcome! The following words are used for your wallet backup.
              Without them, you will lose access to your wallet, keep them safe!
              Write down each word along with the order number next to them.
              (Order is important)
            </Trans>
          </Typography>
          {!isLoading && words ? (
            <Grid container spacing={2}>
              {words.map((word: string, index: number) => (
                <MnemonicField
                  key={index}
                  word={word}
                  id={`id_${index + 1}`}
                  index={index + 1}
                />
              ))}
            </Grid>
          ) : (
            <Loading />
          )}
          <Container maxWidth="xs">
            <ButtonLoading
              onClick={handleNext}
              type="submit"
              variant="contained"
              color="primary"
              disabled={!words}
              loading={isProcessing}
              fullWidth
            >
              <Trans>Next</Trans>
            </ButtonLoading>
          </Container>
        </Flex>
      </Container>
    </LayoutHero>
  );
}
