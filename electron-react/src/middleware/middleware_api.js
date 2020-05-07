import { format_message, incomingMessage } from '../modules/message';




export const handle_message = (store, payload) => {
    store.dispatch(incomingMessage(payload.command, payload.data))
    if (payload.command == "start_server") {
        console.log("fetch state")
        store.dispatch(format_message("logged_in", {}))
    }
    console.log(payload)
}
