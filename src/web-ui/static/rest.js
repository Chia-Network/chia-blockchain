function stopNode()
{
    $.ajax({
        url: "/stop",
        type: "POST",
        success: function(data) {
            window.location.reload();            
        },
        error: function(data) {
            console.log(data.status);
        }
    });
}
