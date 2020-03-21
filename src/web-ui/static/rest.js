function stopNode()
{
    $.ajax({
        url: "/stop",
        type: "POST",
        success: function(data) {
            setTimeout(function() {
                window.location.reload(); 
            }, 5000);           
        },
        error: function(data) {
            console.log(data.status);
        }
    });
}

function disconnectPeer(node_id)
{
    alert(node_id);
    return;
    $.ajax({
        url: "/disconnect",
        type: "POST",
        success: function(data) {
            setTimeout(function() {
                window.location.reload(); 
            }, 5000);            
        },
        error: function(data) {
            console.log(data.status);
        }
    });
}