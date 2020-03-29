var busy = new busy_indicator(document.getElementById("busybox"), document.querySelector("#busydiv"));

function stopNode()
{
    busy.show();
    window.navigate
    $.ajax({
        url: "/stop",
        type: "POST",
        success: function(data) {
            setTimeout(function() {
                gotoRoot();
            }, 5000);
        },
        error: function(data) {
            setTimeout(function() {
                gotoRoot();
            }, 5000);
        }
    });
}

function disconnectPeer(node_id)
{
    busy.show();

    $.ajax({
        url: "/disconnect?node_id=" + node_id,
        type: "POST",
        success: function(data) {
            setTimeout(function() {
                gotoRoot();
            }, 1000);
        },
        error: function(data) {
            setTimeout(function() {
                gotoRoot();
            }, 1000);
        }
    });
}

function gotoRoot()
{
    busy.hide();
    var url = window.location.protocol + "://" + window.location.hostname + ":" + window.location.port;
    window.location.assign(url);
}
