let FullNodeRpcClient = require('./full_node_rpc_client')
let syncing_textfield = document.querySelector('#syncing_textfield');
let block_height_textfield = document.querySelector('#block_height_textfield');
let max_block_height_textfield = document.querySelector('#max_block_height_textfield');
let lca_time_textfield = document.querySelector('#lca_time_textfield');
let connection_textfield = document.querySelector('#connection_textfield');
let connected_to_node_textfield = document.querySelector('#connected_to_node_textfield');
let difficulty_textfield = document.querySelector('#difficulty_textfield');
let ips_textfield = document.querySelector('#ips_textfield');
let min_iters_textfield = document.querySelector('#min_iters_textfield');
let connections_list_tbody = document.querySelector('#connections_list');
let create_conn_button = document.querySelector("#create-conn-button");
let new_ip_field = document.querySelector("#new-ip-address");
let new_port_field = document.querySelector("#new-port");
let header_hash_field = document.querySelector("#new-header-hash");
let search_button = document.querySelector("#search-button");
let stop_node_button = document.querySelector("#stop-node-button");
let latest_blocks_tbody = document.querySelector('#latest-blocks-tbody');
const ipc = require('electron').ipcRenderer;
const { unix_to_short_date } = require("../utils");

let rpc_client = new FullNodeRpcClient();
const connection_types = {
    1: "Full Node",
    2: "Harvester",
    3: "Farmer",
    4: "Timelord",
    5: "Introducer",
    6: "Wallet",
}
const NUM_LATEST_BLOCKS = 10;

class FullNodeView {
    constructor() {
        this.state = {
            tip_prev_hashes: new Set(),
            getting_info: false,
            connections: {},
            displayed_connections: new Set(),
            max_height: 0,
            lca_height: 0,
            lca_timestamp: 1585023165,
            syncing: false,
            difficulty: 0,
            ips: 0,
            min_iters: 0,
            latest_blocks: [],
        }
        this.update_view(true);
        this.initialize_handlers();
        this.get_info();
        this.interval = setInterval(() => this.get_info(), 2000);
    }

    initialize_handlers() {
        create_conn_button.onclick = async () => {
            try {
                let old_host = new_ip_field.value;
                let old_port = new_port_field.value;
                new_ip_field.value = "";
                new_port_field.value = "";
                await rpc_client.open_connection(old_host, old_port);
            } catch (error) {
                alert(error);
            }
        }
        stop_node_button.onclick = async () => {
            try {
                await rpc_client.stop_node();
            } catch (error) {
                alert(error);
            }
        };
        search_button.onclick = async () => {
            try {
                ipc.send('load-page', {
                    "file": "full_node/block.html",
                    "query": "?header_hash=" + header_hash_field.value,
                });
            } catch (error) {
                alert(error);
            }
        };

        new_port_field.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                create_conn_button.onclick();
            }
        });
        header_hash_field.addEventListener('keypress', function (e) {
            if (e.key === 'Enter') {
                search_button.onclick();
            }
        });
    }

    node_connected() {
        connected_to_node_textfield.innerHTML = "Connected to full node";
        connected_to_node_textfield.style.color = "green";
        create_conn_button.disabled = false;
        stop_node_button.disabled = false;
    }

    node_not_connected() {
        connected_to_node_textfield.innerHTML = "Not connected to node";
        connected_to_node_textfield.style.color = "red";
        this.state.connections = {};
        this.state.latest_blocks = [];
        create_conn_button.disabled = true;
        stop_node_button.disabled = true;
        this.update_view(true);
    }

    stop() {
        clearInterval(this.interval);
    }

    areEqualSets(set, subset) {
        for (let elem of subset) {
            if (!set.has(elem)) {
                return false;
            }
        }
        for (let elem of set) {
            if (!subset.has(elem)) {
                return false;
            }
        }
        return true;
    }

    async get_latest_blocks(tips) {
        let max_height = 0;
        let blocks = [];
        let hashes = new Set();
        for (let tip of tips) {
            if (tip.data.height > max_height)  max_height = tip.data.height;
        }
        for (let tip of tips) {
            let curr = tip;
            while (curr.data.height > (max_height - NUM_LATEST_BLOCKS)) {
                if (hashes.has(curr.data.prev_header_hash)) {
                    break;
                }
                let prev_header = await rpc_client.get_header(curr.data.prev_header_hash);
                blocks.push({
                    "header_hash": curr.data.prev_header_hash,
                    "header": prev_header,
                });
                hashes.add(curr.data.prev_header_hash);
                curr = prev_header;
            }
        }
        blocks.sort((b1, b2) => b1.header.data.timestamp > b2.header.timestamp);
        return blocks;
    }

    create_table_cell(text) {
        let cell = document.createElement("td");
        let cellText = document.createTextNode(text);
        cell.appendChild(cellText);
        return cell;
    }

    async update_view(redisplay_blocks) {
        syncing_textfield.innerHTML = this.state.syncing ? "Yes" : "No";
        block_height_textfield.innerHTML = this.state.lca_height;
        max_block_height_textfield.innerHTML = this.state.max_height;
        lca_time_textfield.innerHTML = unix_to_short_date(this.state.lca_timestamp);
        connection_textfield.innerHTML = Object.keys(this.state.connections).length + " connections";
        difficulty_textfield.innerHTML = this.state.difficulty.toLocaleString();
        ips_textfield.innerHTML = this.state.ips.toLocaleString();
        min_iters_textfield.innerHTML = this.state.min_iters.toLocaleString();

        if (!this.areEqualSets(new Set(Object.keys(this.state.connections)), this.state.displayed_connections)) {
            // console.log("Updating connections");
            connections_list_tbody.innerHTML = "";
            for (let node_id of Object.keys(this.state.connections)) {
                let connection = this.state.connections[node_id];
                let node_id_short = node_id.substring(2, 6) + "..." + node_id.substring(62);
                let row = document.createElement("tr");
                row.appendChild(this.create_table_cell(node_id_short));
                row.appendChild(this.create_table_cell(connection_types[connection.type]));
                row.appendChild(this.create_table_cell(connection.peer_host));
                row.appendChild(this.create_table_cell(connection.peer_server_port));
                row.appendChild(this.create_table_cell(unix_to_short_date(connection.creation_time)));
                row.appendChild(this.create_table_cell(unix_to_short_date(connection.last_message_time)));
                let action_cell = document.createElement("td");
                let btn = document.createElement("button");
                btn.innerHTML = "Close";
                btn.classList.add("btn");
                btn.classList.add("btn-primary");
                btn.classList.add("close-btn");
                btn.onclick = async () => {
                    await rpc_client.close_connection(node_id);
                };
                action_cell.appendChild(btn);
                action_cell.onclick =
                row.appendChild(action_cell);
                connections_list_tbody.appendChild(row);
            }
            this.state.displayed_connections = new Set(Object.keys(this.state.connections));
        }
        if (redisplay_blocks) {
            latest_blocks_tbody.innerHTML = "";
            for (let block of this.state.latest_blocks) {
                let row = document.createElement("tr");
                let link = document.createElement("a");
                let action_cell = document.createElement("td");
                action_cell.style.cursor = "pointer";
                action_cell.onclick = async (r) => {
                    console.log("Clicked", r.target.innerHTML);
                    ipc.send('load-page', {
                        "file": "full_node/block.html",
                        "query": "?header_hash=" + block.header_hash,
                    });
                }
                link.innerHTML = block.header_hash;
                link.style.textDecoration = "underline";
                action_cell.appendChild(link);
                row.appendChild(action_cell);
                row.appendChild(this.create_table_cell(block.header.data.height));
                row.appendChild(this.create_table_cell(unix_to_short_date(block.header.data.timestamp)));
                latest_blocks_tbody.appendChild(row);
            }
        }
    }

    async get_info() {
        if ((max_block_height_textfield === undefined) || (max_block_height_textfield === null)) {
            // Stop the interval if we changed tabs.
            this.stop();
            return;
        }
        if (this.state.getting_info) {
            return;
        }
        try {
            let connections_obj = {};
            let connections = await rpc_client.get_connections();
            for (let c of connections) {
                connections_obj[c.node_id] = c;
            }
            this.state.connections = connections_obj;
            this.node_connected();
            let blockchain_state = await rpc_client.get_blockchain_state();
            let max_height = 0;
            let tip_prev_hashes = new Set();
            for (let tip of blockchain_state.tips) {
                if (tip.data.height > max_height) max_height = tip.data.height;
                tip_prev_hashes.add(tip.data.prev_header_hash);
            }
            let redisplay_blocks = false;
            if (!this.areEqualSets(tip_prev_hashes, this.state.tip_prev_hashes)) {
                redisplay_blocks = true;
                this.state.latest_blocks = await this.get_latest_blocks(blockchain_state.tips);
                this.state.tip_prev_hashes = tip_prev_hashes;
            }

            this.state.max_height = max_height;
            this.state.lca_height = blockchain_state.lca.data.height;
            this.state.lca_timestamp = blockchain_state.lca.data.timestamp;
            this.state.syncing = blockchain_state.sync_mode;
            this.state.difficulty = blockchain_state.difficulty;
            this.state.ips = blockchain_state.ips;
            this.state.min_iters = blockchain_state.min_iters;

            await this.update_view(redisplay_blocks);
        } catch (error) {
            console.error("Error getting info from node", error);
            this.node_not_connected();
        }
        this.state.getting_info = false;
    };
}

if (!(max_block_height_textfield === undefined) && !(max_block_height_textfield === null)) {
    window.full_node_view = new FullNodeView();
}
