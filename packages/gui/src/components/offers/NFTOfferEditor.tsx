import React, { useMemo, useState } from 'react';
import { useForm, useFormContext } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import BigNumber from 'bignumber.js';
import { Trans, t } from '@lingui/macro';
import { useLocalStorage } from '@rehooks/local-storage';
import { WalletType } from '@chia/api';
import type { NFTInfo, Wallet } from '@chia/api';
import {
  useCreateOfferForIdsMutation,
  useGetNFTInfoQuery,
  useGetNFTWallets,
  useGetWalletBalanceQuery,
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
  catToMojo,
  chiaToMojo,
  mojoToCAT,
  mojoToCATLocaleString,
  mojoToChia,
  mojoToChiaLocaleString,
  useColorModeValue,
  useCurrencyCode,
  useLocale,
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
import NFTOfferTokenSelector from './NFTOfferTokenSelector';

/* ========================================================================== */
/*              Temporary home for the NFT-specific Offer Editor              */
/*       An NFT offer consists of a single NFT being offered for XCH/CAT      */
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
  const [locale] = useLocale();
  const [amountFocused, setAmountFocused] = useState<boolean>(false);
  const [makerFeeFocused, setMakerFeeFocused] = useState<boolean>(false);

  const tab = methods.watch('exchangeType');
  const tokenWalletInfo = methods.watch('tokenWalletInfo');
  const amount = methods.watch('tokenAmount');
  const makerFee = methods.watch('fee');
  const nftId = methods.watch('nftId');
  const launcherId = launcherIdFromNFTId(nftId ?? '');
  const { data: nft } = useGetNFTInfoQuery({ coinId: launcherId });
  const { data: walletBalance, isLoading: isLoadingWalletBalance } =
    useGetWalletBalanceQuery(
      {
        walletId: tokenWalletInfo.walletId,
      },
      {
        skip: tab !== NFTOfferExchangeType.TokenForNFT,
      },
    );

  const spendableBalanceString: string | undefined = useMemo(() => {
    let balanceString: string | undefined;
    let balance = new BigNumber(0);

    if (
      !isLoadingWalletBalance &&
      tab === NFTOfferExchangeType.TokenForNFT &&
      walletBalance &&
      walletBalance.walletId == tokenWalletInfo.walletId
    ) {
      switch (tokenWalletInfo.walletType) {
        case WalletType.STANDARD_WALLET:
          balanceString = mojoToChiaLocaleString(
            walletBalance.spendableBalance,
            locale,
          );
          balance = mojoToChia(walletBalance.spendableBalance);
          break;
        case WalletType.CAT:
          balanceString = mojoToCATLocaleString(
            walletBalance.spendableBalance,
            locale,
          );
          balance = mojoToCAT(walletBalance.spendableBalance);
          break;
        default:
          break;
      }
    }

    if (
      balanceString !== tokenWalletInfo.spendableBalanceString ||
      !balance.isEqualTo(tokenWalletInfo.spendableBalance)
    ) {
      tokenWalletInfo.spendableBalanceString = balanceString;
      tokenWalletInfo.spendableBalance = balance;

      methods.setValue('tokenWalletInfo', tokenWalletInfo);
    }

    return balanceString;
  }, [tokenWalletInfo.walletId, walletBalance, isLoadingWalletBalance, locale]);

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
    const includedMakerFee =
      tokenWalletInfo.walletType === WalletType.STANDARD_WALLET ? makerFee : 0;

    return {
      ...calculateNFTRoyalties(
        parseFloat(amount ? amount : '0'),
        parseFloat(includedMakerFee ? includedMakerFee : '0'),
        convertRoyaltyToPercentage(nft.royaltyPercentage),
        tab,
      ),
      royaltyPercentage,
    };
  }, [amount, makerFee, nft, tokenWalletInfo, tab]);

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
    <Flex flexDirection="row" gap={2}>
      <Grid xs={6} item>
        <Flex flexDirection="column" gap={1}>
          <Amount
            id={`${tab}-amount}`}
            key={`${tab}-amount}`}
            variant="filled"
            name="tokenAmount"
            color="secondary"
            disabled={disabled}
            label={<Trans>Amount</Trans>}
            defaultValue={amount}
            symbol={tokenWalletInfo.symbol ?? ''}
            onChange={handleAmountChange}
            onFocus={() => setAmountFocused(true)}
            onBlur={() => setAmountFocused(false)}
            showAmountInMojos={true}
            InputLabelProps={{ shrink: shrinkAmount }}
            autoFocus
            required
            fullWidth
          />
          {tab === NFTOfferExchangeType.TokenForNFT && (
            <Flex flexDirection="row" alignItems="center" gap={1}>
              <Typography variant="body2">Spendable balance: </Typography>
              {spendableBalanceString === undefined ? (
                <Typography variant="body2">Loading...</Typography>
              ) : (
                <Typography variant="body2">
                  {spendableBalanceString}
                </Typography>
              )}
            </Flex>
          )}
        </Flex>
      </Grid>
      <Grid xs={6} item>
        <NFTOfferTokenSelector
          selectedWalletId={tokenWalletInfo.walletId}
          id="tokenWalletId"
          onChange={(selection) =>
            handleTokenSelectionChanged(
              selection.walletId,
              selection.walletType,
              selection.symbol,
              selection.name,
            )
          }
        />
      </Grid>
    </Flex>
  );
  const offerElem =
    tab === NFTOfferExchangeType.NFTForToken ? nftElem : amountElem;
  const takerElem =
    tab === NFTOfferExchangeType.NFTForToken ? amountElem : nftElem;
  const showRoyaltyWarning = (royaltyPercentage ?? 0) >= 20;
  const royaltyPercentageColor = showRoyaltyWarning
    ? StateColor.WARNING
    : 'textSecondary';
  const showNegativeAmountWarning = (nftSellerNetAmount ?? 0) < 0;

  function handleAmountChange(amount: string) {
    methods.setValue('tokenAmount', amount);
  }

  function handleFeeChange(fee: string) {
    methods.setValue('fee', fee);
  }

  function handleTokenSelectionChanged(
    walletId: number,
    walletType: WalletType,
    symbol?: string,
    name?: string,
  ) {
    methods.setValue('tokenWalletInfo', { walletId, walletType, symbol, name });
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
          value={NFTOfferExchangeType.TokenForNFT}
          label={<Trans>Buy an NFT</Trans>}
          disabled={disabled}
        />
        <Tab
          value={NFTOfferExchangeType.NFTForToken}
          label={<Trans>Sell an NFT</Trans>}
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
                    {tokenWalletInfo.symbol ?? tokenWalletInfo.name ?? ''}
                  </Typography>
                )}
              </Flex>
            </Flex>
          ) : null}
          {tab === NFTOfferExchangeType.TokenForNFT && (
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
                    {tab === NFTOfferExchangeType.NFTForToken ? (
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
                    {tokenWalletInfo.symbol ?? tokenWalletInfo.name ?? ''}
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
                      {tab === NFTOfferExchangeType.NFTForToken ? (
                        <Trans>Total Amount Requested</Trans>
                      ) : (
                        <Trans>Total Amount Offered</Trans>
                      )}
                    </Typography>
                    <Flex justifyContent="center">
                      <TooltipIcon>
                        {tab === NFTOfferExchangeType.NFTForToken ? (
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
                    {tokenWalletInfo.symbol ?? tokenWalletInfo.name ?? ''}
                    {tab === NFTOfferExchangeType.TokenForNFT &&
                      tokenWalletInfo.walletType !==
                        WalletType.STANDARD_WALLET &&
                      makerFee > 0 && (
                        <div>
                          <FormatLargeNumber
                            value={new BigNumber(makerFee ?? 0)}
                          />
                          {' XCH'}
                        </div>
                      )}
                  </Typography>
                </Flex>
              </>
            </Flex>
          ) : null}
          {tab === NFTOfferExchangeType.NFTForToken && (
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
/*           Currently only supports a single NFT <--> XCH/CAT offer          */
/* ========================================================================== */

export type NFTOfferEditorTokenWalletInfo = {
  walletId: number;
  walletType: WalletType;
  symbol?: string;
  name?: string;
  spendableBalance?: BigNumber;
  spendableBalanceString?: string;
};

type NFTOfferEditorFormData = {
  exchangeType: NFTOfferExchangeType;
  nftId?: string;
  tokenWalletInfo: NFTOfferEditorTokenWalletInfo;
  tokenAmount: string;
  fee: string;
};

type NFTOfferEditorValidatedFormData = {
  exchangeType: NFTOfferExchangeType;
  launcherId: string;
  tokenWalletInfo: NFTOfferEditorTokenWalletInfo;
  tokenAmount: string;
  fee: string;
};

type NFTOfferEditorProps = {
  nft?: NFTInfo;
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
  exchangeType: NFTOfferExchangeType;
};

type NFTBuildOfferRequestParams = {
  exchangeType: NFTOfferExchangeType;
  nft: NFTInfo;
  nftLauncherId: string;
  tokenWalletInfo: NFTOfferEditorTokenWalletInfo;
  tokenAmount: string;
  fee: string;
};

function buildOfferRequest(params: NFTBuildOfferRequestParams) {
  const {
    exchangeType,
    nft,
    nftLauncherId,
    tokenWalletInfo,
    tokenAmount,
    fee,
  } = params;
  const baseMojoAmount: BigNumber =
    tokenWalletInfo.walletType === WalletType.CAT
      ? catToMojo(tokenAmount)
      : chiaToMojo(tokenAmount);
  const mojoAmount =
    exchangeType === NFTOfferExchangeType.NFTForToken
      ? baseMojoAmount
      : baseMojoAmount.negated();
  const feeMojoAmount = chiaToMojo(fee);
  const nftAmount = exchangeType === NFTOfferExchangeType.NFTForToken ? -1 : 1;
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
      [tokenWalletInfo.walletId]: mojoAmount,
    },
    exchangeType === NFTOfferExchangeType.TokenForNFT ? driverDict : undefined,
    feeMojoAmount,
  ];
}

export default function NFTOfferEditor(props: NFTOfferEditorProps) {
  const { nft, onOfferCreated, exchangeType } = props;
  const [createOfferForIds] = useCreateOfferForIdsMutation();
  const [isProcessing, setIsProcessing] = useState(false);
  const { wallets: nftWallets } = useGetNFTWallets();
  const { nfts } = useFetchNFTs(nftWallets.map((wallet: Wallet) => wallet.id));
  const currencyCode = useCurrencyCode();
  const openDialog = useOpenDialog();
  const errorDialog = useShowError();
  const navigate = useNavigate();
  const theme = useTheme();
  const [suppressShareOnCreate] = useLocalStorage<boolean>(
    OfferLocalStorageKeys.SUPPRESS_SHARE_ON_CREATE,
  );
  const defaultValues: NFTOfferEditorFormData = {
    exchangeType: exchangeType,
    nftId: nft?.$nftId ?? '',
    tokenWalletInfo: {
      walletId: 1,
      walletType: WalletType.STANDARD_WALLET,
      symbol: currencyCode,
      name: 'Chia',
      spendableBalance: new BigNumber(0),
    },
    tokenAmount: '',
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
    const { exchangeType, nftId, tokenWalletInfo, tokenAmount, fee } =
      unvalidatedFormData;
    let result: NFTOfferEditorValidatedFormData | undefined = undefined;

    if (!nftId) {
      errorDialog(new Error(t`Please enter an NFT identifier`));
    } else if (!isValidNFTId(nftId)) {
      errorDialog(new Error(t`Invalid NFT identifier`));
    } else if (!launcherId) {
      errorDialog(new Error(t`Failed to decode NFT identifier`));
    } else if (!tokenWalletInfo?.walletId) {
      errorDialog(new Error(t`Please select an asset type`));
    } else if (!tokenAmount || tokenAmount === '0') {
      errorDialog(new Error(t`Please enter an amount`));
    } else if (
      exchangeType === NFTOfferExchangeType.TokenForNFT &&
      tokenWalletInfo.spendableBalance?.isLessThan(tokenAmount)
    ) {
      errorDialog(new Error(t`Amount exceeds spendable balance`));
    } else {
      result = {
        exchangeType,
        launcherId,
        tokenWalletInfo,
        tokenAmount,
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

    const { exchangeType, launcherId, tokenWalletInfo, tokenAmount, fee } =
      formData;

    if (exchangeType === NFTOfferExchangeType.NFTForToken) {
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

    const [offer, driverDict, feeInMojos] = buildOfferRequest({
      exchangeType,
      nft: offerNFT,
      nftLauncherId: launcherId,
      tokenWalletInfo,
      tokenAmount,
      fee,
    });

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
  exchangeType?: NFTOfferExchangeType;
  referrerPath?: string;
  onOfferCreated: (obj: { offerRecord: any; offerData: any }) => void;
};

export function CreateNFTOfferEditor(props: CreateNFTOfferEditorProps) {
  const {
    nft,
    exchangeType = NFTOfferExchangeType.TokenForNFT,
    referrerPath,
    onOfferCreated,
  } = props;

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
        <NFTOfferEditor
          nft={nft}
          onOfferCreated={onOfferCreated}
          exchangeType={exchangeType}
        />
      </Flex>
    </Grid>
  );
}
