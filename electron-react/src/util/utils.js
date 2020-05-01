function unix_to_short_date(unix_timestamp) {
    let d = new Date(unix_timestamp * 1000)
    return d.toLocaleDateString('en-US', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        }) + " " + d.toLocaleTimeString();
}

function get_query_variable(variable) {
    var query = global.location.search.substring(1);
    var vars = query.split('&');
    for (var i = 0; i < vars.length; i++) {
        var pair = vars[i].split('=');
        if (decodeURIComponent(pair[0]) == variable) {
            return decodeURIComponent(pair[1]);
        }
    }
}

function big_int_to_array(x, num_bytes) {
    truncated = BigInt.asUintN(num_bytes * 8, x);
    arr = []
    for (let i = 0; i < num_bytes; i++) {
        arr.splice(0, 0, Number(truncated & BigInt(255)));
        truncated >>= BigInt(8);
    }
    return arr;
}

function hex_to_array(hexString) {
    hexString = hexString.slice(2);
    arr = []
    for (var i = 0; i < hexString.length; i += 2) {
        arr.push(parseInt(hexString.substr(i, 2), 16));
    }
    return arr;
}

function arr_to_hex(buffer) { // buffer is an ArrayBuffer
    return Array.prototype.map.call(new Uint8Array(buffer), x => ('00' + x.toString(16)).slice(-2)).join('');
}


module.exports = {
    unix_to_short_date,
    get_query_variable,
    big_int_to_array,
    hex_to_array,
    arr_to_hex
}
