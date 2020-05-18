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
let startup_alert = document.querySelector('#startup-alert');
const ipc = require('electron').ipcRenderer;
const { unix_to_short_date } = require("../utils");
const { hash_header } = require("./header");

let rpc_client = new FullNodeRpcClient();
const connection_types = {
    1: "Full Node",
    2: "Harvester",
    3: "Farmer",
    4: "Timelord",
    5: "Introducer",
    6: "Wallet",
}
const NUM_LATEST_BLOCKS = 8;

class FullNodeView {
    constructor() {
        this.state = {
            tip_hashes: new Set(),
            getting_info: false,
            getting_info_unfinished: false,
            connections: {},
            displayed_connections: new Set(),
            max_height: 0,
            lca_hash: "",
            lca_height: 0,
            lca_timestamp: 1585023165,
            syncing: false,
            sync_tip_height: 0,
            sync_progress_height: 0,
            difficulty: 0,
            ips: 0,
            min_iters: 0,
            latest_blocks: [],
            latest_unfinished_blocks: [],
        }
        this.update_view(true);
        this.initialize_handlers();
        this.get_info();
        this.get_info_unfinished();
        this.interval = setInterval(() => this.get_info(), 2000);
        this.interval = setInterval(() => this.get_info_unfinished(), 7000);
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
                this.node_not_connected();
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
        startup_alert.style.display = "none";
        connected_to_node_textfield.innerHTML = "Connected to full node";
        connected_to_node_textfield.style.color = "green";
        create_conn_button.disabled = false;
        stop_node_button.disabled = false;
        search_button.disabled = false;
    }

    node_not_connected() {
        startup_alert.style.display = "block";
        connected_to_node_textfield.innerHTML = "Not connected to node";
        connected_to_node_textfield.style.color = "red";
        this.state.connections = {};
        this.state.latest_blocks = [];
        this.state.latest_unfinished_blocks = [];
        create_conn_button.disabled = true;
        stop_node_button.disabled = true;
        search_button.disabled = true;
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
            while (curr.data.height >= Math.max(0, (max_height - NUM_LATEST_BLOCKS))){
                const hh = await hash_header(curr);
                if (hashes.has(hh)) {
                    break;
                }
                blocks.push({
                    "header_hash": hh,
                    "header": curr,
                });
                hashes.add(hh);
                if (curr.data.height == 0) break;
                let prev_header = await rpc_client.get_header(curr.data.prev_header_hash);
                curr = prev_header;
            }
        }
        blocks.sort((b1, b2) => parseFloat(b2.header.data.timestamp) - parseFloat(b1.header.data.timestamp));
        return blocks;
    }

    async get_latest_unfinished_blocks(tips, ips) {
        let num_headers_to_display = 3;
        let min_height = 9999999999;
        let max_height = 0;
         for (let tip of tips) {
            if (tip.data.height < min_height)  min_height = tip.data.height;
            if (tip.data.height > max_height)  max_height = tip.data.height;
        }
        let headers = [];
        for (let height=max_height + 1; height >= min_height; height--) {
            let fetched = await rpc_client.get_unfinished_block_headers(height);
            for (let fetched_h of fetched) {
                fetched_h.header_hash = await hash_header(fetched_h);
                headers.push(fetched_h);
            }
            if (headers.length >= num_headers_to_display) {
                break;
            }
        }
        // Get prev headers to check iterations required for this block
        let iters_map = {};
        for (let header of headers) {
            let prev = await rpc_client.get_header(header.data.prev_header_hash);
            iters_map[header.header_hash] = BigInt(header.data.total_iters) - BigInt(prev.data.total_iters);
        }
        let blocks = [];
        // Add the expected_finish property to each header
        for (let i=0; i < headers.length; i++) {
            let iters = iters_map[headers[i].header_hash];
            let finish_time = BigInt(headers[i].data.timestamp) + BigInt(iters) / BigInt(ips);
            blocks.push({
                "header_hash": headers[i].header_hash,
                "header": headers[i],
                "expected_finish": finish_time,
                "iters": iters,
            })
        }

        // Sort by block height, then expected finish time
        blocks.sort((b1, b2) => {
            if (b2.header.data.height != b1.header.data.height) {
                return b2.header.data.height - b1.header.data.height;
            }
            return Number(b1.expected_finish - b2.expected_finish);
        })
        return blocks.slice(0, num_headers_to_display);
    }

    create_table_cell(text) {
        let cell = document.createElement("td");
        let cellText = document.createTextNode(text);
        cell.appendChild(cellText);
        return cell;
    }

    async update_view(redisplay_blocks) {
        let sync_info = "Verif. blocks " + this.state.sync_progress_height + "/" + this.state.sync_tip_height;
        syncing_textfield.innerHTML = this.state.syncing ? sync_info : "No";
        block_height_textfield.innerHTML = this.state.lca_height;
        max_block_height_textfield.innerHTML = this.state.max_height;
        lca_time_textfield.innerHTML = unix_to_short_date(this.state.lca_timestamp);
        connection_textfield.innerHTML = Object.keys(this.state.connections).length + " connections";
        difficulty_textfield.innerHTML = this.state.difficulty.toLocaleString();
        ips_textfield.innerHTML = this.state.ips.toLocaleString();
        min_iters_textfield.innerHTML = this.state.min_iters.toLocaleString();

        if (!this.areEqualSets(new Set(Object.keys(this.state.connections)), this.state.displayed_connections)) {
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
            let display_blocks = this.state.latest_unfinished_blocks.concat(this.state.latest_blocks);
            let latest_blocks_hh = this.state.latest_blocks.map((b) => b.header_hash);

            for (let block of display_blocks) {
                if ("expected_finish" in block && latest_blocks_hh.includes(block.header_hash)) {
                    // Don't display unfinished blocks that are already in finished blocks list
                    continue;
                }
                let row = document.createElement("tr");
                let link = document.createElement("a");
                let action_cell = document.createElement("td");
                action_cell.style.cursor = "pointer";
                action_cell.onclick = async (r) => {
                    ipc.send('load-page', {
                        "file": "full_node/block.html",
                        "query": "?header_hash=" + block.header_hash,
                    });
                }
                let hh = await hash_header(block.header);
                let height_str = block.header.data.height;
                if (hh === this.state.lca_hash) {
                    height_str += " (LCA)";
                }
                link.innerHTML = block.header_hash.substring(0, 5) + "..." + block.header_hash.substring(59);
                link.style.textDecoration = "underline";
                action_cell.appendChild(link);
                if ("expected_finish" in block) {
                    row.append(this.create_table_cell(link.innerHTML))
                    row.appendChild(this.create_table_cell(height_str + " (unfinished)"));
                    row.appendChild(this.create_table_cell(unix_to_short_date(block.header.data.timestamp)));
                    row.appendChild(this.create_table_cell(unix_to_short_date(block.expected_finish.toString()) + " (" + BigInt(block.iters).toLocaleString() + " iter)"));
                    row.style.color = "orange";
                } else {
                    row.appendChild(action_cell);
                    row.appendChild(this.create_table_cell(height_str));
                    row.appendChild(this.create_table_cell(unix_to_short_date(block.header.data.timestamp)));
                    row.appendChild(this.create_table_cell("Finished"));
                }
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
        this.state.getting_info = true;
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
            let tip_hashes = new Set();
            for (let tip of blockchain_state.tips) {
                if (tip.data.height > max_height) max_height = tip.data.height;
                let hh = await hash_header(tip);
                tip_hashes.add(hh);
            }
            let redisplay_blocks = false;
            if (!this.areEqualSets(tip_hashes, this.state.tip_hashes)) {
                redisplay_blocks = true;
                this.state.latest_blocks = await this.get_latest_blocks(blockchain_state.tips);
                this.state.tip_hashes = tip_hashes;
            }

            this.state.max_height = max_height;
            this.state.lca_height = blockchain_state.lca.data.height;
            this.state.lca_hash = await hash_header(blockchain_state.lca);
            this.state.lca_timestamp = blockchain_state.lca.data.timestamp;
            this.state.syncing = blockchain_state.sync.sync_mode;
            this.state.sync_tip_height = blockchain_state.sync.sync_tip_height;
            this.state.sync_progress_height = blockchain_state.sync.sync_progress_height;
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

    async get_info_unfinished() {
        if ((max_block_height_textfield === undefined) || (max_block_height_textfield === null)) {
            // Stop the interval if we changed tabs.
            this.stop();
            return;
        }
        if (this.state.getting_info_unfinished) {
            return;
        }
        this.state.getting_info_unfinished = true;
        try {
            let blockchain_state = await rpc_client.get_blockchain_state();
            let unfinished_blocks = await this.get_latest_unfinished_blocks(blockchain_state.tips, blockchain_state.ips);
            let update = false;
            for (let b of unfinished_blocks) {
                if (!this.state.latest_unfinished_blocks.map(x => x.header_hash).includes(b.header_hash)) {
                    update = true;
                    this.state.latest_unfinished_blocks = unfinished_blocks;
                    break;
                }
            }
            await this.update_view(update);
        } catch (error) {
            console.error("Error getting unfinished info from node", error);
            this.node_not_connected();
        }
        this.state.getting_info_unfinished = false;
    }

}

if (!(max_block_height_textfield === undefined) && !(max_block_height_textfield === null)) {
    window.full_node_view = new FullNodeView();
}
