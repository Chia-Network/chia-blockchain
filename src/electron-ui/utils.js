function unix_to_short_date(unix_timestamp) {
    let d = new Date(unix_timestamp * 1000)
    return d.toLocaleDateString('en-US', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        }) + " " + d.toLocaleTimeString();
}

module.exports = {
    unix_to_short_date,
}
