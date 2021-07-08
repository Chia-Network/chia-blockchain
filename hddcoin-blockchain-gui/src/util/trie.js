// Trie.js - super simple JS implementation
// https://en.wikipedia.org/wiki/Trie
// https://gist.github.com/tpae/72e1c54471e88b689f85ad2b3940a8f0
// -----------------------------------------

function TrieNode(key) {
  this.key = key;
  this.parent = null;
  this.children = {};
  this.end = false;
}

TrieNode.prototype.getWord = function () {
  var output = [];
  var node = this;

  while (node !== null) {
    output.unshift(node.key);
    node = node.parent;
  }

  return output.join('');
};

function Trie() {
  this.root = new TrieNode(null);
}

Trie.prototype.insert = function (word) {
  var node = this.root;
  for (var i = 0; i < word.length; i++) {
    if (!node.children[word[i]]) {
      node.children[word[i]] = new TrieNode(word[i]);

      node.children[word[i]].parent = node;
    }

    node = node.children[word[i]];

    if (i == word.length - 1) {
      node.end = true;
    }
  }
};

Trie.prototype.contains = function (word) {
  var node = this.root;

  for (var i = 0; i < word.length; i++) {
    if (node.children[word[i]]) {
      node = node.children[word[i]];
    } else {
      return false;
    }
  }

  return node.end;
};

Trie.prototype.find = function (prefix) {
  var node = this.root;
  var output = [];

  for (var i = 0; i < prefix.length; i++) {
    if (node.children[prefix[i]]) {
      node = node.children[prefix[i]];
    } else {
      return output;
    }
  }

  findAllWords(node, output);

  return output;
};

function findAllWords(node, arr) {
  if (node.end) {
    arr.unshift(node.getWord());
  }

  for (var child in node.children) {
    findAllWords(node.children[child], arr);
  }
}
