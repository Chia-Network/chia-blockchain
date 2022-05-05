import React, { useMemo, useState } from 'react';
import { useForm, useFormContext } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import BigNumber from 'bignumber.js';
import { Trans, t } from '@lingui/macro';
import { useLocalStorage } from '@rehooks/local-storage';
import type { NFTInfo } from '@chia/api';
import { useCreateOfferForIdsMutation } from '@chia/api-react';
import {
  Amount,
  Back,
  Button,
  ButtonLoading,
  Fee,
  Flex,
  Form,
  TextField,
  chiaToMojo,
  useOpenDialog,
  useShowError,
} from '@chia/core';
import {
  Box,
  Divider,
  Grid,
  // Skeleton,
  Tabs,
  Tab,
  Typography,
} from '@mui/material';
import OfferLocalStorageKeys from './OfferLocalStorage';
import OfferEditorConfirmationDialog from './OfferEditorConfirmationDialog';
import { isValidNFTId, launcherIdFromNFTId } from './utils';
import NFTCard from '../nfts/NFTCard';

/* ========================================================================== */
/*              Temporary home for the NFT-specific Offer Editor              */
/*        An NFT offer consists of a single NFT being offered for XCH         */
/* ========================================================================== */

/* ========================================================================== */

enum NFTOfferEditorExchangeType {
  NFTForXCH = 'nft_for_xch',
  XCHForNFT = 'xch_for_nft',
}

/* ========================================================================== */

type NFTOfferConditionalsPanelProps = {
  defaultValues: NFTOfferEditorFormData;
  isProcessing: boolean;
};

function NFTOfferConditionalsPanel(props: NFTOfferConditionalsPanelProps) {
  const { defaultValues, isProcessing } = props;
  const disabled = isProcessing;
  const methods = useFormContext();
  const [amountFocused, setAmountFocused] = useState<boolean>(false);

  const tab = methods.watch('exchangeType');
  const amount = methods.watch('xchAmount');
  // HACK: manually determine the value for the amount field's shrink input prop.
  // Without this, toggling between the two tabs with an amount specified will cause
  // the textfield's label and value to overlap.
  const shrink = useMemo(() => {
    if (!amountFocused && (amount === undefined || amount.length === 0)) {
      return false;
    }
    return true;
  }, [amount, amountFocused]);

  const nftElem = (
    <Grid item>
      <TextField
        id={`${tab}-nftId}`}
        key={`${tab}-nftId}`}
        variant="filled"
        name="nftId"
        color="secondary"
        disabled={disabled}
        label={<Trans>NFT</Trans>}
        defaultValue={defaultValues.nftId}
        placeholder={t`NFT Identifier`}
        inputProps={{ spellCheck: false }}
        fullWidth
        required
      />
    </Grid>
  );
  const amountElem = (
    <Grid item>
      <Amount
        id={`${tab}-amount}`}
        key={`${tab}-amount}`}
        variant="filled"
        name="xchAmount"
        color="secondary"
        disabled={disabled}
        label={<Trans>Amount</Trans>}
        defaultValue={amount}
        onChange={handleAmountChange}
        onFocus={() => setAmountFocused(true)}
        onBlur={() => setAmountFocused(false)}
        showAmountInMojos={true}
        InputLabelProps={{ shrink }}
        required
      />
    </Grid>
  );
  const offerElem =
    tab === NFTOfferEditorExchangeType.NFTForXCH ? nftElem : amountElem;
  const takerElem =
    tab === NFTOfferEditorExchangeType.NFTForXCH ? amountElem : nftElem;

  function handleAmountChange(amount: string) {
    methods.setValue('xchAmount', amount);
  }

  function handleFeeChange(fee: string) {
    methods.setValue('fee', fee);
  }

  function handleReset() {
    methods.reset(defaultValues);
  }

  return (
    <Flex
      flexDirection="column"
      flexGrow={1}
      gap={3}
      style={{ padding: '1.5rem' }}
    >
      <Tabs
        value={tab}
        onChange={(_event, newValue) =>
          methods.setValue('exchangeType', newValue)
        }
        textColor="primary"
        indicatorColor="primary"
      >
        <Tab
          value={NFTOfferEditorExchangeType.NFTForXCH}
          label={<Trans>NFT for XCH</Trans>}
          disabled={disabled}
        />
        <Tab
          value={NFTOfferEditorExchangeType.XCHForNFT}
          label={<Trans>XCH for NFT</Trans>}
          disabled={disabled}
        />
      </Tabs>
      <Grid container>
        <Flex flexDirection="column" flexGrow={1} gap={3}>
          <Flex flexDirection="column" gap={1}>
            <Typography variant="subtitle1">You will offer</Typography>
            {offerElem}
          </Flex>
          <Flex flexDirection="column" gap={1}>
            <Typography variant="subtitle1">In exchange for</Typography>
            {takerElem}
          </Flex>
          <Divider />
          <Grid item>
            <Fee
              id="fee"
              variant="filled"
              name="fee"
              color="secondary"
              disabled={disabled}
              onChange={handleFeeChange}
              defaultValue={defaultValues.fee}
              label={<Trans>Fee</Trans>}
            />
          </Grid>
        </Flex>
      </Grid>
      <Flex
        flexDirection="column"
        flexGrow={1}
        alignItems="flex-end"
        justifyContent="flex-end"
      >
        <Flex justifyContent="flex-end" gap={2}>
          <Button
            variant="outlined"
            type="reset"
            onClick={handleReset}
            disabled={isProcessing}
          >
            <Trans>Reset</Trans>
          </Button>
          <ButtonLoading
            variant="contained"
            color="primary"
            type="submit"
            loading={isProcessing}
          >
            <Trans>Create Offer</Trans>
          </ButtonLoading>
        </Flex>
      </Flex>
    </Flex>
  );
}

NFTOfferConditionalsPanel.defaultProps = {
  isProcessing: false,
};

/* ========================================================================== */

type NFTOfferPreviewProps = {
  nft: NFTInfo;
};

function NFTOfferPreview(props: NFTOfferPreviewProps) {
  const { nft } = props;
  const methods = useFormContext();
  const nftId = methods.watch('nftId');

  const isValidNFT = useMemo(() => {
    if (nftId === undefined) {
      return false;
    }
    return isValidNFTId(nftId);
  }, [nftId]);

  const borderStyle = isValidNFT ? '2px solid #E0E0E0' : '2px dashed #E0E0E0';

  return (
    <Flex
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      style={{
        width: '328px',
        height: '576px',
        borderLeft: '1px solid #E0E0E0',
      }}
      gap={1}
    >
      <Flex
        flexDirection="column"
        flexGrow={1}
        gap={1}
        style={{
          padding: '1.5rem',
        }}
      >
        <Typography variant="subtitle1">Preview</Typography>
        <Box
          sx={{
            width: '264px',
            height: '456px',
            boxSizing: 'border-box',
            border: `${borderStyle}`,
            borderRadius: '24px',
            display: 'flex',
            overflow: 'hidden',
          }}
        >
          {isValidNFT ? (
            <NFTCard nft={nft} />
          ) : (
            // // TODO: The following is a placeholder for the NFT preview component
            // <Flex flexDirection="column" flexGrow={1} gap={0}>
            //   <Flex
            //     flexDirection="column"
            //     alignItems="center"
            //     style={{
            //       width: '100%',
            //       padding: '0.5rem 0.5rem 5px 0.5rem',
            //     }}
            //   >
            //     <Skeleton
            //       variant="rectangular"
            //       width="100%"
            //       height="59px"
            //       style={{ borderRadius: '18px 18px 0px 0px' }}
            //     />
            //   </Flex>
            //   <Flex
            //     flexDirection="column"
            //     alignItems="center"
            //     style={{ width: '100%', padding: '0 0.5rem 0 0.5rem' }}
            //   >
            //     <Skeleton variant="rectangular" width="100%" height="264px" />
            //   </Flex>
            //   <Flex
            //     flexDirection="column"
            //     alignItems="center"
            //     style={{ width: '100%', padding: '5px 0.5rem 0px 0.5rem' }}
            //   >
            //     <Skeleton variant="rectangular" width="100%" height="67px" />
            //   </Flex>
            //   <Flex
            //     flexDirection="column"
            //     style={{
            //       width: '100%',
            //       padding: '5px 0.5rem 0.5rem 0.5rem',
            //     }}
            //   >
            //     <Skeleton
            //       variant="rectangular"
            //       width="100%"
            //       height="31px"
            //       style={{ borderRadius: '0px 0px 18px 18px' }}
            //     />
            //   </Flex>
            // </Flex>
            <Flex
              flexDirection="column"
              alignItems="center"
              justifyContent="center"
              flexGrow={1}
              gap={1}
              style={{
                wordBreak: 'break-all',
              }}
            >
              <Typography variant="h6">
                <Trans>NFT not specified</Trans>
              </Typography>
            </Flex>
          )}
        </Box>
      </Flex>
    </Flex>
  );
}

/* ========================================================================== */
/*                              NFT Offer Editor                              */
/*             Currently only supports a single NFT <--> XCH offer            */
/* ========================================================================== */

type NFTOfferEditorFormData = {
  exchangeType: NFTOfferEditorExchangeType;
  nftId?: string;
  xchAmount: string;
  fee: string;
};

type NFTOfferEditorValidatedFormData = {
  exchangeType: NFTOfferEditorExchangeType;
  nftLauncherId: string;
  xchAmount: string;
  fee: string;
};

type NFTOfferEditorProps = {
  nft?: NFTInfo;
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
};

function buildOfferRequest(
  exchangeType: NFTOfferEditorExchangeType,
  nftLauncherId: string,
  xchAmount: string,
) {
  const baseMojoAmount: BigNumber = chiaToMojo(xchAmount);
  const mojoAmount =
    exchangeType === NFTOfferEditorExchangeType.NFTForXCH
      ? baseMojoAmount
      : baseMojoAmount.negated();
  const nftAmount =
    exchangeType === NFTOfferEditorExchangeType.NFTForXCH ? -1 : 1;
  const xchWalletId = 1;
  const driverDict = {
    [nftLauncherId]: {
      launcher_id: `0x${nftLauncherId}`,
      also: {
        metadata: '',
      },
    },
  };

  return {
    [nftLauncherId]: nftAmount,
    [xchWalletId]: mojoAmount,
    driver_dict: driverDict,
  };
}

export default function NFTOfferEditor(props: NFTOfferEditorProps) {
  const { nft, onOfferCreated } = props;
  const [createOfferForIds] = useCreateOfferForIdsMutation();
  const [isProcessing, setIsProcessing] = useState(false);
  const openDialog = useOpenDialog();
  const errorDialog = useShowError();
  const navigate = useNavigate();
  const [suppressShareOnCreate] = useLocalStorage<boolean>(
    OfferLocalStorageKeys.SUPPRESS_SHARE_ON_CREATE,
  );
  const defaultValues: NFTOfferEditorFormData = {
    exchangeType: NFTOfferEditorExchangeType.NFTForXCH,
    nftId: nft?.id ?? '',
    xchAmount: '',
    fee: '',
  };
  const methods = useForm<NFTOfferEditorFormData>({
    shouldUnregister: false,
    defaultValues,
  });

  function validateFormData(
    unvalidatedFormData: NFTOfferEditorFormData,
  ): NFTOfferEditorValidatedFormData | undefined {
    const { exchangeType, nftId, xchAmount, fee } = unvalidatedFormData;
    const nftLauncherId = nftId ? launcherIdFromNFTId(nftId) : undefined;
    let result: NFTOfferEditorValidatedFormData | undefined = undefined;

    console.log('validateFormData:');
    console.log(unvalidatedFormData);

    if (!nftId) {
      errorDialog(new Error(t`Please enter an NFT identifier`));
    } else if (!isValidNFTId(nftId)) {
      errorDialog(new Error(t`Invalid NFT identifier`));
    } else if (!nftLauncherId) {
      errorDialog(new Error(t`Failed to decode NFT identifier`));
    } else if (!xchAmount || xchAmount === '0') {
      errorDialog(new Error(t`Please enter an amount`));
    } else {
      result = {
        exchangeType,
        nftLauncherId,
        xchAmount,
        fee,
      };
    }

    return result;
  }

  async function handleSubmit(unvalidatedFormData: NFTOfferEditorFormData) {
    const formData = validateFormData(unvalidatedFormData);

    if (!formData) {
      console.log('Invalid NFT offer:');
      console.log(unvalidatedFormData);
      return;
    }

    const { exchangeType, nftLauncherId, xchAmount, fee } = formData;
    const offer = buildOfferRequest(exchangeType, nftLauncherId, xchAmount);

    console.log('offer:');
    console.log(offer);

    const confirmedCreation = await openDialog(
      <OfferEditorConfirmationDialog />,
    );

    if (!confirmedCreation) {
      return;
    }

    setIsProcessing(true);

    try {
      await new Promise((resolve) => setTimeout(resolve, 5000));
      // const response = await createOfferForIds({
      //   walletIdsAndAmounts: offer,
      //   feeInMojos: fee,
      //   validateOnly: false,
      // }).unwrap();
      const response = {
        success: true,
        error: '',
        offer: '',
        tradeRecord: {},
      };

      if (response.success === false) {
        const error =
          response.error ||
          new Error('Encountered an unknown error while creating offer');
        errorDialog(error);
      } else {
        const { offer: offerData, tradeRecord: offerRecord } = response;

        navigate(-1);

        if (!suppressShareOnCreate) {
          onOfferCreated({ offerRecord, offerData });
        }
      }
    } catch (err) {
      errorDialog(err);
    } finally {
      setIsProcessing(false);
    }
  }

  return (
    <Form methods={methods} onSubmit={handleSubmit}>
      <Flex
        flexDirection="column"
        flexGrow={1}
        gap={1}
        style={{
          border: '1px solid #E0E0E0',
          boxSizing: 'border-box',
          borderRadius: '8px',
        }}
      >
        <Flex flexDirection="row">
          <NFTOfferConditionalsPanel
            defaultValues={defaultValues}
            isProcessing={isProcessing}
          />
          <NFTOfferPreview nft={nft} />
        </Flex>
      </Flex>
    </Form>
  );
}

/* ========================================================================== */
/*                    Create and Host the NFT Offer Editor                    */
/* ========================================================================== */

type CreateNFTOfferEditorProps = {
  nft?: NFTInfo;
  referrerPath?: string;
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
};

export function CreateNFTOfferEditor(props: CreateNFTOfferEditorProps) {
  const { nft, referrerPath, onOfferCreated } = props;

  const title = <Trans>Create an NFT Offer</Trans>;
  const navElement = referrerPath ? (
    <Back variant="h5" to={referrerPath}>
      {title}
    </Back>
  ) : (
    <>{title}</>
  );

  return (
    <Grid container>
      <Flex flexDirection="column" flexGrow={1} gap={3}>
        <Flex>{navElement}</Flex>
        <NFTOfferEditor nft={nft} onOfferCreated={onOfferCreated} />
      </Flex>
    </Grid>
  );
}
