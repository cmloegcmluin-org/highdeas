"""Local Flask app: the inbox and bin pages for editing and routing memos."""
from urllib.parse import quote

from flask import Flask, jsonify, redirect, render_template_string, request, send_from_directory

# Inline, self-contained brand icons for the route toggle (no external assets).
NOTESNOOK_SVG = (
    '<svg viewBox="162 160 700 700" xmlns="http://www.w3.org/2000/svg" fill="#008837" aria-label="Notesnook">'
    '<path d="M724.985 682.919C707.73 733.33 673.15 775.984 627.397 803.291C581.645 830.598 527.687 840.787 '
    "475.128 832.044C422.568 823.301 374.814 796.194 340.365 755.546C305.916 714.898 287.006 663.347 287 "
    "610.064V499.814L366.121 532.867V610.019C366.114 630.798 370.555 651.337 379.145 670.256C387.735 689.176 "
    "400.276 706.037 415.925 719.707C418.895 722.294 421.978 724.814 425.161 727.166C448.518 744.554 476.563 "
    "754.518 505.655 755.763C506.645 755.763 507.601 755.842 508.58 755.864C509.559 755.887 510.83 755.864 "
    "511.955 755.864C513.08 755.864 514.205 755.864 515.33 755.864C516.455 755.864 517.265 755.864 518.255 "
    "755.763C547.336 754.515 575.371 744.56 598.726 727.188C601.899 724.837 604.981 722.328 607.963 "
    '719.741C628.519 701.761 643.619 678.375 651.545 652.241L724.985 682.919Z"/>'
    '<path d="M737 414V610.065C737 612.596 737 615.139 736.842 617.67L657.879 584.651V414C657.866 376.316 '
    "643.272 340.099 617.154 312.934C591.035 285.77 555.419 269.766 517.765 268.274C480.11 266.782 443.339 "
    "279.918 415.154 304.931C386.968 329.944 369.554 364.893 366.56 402.457C366.279 406.26 366.121 410.119 "
    '366.121 414V462.712L287 429.637V189H512C571.674 189 628.903 212.705 671.099 254.901C713.295 297.097 737 354.326 737 414Z"/>'
    "</svg>"
)
DRIVE_SVG = (
    '<svg viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">'
    '<path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>'
    '<path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44a9.06 9.06 0 0 0 -1.2 4.5h27.5z" fill="#00ac47"/>'
    '<path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z" fill="#ea4335"/>'
    '<path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>'
    '<path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/>'
    '<path d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z" fill="#ffba00"/>'
    "</svg>"
)
TRASH_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg>'
)

# One stylesheet shared by the inbox and bin pages so their chrome is identical —
# same title bar, top-right link, and header row — and nothing jumps when you flip
# between them. The two grids share widths too: a 44px row-handle column, then
# 282 | flex | a 334px middle band | two 104px action columns, so only the middle
# band's contents differ per page.
_STYLE = """<style>
  /* Reserve the scrollbar gutter on every page so a page with a scrollbar and one
     without stay the same width — otherwise margin:auto re-centers and the layout
     shifts sideways when you flip between the inbox and bin views. */
  :root { color-scheme: light dark; scrollbar-gutter: stable; }
  body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; max-width: 1300px;
         margin: 0 auto; padding: 0 24px 24px; line-height: 1.45; }
  h1 { font-size: 1.35rem; margin: 0; }
  #count { opacity: .55; font-weight: 400; }
  /* The title bar and the column headers stay pinned while the rows scroll, so the
     item count and the bulk (Submit/Trash/Restore/Empty) buttons are always in reach. */
  .frozen { position: sticky; top: 0; z-index: 3; background: Canvas; padding-top: 24px; }
  .topbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
  .topbar a { color: #3b82f6; text-decoration: none; font-size: .9rem; }
  /* Manual refresh sits with the Bin link on the right; a link-style button so the
     two read as one row of controls rather than a button shoving the link around. */
  .topbar .links { display: flex; align-items: center; gap: 16px; }
  .refresh { font: inherit; font-size: .9rem; color: #3b82f6; background: transparent;
             border: none; padding: 0; cursor: pointer; }
  .refresh:disabled { opacity: .5; cursor: default; }
  /* Shown only when a submit/trash fails, so a note that didn't actually send stays
     visible and explained instead of silently vanishing from the list. */
  .notice { margin: 12px 0 0; padding: 10px 12px; border-radius: 8px; font-size: .9rem;
            color: #e5484d; background: rgba(229,72,77,.12); border: 1px solid rgba(229,72,77,.4); }
  .notice[hidden] { display: none; }
  /* Consolidating acts on whichever rows are ticked, so its button belongs with the
     selection rather than in a column header. The bar is absent until something is
     picked, which keeps the page as quiet as it was before. */
  .selbar { display: flex; align-items: center; gap: 12px; margin: 12px 0 0; padding: 8px 12px;
            border-radius: 8px; font-size: .9rem;
            background: rgba(59,130,246,.1); border: 1px solid rgba(59,130,246,.4); }
  .selbar[hidden] { display: none; }
  #selcount { margin-right: auto; opacity: .75; }
  .selbtn { font: inherit; font-size: .8rem; padding: 5px 11px; border-radius: 7px; cursor: pointer;
            background: transparent; color: inherit; border: 1px solid rgba(128,128,128,.4);
            transition: color .15s, border-color .15s; }
  .selbtn:hover:not(:disabled) { border-color: #3b82f6; color: #3b82f6; }
  .selbtn:disabled { opacity: .45; cursor: default; }
  .empty { opacity: .7; padding: 48px 0; text-align: center; }
  .grid { display: grid; gap: 14px 18px; align-items: center; }
  .grid.inbox  { grid-template-columns: 44px 282px minmax(220px, 1fr) 34px 200px 100px 104px 104px; }
  .grid.bin    { grid-template-columns: 44px 282px minmax(220px, 1fr) 170px 56px 108px 104px 104px; }
  .grid.body { margin-top: 12px; }
  .grid .head { font-size: .7rem; text-transform: uppercase; letter-spacing: .04em; opacity: .55;
                display: flex; align-items: flex-end; min-height: 32px;
                padding-bottom: 4px; border-bottom: 1px solid rgba(128,128,128,.25); }
  .grid .sep { grid-column: 1 / -1; border-top: 1px solid rgba(128,128,128,.18); }
  .num { font-size: .8rem; opacity: .4; text-align: right; font-variant-numeric: tabular-nums; }
  /* Spreadsheet-style row header: grab the number to drag the row somewhere else,
     tick the box beside it to fold the row into another. */
  .rowhead { display: flex; align-items: center; justify-content: flex-end; gap: 5px; }
  .rowhead .pick { margin: 0; cursor: pointer; }
  /* Bulk actions live in their own column headers so they sit directly over the
     column they act on, instead of being pushed around by the topbar link. */
  .head form { width: 100%; margin: 0; }
  .head-btn { font: inherit; font-size: .72rem; text-transform: none; letter-spacing: normal;
              width: 100%; padding: 4px 9px; border-radius: 7px; cursor: pointer; background: transparent;
              color: inherit; border: 1px solid rgba(128,128,128,.4);
              transition: color .15s, border-color .15s; }
  #submit-all:hover, .restore-all:hover { border-color: #3b82f6; color: #3b82f6; }
  #trash-all:hover, .empty-bin:hover { border-color: #e5484d; color: #e5484d; }

  /* Inbox rows */
  .memo { display: contents; }
  .memo audio { width: 100%; }
  .memo textarea, .memo input[type=text] {
    width: 100%; box-sizing: border-box; padding: 8px; font: inherit;
    border: 1px solid rgba(128,128,128,.4); border-radius: 8px; background: transparent; color: inherit; }
  .memo textarea { min-height: 60px; resize: vertical; }
  /* A row whose submit/trash just failed: outline its fields so it's obvious which
     one stayed behind. */
  .memo.failed textarea, .memo.failed input[type=text] { border-color: #e5484d; }
  /* A row mid-request: dimmed and locked so a bulk run reads as working through the
     list, and so a row can't be double-submitted. A display:contents row generates no
     box of its own, so dimming has to reach its cells — set on the row it does nothing. */
  .memo.sending > * { opacity: .5; transition: opacity .15s; }
  .memo.dragging > * { opacity: .35; }
  .memo .num { cursor: grab; }
  .memo .num:active { cursor: grabbing; }
  .memo.picked .num { opacity: 1; color: #3b82f6; }
  .memo button:disabled { cursor: default; }
  .memo .copy { font: inherit; font-size: 1.4rem; line-height: 1; padding: 0; height: 40px; width: 100%;
                display: flex; align-items: center; justify-content: center; cursor: pointer;
                background: transparent; color: inherit; opacity: .45; border-radius: 8px;
                border: 1px solid rgba(128,128,128,.35);
                transition: opacity .15s, color .15s, border-color .15s; }
  .memo .copy:hover { opacity: 1; color: #3b82f6; border-color: #3b82f6; }
  .memo .go { font: inherit; padding: 9px 0; width: 100%; border-radius: 8px; border: none;
              background: #3b82f6; color: #fff; cursor: pointer; }
  .memo .del { padding: 9px 0; width: 100%; border-radius: 8px; cursor: pointer;
               background: transparent; color: inherit; opacity: .4;
               border: 1px solid rgba(128,128,128,.35);
               transition: color .15s, opacity .15s, border-color .15s; }
  .memo .del:hover { opacity: 1; color: #e5484d; border-color: #e5484d; }
  .memo .del svg { width: 16px; height: 16px; display: block; margin: 0 auto; }
  .toggle { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
  .toggle input { position: absolute; width: 0; height: 0; opacity: 0; }
  .toggle .ic { width: 18px; height: 18px; opacity: .35; transition: opacity .15s; }
  .toggle .ic svg { width: 100%; height: 100%; display: block; }
  .toggle .ns { opacity: 1; }
  .toggle input:checked ~ .ns { opacity: .35; }
  .toggle input:checked ~ .dr { opacity: 1; }
  .toggle .track { position: relative; flex: none; width: 40px; height: 22px; border-radius: 999px;
                   background: rgba(128,128,128,.4); transition: background .15s; }
  .toggle .track::after { content: ""; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px;
                          border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.35); transition: transform .15s; }
  .toggle input:checked ~ .track { background: #2684fc; }
  .toggle input:checked ~ .track::after { transform: translateX(18px); }

  /* Bin rows */
  .row { display: contents; }
  .row audio { width: 100%; }
  .row .text { font-size: .9rem; white-space: pre-wrap; max-height: 5.5em; overflow: auto; opacity: .85; }
  .row .name { font-weight: 600; }
  .row .dest { display: flex; align-items: center; }
  .row .dest svg { width: 20px; height: 20px; display: block; }
  .row .destlink { display: flex; align-items: center; text-decoration: none;
                   background: transparent; border: none; padding: 0; cursor: pointer; }
  .row .dest form { display: contents; }
  .row .when { font-size: .8rem; opacity: .6; }
  .binbtn { font: inherit; padding: 8px 0; width: 100%; border-radius: 8px; cursor: pointer;
            background: transparent; color: inherit; border: 1px solid rgba(128,128,128,.4);
            transition: color .15s, border-color .15s; }
  .binbtn.restore:hover { border-color: #3b82f6; color: #3b82f6; }
  .binbtn.purge:hover { border-color: #e5484d; color: #e5484d; }
  .row form { width: 100%; margin: 0; }
</style>"""


# The inbox page's frozen top: title bar (with the live item count) plus the
# column headers that carry the bulk Submit/Trash buttons. Rendered with `memos`,
# so the headers only appear when there's something to act on.
_PAGE_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inbox</title>
""" + _STYLE + """
</head>
<body>
  <div class="frozen">
    <div class="topbar">
      <h1>Inbox <span id="count">— {{ memos|length }} item{{ 's' if memos|length != 1 else '' }}</span></h1>
      <div class="links">
        <button type="button" id="refresh" class="refresh" title="Check for new notes now">Refresh</button>
        <a href="/bin">Bin →</a>
      </div>
    </div>
    <div id="notice" class="notice" role="alert" hidden></div>
    <div id="selection" class="selbar" hidden>
      <span id="selcount"></span>
      <button type="button" id="consolidate" class="selbtn" disabled
              title="Fold the ticked notes into the topmost one">Consolidate</button>
      <button type="button" id="clear-picks" class="selbtn">Clear</button>
    </div>
    {% if memos %}
    <div class="grid inbox headrow">
      <div class="head"></div>
      <div class="head">Audio</div>
      <div class="head">Transcript</div>
      <div class="head"></div>
      <div class="head">Name</div>
      <div class="head">Route</div>
      <div class="head"><button type="button" id="submit-all" class="head-btn">Submit all</button></div>
      <div class="head"><button type="button" id="trash-all" class="head-btn">Trash all</button></div>
    </div>
    {% endif %}
  </div>
  <main id="content">"""


# The inbox memo rows alone, so they can be rendered both inside the full page
# and returned bare for the client's /pending poll (which splices in new rows).
CONTENT_HTML = """{% if not memos %}
    {% if incoming %}
    <p class="empty">Transcribing your memos…</p>
    {% else %}
    <p class="empty">Your inbox is empty. Record a memo and it'll show up here.</p>
    {% endif %}
  {% else %}
  <div class="grid inbox body">
    {% for m in memos %}
    {% if not loop.first %}<div class="sep"></div>{% endif %}
    <div class="memo" data-file="{{ m.audio_filename }}">
      <div class="rowhead">
        <input type="checkbox" class="pick" aria-label="Pick this note for consolidating">
        <span class="num" draggable="true" title="Drag to move this note">{{ loop.index }}</span>
      </div>
      <audio controls src="/audio/{{ m.audio_filename }}"></audio>
      <textarea name="transcript" aria-label="Transcript">{{ m.transcript }}</textarea>
      <button type="button" class="copy" title="Move transcript into Name" aria-label="Move transcript into Name">&rsaquo;</button>
      <input type="text" name="name" value="{{ m.name }}" placeholder="Name…" autocomplete="off" aria-label="Name">
      <label class="toggle" title="Left = Notesnook, right = Google Drive">
        <input type="checkbox" name="route" value="drive" {{ 'checked' if m.route == 'drive' }}>
        <span class="ic ns" aria-label="Notesnook">""" + NOTESNOOK_SVG + """</span>
        <span class="track"></span>
        <span class="ic dr" aria-label="Google Drive">""" + DRIVE_SVG + """</span>
      </label>
      <button type="button" class="go">Submit</button>
      <button type="button" class="del" title="Delete" aria-label="Delete">""" + TRASH_SVG + """</button>
    </div>
    {% endfor %}
  </div>
  {% endif %}"""


_PAGE_TAIL = """  </main>
<script>
(function () {
  var content = document.getElementById('content');
  if (!content) return;

  // Rows this window has already submitted or trashed. A poll's snapshot can
  // still list one as pending (it was taken before the POST landed), so we skip
  // re-adding anything here — otherwise an optimistically-removed row would flash
  // back in.
  var retired = {};
  var countEl = document.getElementById('count');
  var notice = document.getElementById('notice');
  var selbar = document.getElementById('selection');
  var selcount = document.getElementById('selcount');
  var consolidateBtn = document.getElementById('consolidate');
  var clearPicks = document.getElementById('clear-picks');

  // A submit/trash only leaves the list once the server confirms it; on failure the
  // row stays and we surface why here, so a note that never sent can't silently vanish.
  function notify(msg) { if (notice) { notice.textContent = msg; notice.hidden = false; } }
  function clearNotice() { if (notice) { notice.textContent = ''; notice.hidden = true; } }
  function describe(err) { return err && err.message ? ' (' + err.message + ')' : ''; }

  function rows() { return Array.prototype.slice.call(content.querySelectorAll('.memo')); }
  function picked() { return rows().filter(function (m) { return m.querySelector('.pick').checked; }); }

  function updateCount() {
    if (!countEl) return;
    var n = rows().length;
    countEl.textContent = '— ' + n + ' item' + (n === 1 ? '' : 's');
  }

  // Ticking rows arms the selection bar. Consolidating needs two of them: one note
  // folded into itself is nothing.
  function syncPicks() {
    var chosen = picked();
    rows().forEach(function (memo) {
      memo.classList.toggle('picked', memo.querySelector('.pick').checked);
    });
    if (!selbar) return;
    selbar.hidden = chosen.length === 0;
    selcount.textContent = chosen.length + ' selected';
    consolidateBtn.disabled = chosen.length < 2;
  }

  function sep() {
    var el = document.createElement('div');
    el.className = 'sep';
    return el;
  }

  // Separators and row numbers both describe the current order — numbers are a
  // spreadsheet-style anchor, not IDs, so they always run 1..N down the page. Rebuild
  // both from the DOM after anything is added, removed, or dragged into a new place.
  function resync() {
    var grid = content.querySelector('.grid');
    if (grid) {
      grid.querySelectorAll('.sep').forEach(function (el) { el.remove(); });
      rows().forEach(function (memo, i) {
        if (i) grid.insertBefore(sep(), memo);
        memo.querySelector('.num').textContent = i + 1;
      });
    }
    updateCount();
    syncPicks();
  }

  function urlFor(prefix, memo) { return prefix + encodeURIComponent(memo.dataset.file); }

  function fields(memo) {
    return new URLSearchParams({
      name: memo.querySelector('input[name=name]').value,
      transcript: memo.querySelector('textarea[name=transcript]').value,
      route: memo.querySelector('input[name=route]').checked ? 'drive' : 'notesnook',
    });
  }

  function post(url, data) { return fetch(url, { method: 'POST', body: data }); }

  function save(memo) { return post(urlFor('/edit/', memo), fields(memo)); }

  function scheduleSave(memo) {
    clearTimeout(memo._timer);
    memo._timer = setTimeout(function () { save(memo); }, 400);
  }

  function flush(memo) { clearTimeout(memo._timer); return save(memo); }

  function showEmpty() {
    var p = document.createElement('p');
    p.className = 'empty';
    p.textContent = "Your inbox is empty. Record a memo and it'll show up here.";
    content.innerHTML = '';
    content.appendChild(p);
    var headrow = document.querySelector('.frozen .headrow');
    if (headrow) headrow.remove();
    resync();
  }

  function removeRow(memo) {
    var grid = memo.closest('.grid');
    memo.remove();
    if (grid && !grid.querySelector('.memo')) showEmpty();
    else resync();
  }

  // Dim and lock a row while its request is in flight, so a bulk run visibly works
  // through the list one row at a time instead of rows just vanishing without warning.
  function setBusy(memo, busy) {
    memo.classList.toggle('sending', busy);
    ['.go', '.del'].forEach(function (sel) {
      var btn = memo.querySelector(sel);
      if (btn) btn.disabled = busy;
    });
  }

  // Remove the row only after a 2xx: the memo is retired server-side only on success,
  // so mirror that here. A non-ok response (routing failed, memo still pending) leaves
  // the row in place, flagged, and rejects, so callers can report the failure.
  function retireOnOk(memo, response) {
    memo.classList.remove('failed');
    setBusy(memo, true);
    return Promise.resolve(response).then(function (r) {
      if (!r.ok) return r.text().then(function (t) { throw new Error(t || 'Failed'); });
      retired[memo.dataset.file] = true;
      removeRow(memo);
    }).catch(function (err) {
      setBusy(memo, false);
      memo.classList.add('failed');
      throw err;
    });
  }

  function submitRow(memo) {
    clearTimeout(memo._timer);
    var go = memo.querySelector('.go');
    if (go) go.textContent = 'Sending…';
    return retireOnOk(memo, post(urlFor('/submit/', memo), fields(memo)))
      .catch(function (err) { if (go) go.textContent = 'Submit'; throw err; });
  }

  function trashRow(memo) {
    clearTimeout(memo._timer);
    return retireOnOk(memo, post(urlFor('/delete/', memo)));
  }

  // A .memo is display:contents, so it has no box of its own to grab or hit-test. Its
  // number cell is the handle, and the row under the pointer is reached through
  // whichever of its cells the pointer happens to be over.
  var dragged = null;

  function nextRow(memo) {
    var el = memo.nextElementSibling;
    while (el && !el.classList.contains('memo')) el = el.nextElementSibling;
    return el;
  }

  // A row occupies one grid line across several cells of differing height; the line's
  // extent is their union, so a drop reads the same wherever the pointer crosses it.
  function midpoint(memo) {
    var top = Infinity;
    var bottom = -Infinity;
    Array.prototype.forEach.call(memo.children, function (cell) {
      var box = cell.getBoundingClientRect();
      top = Math.min(top, box.top);
      bottom = Math.max(bottom, box.bottom);
    });
    return (top + bottom) / 2;
  }

  function saveOrder() {
    var data = new URLSearchParams();
    rows().forEach(function (memo) { data.append('order', memo.dataset.file); });
    post('/reorder', data).then(function (r) {
      if (!r.ok) throw new Error('Failed');
    }).catch(function () {
      notify("Couldn't save the new order — the inbox will read back in recorded order next time you open it.");
    });
  }

  // Rows move as you drag over them, so the list you let go of is the list you keep.
  content.addEventListener('dragover', function (event) {
    if (!dragged) return;  // dragging text out of a textarea, not a row
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    var over = event.target.closest('.memo');
    if (!over || over === dragged) return;
    var below = event.clientY > midpoint(over);
    if (below ? nextRow(over) === dragged : nextRow(dragged) === over) return;
    over.parentElement.insertBefore(dragged, below ? nextRow(over) : over);
    resync();
  });
  content.addEventListener('drop', function (event) { if (dragged) event.preventDefault(); });

  function wire(memo) {
    var transcript = memo.querySelector('textarea[name=transcript]');
    var name = memo.querySelector('input[name=name]');
    var route = memo.querySelector('input[name=route]');
    var handle = memo.querySelector('.num');
    [transcript, name].forEach(function (el) {
      el.addEventListener('input', function () { scheduleSave(memo); });
      el.addEventListener('blur', function () { flush(memo); });
    });
    route.addEventListener('change', function () { flush(memo); });
    memo.querySelector('.pick').addEventListener('change', syncPicks);
    handle.addEventListener('dragstart', function (event) {
      dragged = memo;
      memo.classList.add('dragging');
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', memo.dataset.file);
    });
    handle.addEventListener('dragend', function () {
      memo.classList.remove('dragging');
      dragged = null;
      saveOrder();
    });
    memo.querySelector('.copy').addEventListener('click', function () {
      name.value = transcript.value;
      transcript.value = '';
      flush(memo);
    });
    memo.querySelector('.go').addEventListener('click', function () {
      clearNotice();
      submitRow(memo).catch(function (err) {
        notify("Couldn't send that note — it's still in your inbox." + describe(err));
      });
    });
    memo.querySelector('.del').addEventListener('click', function () {
      clearNotice();
      trashRow(memo).catch(function () {
        notify("Couldn't move that note to the bin — it's still in your inbox.");
      });
    });
  }

  rows().forEach(wire);
  resync();

  // Consolidating folds the ticked notes into the topmost of them, so the transcripts
  // arrive in the order they read on screen — which is what dragging rows together is
  // for. The server merges and returns the result, and the rows it absorbed leave.
  if (consolidateBtn) consolidateBtn.addEventListener('click', function () {
    var chosen = picked();
    if (chosen.length < 2) return;
    clearNotice();
    var keeper = chosen[0];
    chosen.forEach(function (memo) { setBusy(memo, true); });
    Promise.all(chosen.map(function (memo) { return flush(memo); })).then(function () {
      var data = new URLSearchParams();
      chosen.forEach(function (memo) { data.append('memo', memo.dataset.file); });
      return post('/consolidate', data);
    }).then(function (response) {
      if (!response.ok) throw new Error('Failed');
      return response.json();
    }).then(function (merged) {
      keeper.querySelector('textarea[name=transcript]').value = merged.transcript;
      keeper.querySelector('input[name=name]').value = merged.name;
      keeper.querySelector('.pick').checked = false;
      setBusy(keeper, false);
      chosen.slice(1).forEach(function (memo) {
        retired[memo.dataset.file] = true;  // a poll snapshot must not re-add a folded row
        memo.remove();
      });
      resync();
    }).catch(function () {
      chosen.forEach(function (memo) { setBusy(memo, false); });
      notify("Couldn't consolidate those notes — they're all still in your inbox.");
    });
  });

  if (clearPicks) clearPicks.addEventListener('click', function () {
    rows().forEach(function (memo) { memo.querySelector('.pick').checked = false; });
    syncPicks();
  });

  // Run an action over the rows one at a time — not a 20-wide burst at the local
  // server and Notesnook — tallying failures so the outcome is reported once at the end.
  function runEach(memos, action) {
    var failures = 0;
    return memos.reduce(function (chain, memo) {
      return chain.then(function () { return action(memo).catch(function () { failures += 1; }); });
    }, Promise.resolve()).then(function () { return failures; });
  }

  var submitAll = document.getElementById('submit-all');
  if (submitAll) submitAll.addEventListener('click', function () {
    var memos = rows();
    if (!memos.length) return;
    clearNotice();
    runEach(memos, submitRow).then(function (failures) {
      if (failures) notify(failures + ' of ' + memos.length + ' note' + (memos.length === 1 ? '' : 's') +
        " couldn't be sent and are still in your inbox. Check that Notesnook is reachable, then try again.");
    });
  });
  var trashAll = document.getElementById('trash-all');
  if (trashAll) trashAll.addEventListener('click', function () {
    var memos = rows();
    if (!memos.length) return;
    if (!confirm('Trash all ' + memos.length + ' memo' + (memos.length === 1 ? '' : 's') + '? They go to the bin.')) return;
    clearNotice();
    runEach(memos, trashRow).then(function (failures) {
      if (failures) notify(failures + ' of ' + memos.length +
        " couldn't be moved to the bin and are still in your inbox.");
    });
  });

  // Keep the list current with recordings that arrive while the app is open.
  // Poll the server (it rescans the inbox) and splice in only memos we're not
  // already showing, leaving existing rows — their edits, focus, and playback —
  // untouched.
  var POLL_MS = 5000;

  function merge(html) {
    var incoming = document.createElement('div');
    incoming.innerHTML = html;
    var shown = {};
    rows().forEach(function (m) { shown[m.dataset.file] = true; });
    var fresh = [];
    incoming.querySelectorAll('.memo').forEach(function (memo) {
      var file = memo.dataset.file;
      if (!shown[file] && !retired[file]) fresh.push(memo);
    });
    if (!fresh.length) return;
    var grid = content.querySelector('.grid');
    if (!grid) { location.reload(); return; }  // empty page: reload to build the grid + frozen header
    // Fresh notes join the end, matching where the server sorts an unplaced memo, so a
    // hand-arranged inbox isn't reshuffled by a recording that lands mid-session.
    fresh.forEach(function (memo) {
      grid.appendChild(memo);
      wire(memo);
    });
    resync();
  }

  function check() {
    return fetch('/pending')
      .then(function (r) { return r.text(); })
      .then(merge)
      .catch(function () {});
  }

  function poll() {
    check().then(function () { setTimeout(poll, POLL_MS); });
  }

  setTimeout(poll, POLL_MS);

  // Manual "check now": the same inbox rescan the poll runs, on demand. A local check
  // returns almost instantly, so hold a "Loading…" label on the button for a beat —
  // even when nothing new turns up — so the click visibly does something and can't
  // double-fire. Whatever it finds still streams in through merge as usual.
  var REFRESH_FEEDBACK_MS = 700;
  var refreshBtn = document.getElementById('refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', function () {
    if (refreshBtn.disabled) return;
    refreshBtn.disabled = true;
    refreshBtn.textContent = 'Loading…';
    var held = new Promise(function (done) { setTimeout(done, REFRESH_FEEDBACK_MS); });
    Promise.all([check(), held]).then(function () {
      refreshBtn.textContent = 'Refresh';
      refreshBtn.disabled = false;
    });
  });
})();
</script>
</body>
</html>
"""


INDEX_HTML = _PAGE_HEAD + CONTENT_HTML + _PAGE_TAIL


BIN_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bin</title>
""" + _STYLE + """
</head>
<body>
  <div class="frozen">
    <div class="topbar">
      <h1>Bin <span id="count">— {{ memos|length }} item{{ 's' if memos|length != 1 else '' }}</span></h1>
      <a href="/">← Back to inbox</a>
    </div>
    {% if memos %}
    <div class="grid bin headrow">
      <div class="head"></div>
      <div class="head">Audio</div>
      <div class="head">Transcript</div>
      <div class="head">Name</div>
      <div class="head">Where</div>
      <div class="head">When</div>
      <div class="head"><form method="post" action="/restore-all" onsubmit="return confirm('Restore all {{ memos|length }} item{{ 's' if memos|length != 1 else '' }} to the inbox?');"><button class="head-btn restore-all" type="submit">Restore all</button></form></div>
      <div class="head"><form method="post" action="/empty-bin" onsubmit="return confirm('Permanently delete all {{ memos|length }} item{{ 's' if memos|length != 1 else '' }}? This cannot be undone.');"><button class="head-btn empty-bin" type="submit">Empty bin</button></form></div>
    </div>
    {% endif %}
  </div>
  <main id="content">
  {% if not memos %}
    <p class="empty">Nothing in the bin. Submitted and deleted memos land here (kept for 90 days).</p>
  {% else %}
  <div class="grid bin body">
    {% for m in memos %}
    {% if not loop.first %}<div class="sep"></div>{% endif %}
    <div class="row">
      <div class="num">{{ loop.index }}</div>
      <audio controls src="/bin-audio/{{ m.audio_filename }}"></audio>
      <div class="text">{{ m.transcript }}</div>
      <div class="name">{{ m.name or m.audio_filename }}</div>
      <div class="dest">{% if m.status == 'deleted' %}<span title="Trashed" aria-label="Trashed">""" + TRASH_SVG + """</span>{% elif m.route == 'drive' %}<form method="post" action="/open-drive"><input type="hidden" name="q" value="{{ m.name or m.audio_filename.rsplit('.', 1)[0] }}"><button class="destlink" type="submit" title="Sent to Google Drive — open in Drive" aria-label="Sent to Google Drive — open in Drive">""" + DRIVE_SVG + """</button></form>{% else %}<span title="Sent to Notesnook" aria-label="Sent to Notesnook">""" + NOTESNOOK_SVG + """</span>{% endif %}</div>
      <div class="when">{{ m.processed_at }}</div>
      <div><form method="post" action="/restore/{{ m.audio_filename }}"><button class="binbtn restore" type="submit">Restore</button></form></div>
      <div><form method="post" action="/purge/{{ m.audio_filename }}" onsubmit="return confirm('Permanently delete this recording? This cannot be undone.');"><button class="binbtn purge" type="submit">Delete</button></form></div>
    </div>
    {% endfor %}
  </div>
  {% endif %}
  </main>
</body>
</html>
"""


def _submitted_fields():
    """Editable field values shared by auto-save (/edit) and Submit (/submit)."""
    return {
        "name": request.form["name"],
        "transcript": request.form["transcript"],
        "route": request.form.get("route", "notesnook"),
    }


def create_app(service, inbox_dir, bin_dir, launch_drive=None):
    app = Flask(__name__)

    @app.get("/")
    def index():
        # No rescan here: the page must paint instantly from what's already stored.
        # The background catch-up transcribes waiting recordings and the /pending
        # poll streams them in, so the first frame never waits on the model.
        return render_template_string(
            INDEX_HTML, memos=service.pending(), incoming=service.has_incoming()
        )

    @app.get("/pending")
    def pending():
        """The inbox rows alone — polled by the open page to pick up recordings
        that arrive after load, so the app stays current without a manual reload."""
        service.refresh()
        return render_template_string(CONTENT_HTML, memos=service.pending())

    @app.get("/audio/<path:filename>")
    def audio(filename):
        return send_from_directory(inbox_dir, filename)

    @app.post("/edit/<path:filename>")
    def edit(filename):
        service.edit(filename, **_submitted_fields())
        return ("", 204)

    @app.post("/submit/<path:filename>")
    def submit(filename):
        service.edit(filename, **_submitted_fields())
        try:
            service.submit(filename)
        except Exception as exc:  # noqa: BLE001 — any routing failure must reach the client
            # Routing failed (e.g. Notesnook rejected the key), so the memo is still
            # pending and its audio still in the inbox. Signal the failure instead of a
            # false 204 so the client keeps the row rather than hiding a note that never
            # sent — the "Submit all vanished everything but sent nothing" bug.
            return (f"Submit failed: {exc}", 502)
        return ("", 204)

    @app.post("/reorder")
    def reorder():
        """Persist the order a drag-and-drop left the inbox rows in, top to bottom."""
        service.reorder(request.form.getlist("order"))
        return ("", 204)

    @app.post("/consolidate")
    def consolidate():
        """Fold the chosen memos, listed top to bottom, into the first of them. The
        merged fields come back so the client can refresh the row it keeps in place."""
        merged = service.consolidate(request.form.getlist("memo"))
        return jsonify(name=merged.name, transcript=merged.transcript)

    @app.post("/delete/<path:filename>")
    def delete(filename):
        service.delete(filename)
        return ("", 204)

    @app.get("/bin")
    def bin_view():
        return render_template_string(BIN_HTML, memos=service.binned())

    @app.get("/bin-audio/<path:filename>")
    def bin_audio(filename):
        return send_from_directory(bin_dir, filename)

    @app.post("/restore/<path:filename>")
    def restore(filename):
        service.restore(filename)
        return redirect("/bin")

    @app.post("/purge/<path:filename>")
    def purge(filename):
        service.purge(filename)
        return redirect("/bin")

    @app.post("/empty-bin")
    def empty_bin():
        service.empty_bin()
        return redirect("/bin")

    @app.post("/restore-all")
    def restore_all():
        service.restore_all()
        return redirect("/bin")

    @app.post("/open-drive")
    def open_drive():
        """Open a memo in Google Drive. A link can't choose which Chrome profile
        opens it, so the app launches Chrome itself (launch_drive) at a Drive search
        for the memo — the server builds the URL so only Drive can be opened."""
        if launch_drive is not None:
            launch_drive("https://drive.google.com/drive/u/0/search?q=" + quote(request.form.get("q", "")))
        return ("", 204)

    return app
