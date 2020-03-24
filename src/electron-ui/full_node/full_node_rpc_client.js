const http = require('http')

class FullNodeRpcClient {
    constructor() {
        this._host = "127.0.0.1";
        this._port = 8555;
    }

    async get_blockchain_state() {
        let state = await this.make_request("get_blockchain_state", {});
        let tips_parsed = [];
        for (let tip of state.tips) {
            tips_parsed.push(JSON.parse(tip));
        }
        state.tips = tips_parsed;
        state.lca = JSON.parse(state.lca);
        return state;
    }

    async get_header(header_hash) {
        return JSON.parse(await this.make_request("get_header", {
            "header_hash": header_hash,
        }));
    }

    async get_block(header_hash) {
        return JSON.parse(await this.make_request("get_block", {
            "header_hash": header_hash,
        }));
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
                if (res.statusCode != 200) {
                    reject(res.statusCode + " " + res.statusMessage);
                    return;
                }

                res.on('data', d => {
                    resolve(JSON.parse(d));
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