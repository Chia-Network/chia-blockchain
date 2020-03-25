function hash_header(header) {
    function toByteArray(buf, hexString) {
        hexString = hexString.slice(2);
        for (var i = 0; i < hexString.length; i += 2) {
            buf.push(parseInt(hexString.substr(i, 2), 16));
        }
        return buf;
    }

    function buf2hex(buffer) { // buffer is an ArrayBuffer
        return Array.prototype.map.call(new Uint8Array(buffer), x => ('00' + x.toString(16)).slice(-2)).join('');
    }

    var buf = [];
    buf = toByteArray(buf, header.data.prev_header_hash);
    var ts = BigInt(header.data.timestamp);
    buf.push(0, 0, 0, 0, 0xff & (ts >> 24), 0xff & (ts >> 16), 0xff & (ts >> 8), 0xff & ts);
    buf = toByteArray(buf, jsn.header.data.filter_hash);
    buf = toByteArray(buf, jsn.header.data.proof_of_space_hash);
    buf = toByteArray(buf, jsn.header.data.body_hash);
    buf = toByteArray(buf, jsn.header.data.extension_data);
    buf = toByteArray(buf, jsn.header.harvester_signature);

    return window.crypto.subtle.digest("SHA-256", new Uint8Array(buf))
        .then(function(hash) {
            hashed_blocks[index] = buf2hex(hash);
            return makeHash(index + 1, added_blocks);
        });
}

module.exports = hash_header
