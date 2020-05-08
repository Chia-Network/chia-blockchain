import { format_message, incomingMessage } from '../modules/message';
import { get_balance_for_wallet, get_transactions } from '../modules/message';
import { get_puzzle_hash } from '../modules/message';




export const handle_message = (store, payload) => {
    store.dispatch(incomingMessage(payload.command, payload.data))
    if (payload.command == "start_server") {
        console.log("fetch state")
        store.dispatch(format_message("logged_in", {}))
        store.dispatch(format_message("get_wallets", {}))
    }
    if (payload.command == "get_wallets") {
        const wallets = payload.data.wallets
        console.log(wallets)
        wallets.map((wallet) =>  {
            store.dispatch(get_balance_for_wallet(wallet.id))
            store.dispatch(get_transactions(wallet.id))
            store.dispatch(get_puzzle_hash(wallet.id))
        })
    }
    console.log(payload)
}
