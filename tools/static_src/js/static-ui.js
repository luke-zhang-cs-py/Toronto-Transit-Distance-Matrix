/* ---------------------------------------------------------------------------
   static-ui.js — the two things this build does differently
   ---------------------------------------------------------------------------
   Loaded last, after app.js and here.js, so it can replace the two functions
   whose behaviour cannot be honest in a build with no trip planner.

   1. The second click. In the Flask app, click one sets a start and click
      two sets a destination and plans a trip. There is no trip planner here,
      so a second click would set a destination and then have nothing to say
      about it. Instead every click moves the start point and recomputes the
      reach, which is the feature this build does have.

   2. The data badge. app.js prints "scheduled" when a response is not live,
      which is true but reads as "the feed was down just now". In this build
      there is no feed to be down: the numbers are modelled and always will
      be, so the badge says so and its tooltip explains it.

   Both are done by replacing the global function rather than by editing
   app.js, because app.js is copied byte for byte from the Flask app and the
   moment it is edited the two start drifting.
   --------------------------------------------------------------------------- */

(function () {
  'use strict';

  const FLAG = 'Click anywhere to move the start point';

  function setFlag() {
    const el = document.getElementById('modeflagText');
    if (el) el.textContent = FLAG;
  }

  /* --------------------------------------------------------- the badge */
  /* Replaces app.js's setLiveBadge, which is also called on a 60-second
     timer by loadLiveStatus() — so setting the text once here would be
     overwritten a minute later. */
  setLiveBadge = function () {
    const el = document.getElementById('liveBadge');
    if (!el) return;
    el.textContent = 'modelled';
    el.title = 'Browser-only build: no live feed. Every wait is the modelled ' +
               'half-headway for the mode that runs the line.';
  };
  setLiveBadge();

  /* ------------------------------------------------------- the clicks */
  const originalSetOrigin = setOrigin;

  setOrigin = function (lat, lon) {
    /* app.js's setOrigin sets stage='destination' and the "click again"
       prompt on its first line, before any await, so both are corrected
       immediately after the call rather than when the search finishes —
       otherwise the wrong prompt is on screen for as long as the Dijkstra
       takes. */
    const done = originalSetOrigin(lat, lon);
    stage = 'origin';
    setFlag();
    return done;
  };

  /* Reached from app.js's map click handler when stage is 'destination'.
     It cannot be, after the line above — but the handler is copied code and
     this build should not depend on having reasoned correctly about it. */
  setDestination = function (lat, lon) {
    return setOrigin(lat, lon);
  };

  /* The load-time setOrigin(Union) in loadNetwork() has usually already run
     by now, through the original rather than the wrapper -- it is kicked off
     while app.js is still executing, and this file is a later <script>. So
     the one call the wrapper cannot catch is the first one, and its two
     leftovers are undone here: the prompt, and the stage it left at
     'destination'. */
  stage = 'origin';
  setFlag();
})();
