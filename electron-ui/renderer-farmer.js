const {shell} = require('electron');
document.getElementById ("link").addEventListener ("click", go_to_readme, false);

function go_to_readme(){
    shell.openExternal('https://github.com/Chia-Network/chia-blockchain/blob/master/README.md');
}

