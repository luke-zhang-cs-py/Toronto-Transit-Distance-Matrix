/* ---------------------------------------------------------------------------
   here.js — where you are, and which way you are facing
   ---------------------------------------------------------------------------
   Two browser permissions the user has to grant, and both fail in ways worth
   explaining rather than showing a dash forever.

   The guidance below is the same advice a phone map app gives, because the
   sensors underneath are the same ones: a coarse fix means precise location
   is off for this site, and a compass reporting a relative angle means the
   magnetometer needs recalibrating.

   Loaded after app.js, which owns the map and setOrigin().
   --------------------------------------------------------------------------- */

let userHeading = null;
let hereMarker = null;
let hereAccuracyRing = null;

/* Past this, a fix came from wifi or cell towers rather than GNSS. On a
   phone that almost always means precise location is switched off for the
   browser, which is a setting the user can change. */
const COARSE_METRES = 200;

/* A magnetometer that has drifted this far off is worth recalibrating. */
const POOR_HEADING_DEGREES = 25;

function hereHint(html) {
  const el = document.getElementById('hereHint');
  if (el) el.innerHTML = html;
}

function hereStat(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function useMyLocation() {
  if (!navigator.geolocation) {
    hereHint('This browser has no geolocation API.');
    return;
  }
  if (!window.isSecureContext) {
    /* Chrome and Safari refuse geolocation outside HTTPS or localhost, and
       the error they raise says "permission denied", which sends people to
       the wrong setting. */
    hereHint('<b>Location needs HTTPS or localhost.</b> This page is on ' +
             'neither, so the browser will refuse regardless of permissions.');
    return;
  }

  hereHint('Asking for your location…');
  navigator.geolocation.getCurrentPosition(onFix, onFixFailed, {
    enableHighAccuracy: true,   /* ask for GNSS, not a network estimate */
    timeout: 12000,
    maximumAge: 0,              /* a cached fix from an hour ago is not a fix */
  });
}

function onFix(pos) {
  const lat = pos.coords.latitude;
  const lon = pos.coords.longitude;
  const accuracy = pos.coords.accuracy;

  hereStat('accVal', '±' + Math.round(accuracy) + ' m');

  if (hereMarker) map.removeLayer(hereMarker);
  if (hereAccuracyRing) map.removeLayer(hereAccuracyRing);
  hereMarker = L.circleMarker([lat, lon], {
    radius: 7, color: '#fff', weight: 2, fillColor: '#4fb6c4', fillOpacity: 1,
  }).addTo(map);
  /* The accuracy is drawn, not only stated. A ±2 km fix reads as precise as
     a number and is obviously useless as a circle over half the city. */
  hereAccuracyRing = L.circle([lat, lon], {
    radius: accuracy, color: '#4fb6c4', weight: 1, fillOpacity: 0.07,
  }).addTo(map);
  map.setView([lat, lon], accuracy > 1000 ? 12 : 14);

  if (typeof setOrigin === 'function') setOrigin(lat, lon);

  if (accuracy > COARSE_METRES) {
    hereHint('<b>That fix is ±' + Math.round(accuracy) + ' m, which is coarse.</b>' +
      ' It came from wifi or cell towers rather than satellites.' +
      '<ol>' +
      '<li>Open <b>Settings &rsaquo; Privacy &rsaquo; Location Services</b>.</li>' +
      '<li>Find this browser and set it to <b>Allow</b>.</li>' +
      '<li>Turn <b>Precise Location</b> on for it.</li>' +
      '<li>Reload this page and try again.</li>' +
      '</ol>' +
      'A coarse fix still plans a trip — it may just start you a few ' +
      'streets from where you are.');
  } else {
    hereHint('Located to ±' + Math.round(accuracy) + ' m. ' +
             'Tap the map to set a destination.');
  }
  startCompass();
}

function onFixFailed(err) {
  const reasons = {
    1: '<b>Location permission was refused.</b> Allow it in ' +
       '<b>Settings &rsaquo; Privacy &rsaquo; Location Services</b> for this ' +
       'browser, turn on <b>Precise Location</b>, then reload.',
    2: 'Your position is unavailable right now — no satellite or network fix.',
    3: 'Locating timed out. Outdoors or beside a window usually helps.',
  };
  hereHint(reasons[err.code] || err.message);
}

/* --------------------------------------------------------------------------
   Compass
   --------------------------------------------------------------------------
   iOS requires an explicit permission request triggered by a user gesture,
   and only iOS reports webkitCompassHeading together with an accuracy
   figure. Everything else exposes `alpha` from deviceorientation, which is
   measured from wherever the device happened to be pointing unless the
   event is flagged absolute — so a bearing derived from it can be
   arbitrarily wrong while looking perfectly stable.

   A laptop has no magnetometer, so there is nothing to point at. Rather
   than an empty field, the dial is drawn north-up and held there, labelled
   as fixed: that is still a true statement about which way the map is drawn,
   and it is what a compass on a desk does. A phone that reports a real
   bearing gets a needle that moves.

   Which of the two you get is decided by whether usable events actually
   arrive, not by sniffing the user agent. A tablet with a broken
   magnetometer and a desktop with none should behave the same, and a phone
   whose browser hides the sensor behind a permission the user declined is
   not a phone for this purpose. So: attach, wait, and see. */
const SENSOR_GRACE_MS = 1500;

let compassLive = false;
let sensorWatchdog = null;

/* Where the needle points, and whether it is a live bearing.
 *
 * `fixed` is the honest default. A grey needle at north says "this is the
 * map's north, not your heading"; a red one that never moves would be a
 * bearing claim, and it would be wrong the moment somebody turned around. */
function setNeedle(degrees, live) {
  const needle = document.getElementById('needle');
  const dial = document.getElementById('compass');
  if (needle) needle.style.transform = 'rotate(' + (degrees || 0) + 'deg)';
  if (dial) dial.classList.toggle('idle', !live);
}

function holdNorthUp(reason) {
  compassLive = false;
  setNeedle(0, false);
  hereStat('headVal', 'north up');
  hereStat('sensorVal', reason);
}

function startCompass() {
  const Orientation = window.DeviceOrientationEvent;
  if (!Orientation) {
    holdNorthUp('none');
    return;
  }

  const attach = () => {
    window.addEventListener('deviceorientationabsolute', onOrientation, true);
    window.addEventListener('deviceorientation', onOrientation, true);
    /* Listening is not the same as receiving. Desktop Chrome fires
       deviceorientation with every field null, and some browsers fire
       nothing at all, so nothing here is believed until a usable heading
       turns up. */
    clearTimeout(sensorWatchdog);
    sensorWatchdog = setTimeout(() => {
      if (!compassLive) holdNorthUp('not reporting');
    }, SENSOR_GRACE_MS);
  };

  if (typeof Orientation.requestPermission === 'function') {
    Orientation.requestPermission()
      .then((state) => {
        if (state === 'granted') attach();
        else holdNorthUp('permission refused');
      })
      .catch(() => holdNorthUp('unavailable'));
  } else {
    attach();
  }
}

function onOrientation(e) {
  let degrees = null;
  if (typeof e.webkitCompassHeading === 'number') {
    degrees = e.webkitCompassHeading;               /* true heading, iOS */
  } else if (e.absolute && typeof e.alpha === 'number') {
    degrees = 360 - e.alpha;                        /* absolute, so usable */
  }

  if (degrees === null || Number.isNaN(degrees)) {
    /* A relative alpha is not a bearing. Rotating the needle by it would
       move convincingly and point nowhere in particular, which is worse
       than not moving. */
    if (!compassLive) holdNorthUp('relative only');
    if (typeof e.alpha === 'number') {
      calibrationHint('<b>The compass is reporting a relative angle rather ' +
                      'than a true bearing.</b>');
    }
    return;
  }

  compassLive = true;
  clearTimeout(sensorWatchdog);
  userHeading = degrees;

  const points = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  hereStat('headVal', Math.round(degrees) + '° ' +
                      points[Math.round(degrees / 45) % 8]);
  hereStat('sensorVal', 'live');

  /* The needle turns to your heading against a fixed north-up dial, so it
     reads the same way as the map beside it. */
  setNeedle(degrees, true);

  const off = e.webkitCompassAccuracy;
  if (typeof off === 'number' && (off < 0 || off > POOR_HEADING_DEGREES)) {
    calibrationHint('<b>Compass accuracy is poor (±' + Math.round(off) + '°).</b>');
  }
}

function calibrationHint(lead) {
  hereHint(lead +
    ' Recalibrate the magnetometer:' +
    '<ol>' +
    '<li>Hold the phone and trace a <b>figure of eight</b> in the air a few ' +
    'times, rotating your wrist as you go.</li>' +
    '<li>Or open your map app in <b>Live View</b> / camera mode and point it ' +
    'at nearby buildings until it locks on.</li>' +
    '<li>Move away from magnets, metal desks, and cases with magnetic ' +
    'clasps — those are the usual cause.</li>' +
    '</ol>');
}

const hereButton = document.getElementById('hereBtn');
if (hereButton) hereButton.onclick = useMyLocation;

/* The dial is correct before anybody asks for anything: north up, held, and
   labelled as held. A compass on a desk is not broken, it is stationary.
   The sensor is only probed when the user asks for their location, because
   iOS will not grant orientation except from a gesture anyway. */
setNeedle(0, false);
hereStat('headVal', 'north up');
hereStat('sensorVal', window.DeviceOrientationEvent ? 'tap to enable' : 'none');
