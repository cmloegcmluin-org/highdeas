/* The group namer. A group takes a single name, so when several of the notes being
   folded are named, the page asks which it should be — here, in its own voice, the way
   the confirm (ask.js) and the editor speak — rather than choosing for the user or
   stringing every name along the title.

   HighdeasNameGroup(names) opens the dialog with a chip per candidate name and a field
   pre-filled with the first, and answers with a promise: the name settled on, or null if
   the ask was dismissed. A chip fills the field; the field is what the answer is read
   from, so picking a note's name and typing a fresh one are the same act. A name that
   matches one of the notes rises to the group and that note's bullet drops its prefix;
   a name that matches none leaves every prefix in place — the server reads which.

   Loaded on the inbox page, ahead of inbox.js. */
(function () {
  'use strict';

  var dialog = document.getElementById('name-group');
  if (!dialog || !dialog.showModal) return;
  var chips = document.getElementById('name-group-chips');
  var field = document.getElementById('name-group-name');
  var ok = document.getElementById('name-group-ok');
  var cancel = document.getElementById('name-group-cancel');
  var answer = null;

  /* Closing the dialog fires 'close', which settles the ask as dismissed — so the
     resolver is taken before the close, and the event that follows finds nothing left
     to answer. */
  function settle(name) {
    var resolve = answer;
    answer = null;
    if (dialog.open) dialog.close();
    if (resolve) resolve(name);
  }

  function chip(name) {
    var button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn name-group-chip';
    button.textContent = name;
    button.addEventListener('click', function () {
      field.value = name;
      field.focus();
    });
    return button;
  }

  function ask(names) {
    settle(null);
    chips.replaceChildren.apply(chips, names.map(chip));
    field.value = names[0] || '';
    dialog.showModal();
    field.focus();
    field.select();
    return new Promise(function (resolve) { answer = resolve; });
  }

  function confirm() { settle(field.value.trim()); }

  ok.addEventListener('click', confirm);
  cancel.addEventListener('click', function () { settle(null); });
  /* Enter anywhere in the field confirms, not only a click on the button. */
  field.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') { event.preventDefault(); confirm(); }
  });
  /* Esc and a click on the backdrop both arrive here, and both mean "don't group". */
  dialog.addEventListener('close', function () { settle(null); });

  window.HighdeasNameGroup = ask;
}());
