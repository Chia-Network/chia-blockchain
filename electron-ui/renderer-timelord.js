const {shell} = require('electron');
document.getElementById ("link").addEventListener ("click", go_to_readme, false);
document.getElementById ("timelord").addEventListener ("click", go_to_timelord, false);

function go_to_readme(){
    shell.openExternal('https://github.com/Chia-Network/chia-blockchain/blob/master/README.md');
}

function go_to_timelord() {
    shell.openExternal('https://github.com/Chia-Network/chia-blockchain/blob/master/LINUX_TIMELORD.md');
}




