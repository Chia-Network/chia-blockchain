const http = require('http')
const { full_node_rpc_host, full_node_rpc_port } = require("../config");

class FullNodeRpcClient {
    constructor() {
        this._host = full_node_rpc_host;
        this._port = full_node_rpc_port;
    }

    async get_blockchain_state() {
        return await this.make_request("get_blockchain_state", {});
    }

    async get_header(header_hash) {
        return await this.make_request("get_header", {
            "header_hash": header_hash,
        });
    }
    async get_unfinished_block_headers(height) {
        return await this.make_request("get_unfinished_block_headers", {
            "height": height,
        });
    }

    async get_block(header_hash) {
        return await this.make_request("get_block", {
            "header_hash": header_hash,
        });
    }

    async get_connections() {
        return await this.make_request("get_connections", {});
    }
    async close_connection(node_id) {
        return await this.make_request("close_connection", {
            "node_id": node_id,
        });
    }
    async open_connection(host, port) {
        return await this.make_request("open_connection", {
            "host": host,
            "port": port,
        });
    }
    async stop_node() {
        return await this.make_request("stop_node", {});
    }

    make_request(path, data)  {
        return new Promise((resolve, reject) => {
            const str_data = JSON.stringify(data)

            const options = {
                hostname: this._host,
                port: this._port,
                path: '/' + path,
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': str_data.length
                }
            }
            const req = http.request(options, res => {
                let collected_data = []
                if (res.statusCode != 200) {
                    reject(res.statusCode + " " + res.statusMessage);
                    return;
                }

                res.on('data', d => {
                    collected_data = collected_data.concat(d)
                })

                res.on('end', () => {
                    resolve(JSON.parse(collected_data))
                })
            })

            req.on('error', error => {
                reject(error);
            })

            req.write(str_data)
            req.end();
        });
  }
}

module.exports = FullNodeRpcClient;