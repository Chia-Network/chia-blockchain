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
    console.log('Query variable %s not found', variable);
}

module.exports = {
    unix_to_short_date,
    get_query_variable,
}
