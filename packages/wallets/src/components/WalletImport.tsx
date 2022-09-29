import React from 'react';
import { Trans } from '@lingui/macro';
import { Typography, Container, Grid } from '@mui/material';
// import { shuffle } from 'lodash';
import { useForm, useFieldArray } from 'react-hook-form';
import {
  useAddKeyMutation,
  useLogInMutation,
  useSetLabelMutation,
} from '@chia/api-react';
import { useNavigate } from 'react-router';
import {
  AlertDialog,
  Autocomplete,
  Button,
  ButtonLoading,
  Form,
  Flex,
  Logo,
  useOpenDialog,
  useTrans,
  TextField,
} from '@chia/core';
import { english } from '@chia/api';
import MnemonicPaste from './PasteMnemonic';

/*
const shuffledEnglish = shuffle(english);
const test = new Array(24).fill('').map((item, index) => shuffledEnglish[index].word);
*/

const emptyMnemonic = Array.from(Array(24).keys()).map((i) => ({
  word: '',
}));

const options = english.map((item) => item.word);

type FormData = {
  mnemonic: {
    word: string;
  }[];
  label: string;
};

export default function WalletImport() {
  const navigate = useNavigate();
  const [setLabel] = useSetLabelMutation();
  const [addKey] = useAddKeyMutation();
  const [logIn] = useLogInMutation();
  const trans = useTrans();
  const openDialog = useOpenDialog();
  const [mnemonicPasteOpen, setMnemonicPasteOpen] = React.useState(false);

  const methods = useForm<FormData>({
    defaultValues: {
      mnemonic: emptyMnemonic,
      label: '',
    },
  });

  const {
    formState: { isSubmitting },
  } = methods;

  const { fields, replace } = useFieldArray({
    control: methods.control,
    name: 'mnemonic',
  });

  const submitMnemonicPaste = (mnemonicList: string) => {
    const mList = mnemonicList.match(/\b(\w+)\b/g);
    const intersection = mList?.filter((element) => options.includes(element));

    if (!intersection || intersection.length !== 24) {
      openDialog(
        <AlertDialog>
          <Trans>
            Your pasted list does not include 24 valid mnemonic words.
          </Trans>
        </AlertDialog>
      );
      return;
    }

    const mnemonic = intersection.map((word) => ({ word }));
    replace(mnemonic);
    closeMnemonicPaste();
  };

  function closeMnemonicPaste() {
    setMnemonicPasteOpen(false);
  }

  function ActionButtons() {
    return (
      <Button
        onClick={() => setMnemonicPasteOpen(true)}
        variant="contained"
        disableElevation
      >
        <Trans>Paste Mnemonic</Trans>
      </Button>
    );
  }

  async function handleSubmit(values: FormData) {
    if (isSubmitting) {
      return;
    }

    const { mnemonic, label } = values;
    const mnemonicWords = mnemonic.map((item) => item.word);
    const hasEmptyWord = !!mnemonicWords.filter((word) => !word).length;
    if (hasEmptyWord) {
      throw new Error(trans('Please fill all words'));
    }

    const fingerprint = await addKey({
      mnemonic: mnemonicWords,
      type: 'new_wallet',
    }).unwrap();

    if (label) {
      await setLabel({
        fingerprint,
        label,
      }).unwrap();
    }

    await logIn({
      fingerprint,
    }).unwrap();

    navigate('/dashboard/wallets/1');
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Container maxWidth="lg">
        <Flex flexDirection="column" gap={3} alignItems="center">
          <Logo />
          <Typography
            variant="h4"
            component="h1"
            textAlign="center"
            gutterBottom
          >
            <Trans>Import Wallet from Mnemonics</Trans>
          </Typography>
          <Typography variant="subtitle1" align="center">
            <Trans>
              Enter the 24 word mnemonic that you have saved in order to restore
              your Chia wallet.
            </Trans>
          </Typography>
          <Grid spacing={2} rowSpacing={3} container>
            {fields.map((field, index) => (
              <Grid key={field.id} xs={6} sm={4} md={2} item>
                <Autocomplete
                  options={options}
                  name={`mnemonic.${index}.word`}
                  label={index + 1}
                  autoFocus={index === 0}
                  variant="filled"
                  disableClearable
                />
              </Grid>
            ))}
          </Grid>
          <Grid container>
            <Grid xs={0} md={4} item />
            <Grid xs={12} md={4} item>
              <Flex flexDirection="column" gap={3}>
                <TextField
                  name="label"
                  label={<Trans>Wallet Name</Trans>}
                  inputProps={{
                    readOnly: isSubmitting,
                  }}
                  fullWidth
                />
                <ButtonLoading
                  type="submit"
                  variant="contained"
                  color="primary"
                  loading={isSubmitting}
                  fullWidth
                >
                  <Trans>Next</Trans>
                </ButtonLoading>
                <ActionButtons />
                {mnemonicPasteOpen && (
                  <MnemonicPaste
                    onSuccess={submitMnemonicPaste}
                    onCancel={closeMnemonicPaste}
                  />
                )}
              </Flex>
            </Grid>
          </Grid>
        </Flex>
      </Container>
    </Form>
  );
}
