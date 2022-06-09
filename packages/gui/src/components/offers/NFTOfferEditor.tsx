import React, { useMemo, useState } from 'react';
import { useForm, useFormContext } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import BigNumber from 'bignumber.js';
import { Trans, t } from '@lingui/macro';
import { useLocalStorage } from '@rehooks/local-storage';
import type { NFTInfo } from '@chia/api';
import {
  useCreateOfferForIdsMutation,
  useGetNFTInfoQuery,
} from '@chia/api-react';
import {
  Amount,
  Back,
  Button,
  ButtonLoading,
  Fee,
  Flex,
  Form,
  FormatLargeNumber,
  StateColor,
  TextField,
  Tooltip,
  TooltipIcon,
  chiaToMojo,
  useCurrencyCode,
  useOpenDialog,
  useShowError,
} from '@chia/core';
import { Box, Divider, Grid, Tabs, Tab, Typography } from '@mui/material';
import { Warning as WarningIcon } from '@mui/icons-material';
import OfferLocalStorageKeys from './OfferLocalStorage';
import OfferEditorConfirmationDialog from './OfferEditorConfirmationDialog';
import {
  convertRoyaltyToPercentage,
  isValidNFTId,
  launcherIdFromNFTId,
} from '../../util/nfts';
import NFTOfferPreview from './NFTOfferPreview';
import styled from 'styled-components';

/* ========================================================================== */
/*              Temporary home for the NFT-specific Offer Editor              */
/*        An NFT offer consists of a single NFT being offered for XCH         */
/* ========================================================================== */

const StyledWarningIcon = styled(WarningIcon)`
  color: ${StateColor.WARNING};
`;

/* ========================================================================== */

enum NFTOfferEditorExchangeType {
  NFTForXCH = 'nft_for_xch',
  XCHForNFT = 'xch_for_nft',
}

/* ========================================================================== */

type CalculateRoyaltiesResult = {
  royaltyAmount: number;
  royaltyAmountString: string;
  nftSellerNetAmount: number;
  totalAmount: number;
  totalAmountString: string;
};

function calculateRoyalties(
  amount: number,
  makerFee: number,
  royaltyPercentage: number,
  exchangeType: NFTOfferEditorExchangeType,
): CalculateRoyaltiesResult {
  const royaltyAmount: number = royaltyPercentage
    ? (royaltyPercentage / 100) * amount
    : 0;
  const royaltyAmountString: string = formatAmount(royaltyAmount);
  const nftSellerNetAmount: number =
    exchangeType === NFTOfferEditorExchangeType.NFTForXCH
      ? amount
      : parseFloat((amount - parseFloat(royaltyAmountString)).toFixed(12));
  // : parseFloat(
  //     (amount - parseFloat(royaltyAmountString) - makerFee).toFixed(12),
  //   );
  const totalAmount: number =
    exchangeType === NFTOfferEditorExchangeType.NFTForXCH
      ? // ? amount + royaltyAmount + makerFee
        amount + royaltyAmount
      : amount + makerFee;
  // : amount;
  const totalAmountString: string = formatAmount(totalAmount);

  return {
    royaltyAmount,
    royaltyAmountString,
    nftSellerNetAmount,
    totalAmount,
    totalAmountString,
  };
}

function formatAmount(amount: number): string {
  let s = amount.toFixed(12).replace(/0+$/, '');
  if (s.endsWith('.')) {
    s = s.slice(0, -1);
  }
  return s;
}

type NFTOfferConditionalsPanelProps = {
  defaultValues: NFTOfferEditorFormData;
  isProcessing: boolean;
};

function NFTOfferConditionalsPanel(props: NFTOfferConditionalsPanelProps) {
  const { defaultValues, isProcessing } = props;
  const disabled = isProcessing;
  const methods = useFormContext();
  const currencyCode = useCurrencyCode();
  const [amountFocused, setAmountFocused] = useState<boolean>(false);

  const tab = methods.watch('exchangeType');
  const amount = methods.watch('xchAmount');
  const makerFee = methods.watch('fee');
  const nftId = methods.watch('nftId');
  const launcherId = launcherIdFromNFTId(nftId ?? '');
  const {
    data: nft,
    isLoading,
    error,
  } = useGetNFTInfoQuery({ coinId: launcherId });

  // HACK: manually determine the value for the amount field's shrink input prop.
  // Without this, toggling between the two tabs with an amount specified will cause
  // the textfield's label and value to overlap.
  const shrink = useMemo(() => {
    if (!amountFocused && (amount === undefined || amount.length === 0)) {
      return false;
    }
    return true;
  }, [amount, amountFocused]);
  const result = useMemo(() => {
    if (!nft || nft.royaltyPercentage === undefined) {
      return undefined;
    }

    const royaltyPercentage = convertRoyaltyToPercentage(nft.royaltyPercentage);

    return {
      ...calculateRoyalties(
        parseFloat(amount ? amount : '0'),
        parseFloat(makerFee ? makerFee : '0'),
        convertRoyaltyToPercentage(nft.royaltyPercentage),
        tab,
      ),
      royaltyPercentage,
    };
  }, [amount, makerFee, nft, tab]);

  const {
    royaltyPercentage,
    royaltyAmount,
    royaltyAmountString,
    nftSellerNetAmount,
    totalAmount,
    totalAmountString,
  } = result ?? {};

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
  const showRoyaltyWarning = (royaltyPercentage ?? 0) >= 20;
  const royaltyPercentageColor = showRoyaltyWarning
    ? StateColor.WARNING
    : 'textSecondary';
  const showNegativeAmountWarning = (nftSellerNetAmount ?? 0) < 0;

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
          {nft?.royaltyPercentage ? (
            <Flex flexDirection="column" gap={2}>
              <Flex flexDirection="column" gap={0.5}>
                <Flex flexDirection="row" alignItems="center" gap={1}>
                  <Typography variant="body1" color={royaltyPercentageColor}>
                    <Trans>Creator Fee ({`${royaltyPercentage}%)`}</Trans>
                  </Typography>
                  {showRoyaltyWarning && (
                    <Tooltip
                      title={
                        <Trans>Creator royalty percentage seems high</Trans>
                      }
                      interactive
                    >
                      <StyledWarningIcon fontSize="small" />
                    </Tooltip>
                  )}
                </Flex>
                {amount && (
                  <Typography variant="subtitle1">
                    <FormatLargeNumber
                      value={new BigNumber(royaltyAmountString ?? 0)}
                    />{' '}
                    {currencyCode}
                  </Typography>
                )}
              </Flex>
            </Flex>
          ) : (
            <Divider />
          )}
          <Grid item>
            <Flex flexDirection="row" gap={1}>
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
              <Flex justifyContent="center">
                <Box style={{ position: 'relative', top: '20px' }}>
                  <TooltipIcon>
                    <Trans>
                      Including a fee in the offer can help expedite the
                      transaction when the offer is accepted. The recommended
                      minimum fee is 0.000005 XCH (5,000,000 mojos)
                    </Trans>
                  </TooltipIcon>
                </Box>
              </Flex>
            </Flex>
          </Grid>
          {nft?.royaltyPercentage && amount ? (
            <Flex flexDirection="column" gap={2}>
              <>
                <Flex flexDirection="column" gap={0.5}>
                  <Typography variant="body1" color="textSecondary">
                    {tab === NFTOfferEditorExchangeType.NFTForXCH ? (
                      <Trans>You will receive</Trans>
                    ) : (
                      <Trans>They will receive</Trans>
                    )}
                  </Typography>
                  <Typography
                    variant="subtitle1"
                    color={
                      showNegativeAmountWarning ? StateColor.ERROR : 'inherit'
                    }
                  >
                    <FormatLargeNumber
                      value={new BigNumber(nftSellerNetAmount ?? 0)}
                    />{' '}
                    {currencyCode}
                  </Typography>
                  {showNegativeAmountWarning && (
                    <Typography variant="body2" color={StateColor.WARNING}>
                      <Trans>
                        Unable to create an offer where the net amount is
                        negative
                      </Trans>
                    </Typography>
                  )}
                </Flex>
                <Divider />
                <Flex flexDirection="column" gap={0.5}>
                  <Typography variant="h6">
                    {tab === NFTOfferEditorExchangeType.NFTForXCH ? (
                      <Trans>Total Amount Requested</Trans>
                    ) : (
                      <Trans>Total Amount Offered</Trans>
                    )}
                  </Typography>
                  <Typography variant="h5" fontWeight="bold">
                    <FormatLargeNumber
                      value={new BigNumber(totalAmountString ?? 0)}
                    />{' '}
                    {currencyCode}
                  </Typography>
                </Flex>
              </>
            </Flex>
          ) : null}
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
  launcherId: string;
  xchAmount: string;
  fee: string;
};

type NFTOfferEditorProps = {
  nft?: NFTInfo;
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
};

function buildOfferRequest(
  exchangeType: NFTOfferEditorExchangeType,
  nft: NFTInfo,
  nftLauncherId: string,
  xchAmount: string,
  fee: string,
) {
  const baseMojoAmount: BigNumber = chiaToMojo(xchAmount);
  const mojoAmount =
    exchangeType === NFTOfferEditorExchangeType.NFTForXCH
      ? baseMojoAmount
      : baseMojoAmount.negated();
  const feeMojoAmount = chiaToMojo(fee);
  const nftAmount =
    exchangeType === NFTOfferEditorExchangeType.NFTForXCH ? -1 : 1;
  const xchWalletId = 1;
  const driverDict = {
    [nftLauncherId]: {
      type: 'singleton',
      launcher_id: `0x${nftLauncherId}`,
      launcher_ph: nft.launcherPuzhash,
      also: {
        type: 'metadata',
        metadata: nft.chainInfo,
        updater_hash: nft.updaterPuzhash,
      },
    },
  };

  return [
    {
      [nftLauncherId]: nftAmount,
      [xchWalletId]: mojoAmount,
    },
    driverDict,
    feeMojoAmount,
  ];
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
    nftId: nft?.$nftId ?? '',
    xchAmount: '',
    fee: '',
  };
  const methods = useForm<NFTOfferEditorFormData>({
    shouldUnregister: false,
    defaultValues,
  });
  const nftId = methods.watch('nftId');
  const launcherId = launcherIdFromNFTId(nftId ?? '');
  const {
    data: queriedNFTInfo,
    isLoading,
    error,
  } = useGetNFTInfoQuery({ coinId: launcherId });

  function validateFormData(
    unvalidatedFormData: NFTOfferEditorFormData,
  ): NFTOfferEditorValidatedFormData | undefined {
    const { exchangeType, nftId, xchAmount, fee } = unvalidatedFormData;
    let result: NFTOfferEditorValidatedFormData | undefined = undefined;

    if (!nftId) {
      errorDialog(new Error(t`Please enter an NFT identifier`));
    } else if (!isValidNFTId(nftId)) {
      errorDialog(new Error(t`Invalid NFT identifier`));
    } else if (!launcherId) {
      errorDialog(new Error(t`Failed to decode NFT identifier`));
    } else if (!xchAmount || xchAmount === '0') {
      errorDialog(new Error(t`Please enter an amount`));
    } else {
      result = {
        exchangeType,
        launcherId,
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

    const offerNFT = nft || queriedNFTInfo;

    if (!offerNFT) {
      errorDialog(new Error(t`NFT details not available`));
      return;
    }

    const { exchangeType, launcherId, xchAmount, fee } = formData;

    const royaltyPercentage = convertRoyaltyToPercentage(
      offerNFT.royaltyPercentage ?? 0,
    );

    if (royaltyPercentage > 100) {
      errorDialog(
        new Error(
          t`Unable to create an offer for an NFT with a creator royalty percentage greater than 100%`,
        ),
      );
      return;
    }

    const [offer, driverDict, feeInMojos] = buildOfferRequest(
      exchangeType,
      offerNFT,
      launcherId,
      xchAmount,
      fee,
    );

    const confirmedCreation = await openDialog(
      <OfferEditorConfirmationDialog />,
    );

    if (!confirmedCreation) {
      return;
    }

    setIsProcessing(true);

    try {
      const response = await createOfferForIds({
        walletIdsAndAmounts: offer,
        feeInMojos,
        driverDict,
        validateOnly: false,
        disableJSONFormatting: true,
      }).unwrap();

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
          <NFTOfferPreview nftId={nftId} />
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
