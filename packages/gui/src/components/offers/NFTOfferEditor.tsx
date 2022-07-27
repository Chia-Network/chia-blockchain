import React, { useMemo, useState } from 'react';
import { useForm, useFormContext } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import BigNumber from 'bignumber.js';
import { Trans, t } from '@lingui/macro';
import { useLocalStorage } from '@rehooks/local-storage';
import type { NFTInfo, Wallet } from '@chia/api';
import {
  useCreateOfferForIdsMutation,
  useGetNFTInfoQuery,
  useGetNFTWallets,
} from '@chia/api-react';
import {
  Amount,
  AmountProps,
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
  useColorModeValue,
  useCurrencyCode,
  useOpenDialog,
  useShowError,
} from '@chia/core';
import {
  Box,
  Divider,
  Grid,
  Tabs,
  Tab,
  Typography,
  useTheme,
} from '@mui/material';
import { Warning as WarningIcon } from '@mui/icons-material';
import OfferLocalStorageKeys from './OfferLocalStorage';
import OfferEditorConfirmationDialog from './OfferEditorConfirmationDialog';
import {
  convertRoyaltyToPercentage,
  isValidNFTId,
  launcherIdFromNFTId,
} from '../../util/nfts';
import { calculateNFTRoyalties } from './utils';
import useFetchNFTs from '../../hooks/useFetchNFTs';
import NFTOfferPreview from './NFTOfferPreview';
import NFTOfferExchangeType from './NFTOfferExchangeType';
import styled from 'styled-components';

/* ========================================================================== */
/*              Temporary home for the NFT-specific Offer Editor              */
/*        An NFT offer consists of a single NFT being offered for XCH         */
/* ========================================================================== */

const StyledWarningIcon = styled(WarningIcon)`
  color: ${StateColor.WARNING};
`;

/* ========================================================================== */

type NFTOfferCreationFeeProps = AmountProps & {
  disabled?: boolean;
  onChange?: (fee: string) => void;
  defaultValue?: string;
};

function NFTOfferCreationFee(props: NFTOfferCreationFeeProps) {
  const { disabled = true, onChange, defaultValue = '', ...rest } = props;

  return (
    <Flex flexDirection="column" gap={1}>
      <Grid item>
        <Flex flexDirection="row" gap={1}>
          <Fee
            id="fee"
            variant="filled"
            name="fee"
            color="secondary"
            disabled={disabled}
            onChange={onChange}
            defaultValue={defaultValue}
            label={<Trans>Fee (Optional)</Trans>}
            {...rest}
          />
          <Box style={{ position: 'relative', top: '20px' }}>
            <TooltipIcon>
              <Trans>
                Including a fee in the offer can help expedite the transaction
                when the offer is accepted. The recommended minimum fee is
                0.000005 XCH (5,000,000 mojos)
              </Trans>
            </TooltipIcon>
          </Box>
        </Flex>
      </Grid>
    </Flex>
  );
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
  const currencyCode = useCurrencyCode();
  const [amountFocused, setAmountFocused] = useState<boolean>(false);
  const [makerFeeFocused, setMakerFeeFocused] = useState<boolean>(false);

  const tab = methods.watch('exchangeType');
  const amount = methods.watch('xchAmount');
  const makerFee = methods.watch('fee');
  const nftId = methods.watch('nftId');
  const launcherId = launcherIdFromNFTId(nftId ?? '');
  const { data: nft } = useGetNFTInfoQuery({ coinId: launcherId });

  // HACK: manually determine the value for the amount field's shrink input prop.
  // Without this, toggling between the two tabs with an amount specified will cause
  // the textfield's label and value to overlap.
  const shrinkAmount = useMemo(() => {
    if (!amountFocused && (amount === undefined || amount.length === 0)) {
      return false;
    }
    return true;
  }, [amount, amountFocused]);
  const shrinkMakerFee = useMemo(() => {
    if (!makerFeeFocused && (makerFee === undefined || makerFee.length === 0)) {
      return false;
    }
    return true;
  }, [makerFee, makerFeeFocused]);
  const result = useMemo(() => {
    if (!nft || nft.royaltyPercentage === undefined) {
      return undefined;
    }

    const royaltyPercentage = convertRoyaltyToPercentage(nft.royaltyPercentage);

    return {
      ...calculateNFTRoyalties(
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
    royaltyAmountString,
    nftSellerNetAmount,
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
        InputLabelProps={{ shrink: shrinkAmount }}
        required
      />
    </Grid>
  );
  const offerElem =
    tab === NFTOfferExchangeType.NFTForXCH ? nftElem : amountElem;
  const takerElem =
    tab === NFTOfferExchangeType.NFTForXCH ? amountElem : nftElem;
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

  const makerFeeElem = (
    <NFTOfferCreationFee
      disabled={disabled}
      onChange={handleFeeChange}
      defaultValue={defaultValues.fee}
      onFocus={() => setMakerFeeFocused(true)}
      onBlur={() => setMakerFeeFocused(false)}
      InputLabelProps={{ shrink: shrinkMakerFee }}
    />
  );

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
          value={NFTOfferExchangeType.NFTForXCH}
          label={<Trans>NFT for XCH</Trans>}
          disabled={disabled}
        />
        <Tab
          value={NFTOfferExchangeType.XCHForNFT}
          label={<Trans>XCH for NFT</Trans>}
          disabled={disabled}
        />
      </Tabs>
      <Grid container>
        <Flex flexDirection="column" flexGrow={1} gap={3}>
          <Flex flexDirection="column" gap={1}>
            <Typography variant="subtitle1" color="textSecondary">
              You will offer
            </Typography>
            {offerElem}
          </Flex>
          <Flex flexDirection="column" gap={1}>
            <Typography variant="subtitle1" color="textSecondary">
              In exchange for
            </Typography>
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
                  <Typography variant="subtitle1" color="textSecondary">
                    <FormatLargeNumber
                      value={new BigNumber(royaltyAmountString ?? 0)}
                    />{' '}
                    {currencyCode}
                  </Typography>
                )}
              </Flex>
            </Flex>
          ) : null}
          {tab === NFTOfferExchangeType.XCHForNFT && (
            <Flex flexDirection="column" gap={2}>
              {!nft?.royaltyPercentage && <Divider />}
              {makerFeeElem}
            </Flex>
          )}
          {nft?.royaltyPercentage && amount ? (
            <Flex flexDirection="column" gap={2}>
              <>
                <Flex flexDirection="column" gap={0.5}>
                  <Typography variant="body1" color="textSecondary">
                    {tab === NFTOfferExchangeType.NFTForXCH ? (
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
                    <Typography variant="body2" color={StateColor.ERROR}>
                      <Trans>
                        Unable to create an offer where the net amount is
                        negative
                      </Trans>
                    </Typography>
                  )}
                </Flex>
                <Divider />
                <Flex flexDirection="column" gap={0.5}>
                  <Flex flexDirection="row" alignItems="center" gap={1}>
                    <Typography variant="h6" color="textSecondary">
                      {tab === NFTOfferExchangeType.NFTForXCH ? (
                        <Trans>Total Amount Requested</Trans>
                      ) : (
                        <Trans>Total Amount Offered</Trans>
                      )}
                    </Typography>
                    <Flex justifyContent="center">
                      <TooltipIcon>
                        {tab === NFTOfferExchangeType.NFTForXCH ? (
                          <Trans>
                            The total amount requested includes the asking
                            price, plus the associated creator fees (if the NFT
                            has royalty payments enabled). Creator fees will be
                            paid by the party that accepts the offer.
                            <p />
                            The optional offer creation fee is not included in
                            this total, and will be deducted from your spendable
                            balance upon offer creation.
                          </Trans>
                        ) : (
                          <Trans>
                            The total amount offered includes the price
                            you&apos;re willing to pay for the NFT, plus the
                            optional offer creation fee. One or more coins
                            totalling at least the amount shown below will be
                            deducted from your spendable balance upon offer
                            creation.
                            <p />
                            If the NFT has royalty payments enabled, those
                            creator fees will be paid by the party that accepts
                            the offer.
                          </Trans>
                        )}
                      </TooltipIcon>
                    </Flex>
                  </Flex>
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
          {tab === NFTOfferExchangeType.NFTForXCH && (
            <Flex flexDirection="column" gap={2}>
              <Divider />
              {makerFeeElem}
            </Flex>
          )}
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
  exchangeType: NFTOfferExchangeType;
  nftId?: string;
  xchAmount: string;
  fee: string;
};

type NFTOfferEditorValidatedFormData = {
  exchangeType: NFTOfferExchangeType;
  launcherId: string;
  xchAmount: string;
  fee: string;
};

type NFTOfferEditorProps = {
  nft?: NFTInfo;
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
};

function buildOfferRequest(
  exchangeType: NFTOfferExchangeType,
  nft: NFTInfo,
  nftLauncherId: string,
  xchAmount: string,
  fee: string,
) {
  const baseMojoAmount: BigNumber = chiaToMojo(xchAmount);
  const mojoAmount =
    exchangeType === NFTOfferExchangeType.NFTForXCH
      ? baseMojoAmount
      : baseMojoAmount.negated();
  const feeMojoAmount = chiaToMojo(fee);
  const nftAmount = exchangeType === NFTOfferExchangeType.NFTForXCH ? -1 : 1;
  const xchWalletId = 1;
  const innerAlsoDict = nft.supportsDid
    ? {
        type: 'ownership',
        owner: '()',
        transfer_program: {
          type: 'royalty transfer program',
          launcher_id: `0x${nftLauncherId}`,
          royalty_address: nft.royaltyPuzzleHash,
          royalty_percentage: `${nft.royaltyPercentage}`,
        },
      }
    : undefined;
  const outerAlsoDict = {
    type: 'metadata',
    metadata: nft.chainInfo,
    updater_hash: nft.updaterPuzhash,
    ...(innerAlsoDict ? { also: innerAlsoDict } : undefined),
  };
  const driverDict = {
    [nftLauncherId]: {
      type: 'singleton',
      launcher_id: `0x${nftLauncherId}`,
      launcher_ph: nft.launcherPuzhash,
      also: outerAlsoDict,
    },
  };

  return [
    {
      [nftLauncherId]: nftAmount,
      [xchWalletId]: mojoAmount,
    },
    exchangeType === NFTOfferExchangeType.XCHForNFT ? driverDict : undefined,
    // driverDict,
    feeMojoAmount,
  ];
}

export default function NFTOfferEditor(props: NFTOfferEditorProps) {
  const { nft, onOfferCreated } = props;
  const [createOfferForIds] = useCreateOfferForIdsMutation();
  const [isProcessing, setIsProcessing] = useState(false);
  const { wallets: nftWallets } = useGetNFTWallets();
  const { nfts } = useFetchNFTs(
    nftWallets.map((wallet: Wallet) => wallet.id),
  );
  const openDialog = useOpenDialog();
  const errorDialog = useShowError();
  const navigate = useNavigate();
  const theme = useTheme();
  const [suppressShareOnCreate] = useLocalStorage<boolean>(
    OfferLocalStorageKeys.SUPPRESS_SHARE_ON_CREATE,
  );
  const defaultValues: NFTOfferEditorFormData = {
    exchangeType: NFTOfferExchangeType.NFTForXCH,
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
  const { data: queriedNFTInfo } = useGetNFTInfoQuery({ coinId: launcherId });

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

    if (exchangeType === NFTOfferExchangeType.NFTForXCH) {
      const haveNFT =
        nfts.find((nft: NFTInfo) => nft.$nftId === offerNFT.$nftId) !==
        undefined;

      if (!haveNFT) {
        errorDialog(
          new Error(
            t`Unable to create an offer for an NFT that you do not own.`,
          ),
        );
        return;
      }
    }

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
        sx={{
          border: `1px solid ${useColorModeValue(theme, 'border')}`,
          borderRadius: '4px',
          bgcolor: 'background.paper',
          boxShadow:
            '0px 2px 1px -1px rgb(0 0 0 / 20%), 0px 1px 1px 0px rgb(0 0 0 / 14%), 0px 1px 3px 0px rgb(0 0 0 / 12%)',
          overflow: 'hidden',
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
