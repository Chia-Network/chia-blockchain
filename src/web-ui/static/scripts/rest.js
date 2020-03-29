var busy = new busy_indicator(document.getElementById("busybox"), document.querySelector("#busydiv"));

function stopNode()
{
    busy.show();
    $.ajax({
        url: "/stop",
        type: "POST",
        success: function(data) {
            setTimeout(function() {
                busy.hide(); 
            }, 5000);           
        },
        error: function(data) {
            busy.hide(); 
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
                busy.hide();                
            }, 1000);            
        },
        error: function(data) {
            setTimeout(function() {
                busy.hide();                      
            }, 1000);            
        }
    });
}
