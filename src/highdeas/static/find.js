/* The page's own find, in place of the browser's. A search box sits in the title bar from
   the start — magnifier and all — and filters the list down to the rows whose name or
   transcript holds what you type. It reaches the whole transcript, including the part the
   three-line preview clips off and the part the bin's scrolling text box hides, neither of
   which the browser's own find can see. Ctrl+F just puts the cursor in the box; Esc clears
   it and brings the whole list back.

   Loaded from the shared chrome, so the inbox and the bin both have it. It knows nothing
   about what a row is beyond its name and its text: it filters the inbox's .memo rows and
   the bin's .row rows the same way, and re-runs itself whenever the list changes under an
   open search — a recording the poll splices in, a merge that rebuilds the rows — so a
   note that arrives mid-search is filtered like the rest. */
(function () {
  'use strict';

  var input = document.getElementById('find-input');
  var content = document.getElementById('content');
  if (!input || !content) return;

  var tally = document.getElementById('find-tally');

  function rows() {
    return Array.prototype.slice.call(content.querySelectorAll('.memo, .row'));
  }

  // What a row is searched by: its name and its transcript, wherever each of them lives.
  // The inbox keeps the name in an editable field and the bin in a plain cell.
  //
  // The transcript is the whole note, not the clipped preview — reaching the text a row
  // only shows three lines of is the whole point of not leaving this to the browser's
  // find. An inbox row carries the note as written in an attribute, since its preview
  // draws the list markers as a real list and so no longer reads the note back: "- milk"
  // becomes a bullet saying "milk", and the cell ran the items together besides. The bin
  // prints the note plainly, so there the cell IS the note.
  function noteOf(row) {
    if (row.dataset.transcript !== undefined) return row.dataset.transcript;
    var body = row.querySelector('.text');
    return body ? body.textContent : '';
  }

  function haystack(row) {
    var parts = [];
    var field = row.querySelector('input[name=name]');
    if (field) parts.push(field.value);
    var name = row.querySelector('.name');
    if (name) parts.push(name.textContent);
    parts.push(noteOf(row));
    return parts.join(' ').toLowerCase();
  }

  function query() { return input.value.trim().toLowerCase(); }

  // The line between two rows is a separate element sitting before the lower one, so a
  // hidden row would strand its line. Show the separator above a row only when that row
  // shows AND a row already showed above it: no line leads the first match, and exactly
  // one sits between any two. Only classes are toggled here — never the child list — so
  // the observer below never trips on this work.
  function apply() {
    var term = query();
    var filtering = term.length > 0;
    var all = rows();
    var shown = 0;
    var seen = false;
    all.forEach(function (row) {
      var hit = !filtering || haystack(row).indexOf(term) >= 0;
      row.classList.toggle('find-miss', !hit);
      var before = row.previousElementSibling;
      if (before && before.classList.contains('sep')) {
        before.classList.toggle('find-miss', !(hit && seen));
      }
      if (hit) { shown += 1; seen = true; }
    });
    report(filtering, shown, all.length);
  }

  function report(filtering, shown, total) {
    if (!tally) return;
    if (!filtering) tally.textContent = '';
    else if (total === 0) tally.textContent = 'Nothing to find';
    else if (shown === 0) tally.textContent = 'No matches';
    else tally.textContent = shown + ' of ' + total;
  }

  input.addEventListener('input', apply);

  // An open dialog keeps the keyboard to itself: the editor's body is a long text the
  // browser's own find is the right tool for, and Esc there closes the editor.
  function dialogOpen() { return !!document.querySelector('dialog[open]'); }

  document.addEventListener('keydown', function (event) {
    var isFind = (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
      && event.key.toLowerCase() === 'f';
    if (isFind) {
      if (dialogOpen()) return;  // let the browser's find work the note being edited
      event.preventDefault();    // take Ctrl+F off the browser: ours reaches the clipped text
      input.focus();
      input.select();
    } else if (event.key === 'Escape' && document.activeElement === input) {
      // The box is always there, so Esc empties it rather than closing it, and hands focus
      // back to the page so the whole list is in front of you again.
      input.value = '';
      apply();
      input.blur();
    }
  });

  // The list changes under an open search, so the filter re-runs when it does — otherwise
  // a row the poll splices in arrives unfiltered, and a merge that rebuilds every row
  // comes back with the search forgotten. A MutationObserver's callback is a microtask
  // delivered once after the mutations settle, so a whole merge's worth of adds and
  // removes collapses into one re-run, timed after the list is whole and before the next
  // paint. Watching only childList (rows and separators coming and going) while this
  // toggles only classes means it never sees its own work and loops; nothing to re-filter
  // while the box is empty, so it stays out of the poll's way until a search is on.
  if (window.MutationObserver) {
    new MutationObserver(function () {
      if (query()) apply();
    }).observe(content, { childList: true, subtree: true });
  }
}());
