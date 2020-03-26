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
    $.ajax({
        url: "/disconnect?node_id=" + node_id,
        type: "POST",
        success: function(data) {
            setTimeout(function() {
                window.history.back();
                window.location.reload();                  
            }, 1000);            
        },
        error: function(data) {
            console.log(data.status);
        }
    });
}
