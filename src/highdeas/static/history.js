/* The inbox's undo stack. An action is recorded as the pair of steps that walk it back
   and forward again, so this file never has to know what a memo is — inbox.js hands it
   two thunks and it drives the Undo/Redo buttons and Ctrl+Z from there.

   It holds only the actions that can be walked back. Submitting, trashing, and grouping
   can't be, and they empty the stack rather than leave a step that would quietly reach
   past them to undo something older and unrelated. */
(function () {
  'use strict';

  var undoBtn = document.getElementById('undo');
  var redoBtn = document.getElementById('redo');
  if (!undoBtn || !redoBtn) return;

  var done = [];    // actions taken, most recent last
  var undone = [];  // actions walked back, ready to be walked forward again

  function sync() {
    undoBtn.disabled = !done.length;
    redoBtn.disabled = !undone.length;
  }

  // Record an action that has already happened. Doing something new abandons whatever
  // was walked back before it: the branch it would have been redone onto is gone.
  function did(action) {
    done.push(action);
    undone.length = 0;
    sync();
  }

  function clear() {
    done.length = 0;
    undone.length = 0;
    sync();
  }

  // A step walked back leaves no mark on the page — the row it touched may well be
  // scrolled out of sight. Blink the button the step belongs to, so a shortcut and a
  // click read as the same action. Restarting the animation costs a reflow, which is
  // what makes a held Ctrl+Z blink once per step instead of sticking lit.
  function flash(button) {
    button.classList.remove('flash');
    void button.offsetWidth;
    button.classList.add('flash');
  }

  function step(from, onto, direction) {
    var action = from.pop();
    if (!action) return false;
    onto.push(action);
    sync();
    action[direction]();
    return true;
  }

  function undo() { if (step(done, undone, 'undo')) flash(undoBtn); }
  function redo() { if (step(undone, done, 'redo')) flash(redoBtn); }

  // Inside a text field or the editor's body, Ctrl+Z belongs to the browser: its
  // per-field typing history is the one the caret is standing in, and it is better than
  // anything we would put in front of it. The open editor is off limits for the same
  // reason — its dialog holds a copy of the note, and walking a row out from under it
  // would leave the two disagreeing.
  function browsers(target) {
    return !!(target.closest && target.closest('input, textarea, [contenteditable]'))
      || !!document.querySelector('dialog[open]');
  }

  document.addEventListener('keydown', function (event) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey) return;
    var key = event.key.toLowerCase();
    if (key !== 'z' && key !== 'y') return;
    if (browsers(event.target)) return;
    event.preventDefault();
    if (key === 'y' || event.shiftKey) redo();
    else undo();
  });

  undoBtn.addEventListener('click', undo);
  redoBtn.addEventListener('click', redo);
  [undoBtn, redoBtn].forEach(function (button) {
    button.addEventListener('animationend', function () { button.classList.remove('flash'); });
  });

  window.HighdeasHistory = { did: did, clear: clear };
})();
