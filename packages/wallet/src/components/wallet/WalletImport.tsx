import React from 'react';
import { Trans } from '@lingui/macro';
import {
  Typography,
  Container,
  Button,
  Grid,
} from '@material-ui/core';
import { shuffle } from 'lodash';
import { useForm, useFieldArray } from 'react-hook-form';
import { useAddKeyMutation } from '@chia/api-react';
import { ArrowBackIos as ArrowBackIosIcon } from '@material-ui/icons';
import { useHistory } from 'react-router';
import { Autocomplete, Form, Flex, Logo } from '@chia/core';
import LayoutHero from '../layout/LayoutHero';
import english from '../../util/english';
import useTrans from '../../hooks/useTrans';

const shuffledEnglish = shuffle(english);

const test = new Array(24).fill('').map((item, index) => shuffledEnglish[index].word);
console.log('test', test);

const options = english.map((item) => item.word);

type FormData = {
  mnemonic: string[];
};

export default function WalletImport() {
  const history = useHistory();
  const [addKey, rest] = useAddKeyMutation();
  const trans = useTrans();

  const methods = useForm<FormData>({
    defaultValues: {
      mnemonic: shuffle(test), //new Array(24).fill(''),
    },
  });

  const { fields } = useFieldArray({
    control: methods.control,
    name: 'mnemonic',
  });

  function handleBack() {
    history.push('/');
  }

  async function handleSubmit(values: FormData) {
    const { mnemonic } = values;
    const hasEmptyWord = !!mnemonic.find((word) => !word);
    if (hasEmptyWord) {
      throw new Error(trans('Please fill all words'));
    }

    
    await addKey({
      mnemonic,
      type: 'skip',
    }).unwrap();

  }

  console.log('rest', rest);

  const errorIndex = -1;

  return (
    <LayoutHero
      header={
        <ArrowBackIosIcon
          onClick={handleBack}
          fontSize="large"
          color="secondary"
        />
      }
    >
      <Form methods={methods} onSubmit={handleSubmit}>
        <Container maxWidth="lg">
          <Flex flexDirection="column" gap={3} alignItems="center">
            <Logo />
            <Typography variant="h4" component="h1" gutterBottom>
              <Trans>Import Wallet from Mnemonics</Trans>
            </Typography>
            <Typography variant="subtitle1" align="center">
              <Trans>
                Enter the 24 word mnemonic that you have saved in order to restore
                your Chia wallet.
              </Trans>
            </Typography>
            <Grid container spacing={2}>
              {fields.map((field, index) => (
                <Grid key={field.id} xs={2} item>
                  <Autocomplete
                    options={options}
                    name={`mnemonic.${index}`}
                    label={index + 1}
                    autoFocus={index === 0}
                    error={index === errorIndex}
                    variant="filled"
                    disableClearable
                  />
                </Grid>
              ))}
            </Grid>
            <Container maxWidth="xs">
              <Button
                type="submit"
                variant="contained"
                color="primary"
                fullWidth
              >
                <Trans>Next</Trans>
              </Button>
            </Container>
          </Flex>
        </Container>
      </Form>
    </LayoutHero>
  );
}
