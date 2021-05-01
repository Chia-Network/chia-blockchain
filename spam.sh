
# Let's countdown before sending a transaction
for ((count=$SEND_QTY; count>0; count--)); do
        # Transaction fees
        RANDOMISE_FEE="`seq $MIN_FEE 0.01 $MAX_FEE | sort -R | head -n 1`"
        printf "Transaction fee: $RANDOMISE_FEE\n"

        # Amount to send
        AMOUNT="`seq $MIN_AMOUNT 0.01 $MAX_AMOUNT | sort -R | head -n 1`"
        printf "Amount to send: $AMOUNT\n"

        # Send transaction to a random wallet!
        WALLET_ADDRESS="`sort -R $WALLETS | head -n 1`"

        #printf "chia wallet send -t $WALLET_ADDRESS -m $RANDOMISE_FEE -a $AMOUNT\n"
        chia wallet send -t $WALLET_ADDRESS -m $RANDOMISE_FEE -a $AMOUNT

        # Let's sleep for a moment before the next transaction
        TIME_LAG="`seq 0 1 300 | sort -R | head -n 1`"
        printf "Waiting time: $TIME_LAG seconds\n"
        sleep $TIME_LAG

        printf "\n\n";
done