/* ---------------------------------------------------------------------------
   when.js — leave now, or leave at a time
   ---------------------------------------------------------------------------
   "Leave now" needs no input at all: it plans from this moment, to the
   second, against the live feed. Choosing a time plans against the timetable
   for that moment instead.

   A segmented control rather than a checkbox, because the two are equal
   choices — "now" is not the absence of a setting, and a checkbox would make
   the common case look like the special one.

   Loaded after app.js, which owns planTrip().
   --------------------------------------------------------------------------- */

let whenMode = 'now';

/* What /api/trips is sent. "now" rather than a client clock reading: the
   server knows the time, and sending our own invites the two to disagree by
   however far the browser's clock has drifted. */
function departValue() {
  if (whenMode === 'now') return 'now';
  const raw = document.getElementById('departAt').value;
  if (!raw) return 'now';
  return raw.length === 5 ? raw + ':00' : raw;   /* HH:MM -> HH:MM:SS */
}

function twoDigit(n) {
  return String(n).padStart(2, '0');
}

function setWhenMode(mode) {
  whenMode = mode;
  document.querySelectorAll('#whenMode .seg').forEach((b) => {
    b.classList.toggle('sel', b.dataset.when === mode);
  });
  const row = document.getElementById('departRow');
  if (row) row.style.display = mode === 'at' ? 'flex' : 'none';

  if (mode === 'at') {
    const field = document.getElementById('departAt');
    if (field && !field.value) {
      /* Seeded with the current time including seconds, so switching over
         continues from where "leave now" was rather than jumping to 00:00
         and reporting that there are no trains. */
      const now = new Date();
      field.value = [now.getHours(), now.getMinutes(), now.getSeconds()]
        .map(twoDigit).join(':');
    }
  }
  if (typeof planTrip === 'function') planTrip();
}

document.querySelectorAll('#whenMode .seg').forEach((b) => {
  b.onclick = () => setWhenMode(b.dataset.when);
});

const departField = document.getElementById('departAt');
if (departField) {
  /* Replanning rather than rescaling: a different departure is a different
     set of trains, not the same trip shifted. */
  departField.addEventListener('change', () => {
    if (typeof planTrip === 'function') planTrip();
  });
}

/* In "leave now" mode the answer goes stale on its own, so it is refreshed.
   Only then -- re-planning a trip somebody pinned to 17:20 would be
   replacing an answer they asked a specific question to get. */
setInterval(() => {
  if (whenMode === 'now' && typeof planTrip === 'function' &&
      typeof lastTrip !== 'undefined' && lastTrip) {
    planTrip();
  }
}, 60000);
