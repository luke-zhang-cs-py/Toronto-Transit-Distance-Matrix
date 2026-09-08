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
    let color = '#4fb6c4', weight=2.5, opacity=0.45, dash=null;
    if(line && line.startsWith('Line 1')) { color='#f0a93a'; weight=5; opacity=0.85; }
    else if(line && line.startsWith('Line 2')) { color='#3aa65c'; weight=5; opacity=0.85; }
    else if(line && line.startsWith('YRT')) { color='#8e44ad'; weight=3; opacity=0.7; dash='6 6'; }
    else if(line && line.includes('Hwy') && line.startsWith('MiWay')) { color='#b8860b'; weight=2.8; opacity=0.7; dash='3 5'; }
    else if(line && line.startsWith('MiWay')) { color='#d97706'; weight=3; opacity=0.7; dash='6 6'; }
    else if(line && line.startsWith('GO')) { color='#0f7a6c'; weight=3.5; opacity=0.75; dash='2 8'; }
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
  const departAt = document.getElementById('departAt').value || 'now';
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
function renderOptionList(){
  const el = document.getElementById('optionList');
  el.innerHTML = tripOptions.map((o, i) => {
    const lines = o.lines.length ? o.lines.map(shortLine).join(' → ') : 'walk';
    const changes = o.transfers === 0 ? 'direct'
      : o.transfers + (o.transfers === 1 ? ' change' : ' changes');
    return `<button class="tripOption${i === chosenOption ? ' sel' : ''}" data-i="${i}"
              style="display:block;width:100%;text-align:left;margin-bottom:6px;
                     background:${i === chosenOption ? '#16232b' : '#0e1418'};
                     border:1px solid ${i === chosenOption ? '#4fb6c4' : '#2a3640'};
                     border-radius:6px;padding:7px 9px;color:#e8eef1;cursor:pointer;">
              <b style="font-size:13px;">${esc(o.departAt)} → ${esc(o.arriveAt)}</b>
              <span style="color:#8fa3ad;font-size:12px;"> · ${Math.round(o.totalMinutes)} min · ${esc(changes)}</span>
              <div style="color:#8fa3ad;font-size:11px;margin-top:2px;">${esc(lines)}</div>
              ${o.laterDepartures.length ? `<div style="color:#6d8290;font-size:11px;">
                 or ${o.laterDepartures.map(esc).join(', ')}</div>` : ''}
            </button>`;
  }).join('');
  el.querySelectorAll('.tripOption').forEach(b => {
    b.onclick = () => { chosenOption = Number(b.dataset.i); renderOptionList(); drawOption(chosenOption); };
  });
}

function shortLine(name){
  const m = /^Line (\d)/.exec(name);
  return m ? 'Line ' + m[1] : name.split(' ')[0];
}

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
  '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function drawOption(index){
  const route = tripOptions[index];
  if(!route) return;

  routeLayer.clearLayers();
  const LINE_COLORS = {};
  NETWORK.edges.forEach(([a,b,min,line])=>{
    if(!line) return;
    if(line.startsWith('Line 1')) LINE_COLORS[line]='#f0a93a';
    else if(line.startsWith('Line 2')) LINE_COLORS[line]='#3aa65c';
    else if(line.startsWith('YRT')) LINE_COLORS[line]='#8e44ad';
    else if(line.startsWith('MiWay')) LINE_COLORS[line]='#d97706';
    else if(line.startsWith('GO')) LINE_COLORS[line]='#0f7a6c';
  });

  const ul = document.getElementById('steps'); ul.innerHTML='';
  route.legs.forEach(leg=>{
    const dist = leg.km != null ? ' · ' + fmtKm(leg.km) : '';
    const clock = `<span class="mins">${esc(leg.startTime)}–${esc(leg.endTime)}${dist}</span>`;
    let text;
    if(leg.type==='walk'){
      text = `Walk to <b>${esc(leg.to.name)}</b> ${clock}`;
    } else if(leg.type==='transfer'){
      text = `Change at <b>${esc(leg.to.name)}</b> ${clock}`;
    } else if(leg.type==='wait'){
      /* The wait is its own step, with the source named. A departure time
       * from the timetable and one assumed from an average headway are
       * different claims, and showing them identically would hide which is
       * which. */
      const how = leg.source === 'timetable' ? 'timetabled'
                : leg.source === 'headway' ? 'from live headway' : 'estimated';
      text = `Wait for <b>${esc(shortLine(leg.line))}</b>, board ${esc(leg.boardAt)}`
           + ` <span class="mins">${leg.minutes.toFixed(1)} min · ${esc(how)}</span>`;
    } else {
      const stops = leg.stops ? ` · ${leg.stops} stops` : '';
      text = `Ride <b>${esc(leg.line)}</b> to <b>${esc(leg.to.name)}</b>`
           + ` <span class="mins">${esc(leg.startTime)}–${esc(leg.endTime)}${stops}${dist}</span>`;
    }
    const li = document.createElement('li'); li.innerHTML = text; ul.appendChild(li);

    if(!leg.from || leg.from.lat == null || !leg.to || leg.to.lat == null) return;
    if(leg.type==='walk' || leg.type==='transfer'){
      L.polyline([[leg.from.lat,leg.from.lon],[leg.to.lat,leg.to.lon]],
        {color:'#dfe6ea', weight:3, dashArray: leg.type==='walk' ? '2 7':'1 5', opacity:0.85}).addTo(routeLayer);
    } else if(leg.type==='transit'){
      L.polyline([[leg.from.lat,leg.from.lon],[leg.to.lat,leg.to.lon]],
        {color: LINE_COLORS[leg.line] || '#4fb6c4', weight:6, opacity:0.95}).addTo(routeLayer);
    }
  });
  document.getElementById('tripTotal').textContent =
    `${route.departAt}–${route.arriveAt} · ${Math.round(route.totalMinutes)} min`;
  document.getElementById('tripDist').textContent = fmtKm(route.totalKm);
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
});

loadNetwork();

loadLiveStatus();
setInterval(loadLiveStatus, 60000);

/* Changing the departure time replans rather than rescaling the old answer:
 * a different time is a different set of trains. */
document.getElementById('departAt').addEventListener('change', planTrip);
