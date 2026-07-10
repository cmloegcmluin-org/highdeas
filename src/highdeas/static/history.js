/* The inbox's undo stack. An action is recorded as the pair of steps that walk it back
   and forward again, so this file never has to know what a memo is — inbox.js hands it
   two thunks and it drives the Undo/Redo buttons and Ctrl+Z from there.

   It holds the actions whose rows can be handed back. A submitted note is in Notesnook and
   a trashed one is in the bin; breaking a group all the way up is a walk back of its own,
   past however many steps are still recorded for it. Those three empty the stack rather
   than leave one that would quietly reach past them to undo something older and unrelated.
   A step names the row it touched rather than holding it, so grouping — which takes the
   whole list back from the server — can join the stack like anything else. */
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
  // click read as the same action. The class stays on afterwards, which costs nothing
  // (the animation fills neither end); dropping and re-adding it around a forced reflow
  // is what restarts the blink, so a held Ctrl+Z blinks once per step.
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

  window.HighdeasHistory = { did: did, clear: clear };
})();
