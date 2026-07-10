/* The app's own confirm, in place of the browser's. window.confirm() stamps
   "127.0.0.1:<port> says" over the top of whatever it is asked to ask, and returns a
   boolean the moment it is called; this asks in the page's own voice and answers with a
   promise, which is the whole of the difference at the call sites.

   Two ways in. A form that must ask first carries the question in data-confirm (and
   data-danger when what it does cannot be undone): its submit is held, the question put,
   and the form posted only on a yes. Everything else calls window.HighdeasAsk directly.

   Loaded on every page, ahead of the page's own scripts. */
(function () {
  var dialog = document.getElementById('ask');
  if (!dialog) return;
  var text = document.getElementById('ask-text');
  var ok = document.getElementById('ask-ok');
  var cancel = document.getElementById('ask-cancel');
  var answer = null;

  /* Closing the dialog fires 'close', which settles it as a no — so the resolver is
     taken before the close, and the event that follows finds nothing left to answer. */
  function settle(said) {
    var resolve = answer;
    answer = null;
    if (dialog.open) dialog.close();
    if (resolve) resolve(said);
  }

  function ask(question, destructive) {
    settle(false);
    text.textContent = question;
    ok.classList.toggle('danger', !!destructive);
    dialog.showModal();
    return new Promise(function (resolve) { answer = resolve; });
  }

  ok.addEventListener('click', function () { settle(true); });
  cancel.addEventListener('click', function () { settle(false); });
  /* Esc and a click on the backdrop both arrive here, and both mean no. */
  dialog.addEventListener('close', function () { settle(false); });

  document.querySelectorAll('form[data-confirm]').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      ask(form.dataset.confirm, 'danger' in form.dataset).then(function (yes) {
        // form.submit() posts without firing this listener again.
        if (yes) form.submit();
      });
    });
  });

  window.HighdeasAsk = ask;
}());
