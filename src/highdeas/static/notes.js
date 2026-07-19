/* What a note is made of. A note is stored as plain text, so a list is just its
   Markdown line ("- x", "1. x") — the form the routers turn into HTML for Notesnook
   and into styled paragraphs for a Drive .docx.

   Two surfaces have to draw those lines: the inbox row's preview and the editor
   dialog's body. Reading the grammar from here is what keeps them showing the same
   note — a list that reads as bullets in the dialog and as dashes in the row is the
   bug this file exists to make impossible.

   render(text) builds the blocks: one <p> per prose line, one <ul>/<ol> per run of
   list lines. read(root) walks them back to lines. They are inverses, so a note
   survives any number of trips through the editor unchanged. */
(function () {
  'use strict';

  var BULLET = /^\s*[-*•]\s+(.*)$/;
  var NUMBER = /^\s*\d+[.)]\s+(.*)$/;

  // The list a line belongs to ("UL"/"OL"), and the text left once its marker is off.
  // Null tag for prose, which is every line that opens with neither marker.
  function lineOf(line) {
    var bullet = BULLET.exec(line);
    if (bullet) return { tag: 'UL', text: bullet[1] };
    var number = NUMBER.exec(line);
    if (number) return { tag: 'OL', text: number[1] };
    return { tag: null, text: line };
  }

  function render(text) {
    var frag = document.createDocumentFragment();
    var list = null;
    var listTag = null;
    text.split('\n').forEach(function (line) {
      var parsed = lineOf(line);
      if (parsed.tag !== listTag) {
        list = parsed.tag ? frag.appendChild(document.createElement(parsed.tag)) : null;
        listTag = parsed.tag;
      }
      if (list) {
        var item = document.createElement('li');
        item.textContent = parsed.text;
        list.appendChild(item);
      } else {
        frag.appendChild(paragraph(parsed.text));
      }
    });
    if (!frag.childNodes.length) frag.appendChild(paragraph(''));
    return frag;
  }

  // An empty block still has to be a line you can put the caret on, so it carries the
  // filler <br> the engine would otherwise park there itself.
  function paragraph(text) {
    var block = document.createElement('p');
    if (text) block.textContent = text;
    else block.appendChild(document.createElement('br'));
    return block;
  }

  function flatten(element) {
    var text = '';
    Array.prototype.forEach.call(element.childNodes, function (node) {
      if (node.nodeType === Node.TEXT_NODE) text += node.nodeValue;
      else if (node.nodeType === Node.ELEMENT_NODE) text += node.tagName === 'BR' ? '\n' : flatten(node);
    });
    // Chromium parks a filler <br> at the end of an otherwise empty block.
    return text.replace(/\n$/, '');
  }

  // One line per <li>, one per prose block. A block's own line breaks become lines too,
  // so a <br> typed into a paragraph reads back as the newline it looks like.
  function read(root) {
    var lines = [];
    Array.prototype.forEach.call(root.childNodes, function (node) {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.nodeValue.trim()) lines.push(node.nodeValue);
      } else if (node.nodeType !== Node.ELEMENT_NODE) {
        return;
      } else if (node.tagName === 'UL' || node.tagName === 'OL') {
        var ordered = node.tagName === 'OL';
        var index = 0;
        Array.prototype.forEach.call(node.children, function (item) {
          if (item.tagName !== 'LI') return;
          index += 1;
          lines.push((ordered ? index + '. ' : '- ') + flatten(item).replace(/\n/g, ' '));
        });
      } else {
        flatten(node).split('\n').forEach(function (line) { lines.push(line); });
      }
    });
    while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
    return lines.join('\n');
  }

  window.HighdeasNote = { render: render, read: read };
})();
