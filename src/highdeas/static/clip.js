/* The one move every copy button in the app makes: put the text on the clipboard, then
   hold a green check on the button that asked for it for a beat, since the clipboard
   gives no sign of its own that anything landed. Five buttons press it — a row's
   transcript and name, the editor's two fields, and the error notice's sentence — and
   they are spread across two files that don't otherwise know about each other.

   What a refused clipboard means is left to whoever called: a row complains into the
   notice, the editor has no bar to complain into, and the notice must stay silent —
   saying anything there would overwrite the very words the press was reaching for. So
   this hands back the promise and takes no view. */
(function () {
  'use strict';

  var COPIED_MS = 1200;

  function copy(btn, text) {
    var written;
    try {
      written = navigator.clipboard.writeText(text);
    } catch (err) {
      return Promise.reject(err);  // no Clipboard API at all (insecure origin, old webview)
    }
    return written.then(function () {
      btn.classList.add('copied');
      clearTimeout(btn._copied);
      btn._copied = setTimeout(function () { btn.classList.remove('copied'); }, COPIED_MS);
    });
  }

  window.HighdeasClip = { copy: copy };
})();
