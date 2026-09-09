const map = L.map('map', {zoomControl:true}).setView([43.72,-79.46], 10);
L.control.scale({metric:true, imperial:false, position:'bottomleft', maxWidth:150}).addTo(map);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18, attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);
setTimeout(()=>{
  const pane = document.querySelector('.leaflet-tile-pane');
  if(pane) pane.style.filter = 'invert(1) hue-rotate(180deg) brightness(0.9) contrast(0.9)';
},50);

let NETWORK = null; // {nodes, edges}
let originLatLng = null, originMarker=null, destMarker=null, currentTimes=null;
let stage = 'origin';
const nodeMarkers = {};
let routeLayer = L.layerGroup().addTo(map);
let radarOn = true;
const heatLayer = L.heatLayer([], {
  radius: 30, blur: 34, maxZoom: 16, minOpacity: 0.06,
  gradient: {0.15:'rgba(79,182,255,0.22)', 0.4:'rgba(79,182,255,0.32)',
             0.65:'rgba(240,211,58,0.32)', 0.85:'rgba(178,58,58,0.32)', 1:'rgba(178,58,58,0.4)'}
}).addTo(map);

/* Whether the numbers on screen came from the live feed or the fixed
 * schedule. Shown rather than inferred: a travel time that silently switches
 * between measured and assumed is worse than either, because the reader
 * cannot tell which one they are looking at. */
let liveNote = '';
function setLiveBadge(isLive){
  const el = document.getElementById('liveBadge');
  if(!el) return;
  el.textContent = isLive ? ('live' + (liveNote ? ' — ' + liveNote : '')) : 'scheduled';
  el.title = isLive
    ? 'Waits measured from TTC GTFS-realtime; closed lines routed around.'
    : 'Fixed schedule model — the live feed was unavailable.';
}

async function loadLiveStatus(){
  try{
    const s = await (await fetch('/api/live')).json();
    const closed = (s.closed || []);
    liveNote = closed.length ? (closed.length + ' disrupted') : (s.routesWithObservedHeadway + ' routes measured');
    setLiveBadge(s.live);
  }catch(e){ /* the badge stays as the last route set it */ }
}

function fmtKm(km){ return km < 1 ? Math.round(km*1000)+' m' : km.toFixed(1)+' km'; }
function lerpColor(f){
  const stops=[[57,182,255],[240,211,58],[178,58,58]];
  let a,b,lf;
  if(f<0.5){a=stops[0];b=stops[1];lf=f/0.5;} else {a=stops[1];b=stops[2];lf=(f-0.5)/0.5;}
  const r=Math.round(a[0]+(b[0]-a[0])*lf), g=Math.round(a[1]+(b[1]-a[1])*lf), bl=Math.round(a[2]+(b[2]-a[2])*lf);
  return `rgb(${r},${g},${bl})`;
}

async function loadNetwork(){
  const res = await fetch('/api/network');
  NETWORK = await res.json();
  drawNetwork();
  document.getElementById('modeflagText').textContent = 'Click the map to set a start point';
  setOrigin(43.6453, -79.3806); // Union Station
}

function drawNetwork(){
  NETWORK.edges.forEach(([a,b,min,line])=>{
    const na = NETWORK.nodes[a], nb = NETWORK.nodes[b];
    if(!na || !nb) return;
    /* Colour comes from lineColor, which the badges and the route overlay
     * also use -- this had its own copy of the table, so a line could be
     * one colour on the map and another in the panel. Weight, opacity and
     * dash stay local: the background network is deliberately quieter than
     * a highlighted route. */
    const color = lineColor(line);
    let weight=2.5, opacity=0.45, dash=null;
    if(line && line.startsWith('Line ')) { weight=5; opacity=0.85; }
    else if(line && line.startsWith('YRT')) { weight=3; opacity=0.7; dash='6 6'; }
    else if(line && line.includes('Hwy') && line.startsWith('MiWay')) { weight=2.8; opacity=0.7; dash='3 5'; }
    else if(line && line.startsWith('MiWay')) { weight=3; opacity=0.7; dash='6 6'; }
    else if(line && line.startsWith('GO')) { weight=3.5; opacity=0.75; dash='2 8'; }
    L.polyline([[na.lat,na.lon],[nb.lat,nb.lon]], {color, weight, opacity, dashArray:dash}).addTo(map);
  });
}

function buildHeatPoints(){
  const shade = parseFloat(document.getElementById('shadeSlider').value)/100;
  const times = currentTimes || {};
  const vals = Object.values(times);
  const maxT = vals.length ? Math.max(...vals) : 60;
  function inten(t){
    const v = (t==null) ? 0.35 : Math.max(0.06, 1 - Math.min(1, t/maxT));
    return Math.min(1, v) * shade;
  }
  const pts = [];
  Object.entries(NETWORK.nodes).forEach(([id,n])=>{
    pts.push([n.lat, n.lon, Math.min(1, inten(times[id]) + 0.12)]);
  });
  const seen = new Set();
  NETWORK.edges.forEach(([a,b])=>{
    const key = a<b ? a+'|'+b : b+'|'+a;
    if(seen.has(key)) return; seen.add(key);
    const na = NETWORK.nodes[a], nb = NETWORK.nodes[b];
    if(!na || !nb) return;
    const ta = times[a], tb = times[b];
    for(let s=1;s<=3;s++){
      const t = s/4;
      const lat = na.lat+(nb.lat-na.lat)*t, lon = na.lon+(nb.lon-na.lon)*t;
      const tt = (ta!=null && tb!=null) ? ta+(tb-ta)*t : null;
      pts.push([lat, lon, inten(tt)]);
    }
  });
  return pts;
}
function refreshHeatRadar(){ heatLayer.setLatLngs(buildHeatPoints()); }

document.getElementById('radarBtn').addEventListener('click', ()=>{
  radarOn = !radarOn;
  document.getElementById('radarBtn').textContent = 'Heat radar: ' + (radarOn?'ON':'OFF');
  if(radarOn){ refreshHeatRadar(); map.addLayer(heatLayer); } else { map.removeLayer(heatLayer); }
});
document.getElementById('shadeSlider').addEventListener('input', (e)=>{
  document.getElementById('valShade').textContent = e.target.value+'%';
  if(radarOn) refreshHeatRadar();
});

function paintNodes(){
  if(!currentTimes) return;
  const cutoff = parseFloat(document.getElementById('slider').value);
  let count=0;
  Object.entries(currentTimes).forEach(([id,t])=>{
    if(t<=cutoff) count++;
    const color = t>cutoff ? '#2a2e33' : lerpColor(Math.min(1,t/cutoff));
    const r = t>cutoff ? 4 : 7;
    const n = NETWORK.nodes[id];
    if(!nodeMarkers[id]){
      nodeMarkers[id] = L.circleMarker([n.lat,n.lon], {radius:r, color:'#080a0d', weight:1,
        fillColor:color, fillOpacity:0.9}).addTo(map).bindTooltip(`${n.name}: ${t.toFixed(1)} min`);
    } else {
      nodeMarkers[id].setStyle({fillColor:color, radius:r, fillOpacity:0.9, opacity:1});
      nodeMarkers[id].setTooltipContent(`${n.name}: ${t.toFixed(1)} min`);
    }
  });
  document.getElementById('stCount').textContent = count + ' of ' + Object.keys(NETWORK.nodes).length;
}

async function setOrigin(lat, lon){
  stage = 'destination';
  document.getElementById('modeflagText').textContent = 'Click again to set a destination';
  document.getElementById('tripCard').style.display='none';
  document.getElementById('filterCard').style.display='block';
  routeLayer.clearLayers();
  if(destMarker){ map.removeLayer(destMarker); destMarker=null; }
  originLatLng = {lat, lon};
  if(originMarker) map.removeLayer(originMarker);
  originMarker = L.circleMarker([lat,lon], {radius:9, color:'#fff', weight:2,
    fillColor:'#39b6ff', fillOpacity:1}).addTo(map);

  const res = await fetch('/api/reach', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({lat, lon})});
  const reach = await res.json();
  currentTimes = reach.times;
  setLiveBadge(reach.live);
  renderScale();

  let nearestId=null, nd=Infinity;
  Object.entries(currentTimes).forEach(([id,t])=>{ if(t<nd){ nd=t; nearestId=id; } });
  if(nearestId){
    document.getElementById('stName').textContent = NETWORK.nodes[nearestId].name;
    document.getElementById('stWalk').textContent = nd.toFixed(1)+' min';
  }
  paintNodes();
  if(radarOn) refreshHeatRadar();
}

async function setDestination(lat, lon){
  stage = 'origin';
  document.getElementById('modeflagText').textContent = 'Click to start a new trip';
  document.getElementById('filterCard').style.display='none';
  document.getElementById('tripCard').style.display='block';
  if(destMarker) map.removeLayer(destMarker);
  destMarker = L.circleMarker([lat,lon], {radius:9, color:'#fff', weight:2,
    fillColor:'#b23a3a', fillOpacity:1}).addTo(map);
  Object.values(nodeMarkers).forEach(m=>m.setStyle({fillOpacity:0.25, opacity:0.4}));

  lastTrip = {olat: originLatLng.lat, olon: originLatLng.lon, dlat: lat, dlon: lon};
  await planTrip();
}

/* Several ways to make the trip, for a chosen departure time.
 *
 * /api/trips rather than /api/route: a duration is the right answer for the
 * heat map and the wrong one for a journey, because it cannot say what time
 * you arrive or which train you are catching. */
let lastTrip = null;
let tripOptions = [];
let chosenOption = 0;

async function planTrip(){
  if(!lastTrip) return;
  /* when.js owns this: "now" or a time to the second. */
  const departAt = typeof departValue === 'function' ? departValue() : 'now';
  const res = await fetch('/api/trips', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({...lastTrip, departAt, alternatives: 3})});
  const plan = await res.json();
  if(!res.ok || !plan.options || !plan.options.length){
    document.getElementById('optionList').innerHTML =
      `<div class="cc-note" style="font-size:12px;color:#8fa3ad;">`
      + `No trip found for that time.</div>`;
    return;
  }
  tripOptions = plan.options;
  chosenOption = 0;
  setLiveBadge(plan.live);
  renderOptionList();
  drawOption(0);
}

/* One row per option. The lines and the arrival time are what somebody picks
 * on, so those are what the row leads with. */
/* Line colour, decided once. The map drew its polylines from one table and
 * the panel had no colours at all; now a badge in the list and the line on
 * the map are the same colour, which is what makes an option recognisable
 * without reading it. */
function lineColor(line){
  if(!line) return '#4a5a63';
  if(line.startsWith('Line 1')) return '#f0a93a';
  if(line.startsWith('Line 2')) return '#3aa65c';
  if(line.startsWith('Line 4')) return '#a8438f';
  if(line.startsWith('YRT')) return '#8e44ad';
  if(line.startsWith('MiWay')) return '#d97706';
  if(line.startsWith('GO')) return '#0f7a6c';
  if(line === 'Transfer') return '#4a5a63';
  return '#4fb6c4';                      /* streetcars */
}

function badge(line){
  const c = lineColor(line);
  return `<span class="badge" style="background:${c};">${esc(shortLine(line))}</span>`;
}

function modeBadge(kind){
  const label = kind === 'drive' ? 'Drive' : 'Walk';
  return `<span class="badge ${esc(kind)}">${label}</span>`;
}

/* How long, worded the way a person says it. "68 min" is a number you have
 * to convert; "1 hr 8 min" is a duration you already understand. */
function fmtDur(mins){
  const m = Math.round(mins);
  if(m < 60) return m + ' min';
  const h = Math.floor(m / 60);
  return h + ' hr' + (m % 60 ? ' ' + (m % 60) + ' min' : '');
}

/* Where a trip's numbers came from, as one tag rather than a sentence per
 * leg. Live and timetabled and estimated are different claims and the
 * strongest one a trip relies on is what the row should show. */
function sourceTag(option){
  const s = option.waitSources || [];
  if(s.includes('timetable')) return '<span class="tag sched">timetabled</span>';
  if(s.includes('headway')) return '<span class="tag live">live headway</span>';
  if(s.includes('modelled')) return '<span class="tag est">estimated</span>';
  return '';
}

function renderOptionList(){
  const el = document.getElementById('optionList');
  el.innerHTML = tripOptions.map((o, i) => {
    const chain = o.lines.length
      ? o.lines.map(badge).join('<span class="arrow">›</span>')
      : modeBadge(o.kind === 'drive' ? 'drive' : 'walk');
    const access = o.kind === 'drive+transit' ? modeBadge('drive') + '<span class="arrow">›</span>' : '';
    const changes = o.lines.length
      ? (o.transfers === 0 ? 'direct' : o.transfers + (o.transfers === 1 ? ' change' : ' changes'))
      : '';
    return `<button class="optRow${i === chosenOption ? ' sel' : ''}${o.isBaseline ? ' base' : ''}"
              data-i="${i}">
      <div class="optHead">
        <span class="optWhen">${esc(o.departAt)} – ${esc(o.arriveAt)}</span>
        <span class="optDur">${esc(fmtDur(o.totalMinutes))}</span>
      </div>
      <div class="optMeta">${access}${chain}
        ${changes ? '<span>· ' + esc(changes) + '</span>' : ''}
        ${o.isBaseline ? '<span class="tag">yardstick</span>' : sourceTag(o)}
      </div>
    </button>`;
  }).join('');
  el.querySelectorAll('.optRow').forEach(b => {
    b.onclick = () => { chosenOption = Number(b.dataset.i); renderOptionList(); drawOption(chosenOption); };
  });
}

function shortLine(name){
  if(!name) return '';
  const m = /^Line (\d)/.exec(name);
  if(m) return 'Line ' + m[1];
  if(name === 'Transfer') return 'walk';
  return name.split(' ')[0];
}

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function drawOption(index){
  const route = tripOptions[index];
  if(!route) return;

  routeLayer.clearLayers();
  renderItinerary(route);

  route.legs.forEach(leg => {
    if(!leg.from || leg.from.lat == null || !leg.to || leg.to.lat == null) return;
    const pts = [[leg.from.lat, leg.from.lon], [leg.to.lat, leg.to.lon]];
    if(leg.type === 'transit'){
      L.polyline(pts, {color: lineColor(leg.line), weight:6, opacity:0.95}).addTo(routeLayer);
    } else if(leg.type === 'drive'){
      L.polyline(pts, {color:'#d97706', weight:4, dashArray:'8 6', opacity:0.9}).addTo(routeLayer);
    } else if(leg.type === 'walk' || leg.type === 'transfer'){
      L.polyline(pts, {color:'#dfe6ea', weight:3,
        dashArray: leg.type === 'walk' ? '2 7' : '1 5', opacity:0.85}).addTo(routeLayer);
    }
  });
}

/* The steps for the chosen option.
 *
 * Each row leads with the clock time, because that is what somebody checks
 * against their own watch, and the verb comes second. A wait is its own row
 * rather than folded into the ride: "wait 2 min, board 17:22" is actionable
 * and "the ride takes 40 minutes including a wait" is not. */
function renderItinerary(route){
  const el = document.getElementById('tripDetail');
  if(!route){ el.innerHTML = ''; return; }

  const rows = route.legs.map(leg => {
    const when = `<span class="when">${esc(leg.startTime)}</span>`;
    const dist = leg.km != null && leg.km > 0 ? ` · ${fmtKm(leg.km)}` : '';
    if(leg.type === 'walk'){
      return `<li><div>${when}Walk to <b>${esc(leg.to.name)}</b></div>
        <div class="sub">${fmtDur(leg.minutes)}${dist}</div></li>`;
    }
    if(leg.type === 'drive'){
      const park = leg.parkMinutes ? `, incl. ${leg.parkMinutes} min to park and walk in` : '';
      return `<li><div>${when}Drive to <b>${esc(leg.to.name)}</b></div>
        <div class="sub">${fmtDur(leg.minutes)}${dist}${esc(park)}</div></li>`;
    }
    if(leg.type === 'transfer'){
      return `<li><div>${when}Change at <b>${esc(leg.to.name)}</b></div>
        <div class="sub">${fmtDur(leg.minutes)} on foot</div></li>`;
    }
    if(leg.type === 'wait'){
      /* Naming the source is the point. A timetabled departure and a figure
       * assumed from an average headway are different claims, and showing
       * them identically would hide which one you are trusting. */
      const how = leg.source === 'timetable' ? '<span class="tag sched">timetabled</span>'
                : leg.source === 'headway' ? '<span class="tag live">live headway</span>'
                : '<span class="tag est">estimated</span>';
      return `<li class="waitStep"><div>${when}Wait for ${badge(leg.line)}
          — board <b>${esc(leg.boardAt)}</b></div>
        <div class="sub">${fmtDur(leg.minutes)} ${how}</div></li>`;
    }
    const stops = leg.stops ? `${leg.stops} stop${leg.stops === 1 ? '' : 's'}` : '';
    return `<li class="ride"><div>${when}${badge(leg.line)}
        to <b>${esc(leg.to.name)}</b></div>
      <div class="sub">${fmtDur(leg.minutes)}${stops ? ' · ' + stops : ''}${dist}</div></li>`;
  }).join('');

  const later = route.laterDepartures && route.laterDepartures.length
    ? `<div class="optNote">Or catch the ${route.laterDepartures.map(esc).join(', ')}.</div>`
    : '';
  const note = route.note ? `<div class="optNote">${esc(route.note)}</div>` : '';

  el.innerHTML = `<ul class="itin">${rows}</ul>${later}${note}`;
}

map.on('click', (e)=>{
  if(!NETWORK) return;
  const {lat, lng:lon} = e.latlng;
  if(stage==='origin') setOrigin(lat,lon); else setDestination(lat,lon);
});
document.getElementById('newTripBtn').addEventListener('click', ()=>{
  document.getElementById('tripCard').style.display='none';
  document.getElementById('filterCard').style.display='block';
  document.getElementById('modeflagText').textContent = 'Click the map to set a start point';
  stage='origin';
  routeLayer.clearLayers();
  if(destMarker){ map.removeLayer(destMarker); destMarker=null; }
  Object.values(nodeMarkers).forEach(m=>m.setStyle({opacity:1}));
});
document.getElementById('slider').addEventListener('input', (e)=>{
  document.getElementById('valMin').textContent = e.target.value;
  paintNodes();
  renderScale();
});

loadNetwork();

loadLiveStatus();
setInterval(loadLiveStatus, 60000);

/* ---------------------------------------------------------------------------
   The reach scale
   ---------------------------------------------------------------------------
   Drawn from lerpColor, the same ramp the heat radar and the stop markers
   use, so the legend and the map are the same statement. It used to be two
   bare numbers with no visual relationship to anything on screen, which
   meant reading the map required guessing what the colours meant.

   Distances come from the reach itself: the furthest stop inside the current
   time limit, straight-line, which is the honest way to express "how far is
   thirty minutes" for a network where that depends entirely on direction. */
function renderScale(){
  const host = document.getElementById('reachScale');
  if(!host) return;
  const limit = parseFloat(document.getElementById('slider').value);

  const ramp = [];
  for(let i = 0; i <= 10; i++) ramp.push(`${lerpColor(i / 10)} ${i * 10}%`);
  const bar = `<div class="scaleBar" style="background:linear-gradient(90deg,${ramp.join(',')});"></div>`;

  let reachKm = null, reachStops = 0;
  if(currentTimes && originLatLng){
    let furthest = 0;
    Object.entries(currentTimes).forEach(([id, mins]) => {
      if(mins > limit) return;
      const n = NETWORK.nodes[id];
      if(!n) return;
      reachStops++;
      const km = haversineKm(originLatLng.lat, originLatLng.lon, n.lat, n.lon);
      if(km > furthest) furthest = km;
    });
    reachKm = furthest;
  }

  const ticks = `<div class="scaleTicks"><span>0 min</span>
      <span>${Math.round(limit / 2)}</span><span>${Math.round(limit)} min</span></div>`;
  const rows = reachKm === null ? '' : `
    <div class="scaleRow"><span class="scaleSwatch" style="background:${lerpColor(0)};"></span>
      ${reachStops} stops within ${Math.round(limit)} min</div>
    <div class="scaleRow"><span class="scaleSwatch" style="background:${lerpColor(1)};"></span>
      reaching ${fmtKm(reachKm)} out, straight line</div>`;

  host.innerHTML = bar + ticks + rows;
}

/* Straight-line distance, matching the server. Duplicated deliberately and
 * narrowly: shipping the whole routing engine to the browser to draw a
 * legend would be worse than eleven lines of trigonometry. */
function haversineKm(lat1, lon1, lat2, lon2){
  const R = 6371, rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
