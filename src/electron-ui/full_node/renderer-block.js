let FullNodeRpcClient = require('./full_node_rpc_client')
let block_tbody = document.querySelector('#block-tbody');
let block_title = document.querySelector('#block-title');
const { unix_to_short_date, get_query_variable } = require("../utils");
let chia_formatter = require('../chia');
let rpc_client = new FullNodeRpcClient();


function create_table_row(textL, textR) {
    let row = document.createElement("tr");
    let cellL = document.createElement("td");
    let cellTextL = document.createTextNode(textL);
    cellL.appendChild(cellTextL);
    let cellR = document.createElement("td");
    let cellTextR = document.createTextNode(textR);
    cellR.appendChild(cellTextR);
    row.appendChild(cellL);
    row.appendChild(cellR);
    return row;
}

async function render() {
    let header_hash = get_query_variable("header_hash");
    if (!header_hash.startsWith("0x") && !header_hash.startsWith("0X")) {
        header_hash = "0x" + header_hash;
    }
    try {
        const block = await rpc_client.get_block(header_hash);

        block_title.innerHTML = "Block " + block.header.data.height + " in the Chia blockchain";
        const prev_header = await rpc_client.get_header(block.header.data.prev_header_hash);
        let diff = block.header.data.weight - prev_header.data.weight;

        // TODO: don't use float here
        let chia_cb = chia_formatter(parseFloat(BigInt(block.header.data.coinbase.amount)), 'mojo').to('chia').toString();
        let chia_fees = chia_formatter(parseFloat(BigInt(block.header.data.fees_coin.amount)), 'mojo').to('chia').toString();
        block_tbody.innerHTML = "";
        block_tbody.appendChild(create_table_row("Header Hash", header_hash));
        block_tbody.appendChild(create_table_row("Timestamp", unix_to_short_date(block.header.data.timestamp)));
        block_tbody.appendChild(create_table_row("Height", block.header.data.height));
        block_tbody.appendChild(create_table_row("Weight", BigInt(block.header.data.weight).toLocaleString()));
        block_tbody.appendChild(create_table_row("Cost", block.header.data.cost));
        block_tbody.appendChild(create_table_row("Difficulty", BigInt(diff).toLocaleString()));
        block_tbody.appendChild(create_table_row("Total VDF Iterations", BigInt(block.header.data.total_iters).toLocaleString()));
        block_tbody.appendChild(create_table_row("Block VDF Iterations", block.proof_of_time.number_of_iterations));
        block_tbody.appendChild(create_table_row("Proof of Space Size", block.proof_of_space.size));
        block_tbody.appendChild(create_table_row("Plot Public Key", block.proof_of_space.plot_pubkey));
        block_tbody.appendChild(create_table_row("Pool Public Key", block.proof_of_space.pool_pubkey));
        block_tbody.appendChild(create_table_row("Transactions Filter Hash", block.header.data.filter_hash));
        block_tbody.appendChild(create_table_row("Transactions Generator Hash", block.header.data.generator_hash));
        block_tbody.appendChild(create_table_row("Coinbase Amount", chia_cb + " CH"));
        block_tbody.appendChild(create_table_row("Coinbase Puzzle Hash", block.header.data.coinbase.puzzle_hash));
        block_tbody.appendChild(create_table_row("Fees Amount", chia_fees + " CH"));
        block_tbody.appendChild(create_table_row("Fees Puzzle Hash", block.header.data.fees_coin.puzzle_hash));

        if (block.header.data.aggregated_signature === undefined || block.header.data.aggregated_signature === null) {
            block_tbody.appendChild(create_table_row("Aggregated Signature", "None"));
        } else {
            block_tbody.appendChild(create_table_row("Aggregated Signature", block.header.data.aggregated_signature.sig));
        }
    } catch (error) {
        console.log("ERROR", error);
        alert("Block " + header_hash + " not found.");
    }
}

render();
// console.log("header hash", header_hash);