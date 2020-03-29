var busy = new busy_indicator(document.getElementById("busybox"), document.querySelector("#busydiv"));

function stopNode() {
    busy.show();
    window.navigate
    $.ajax({
        url: "/stop",
        type: "POST",
        success: function(data) {
            gotoRoot(10000);
        },
        error: function(data) {
            console.log(data);
            gotoRoot(1000);
        }
    });
}

function disconnectPeer(node_id) {
    busy.show();

    $.ajax({
        url: "/disconnect?node_id=" + node_id,
        type: "POST",
        success: function(data) {
            gotoRoot(1000);
        },
        error: function(data) {
            console.log(data);            
            gotoRoot(1000);
        }
    });
}

function gotoRoot(wait) {
    setTimeout(function() {
        busy.hide();
        window.location.assign("/");
    }, wait);
}
