/* eslint-disable */module.exports={languageData:{"plurals":function(n,ord){var s=String(n).split("."),v0=!s[1],t0=Number(s[0])==n,n10=t0&&s[0].slice(-1),n100=t0&&s[0].slice(-2);if(ord)return n10==1&&n100!=11?"one":n10==2&&n100!=12?"two":n10==3&&n100!=13?"few":"other";return n==1&&v0?"one":"other"}},messages:{"AddressCard.address":"Address","AddressCard.copy":"Copy","AddressCard.newAddress":"New Address","AddressCard.title":"Receive Address","Application.closing":"Closing down node and server","Application.connectingToWallet":"Connecting to wallet","Application.loggingIn":"Logging in","BalanceCard.balance":"Balance","BalanceCard.pendingBalance":"Pending Balance","BalanceCard.pendingBalanceTooltip":"This is the sum of the incoming and outgoing pending transactions (not yet included into the blockchain). This does not include farming rewards.","BalanceCard.pendingChange":"Pending Change","BalanceCard.pendingChangeTooltip":"This is the pending change, which are change coins which you have sent to yourself, but have not been confirmed yet.","BalanceCard.pendingFarmingRewards":"Pending Farming Rewards","BalanceCard.pendingFarmingRewardsTooltip":"This is the total amount of farming rewards farmed recently, that have been confirmed but are not yet spendable. Farming rewards are frozen for 200 blocks.","BalanceCard.pendingTotalBalance":"Pending Total Balance","BalanceCard.pendingTotalBalanceTooltip":"This is the total balance + pending balance: it it what your balance will be after all pending transactions are confirmed.","BalanceCard.spendableBalance":"Spendable Balance","BalanceCard.spendableBalanceTooltip":"This is the amount of Chia that you can currently use to make transactions. It does not include pending farming rewards, pending incoming transctions, and Chia that you have just spent but is not yet in the blockchain.","BalanceCard.totalBalance":"Total Balance","BalanceCard.totalBalanceTooltip":"This is the total amount of Chia in the blockchain at the LCA block (latest common ancestor) that is controlled by your private keys. It includes frozen farming rewards, but not pending incoming and outgoing transactions.","BalanceCard.viewPendingBalances":"View pending balances","Block.blockVDFIterations":"Block VDF Iterations","Block.blockVDFIterationsTooltip":"The total number of VDF (verifiable delay function) or proof of time iterations on this block.","Block.coinbaseAmount":"Coinbase Amount","Block.coinbaseAmountTooltip":"The Chia block reward, goes to the pool (or farmer if not pooling)","Block.coinbasePuzzleHash":"Coinbase Puzzle Hash","Block.description":function(a){return["Block at height ",a("0")," in the Chia blockchain"]},"Block.difficulty":"Difficulty","Block.feesAmount":"Fees Amount","Block.feesAmountTooltip":"The total fees in this block, goes to the farmer","Block.feesPuzzleHash":"Fees Puzzle Hash","Block.headerHash":"Header hash","Block.height":"Height","Block.plotId":"Plot Id","Block.plotIdTooltip":"The seed used to create the plot, this depends on the pool pk and plot pk","Block.plotPublicKey":"Plot Public Key","Block.poolPublicKey":"Pool Public Key","Block.previousBlock":"Previous block","Block.proofOfSpaceSize":"Proof of Space Size","Block.timestamp":"Timestamp","Block.timestampTooltip":"This is the time the block was created by the farmer, which is before it is finalized with a proof of time","Block.title":"Block","Block.totalVDFIterations":"Total VDF Iterations","Block.totalVDFIterationsTooltip":"The total number of VDF (verifiable delay function) or proof of time iterations on the whole chain up to this block.","Block.transactionsFilterHash":"Transactions Filter Hash","Block.transactionsGeneratorHash":"Transactions Generator Hash","Block.weight":"Weight","Block.weightTooltip":"Weight is the total added difficulty of all blocks up to and including this one","BlocksCard.expectedFinishTime":"Expected finish time","BlocksCard.headerHash":"Header Hash","BlocksCard.height":"Height","BlocksCard.timeCreated":"Time Created","BlocksCard.title":"Blocks","CCListItems.title":"Coloured Coin Options","Challenges.bestEstimate":"Best estimate","Challenges.challengeHash":"Challenge hash","Challenges.height":"Height","Challenges.numberOfProofs":"Number of proofs","Challenges.title":"Challenges","ColourCard.colour":"Colour:","ColourCard.nickname":"Nickname","ColourCard.rename":"Rename","ColourCard.title":"Colour Info","ColouredAddressCard.address":"Address","ColouredAddressCard.copy":"Copy","ColouredAddressCard.newAddress":"New Address","ColouredAddressCard.title":"Receive Addresss","ColouredBalanceCard.spendableBalance":"Spendable Balance","ColouredBalanceCard.title":"Balance","ColouredBalanceCard.totalBalance":"Total Balance","ColouredBalanceCard.viewPendingBalances":"View pending balances...","ColouredHistoryCard.title":"History","ColouredSendCard.address":"Address","ColouredSendCard.amount":function(a){return["Amount (",a("cc_unit"),")"]},"ColouredSendCard.farm":"Farm","ColouredSendCard.fee":"Fee (TXCH)","ColouredSendCard.send":"Send","ColouredSendCard.title":"Create Transaction","ColouredTransactionTable.amount":"Amount","ColouredTransactionTable.confirmed":"Confirmed","ColouredTransactionTable.date":"Date","ColouredTransactionTable.fee":"Fee","ColouredTransactionTable.incoming":"Incoming","ColouredTransactionTable.noPreviousTransactions":"No previous transactions","ColouredTransactionTable.outgoing":"Outgoing","ColouredTransactionTable.pending":"Pending","ColouredTransactionTable.status":"Status","ColouredTransactionTable.to":"To","ColouredTransactionTable.type":"Type","Connections.connect":"Connect","Connections.connectToOtherPeersTitle":"Connect to other peers","Connections.connected":"Connected","Connections.connectionType":"Connection type","Connections.delete":"Delete","Connections.ipAddress":"Ip address","Connections.ipAddressHost":"Ip address / host","Connections.lastMessage":"Last message","Connections.nodeId":"Node Id","Connections.port":"Port","Connections.title":"Connections","Connections.upDown":"Up/Down","CreateExistingCCWallet.colourString":"Colour String","CreateExistingCCWallet.create":"Create","CreateExistingCCWallet.enterValidFee":"Please enter a valid numeric fee","CreateExistingCCWallet.fee":"Fee","CreateExistingCCWallet.title":"Create wallet for colour","CreateNewCCWallet.amount":"Amount","CreateNewCCWallet.create":"Create","CreateNewCCWallet.enterValidAmount":"Please enter a valid numeric amount","CreateNewCCWallet.enterValidFee":"Please enter a valid numeric fee","CreateNewCCWallet.fee":"Fee","CreateNewCCWallet.generateNewColour":"Generate New Colour","CreateOffer.add":"Add","CreateOffer.addTradePair":"Please add trade pair","CreateOffer.amount":"Amount","CreateOffer.availableOnlyFromElectron":"This feature is available only from electron app","CreateOffer.buyOrSell":"Buy Or Sell","CreateOffer.cancel":"Cancel","CreateOffer.colour":"Colour","CreateOffer.save":"Save","CreateOffer.selectAmount":"Please select amount","CreateOffer.selectBuyOrSell":"Please select buy or sell","CreateOffer.selectCoinType":"Please select coin type","CreateOffer.title":"Create Trade Offer","CreatePlot.colour":"Colour","CreatePlot.create":"Create","CreatePlot.description":"Using this tool, you can create plots, which are allocated space on your hard drive used to farm and earn Chia. Also, temporary files are created during the plotting process, which exceed the size of the final plot files, so make sure you have enough space. Try to use a fast drive like an SSD for the temporary folder, and a large slow hard drive (like external HDD) for the final folder.","CreatePlot.numberOfBuckets":"Number of buckets","CreatePlot.numberOfBucketsDescription":"0 automatically chooses bucket count","CreatePlot.numberOfThreads":"Number of threads","CreatePlot.plotCount":"Plot Count","CreatePlot.plotSize":"Plot Size","CreatePlot.ramMaxUsage":"RAM max usage","CreatePlot.ramMaxUsageDescription":"More memory slightly increases speed","CreatePlot.specifyFinalDirectory":"Please specify a temporary and final directory","CreatePlot.stripeSize":"Stripe Size","CreatePlot.title":"Create Plot","CreateRLAdminWallet.amountForInitialCoin":"Amount For Initial Coin","CreateRLAdminWallet.create":"Create","CreateRLAdminWallet.createRateLimitedAdminWallet":"Create Rate Limited Admin Wallet","CreateRLAdminWallet.enterValidInitialCoin":"Please enter a valid initial coin amount","CreateRLAdminWallet.enterValidNumericFee":"Please enter a valid numeric fee","CreateRLAdminWallet.enterValidNumericInterval":"Please enter a valid numeric interval length","CreateRLAdminWallet.enterValidPubkey":"Please enter a valid pubkey","CreateRLAdminWallet.enterValidSpendableAmount":"Please enter a valid numeric spendable amount","CreateRLAdminWallet.fee":"Fee","CreateRLAdminWallet.initialAmount":"Initial Amount","CreateRLAdminWallet.interval":"Interval","CreateRLAdminWallet.pubkey":"Pubkey","CreateRLAdminWallet.spendableAmount":"Spendable Amount","CreateRLAdminWallet.spendableAmountPerInterval":"Spendable Amount Per Interval","CreateRLAdminWallet.spendingIntervalLength":"Spending Interval Length (number of blocks)","CreateRLAdminWallet.userPubkey":"User Pubkey","CreateRLUserWallet.create":"Create","CreateRLUserWallet.description":"Initialize a Rate Limited User Wallet:","CreateRLUserWallet.title":"Create Rate Limited User Wallet","CreateWallet.addWallet":"Add Wallet","DashboardSideBar.farm":"Farm","DashboardSideBar.home":"Full Node","DashboardSideBar.keys":"Keys","DashboardSideBar.plot":"Plot","DashboardSideBar.trade":"Trade","DashboardSideBar.wallets":"Wallets","DeleteAllKeys.back":"Back","DeleteAllKeys.delete":"Delete","DeleteAllKeys.description":"Deleting all keys will permanatly remove the keys from your computer, make sure you have backups. Are you sure you want to continue?","DeleteAllKeys.title":"Delete all keys","Farmer.title":"Farming","FarmerStatus.connected":"Connected","FarmerStatus.connectionStatus":"Connection Status","FarmerStatus.lastHeightFarmed":"Last height farmed","FarmerStatus.noBlocksFarmedYet":"No blocks farmed yet","FarmerStatus.notConnected":"Not connected","FarmerStatus.title":"Farmer Status","FarmerStatus.totalChiaFarmed":"Total chia farmed","FarmerStatus.totalSizeOfLocalPlots":"Total size of local plots","FullNode.title":"Full Node","FullNodeStatus.title":"Full Node Status","HistoryCard.title":"History","LocaleToggle.helpToTranslate":"Help to translate","MainWalletList.colouredCoin":"Coloured Coin","MainWalletList.createAdminWallet":"Create admin wallet","MainWalletList.createNewColouredCoin":"Create new coloured coin","MainWalletList.createUserWallet":"Create user wallet","MainWalletList.createWalletForExistingColour":"Create wallet for existing colour","MainWalletList.rateLimited":"Rate Limited","MainWalletList.title":"Select Wallet Type","OfferDropView.dragAndDropOfferFile":"Drag and drop offer file","OfferDropView.title":"View Offer","OfferRow.buy":"Buy","OfferRow.sell":"Sell","OfferView.accept":"Accept","OfferView.cancel":"Cancel","OfferView.title":"View Offer","PendingTrades.title":"Offers Created","Plots.back":"Back","Plots.delete":"Delete","Plots.deleteAllKeys":"Delete all keys","Plots.deleteAllKeysDescription":"Are you sure you want to delete the plot? The plot cannot be recovered.","Plots.deletePlotsDescription":"Caution, deleting these plots will delete them forever. Check that the storage devices are properly connected.","Plots.failedToOpenPlots":"Failed to open (invalid plots)","Plots.failedToOpenPlotsDescription":"These plots are invalid, you might want to delete them forever.","Plots.filename":"Filename","Plots.managePlotDirectories":"Manage plot directories","Plots.notFoundPlots":"Not found plots","Plots.plotId":"Plot id","Plots.plotPk":"Plot pk","Plots.poolPk":"Pool pk","Plots.refreshPlots":"Refresh plots","Plots.size":"Size","Plots.title":"Plots","Plotter.title":"Plot","PlotterFinalLocation.availableOnlyFromElectron":"This feature is available only from electron app","PlotterFinalLocation.finalFolderLocation":"Final folder location","PlotterFinalLocation.select":"Select","PlotterProgress.cancel":"Cancel","PlotterProgress.clearLog":"Clear Log","PlotterProgress.plottingStoppedSuccesfully":"Plotting stopped succesfully.","PlotterProgress.title":"Progress","PlotterWorkLocation.availableOnlyFromElectron":"This feature is available only from electron app","PlotterWorkLocation.select":"Select","PlotterWorkLocation.temporaryFolderLocation":"Temporary folder location","RLBalanceCard.pendingBalance":"Pending Balance","RLBalanceCard.pendingChange":"Pending Change","RLBalanceCard.pendingTotalBalance":"Pending Total Balance","RLBalanceCard.spendableBalance":"Spendable Balance","RLBalanceCard.title":"Balance","RLBalanceCard.totalBalance":"Total Balance","RLBalanceCard.viewPendingBalances":"View pending balances","RLDetailsCard.copy":"Copy","RLDetailsCard.description":"Send this info packet to your Rate Limited Wallet user who must use it to complete setup of their wallet:","RLDetailsCard.infoPacket":"Info Packet","RLDetailsCard.myPubkey":"My Pubkey","RLDetailsCard.spendingInterval":function(a){return["Spending Interval (number of blocks): ",a("interval")]},"RLDetailsCard.spendingLimit":function(a){return["Spending Limit (chia per interval): ",a("0")]},"RLDetailsCard.title":"Rate Limited Info","RLHistoryCard.title":"History","RLListItems.title":"Rate Limited Options","RLSendCard.addressPuzzleHash":"Address / Puzzle hash","RLSendCard.amount":"Amount","RLSendCard.enter0fee":"Please enter 0 fee. Positive fees not supported yet for RL.","RLSendCard.enterValidAmount":"Please enter a valid numeric amount","RLSendCard.enterValidFee":"Please enter a valid numeric fee","RLSendCard.fee":"Fee","RLSendCard.send":"Send","RLSendCard.title":"Create Transaction","RLSendCard.waitForSyncing":"Please finish syncing before making a transaction","RLTransactionTable.amount":"Amount","RLTransactionTable.confirmed":"Confirmed","RLTransactionTable.date":"Date","RLTransactionTable.fee":"Fee","RLTransactionTable.incoming":"Incoming","RLTransactionTable.noPreviousTransactions":"No previous transactions","RLTransactionTable.outgoing":"Outgoing","RLTransactionTable.pending":"Pending","RLTransactionTable.status":"Status","RLTransactionTable.to":"To","RLTransactionTable.type":"Type","RTIncompleteCard.copy":"Copy","RTIncompleteCard.description":"Send your pubkey to your Rate Limited Wallet admin:","RTIncompleteCard.description2":"When you receive the setup info packet from your admin, enter it below to complete your Rate Limited Wallet setup:","RTIncompleteCard.infoPacket":"Info Packet","RTIncompleteCard.submit":"Submit","RTIncompleteCard.title":"Rate Limited User Wallet Setup","RTIncompleteCard.userPubkey":"User Pubkey","SearchBlock.blockHash":"Block hash","SearchBlock.search":"Search","SearchBlock.title":"Search block by header hash","SelectKey.createNewPrivateKey":"Create a new private key","SelectKey.deleteAllKeys":"Delete all keys","SelectKey.importFromMnemonics":"Import from Mnemonics (24 words)","SelectKey.selectFingerprint":function(a){return["Private key with public fingerprint ",a("fingerprint")]},"SelectKey.selectKeyCanBeBacked":"Can be backed up to mnemonic seed","SelectKey.signInDescription":"Welcome to Chia. Please log in with an existing key, or create a a new key.","SelectKey.signInTitle":"Sign In","SelectKey.title":"Select Key","SendCard.address":"Address / Puzzle hash","SendCard.amount":"Amount","SendCard.enterValidAddress":"Error: Cannot send chia to coloured address. Please enter a chia address.","SendCard.enterValidAmount":"Please enter a valid numeric amount","SendCard.enterValidFee":"Please enter a valid numeric fee","SendCard.farm":"Farm","SendCard.fee":"Fee","SendCard.finishSyncingBeforeTransaction":"Please finish syncing before making a transaction","SendCard.send":"Send","SendCard.title":"Create Transaction","StatusCard.connections":"connections:","StatusCard.height":"height:","StatusCard.status":"status:","StatusCard.synced":"synced","StatusCard.syncing":"syncing","StatusCard.title":"Status","StatusItem.connectionStatus":"Connection Status","StatusItem.connectionStatusConnected":"Connected","StatusItem.connectionStatusNotConnected":"Not connected","StatusItem.difficulty":"Difficulty","StatusItem.estimatedNetworkSpace":"Estimated network space","StatusItem.estimatedNetworkSpaceTooltip":"Estimated sum of all the plotted disk space of all farmers in the network","StatusItem.iterationsPerSecond":"Iterations per Second","StatusItem.iterationsPerSecondTooltip":"The estimated proof of time speed of the fastest timelord in the network.","StatusItem.lcaBlockHeight":"LCA Block Height","StatusItem.lcaTime":"LCA Time","StatusItem.lcaTimeTooltip":"This is the time of the latest common ancestor, which is a block ancestor of all tip blocks. Note that the full node keeps track of up to three tips at each height.","StatusItem.maxTipBlockHeight":"Max Tip Block Height","StatusItem.minIterations":"Min Iterations","StatusItem.status":"Status","StatusItem.statusNotConnected":"Not connected","StatusItem.statusSynced":"Synced","StatusItem.statusSyncedTooltip":"This node is fully caught up and validating the network","StatusItem.statusTooltip":"The node is syncing, which means it is downloading blocks from other nodes, to reach the latest block in the chain","StatusItem.statusValue":function(a){return["Syncing ",a("progress"),"/",a("tip")]},"TradeDetail.acceptedAtTime":"Accepted at time:","TradeDetail.acceptedAtTimeTooltip":"Indicated what time this offer was accepted","TradeDetail.cancel":"Cancel","TradeDetail.cancelAndSpend":"Cancel and Spend","TradeDetail.coins":"Coins:","TradeDetail.confirmedAtBlock":"Confirmed at block:","TradeDetail.confirmedAtBlockTooltip":"This trade was included on blockchain at this block height","TradeDetail.createdAt":"Created At:","TradeDetail.createdAtTooltip":"Time this trade was created at this time","TradeDetail.createdByUs":"Created by us:","TradeDetail.createdByUsTooltip":"Indicated if this offer was created by us","TradeDetail.no":"No","TradeDetail.notAcceptedYet":"Not accepted yet","TradeDetail.notConfirmedYet":"Not confirmed yet","TradeDetail.status":"Status:","TradeDetail.statusTooltip":"Current trade status","TradeDetail.title":"Trade Details","TradeDetail.tradeId":"Trade ID:","TradeDetail.tradeIdTooltip":"Unique identifier","TradeDetail.yes":"Yes","TradeList.amount":"Amount","TradeList.colour":"Colour","TradeList.side":"Side","TradeManager.createTrade":"Create Trade","TradeManager.title":"Trading","TradeManager.tradeOverview":"Trade Overview","TradeManager.viewTrade":"View Trade","TradeOfferRow.buy":"Buy","TradeOfferRow.sell":"Sell","TradeOverviewTable.tradesShowUpHere":"Trades will show up here","TradeOverviewTableHeader.date":"Date","TradeOverviewTableHeader.status":"Status","TradeOverviewTableHeader.tradeId":"Trade ID","TradingHistory.title":"Trading History","TransactionTable.amount":"Amount","TransactionTable.confirmedAtHeight":function(a){return["Confirmed at height ",a("0")]},"TransactionTable.date":"Date","TransactionTable.fee":"Fee","TransactionTable.incoming":"Incoming","TransactionTable.outgoing":"Outgoing","TransactionTable.pending":"Pending","TransactionTable.status":"Status","TransactionTable.to":"To","TransactionTable.type":"Type","WalletAdd.description":"Welcome! The following words are used for your wallet backup. Without them, you will lose access to your wallet, keep them safe! Write down each word along with the order number next to them. (Order is important)","WalletAdd.next":"Next","WalletAdd.title":"New Wallet","WalletImport.description":"Enter the 24 word mmemonic that you have saved in order to restore your Chia wallet.","WalletImport.next":"Next","WalletImport.title":"Import Wallet from Mnemonics","WalletItem.ccWallet":"CC Wallet","WalletItem.chiaWallet":"Chia Wallet","WalletItem.rlWallet":"RL Wallet","WalletStatusCard.connections":"connections:","WalletStatusCard.height":"height:","WalletStatusCard.status":"status:","WalletStatusCard.synced":"synced","WalletStatusCard.syncing":"syncing","WalletStatusCard.title":"Status","Wallets.title":"Wallets"}};