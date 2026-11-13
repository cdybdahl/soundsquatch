/* Soundsquatch: the iPad's music app. Lyrion plays and keeps the library; soundsquatch.py on sasquatch-server
   serves this page, passes Lyrion's JSON-RPC through (/jsonrpc.js) and keeps the artist profiles (/api/…).
   No framework and no build step: plain script that older Safari reads (no lookbehind, no Array.at, no replaceAll). */
"use strict";

/* ───────────────────────── basics ───────────────────────── */
const $ = (s, el) => (el || document).querySelector(s);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const norm = s => String(s || "").trim().toLowerCase().replace(/\s+/g, " ");
const plain = s => norm(s).replace(/[(\[].*?[)\]]/g, "").replace(/&/g, "and").replace(/[^a-z0-9]/g, "");
// this device's own settings (room, sorts, filters); under the old "dvs-" names until first saved again
const store = { get(k, d) { try { let v = localStorage.getItem(k); if (v == null) v = localStorage.getItem(k.replace(/^sq-/, "dvs-")); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
// a room as the house's settings have it: its own name (else Lyrion's), and whether its volume is set on the device itself
// (a WiiM kept at full, an amplifier's input): no volume slider there
const houseRoom = id => (A.cfg && A.cfg.rooms && A.cfg.rooms[id]) || {};
const fixedVolume = id => !!houseRoom(id).fixed;

const ICONS = {
  compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
  person: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"/>',
  tag: '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8" r="1.3"/>',
  radio_plus: '<circle cx="10" cy="13" r="1.8"/><path d="M7 10a4.3 4.3 0 0 0 0 6M13 10a4.3 4.3 0 0 1 0 6M4.4 7.4a8 8 0 0 0 0 11.2M15.6 7.4a8 8 0 0 1 0 11.2M19.5 2.5v6M16.5 5.5h6"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5"/>',
  play: '<path d="M7 4.5v15l13-7.5z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none"/>',
  next: '<path d="M5 5v14l10-7z" fill="currentColor" stroke="none"/><path d="M18 5v14"/>',
  prev: '<path d="M19 5v14L9 12z" fill="currentColor" stroke="none"/><path d="M6 5v14"/>',
  queue: '<path d="M4 6h12M4 11h12M4 16h7M17 14v6M14 17h6"/>',
  next_up: '<path d="M4 6h16M4 11h10M15 15l4 3-4 3"/><path d="M4 16h7"/>',
  shuffle: '<path d="M4 7h3c5 0 5 10 10 10h3M4 17h3c2 0 3-1.5 4-3M14 9.5c1-1.5 2-2.5 3-2.5h3M18 4l3 3-3 3M18 14l3 3-3 3"/>',
  heart: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>',
  speaker: '<rect x="6" y="3" width="12" height="18" rx="2"/><circle cx="12" cy="14" r="3.2"/><circle cx="12" cy="7" r="1"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  back: '<path d="M15 5l-7 7 7 7"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  dice: '<rect x="4" y="4" width="16" height="16" rx="3"/><circle cx="9" cy="9" r="1.2" fill="currentColor"/><circle cx="15" cy="15" r="1.2" fill="currentColor"/><circle cx="15" cy="9" r="1.2" fill="currentColor"/><circle cx="9" cy="15" r="1.2" fill="currentColor"/>',
  vol: '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M16 9c1.5 1.5 1.5 4.5 0 6"/>',
  disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  heart_on: '<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" fill="currentColor"/>',
  star: '<path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/>',
  star_on: '<path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z" fill="currentColor"/>',
  repeat: '<path d="M4 11V9a3 3 0 0 1 3-3h12M16 3l3 3-3 3M20 13v2a3 3 0 0 1-3 3H5M8 21l-3-3 3-3"/>',
  more: '<circle cx="5" cy="12" r="1.5" fill="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="19" cy="12" r="1.5" fill="currentColor"/>',
  radio: '<circle cx="12" cy="12" r="2"/><path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  grip: '<path d="M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01" stroke-width="3.2"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  share: '<path d="M12 3v12M8 7l4-4 4 4"/><path d="M6 11H5a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1h-1"/>',
  move: '<path d="M3 12h13M11 6l6 6-6 6"/><path d="M21 4v16"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1L7 17M17 7l2.1-2.1"/>',
  ban: '<circle cx="12" cy="12" r="9"/><path d="M5.6 5.6l12.8 12.8"/>',
  list: '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1" fill="currentColor"/><circle cx="4" cy="12" r="1" fill="currentColor"/><circle cx="4" cy="18" r="1" fill="currentColor"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>'

};
const icon = n => `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ICONS[n] || ""}</svg>`;

// the house's settings (/api/settings) and this device's own (localStorage, sq-dev-*)
// what this Lyrion has (the server asks it): a feature whose plugin is missing is off, whatever the setting
const has = k => !A.cfg || !A.cfg.have || A.cfg.have[k] !== false;
const NEEDS = { archive: "archive", stations: "radio" };
const on = (group, k) => (group !== "features" || !NEEDS[k] || has(NEEDS[k])) && (!A.cfg || !A.cfg[group] || A.cfg[group][k] !== false);
const device = { get: (k, d) => store.get("sq-dev-" + k, d), set: (k, v) => store.set("sq-dev-" + k, v) };
const A = { cfg: null, marks: { album: {}, track: {}, artist: {} }, npTab: store.get("sq-np-tab", "next"), albums: [], byId: new Map(), artists: [], byArtist: new Map(), artistInfo: new Map(), genres: [], rooms: [], room: store.get("sq-room", ""),
  st: null, stAt: 0, curKey: "\u0000", profiles: new Map(), views: new Map(), home: null, homeAt: 0 };

function api(path, body, again) {
  const headers = { "Content-Type": "application/json" }, pin = store.get("sq-pin", "");
  if (pin) headers["X-Soundsquatch-PIN"] = pin;
  const opts = body ? { method: "POST", headers: headers, body: JSON.stringify(body) } : {};
  return fetch(path, opts).then(r => {
    if (r.status === 403 && body) return askPin(again).then(() => api(path, body, true)); // the house's PIN, asked once on this device
    if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
}
function askPin(wrong) {
  return new Promise((ok, no) => {
    openSheet(`<div class="kicker">This house has a PIN</div><h3>${wrong ? "That isn't it" : "The PIN, please"}</h3>
      <div class="seed-add"><input id="pin-in" type="password" inputmode="numeric" maxlength="20" autocomplete="off"><button class="btn" id="pin-go">OK</button></div>
      <p class="plan-note">Settings and changes to music files ask for it. This device remembers it.</p>
      <div class="acts col"><button class="btn ghost" id="pin-no">Not now</button></div>`);
    const go = () => { store.set("sq-pin", $("#pin-in").value.trim()); closeSheet(); ok(); };
    $("#pin-go").addEventListener("click", go);
    $("#pin-in").addEventListener("keydown", e => { if (e.key === "Enter") go(); });
    $("#pin-no").addEventListener("click", () => { closeSheet(); no(new Error("no PIN")); });
    $("#pin-in").focus();
  });
}
function lms(player, cmd) {
  return fetch("/jsonrpc.js", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: 1, method: "slim.request", params: [player, cmd] }) })
    .then(r => { if (!r.ok) { const e = new Error("HTTP " + r.status); e.lyrion = true; throw e; } shelvesTag(r.headers.get("X-Shelves")); return r.json(); }).then(j => j.result || {});
}
// covers and pictures come from the server's own cache, at the sizes it keeps (soundsquatch.py COVER_SIZES, PICTURE_WIDTHS)
const COVER_SIZES = [150, 300, 600, 800], PICTURE_WIDTHS = [160, 320, 640, 1600];
const snap = (sizes, s) => sizes.filter(x => x >= s)[0] || sizes[sizes.length - 1];
// an album with no cover of its own: a plain dark square where its picture would be (never a broken image)
const NO_COVER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1 1'%3E%3Crect width='1' height='1' fill='%23221e1b'/%3E%3C/svg%3E";
const cover = (art, s) => art ? `/cover/${art}/${snap(COVER_SIZES, s || 300)}.jpg` : NO_COVER;
const pic = (u, w) => !u ? "" : u.charAt(0) === "/" ? u : "/img?u=" + encodeURIComponent(u) + (w ? "&w=" + snap(PICTURE_WIDTHS, w) : "");
const artistHref = n => "#/artist/" + encodeURIComponent(n);
const albumHref = id => "#/album/" + id;
const roomName = id => houseRoom(id).name || ((A.rooms.find(r => r.playerid === id) || {}).name) || "a room";
const mmss = s => { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
const paras = t => String(t || "").replace(/\r/g, "").replace(/&copy;?/g, "\u00a9").split(/\n\s*\n|\n/).map(p => p.trim()).filter(Boolean);
// paragraphs as a story prints them: a heading (the server marks Wikipedia's with §) set as one, a drop cap on the first
const prose = (list, ctx) => list.map(p => p.indexOf("\u00a7 ") === 0 ? `<h4 class="sub">${esc(p.slice(2))}</h4>` : `<p>${linked(p, ctx)}</p>`).join("");
// the first few paragraphs, the rest behind "Continue reading"
function folded(list, n, ctx) {
  while (n > 1 && n < list.length && String(list[n - 1]).indexOf("\u00a7 ") === 0) n--; // never end the shown part on a heading
  return dropcap(list.slice(0, n), ctx) + (list.length > n ? `<div class="rest" hidden>${prose(list.slice(n), ctx)}</div><button class="more-story" data-act="unfold">Continue reading</button>` : "");
}
/* names in a story linked to the shelves: every artist on them, and (in a story about an artist or one of their
   records) that artist's own albums; each once a paragraph, the story's own artist never. A one-word name ("Low",
   "Come") only mid-sentence, where it can't be a word that opens one. */
const linkCache = {};
const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const COMMON = ["live", "music", "christmas", "love", "home", "light", "air", "yes", "low"]; // one-word names that are words first (Low only mid-sentence, as below)
function linkRule(ctx) {
  const k = norm(ctx || "") + "|" + A.artists.length;
  if (linkCache[k]) return linkCache[k];
  const albums = {}, artists = {};
  (ctx ? albumsBy(ctx) : []).forEach(a => { const t = a[1].replace(/\s*[(\[].*$/, "").trim(); if (t.length >= 4 && norm(t) !== norm(ctx)) albums[esc(t).toLowerCase()] = [esc(t), albumHref(a[0])]; });
  A.artists.forEach(a => {
    const n = a[0], one = n.indexOf(" ") < 0;
    if ((ctx && norm(n) === norm(ctx)) || n.length < 3 || (one && n === n.toLowerCase()) || (one && COMMON.indexOf(n.toLowerCase()) >= 0 && n !== "Low")) return;
    artists[esc(n)] = artistHref(n);
  });
  const alt = names => names.sort((x, y) => y.length - x.length).map(reEsc).join("|");
  const edge = body => "(^|[^A-Za-z0-9&;])(" + body + ")(?=[^A-Za-z0-9]|$)";
  return (linkCache[k] = {
    albums: Object.keys(albums).length ? { to: albums, re: new RegExp(edge(alt(Object.keys(albums).map(t => albums[t][0]))), "gi") } : null,
    artists: Object.keys(artists).length ? { to: artists, re: new RegExp(edge(alt(Object.keys(artists))), "g") } : null
  });
}
function linked(text, ctx) {
  let html = esc(text);
  const rule = A.artists && A.artists.length ? linkRule(ctx) : null;
  if (!rule) return html;
  const done = {};
  const pass = (part, r, href, caseless) => part.replace(r.re, (m, pre, name, at) => {
    const key = caseless ? name.toLowerCase() : name, before = part.slice(0, at + pre.length).replace(/\s+$/, "");
    const opening = !before || /[.!?:"\u201c]$|&quot;$/.test(before);
    if (done[key] || (opening && name.indexOf(" ") < 0)) return m;
    done[key] = 1;
    return `${pre}<a class="inlink" href="${href(key)}">${name}</a>`;
  });
  if (rule.albums) html = pass(html, rule.albums, k => rule.albums.to[k][1], true); // the records first, whatever their capitals
  if (rule.artists) html = html.split(/(<a [^>]*>.*?<\/a>)/).map(part => part.indexOf("<a ") === 0 ? part : pass(part, rule.artists, k => rule.artists.to[k], false)).join("");
  return html;
}
function standfirst(t, n) {
  t = String(t || "").replace(/\s+/g, " ").trim();
  if (t.length <= n) return t;
  const cut = t.slice(0, n), i = cut.lastIndexOf(". ");
  return i > n * 0.4 ? cut.slice(0, i + 1) : cut.replace(/\s+\S*$/, "") + "…";
}
function seeded(seed) { let s = 0; for (let i = 0; i < seed.length; i++) s = (s * 31 + seed.charCodeAt(i)) >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
function shuffled(list, rnd) { const a = list.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor((rnd || Math.random)() * (i + 1)); const t = a[i]; a[i] = a[j]; a[j] = t; } return a; }

let toastT;
function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; t.classList.add("on"); clearTimeout(toastT); toastT = setTimeout(() => { t.classList.remove("on"); setTimeout(() => { t.hidden = true; }, 300); }, 2600); }

/* The colour of a picture (its most vivid tones, averaged), for a page's accent: covers and portraits come from this
   same address, so the canvas may read them. */
function tint(img, el) {
  const go = () => {
    try {
      const c = document.createElement("canvas"); c.width = c.height = 24;
      const x = c.getContext("2d"); x.drawImage(img, 0, 0, 24, 24);
      const d = x.getImageData(0, 0, 24, 24).data;
      let r = 0, g = 0, b = 0, w = 0;
      for (let i = 0; i < d.length; i += 4) {
        const mx = Math.max(d[i], d[i + 1], d[i + 2]), mn = Math.min(d[i], d[i + 1], d[i + 2]);
        const sat = mx ? (mx - mn) / mx : 0, lum = mx / 255, wt = sat * sat * (lum > 0.25 && lum < 0.95 ? 1 : 0.1) + 0.002;
        r += d[i] * wt; g += d[i + 1] * wt; b += d[i + 2] * wt; w += wt;
      }
      r /= w; g /= w; b /= w;
      const mx = Math.max(r, g, b);
      if (mx < 24) { el.style.removeProperty("--accent"); return; } // a near-black cover has no colour to give: the house amber
      const lift = mx < 170 ? 170 / mx : 1; // light enough to read on the dark page
      el.style.setProperty("--accent", `rgb(${Math.min(255, Math.round(r * lift))},${Math.min(255, Math.round(g * lift))},${Math.min(255, Math.round(b * lift))})`);
    } catch (e) {}
  };
  if (img.complete && img.naturalWidth) go(); else img.addEventListener("load", go, { once: true });
}

/* ───────────────────────── the library ───────────────────────── */
// an album: [id, album, artist, year, artwork, rank (0 newest), quality, artist id, [genres]]
// the shelves, read again only when they changed (the server's tag for them differs); a page kept open picks them up too
function loadLibrary() {
  return fetch("/api/library").then(r => {
    if (!r.ok) throw new Error("HTTP " + r.status);
    const tag = r.headers.get("ETag");
    if (tag && tag === A.libTag && A.albums.length) return false;
    return r.json().then(lib => { useLibrary(lib); A.libTag = tag; return true; });
  });
}
function freshShelves() {
  if (document.hidden) return;
  loadLibrary().then(changed => {
    if (!changed) return;
    Array.from(A.views.keys()).forEach(h => { const view = A.views.get(h); if (view !== current) { view.el.remove(); A.views.delete(h); } }); // drawn again when next opened
  }).catch(() => {});
}
// the server stamps its replies with the shelves' tag: when it moves (a scan done, something added), they're read again
let shelvesSeen = "";
function shelvesTag(tag) {
  if (!tag) return;
  if (shelvesSeen && tag !== shelvesSeen) freshShelves();
  shelvesSeen = tag;
}
function useLibrary(lib) {
  {
    A.albums = lib.albums; A.byId = new Map(lib.albums.map(a => [a[0], a]));
    lib.albums.forEach(a => (a[10] || []).forEach(v => { if (!A.byId.has(v[0])) A.byId.set(v[0], [v[0], v[1], a[2], v[3], v[4], a[5], v[2], a[7], a[8], v[5], [], v[6] || 0, a[0]]); })); // [11] when added, [12]: the album it is a pressing of
    A.byArtist = new Map();
    lib.albums.forEach(a => { const k = norm(a[2]); if (!A.byArtist.has(k)) A.byArtist.set(k, []); A.byArtist.get(k).push(a); });
    A.artists = lib.artists; // [name, id, albums, photo, kind]
    A.artistInfo = new Map(lib.artists.map(a => [norm(a[0]), a]));
    Object.keys(linkCache).forEach(k => { delete linkCache[k]; });
    const g = {}; lib.albums.forEach(a => (a[8] || []).forEach(x => { g[x] = (g[x] || 0) + 1; }));
    A.genres = Object.keys(g).map(k => [k, g[k]]).sort((a, b) => b[1] - a[1]);
  }
}
// an album's versions, the one on the shelves first: [id, title, quality, year, art, source]
// an artist's shelves by kind, as MusicBrainz files their releases (else the title says): albums, EPs and singles, live
// and sessions (with their Archive shows), compilations; one heading only when there is more than one kind
const KINDS = [["album", "Albums"], ["ep", "EPs & singles"], ["live", "Live & sessions"], ["comp", "Compilations"]];
function kindOf(a, rgs) {
  const t = plain(a[1]), g = (rgs || []).find(r => plain(r.title) === t || t.indexOf(plain(r.title)) === 0 && plain(r.title).length > 3);
  if (g) { // MusicBrainz knows the record: its word goes ("I Could Live in Hope" is no live album)
    const extra = g.extra || [];
    return extra.indexOf("Live") >= 0 ? "live" : extra.indexOf("Compilation") >= 0 ? "comp" : /^(ep|single)$/i.test(g.type || "") ? "ep" : "album";
  }
  if (/^\d{4}-\d\d-\d\d|^live\b|[(\[\u2013-]\s*live\b|\bsessions?\b|\bpeel\b/i.test(a[1])) return "live"; // "Live at…", "– Live in…", "(Live)": not "I Could Live in Hope"
  if (/\b(best of|greatest hits|anthology|collection|singles|rarities|b-sides|early years)\b/i.test(a[1])) return "comp";
  if (/\b(ep|single)\b/i.test(a[1])) return "ep";
  return "album";
}
function discography(mine, shows, p) {
  const by = {}; mine.forEach(a => { const k = kindOf(a, p.rgs); (by[k] = by[k] || []).push(albumCard(a)); });
  if (shows.length) by.live = (by.live || []).concat(shows.map(x => archCard(x)));
  const kinds = KINDS.filter(k => by[k[0]]);
  if (!kinds.length) return "";
  if (kinds.length === 1) return section("In the library", "On your shelves", `<div class="grid">${by[kinds[0][0]].join("")}</div>`);
  return kinds.map((k, i) => section(i ? "" : "In the library", k[1], `<div class="grid">${by[k[0]].join("")}</div>`)).join("");
}
// the artist of the page on screen (its tags, its name for the pickers), not the last one drawn
const pageArtist = () => (current && current.el && current.el.artistTags) || null;
function newArrivals(n) { return A.albums.concat(on("features", "archive") ? A.archive.map(archRow) : []).filter(a => a[11]).sort(SORTS.added[1]).slice(0, n); }
const arrivalCard = a => a.archive ? archCard(a.archive) : albumCard(a);
function versionsOf(a) {
  const main = A.byId.get(a[12] || a[0]) || a;
  return [[main[0], main[1], main[6], main[3], main[4], main[9]]].concat(main[10] || []);
}
const onShelves = name => A.artistInfo.has(norm(name));
const albumsBy = name => (A.byArtist.get(norm(name)) || []).slice().sort((a, b) => (a[3] || 9999) - (b[3] || 9999));

function profile(name) {
  const k = norm(name);
  const have = A.profiles.get(k);
  if (have && (!have.partial || Date.now() - have._at < 1200)) return have._p || Promise.resolve(have);
  const p = api("/api/artist?name=" + encodeURIComponent(name)).then(d => { d._at = Date.now(); A.profiles.set(k, d); return d; })
    .catch(e => { A.profiles.delete(k); throw e; });
  A.profiles.set(k, Object.assign(have || {}, { _p: p, partial: true, _at: Date.now() }));
  return p;
}

/* ───────────────────────── hearts, stars and tags ─────────────────────────
   Kept by the server for the whole house (/api/marks). An album is known as the server's copies() knows it ("artist|album",
   lower case, no asides, letters and digits), so a mark survives a rescan and follows the best copy; a track adds its title. */
const copiesKey = (artist, album) => (artist + "|" + album).toLowerCase().replace(/&/g, "and").replace(/[(\[].*?[)\]]/g, "").replace(/[^a-z0-9|]/g, "");
const albumKey = a => copiesKey(a[2], a[1]);
const trackKey = t => copiesKey(t.artist || "", t.album || "") + "|" + String(t.title || "").toLowerCase().replace(/[(\[].*?[)\]]/g, "").replace(/[^a-z0-9]/g, "");
const markOf = (kind, k) => A.marks[kind][k] || [0, 0, []];
function loadMarks() { return api("/api/marks").then(m => { A.marks = Object.assign({ album: {}, track: {}, artist: {} }, m); }).catch(() => {}); }
function setMark(kind, k, change) {
  const was = markOf(kind, k), now = [change.heart != null ? +change.heart : was[0], change.rating != null ? change.rating : was[1], change.tags || was[2]];
  A.marks[kind][k] = now; refreshMarks(kind, k);
  api("/api/mark", Object.assign({ kind: kind, key: k }, change)).catch(() => { A.marks[kind][k] = was; refreshMarks(kind, k); toast("Couldn't save that"); });
}
// a mark on the page: <span class="mk" data-mark="kind|key" data-mk="heart|stars|tags|loved">; drawn again wherever it shows when it changes
function mk(kind, k, type) { return `<span class="mk mk-${type}" data-mark="${kind}|${esc(k)}" data-mk="${type}">${mkInner(type, markOf(kind, k))}</span>`; }
function mkInner(type, m) {
  if (type === "heart") return `<button class="heart ${m[0] ? "on" : ""}" data-act="heart" aria-label="${m[0] ? "Loved" : "Love"}">${icon(m[0] ? "heart_on" : "heart")}</button>`;
  if (type === "loved") return m[0] ? icon("heart_on") : "";
  if (type === "stars") return [1, 2, 3, 4, 5].map(n => `<button class="star ${n <= m[1] ? "on" : ""}" data-act="rate" data-v="${n}" aria-label="${n} stars">${icon(n <= m[1] ? "star_on" : "star")}</button>`).join("");
  if (type === "tags") return m[2].map(t => `<span class="tag"><a href="#/albums" data-act="tagFilter" data-v="${esc(t)}">#${esc(t)}</a><button data-act="untag" data-v="${esc(t)}" aria-label="Remove">${icon("close")}</button></span>`).join("") +
    `<button class="tag add" data-act="addTag">+ Tag</button>`;
  return "";
}
function refreshMarks(kind, k) {
  document.querySelectorAll(`[data-mark="${kind}|${k}"]`).forEach(el => { el.innerHTML = mkInner(el.dataset.mk, markOf(kind, k)); });
}
// a name and its heart, the heart fast to the last word so a wrap never leaves it dangling on a line of its own;
// open/close wrap each part (a link, say) and the heart stays outside them
function hearted(text, heart, open, close) {
  open = open || ""; close = close || "";
  const t = String(text || "").trim(), cut = t.lastIndexOf(" ");
  const head = cut > 0 ? t.slice(0, cut + 1) : "", last = cut > 0 ? t.slice(cut + 1) : t;
  return `${head ? open + esc(head) + close : ""}<span class="nw">${open}${esc(last)}${close}${heart}</span>`;
}
const markAt = t => { const el = t.closest(".mk"), i = el.dataset.mark.indexOf("|"); return [el.dataset.mark.slice(0, i), el.dataset.mark.slice(i + 1)]; };

/* ───────────────────────── pieces ───────────────────────── */
function albumCard(a, cls) {
  if (!a) return "";
  if (a.archive) return archCard(a.archive, cls);
  const art = a[4] ? `<img loading="lazy" decoding="async" src="${cover(a[4], 300)}" alt="">` : `<div class="noart">${esc((a[1] || "?").slice(0, 1))}</div>`;
  return `<a class="card ${cls || ""}" href="${albumHref(a[0])}"><div class="art">${art}<button class="chip" data-act="playAlbum" data-v="${a[0]}" aria-label="Spin it">${icon("play")}</button></div>
    <div class="t">${esc(a[1])}</div><div class="s">${esc(a[2])}${a[3] ? " &middot; " + a[3] : ""}</div></a>`;
}
// a kindred artist in the margin: their picture in a circle, the name, and whether they're new to the house
function kinRow(x) {
  const info = A.artistInfo.get(norm(x.name)), img = (info && info[3]) || x.image || "", here = onShelves(x.name);
  return `<a class="kin ${here ? "own" : "new"}" href="${artistHref(x.name)}">${img ? `<img loading="lazy" decoding="async" src="${esc(pic(img, 120))}" alt="">` : `<i>${esc(x.name.replace(/^the /i, "").slice(0, 1))}</i>`}<span><b>${esc(x.name)}</b><em>${here ? "on your shelves" : "new to you"}</em></span></a>`;
}
function face(name, image, sub, cls) {
  // someone on the shelves wears their own picture (the one chosen for them), whatever another list offers: Qobuz's
  // similar artists can name a namesake ("LUNA", a singer, for Luna the band)
  const info = A.artistInfo.get(norm(name)), img = (info && info[3]) || image || "";
  const inner = img ? `<img loading="lazy" decoding="async" src="${esc(pic(img, 320))}" alt="">` : `<div class="mono">${esc(name.replace(/^the /i, "").slice(0, 1))}</div>`;
  return `<a class="face ${cls || ""} ${info ? "own" : ""}" href="${artistHref(name)}"><div class="ph">${inner}</div>${mk("artist", norm(name), "loved")}<div class="t">${esc(name)}</div>${sub ? `<div class="s">${sub}</div>` : ""}</a>`;
}
function section(kicker, title, body, more, cls) {
  return `<section class="sec ${cls || ""}"><header><div><div class="kicker">${kicker}</div><h2>${title}</h2></div>${more || ""}</header>${body}</section>`;
}
const shelf = items => `<div class="shelf">${items.join("")}</div>`;
const dropcap = (list, ctx) => list.filter(p => p.indexOf("\u00a7 ") !== 0 || list.indexOf(p) > 0).map((p, i) => i === 0 ? `<p class="dc">${linked(p, ctx)}</p>` : prose([p], ctx)).join("");

/* ───────────────────────── the router: a page is kept once drawn, so going back is instant ───────────────────────── */
const main = () => $("#main");
let current = null;
function route() {
  const h = location.hash || "#/";
  if (current) { current.scroll = main().scrollTop; current.el.hidden = true; }
  const parts = h.slice(2).split("/"), kind = parts[0] || "discover", arg = decodeURIComponent(parts.slice(1).join("/"));
  document.querySelectorAll("#rail a").forEach(a => a.classList.toggle("on", a.dataset.tab === kind || (kind === "discover" && a.dataset.tab === "discover") ||
    (kind === "genre" && a.dataset.tab === "genres") || (kind === "playlist" && a.dataset.tab === "playlists")));
  let v = A.views.get(h);
  const fresh = !v || (kind === "discover" && Date.now() - A.homeAt > 15 * 60000);
  if (!v) {
    v = { el: document.createElement("div"), scroll: 0, kind };
    v.el.className = "view v-" + kind;
    main().appendChild(v.el);
    A.views.set(h, v);
  }
  v.at = Date.now();
  v.el.hidden = false; current = v;
  if (fresh) { v.scroll = 0; ((magOn() && MAG[kind]) || VIEWS[kind] || VIEWS.discover)(v.el, arg); }
  main().scrollTop = v.scroll;
  v.el.classList.remove("enter"); void v.el.offsetWidth; v.el.classList.add("enter");
  // keep the dozen most recent pages; the tabs' own pages always
  const old = Array.from(A.views.entries()).filter(e => e[1] !== v && ["artist", "album", "genre", "person", "playlist", "show"].indexOf(e[1].kind) >= 0).sort((a, b) => b[1].at - a[1].at).slice(12);
  old.forEach(e => { e[1].el.remove(); A.views.delete(e[0]); });
}
// an album's or an artist's page: the bar's small title only once the big one has scrolled away under it (the bar then
// stays at the top, frosted), so the two never show together
let headT = 0;
function watchHead() {
  if (headT) return;
  headT = requestAnimationFrame(() => {
    headT = 0;
    if (!current || ["album", "artist", "show"].indexOf(current.kind) < 0) return;
    const big = $(".al-title, .hero h1", current.el), bar = $(".mast", current.el);
    if (!big || !bar) return;
    current.el.classList.toggle("scrolled", big.getBoundingClientRect().bottom < bar.getBoundingClientRect().bottom);
  });
}
function back() { if (history.length > 1) history.back(); else location.hash = "#/"; }
// every page's bar: as tall as the rail's logo and level with it; a way back where there is one, the title, a line or two
// beside it, and the page's own controls at the right
function pageBar(title, lines, right, back, cls) {
  return `<header class="mast">${back ? `<button class="backbtn" data-act="back" aria-label="Back">${icon("back")}</button>` : ""}<div class="mast-name">${title}</div>
    <div class="mast-line">${lines.filter(Boolean).map(l => `<span>${l}</span>`).join("")}</div><span class="mast-acts ${cls || ""}">${right || ""}</span>${cls && cls.indexOf("search-bar") >= 0 ? "" : `<button class="mast-search" data-act="searchOpen" aria-label="Search">${icon("search")}</button>`}</header>`;
}

const VIEWS = {};

/* ───────────────────────── Discover ───────────────────────── */
VIEWS.discover = function (el) {
  if (emptyShelves(el)) return;
  const when = new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
  el.innerHTML = `${pageBar(`<img class="mast-logo" src="logo.png" alt=""><span>Sound<em>squatch</em></span>`, [esc(when), `${A.albums.length.toLocaleString()} albums &middot; ${A.artists.length.toLocaleString()} artists`],
    `<a class="pill gear" href="#/settings" aria-label="Settings">${icon("gear")}</a><button class="pill" data-act="pickArtist" aria-label="Random artist">${icon("person")}<span class="pl">Random artist</span></button><button class="pill" data-act="surprise" aria-label="Random album">${icon("dice")}<span class="pl">Random album</span></button>`)}
    <div id="d-hero" class="hero skeleton"></div><div id="d-body"></div>`;
  A.homeAt = Date.now();
  settlingStrip(el);
  Promise.all([api("/api/home").catch(() => null), api("/api/cover").catch(() => null)]).then(r => { A.home = r[0]; A.cover = r[1]; drawDiscover(el); });
};
// the lead story's words, where it has none of its own: the opening of the album's review, else a few lines on the
// artist (what a printed lead would carry, and what fills the column beside the shorter stories)
function leadWords(el, x) {
  const box = $(".fp-top .fp-story.lead", el);
  if (!box || !x || box.querySelector("p") || !(x.album_id || x.name)) return;
  const put = text => {
    const first = String(text || "").split(/\n\s*\n/).filter(s => s.trim() && s.charAt(0) !== "§")[0];
    if (!first || !box.isConnected || box.querySelector("p")) return;
    const p = document.createElement("p"); p.textContent = standfirst(first, 460);
    const spin = box.querySelector(".fp-spin"); spin ? box.insertBefore(p, spin) : box.appendChild(p);
  };
  const artist = () => { const who = x.artist || x.name; if (who) profile(who).then(p => put((p.wiki && p.wiki.extract) || (p.qobuz && p.qobuz.bio))).catch(() => {}); };
  if (x.album_id) api("/api/review?id=" + x.album_id).then(r => { if (r.review) put(r.review); else artist(); }).catch(artist);
  else artist();
}
// no albums at all: Lyrion's first scan still running (how far), or no music folder yet (where to set one). Asked
// again every ten seconds; the page starts over once there are albums
function emptyShelves(el) {
  if (A.albums.length) return false;
  const head = `<img class="load-logo" src="logo.png" alt=""><div class="mast-name"><span>Sound<em>squatch</em></span></div>`;
  const look = () => lms("", ["serverstatus", 0, 0]).then(s => {
    if (!el.isConnected) return;
    if (+s["info total albums"] > 0 && !s.rescan) return location.reload();
    const scanning = s.rescan, done = +s.progressdone || 0, total = +s.progresstotal || 0;
    el.innerHTML = `<div class="loading empty-shelves">${head}${scanning
      ? `<h2>Lyrion is reading your music</h2><p>${esc(s.progressname || "Its first scan")}${total ? `: ${done.toLocaleString()} of ${total.toLocaleString()}` : ""}. The shelves fill as soon as it's done.</p>`
      : `<h2>The shelves are bare</h2><p>Lyrion has no music yet. Add your music folder in Lyrion's own Settings (Basic Settings, Media Folders) and let it scan; Soundsquatch picks the albums up by itself.</p>`}</div>`;
    setTimeout(look, 10000);
  }).catch(() => setTimeout(look, 10000));
  el.innerHTML = `<div class="loading">${head}<p>Looking at the shelves&hellip;</p></div>`;
  look();
  return true;
}
/* A new house's first hours: Soundsquatch is still gathering what it knows about the shelves (MusicBrainz answers one
   question a second). The first time a screen opens then, it says so; until it's done, Discover carries a slim strip of
   how far it has got. Gone by itself once it has settled. */
function settlingStrip(el) {
  api("/api/settling").then(s => {
    if (s.settled || !el.isConnected || el.querySelector(".settling")) return;
    A.settling = s;
    const done = s.albums ? (s.profiled / Math.max(1, s.artists)) * 0.5 + (1 - s.genres_left / s.albums) * 0.25 + (1 - s.credits_left / s.albums) * 0.25 : 0;
    const html = `<button class="settling" data-act="settlingWhy"><span class="settling-t"><b>Getting to know your shelves</b><span>${s.profiled.toLocaleString()} of ${s.artists.toLocaleString()} artists &middot; about ${timeLeft(s.minutes)} to go</span></span><span class="settling-bar"><i style="width:${Math.round(done * 100)}%"></i></span></button>`;
    const at = el.querySelector(".fp-plate") || el.querySelector(".mast");
    if (at) at.insertAdjacentHTML("afterend", html); else el.insertAdjacentHTML("afterbegin", html);
    if (!store.get("sq-settling-told", false)) { store.set("sq-settling-told", true); ACT.settlingWhy(); }
  }).catch(() => {});
}
const timeLeft = m => m < 50 ? "under an hour" : m < 90 ? "an hour" : Math.round(m / 60) + " hours";
function nowArtist() { const t = curTrack(); return t && t.artist ? splitArtist(t.artist) : ""; }
function splitArtist(s) {
  if (onShelves(s)) return s;
  return s.split(/\s+(?:feat\.?|ft\.?|featuring|with|&|and|x|vs\.?)\s+|\s*[,;\/]\s*/i)[0].trim() || s;
}
function drawDiscover(el) {
  if (magOn()) return VIEWS.front(el);
  const h = A.home || { rotation: [], back: [], rediscover: [], connections: [], beyond: [], decade_albums: [] };
  // the lead: an artist picked at random when asked for (until "Back to what's playing"), else what is playing, else the artist of the day
  // the top: the day's cover stories, turning; a random artist in their place when one is asked for
  const playing = nowArtist();
  if (A.cover) A.cover.stories = A.cover.stories.filter(st => st.kind !== "night" || on("features", "archive"));
  if (A.heroAlbum) drawAlbumHero($("#d-hero", el), A.heroAlbum);
  else if (A.heroPick) drawHero($("#d-hero", el), A.heroPick, "Picked at random from your shelves");
  else if (on("discover", "cover") && A.cover && A.cover.stories.length) drawCover($("#d-hero", el));
  else drawHero($("#d-hero", el), h.spotlight, "Artist of the day");
  const out = [];
  if (on("discover", "stations") && A.stations && A.stations.stations.length) out.push(section("The radio", "Stations", shelf(A.stations.stations.map(stationCard).concat([newStationCard()]))));
  if (on("discover", "because") && playing) out.push(`<div id="d-because"></div>`);
  if (on("discover", "rotation") && h.rotation.length) out.push(section("From the listening log", "On rotation", shelf(h.rotation.map(n => face(n, "", albumsBy(n).length + " on the shelves")))));
  if (on("discover", "back") && h.back.length) out.push(section("Pick up where you left off", "Back to it", shelf(h.back.map(id => albumCard(A.byId.get(id))))));
  if (on("discover", "new") && (h.new || []).length) out.push(section("Out lately", "New from your artists", shelf(h["new"].map(newCard))));
  if (on("discover", "spotlight") && h.spotlight && (A.heroPick || A.heroAlbum || (on("discover", "cover") && A.cover && A.cover.stories.length))) out.push(`<div id="d-spot"></div>`); // the artist of the day, when something else leads
  if (on("discover", "fresh")) out.push(section("Just in", "Fresh on the shelves", shelf(newArrivals(20).map(arrivalCard)), `<a class="more" href="#/albums">All albums</a>`));
  if (on("discover", "rediscover") && h.rediscover.length) out.push(section("Not heard lately", "Rediscover", `<div class="mosaic">${h.rediscover.slice(0, 12).map((id, i) => albumCard(A.byId.get(id), i === 0 ? "big" : "")).join("")}</div>`));
  if (on("discover", "connections") && h.connections.length) out.push(section("Who played with whom", "Connections", `<div class="links">${h.connections.slice(0, 6).map(linkCard).join("")}</div>`));
  if (on("discover", "beyond") && h.beyond.length) out.push(section("Not on your shelves yet", "Beyond the shelves", shelf(h.beyond.map(b => face(b.name, b.image, b.because.length ? "like " + esc(b.because.slice(0, 2).join(", ")) : "", "new"))), "", "beyond"));
  if (on("discover", "archive") && A.archive.length) out.push(section("From the Internet Archive", "Live on your shelves", shelf(A.archive.map(x => archCard(x))), `<a class="more" href="#/albums" data-act="tagFilter" data-v="@archive">All of them</a>`));
  const loved = shuffled(A.albums.filter(a => markOf("album", albumKey(a))[0]), seeded(h.date || ""));
  if (on("discover", "loved") && loved.length) out.push(section("The ones with hearts", "Loved", shelf(loved.slice(0, 20).map(a => albumCard(a))), `<a class="more" href="#/albums" data-act="tagFilter" data-v="@loved">All of them</a>`));
  if (on("discover", "round") && (h.round || []).length) { // albums turning a round number this month, the oldest anniversaries first, each with its age
    const groups = h.round.map(r => [r.age, r.albums.map(id => A.byId.get(id)).filter(Boolean)]).filter(g => g[1].length);
    const cards = [].concat.apply([], groups.map(g => g[1].map(a => `<div class="rn"><span class="rn-age">${g[0]}</span>${albumCard(a)}</div>`)));
    if (cards.length) out.push(section("Round numbers", groups.length === 1 ? `${cap(inWords(groups[0][0]))} this month` : "This month's anniversaries", shelf(cards.slice(0, 24))));
  }
  if (on("discover", "decade") && h.decade_albums.length) out.push(section("A decade, drawn at random", `The ${h.decade}s`, shelf(h.decade_albums.map(id => albumCard(A.byId.get(id))))));
  if (on("discover", "genre") && h.genre) {
    const g = shuffled(A.albums.filter(a => a[4] && (a[8] || []).indexOf(h.genre) >= 0), seeded(h.date || "")).slice(0, 16);
    if (g.length) out.push(section("Genre of the day", esc(h.genre), shelf(g.map(a => albumCard(a))), `<a class="more" href="#/genre/${encodeURIComponent(h.genre)}">The whole bin</a>`));
  }
  $("#d-body", el).innerHTML = out.join("");
  if (playing) profile(playing).then(p => { const box = $("#d-because", el); if (box) box.outerHTML = becauseHtml(p); }).catch(() => {});
  if ($("#d-spot", el)) profile(h.spotlight).then(p => { const box = $("#d-spot", el); if (box) box.outerHTML = spotlightHtml(p); }).catch(() => {});
}
function newCard(r) {
  const when = new Date(r.date + "T12:00"), soon = when > new Date();
  const date = (soon ? "Out " : "") + when.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `<div class="card q" data-act="newRelease" data-v="${esc(JSON.stringify(r))}"><div class="art"><img loading="lazy" decoding="async" src="${esc(pic(r.cover, 320))}" alt="">
    ${r.owned ? `<span class="badge">On your shelves</span>` : r.qobuz ? `<span class="badge">Qobuz</span>` : ""}</div><div class="t">${esc(r.title)}</div><div class="s">${esc(r.artist)} &middot; ${date}</div></div>`;
}
/* the cover: the day's stories, a spread each, turning every ten seconds (still while touched; swipe or tap a dot) */
const NUM = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
  "seventeen", "eighteen", "nineteen"], TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];
function inWords(n) { return n < 20 ? NUM[n] : TENS[Math.floor(n / 10)] + (n % 10 ? "-" + NUM[n % 10] : ""); }
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
// a cover story as a magazine spread: its picture across the whole page, the headline over it, and a mark of its own kind
// (a date stamp, a gig ticket, a sticker)
function coverSlide(st, i) {
  let kicker, head, title, by, bg, href, acts, stamp, text = st.text || "", credit = "";
  const when = st.date ? MON[+st.date.slice(5, 7) - 1] + " " + (+st.date.slice(8, 10)) : "";
  if (st.kind === "day") {
    kicker = "On this day"; head = st.years ? cap(inWords(st.years)) + (st.years === 1 ? " year" : " years") + " ago today" : "Out today";
    title = st.title; by = esc(st.artist); bg = cover(st.art, 1600); href = albumHref(st.album_id);
    acts = `<button class="btn" data-act="playAlbum" data-v="${st.album_id}">${icon("play")} Spin it</button><a class="btn ghost" href="${href}">The record</a>`;
    stamp = `<div class="stamp-date"><b>${when}</b><span>${st.date.slice(0, 4)}</span></div>`;
  } else if (st.kind === "night") {
    kicker = "On this night"; head = cap(inWords(st.years)) + (st.years === 1 ? " year" : " years") + " ago tonight";
    title = st.artist; by = "Live at " + esc(st.venue) + (st.place ? ", " + esc(st.place) : ""); bg = st.bg ? pic(st.bg, 1600) : pic(st.image, 640); href = "#/show/" + encodeURIComponent(st.id);
    A.shows[st.id] = A.shows[st.id] || { id: st.id, artist: st.artist, venue: st.venue, date: st.date, title: st.title, image: pic(st.image, 640), ctx: null };
    acts = `<a class="btn" href="${href}">${icon("play")} The show</a>`;
    text = text || (st.others ? `One of ${st.others + 1} shows in your Archive collections recorded on this date.` : "");
    stamp = `<div class="ticket"><div class="t-top">Admit one</div><b>${esc(st.artist)}</b><span>${esc(st.venue)}</span><div class="t-foot">${when} ${st.date.slice(0, 4)}${st.place ? " &middot; " + esc(st.place.split(",")[0]) : ""}</div></div>`;
    credit = st.credit || "";
  } else if (st.kind === "born" || st.kind === "died") {
    // one of the shelves' people: a birthday (the living), or the day they died
    const of = st.member ? "of " + esc(st.artist) : "";
    kicker = st.kind === "born" ? "Born on this day" : "Remembered";
    head = st.kind === "born" ? cap(inWords(st.years)) + " today" : cap(inWords(st.years)) + (st.years === 1 ? " year" : " years") + " ago today";
    title = st.name; by = [of ? cap(of) : "", st.kind === "died" && st.born ? st.born + "–" + st.died : ""].filter(Boolean).join(" &middot; ");
    bg = st.pic ? pic(st.pic, 1600) : ""; href = artistHref(st.member ? st.artist : st.name);
    acts = `<button class="btn" data-act="shuffleArtist" data-v="${esc(st.artist)}">${icon("shuffle")} ${st.member ? esc(st.artist) : "Their records"}</button><a class="btn ghost" href="${href}">${st.member ? "The band" : "Their page"}</a>`;
    stamp = st.kind === "born" ? `<div class="stamp-born"><span>Born</span><b>${when}</b><span>${st.date.slice(0, 4)}</span></div>`
      : `<div class="stamp-memory"><span>In memory</span><b>${esc(st.name)}</b><i>${st.born ? st.born + " – " : ""}${st.died}</i></div>`;
  } else {
    kicker = "Record of the day"; head = "Not heard lately"; title = st.title; by = esc(st.artist) + (st.year ? " &middot; " + st.year : ""); bg = cover(st.art, 1600); href = albumHref(st.album_id);
    acts = `<button class="btn" data-act="playAlbum" data-v="${st.album_id}">${icon("play")} Spin it</button><a class="btn ghost" href="${href}">The record</a>`;
    stamp = `<div class="stamp-record"><span>Record</span><b>of the</b><span>day</span></div>`;
  }
  return `<div class="slide k-${st.kind}${i === 0 ? " on" : ""}" data-i="${i}"><div class="sl-bg"><img src="${esc(bg)}" alt=""></div><div class="sl-shade"></div>
    ${stamp}<div class="sl-text"><div class="kicker">${kicker}</div><div class="sl-head">${esc(head)}</div><h1><a href="${href}">${esc(title)}</a></h1><div class="sl-by">${by}</div>
      ${text ? `<p class="stand">${esc(standfirst(text, 220))}</p>` : ""}<div class="acts">${acts}</div></div>${credit ? `<div class="sl-credit">Photo: ${esc(credit)}</div>` : ""}</div>`;
}
function drawCover(box) {
  const stories = A.cover.stories;
  box.className = "cover";
  box.innerHTML = `<div class="slides">${stories.map(coverSlide).join("")}</div>${stories.length > 1 ? `<div class="dots">${stories.map((s, i) => `<button class="${i === 0 ? "on" : ""}" data-act="coverGo" data-v="${i}" aria-label="Story ${i + 1}"></button>`).join("")}</div>` : ""}`;
  box.querySelectorAll(".sl-bg img").forEach(img => tint(img, img.closest(".slide")));
  A.coverAt = 0; clearInterval(A.coverT);
  const first = +((/[?&]slide=(\d)/.exec(location.search) || [])[1] || 0); // ?slide=N opens on that story (for looking at each)
  if (first) setTimeout(() => coverGo(first), 0);
  if (stories.length > 1 && !device.get("still", false)) A.coverT = setInterval(() => { if (!box.isConnected) return clearInterval(A.coverT); if (Date.now() > (A.coverHold || 0)) coverGo((A.coverAt + 1) % stories.length); }, 10000);
  let x0 = null;
  box.addEventListener("touchstart", e => { A.coverHold = Date.now() + 20000; x0 = e.touches[0].clientX; }, { passive: true });
  box.addEventListener("touchend", e => { if (x0 == null) return; const dx = e.changedTouches[0].clientX - x0; x0 = null;
    if (Math.abs(dx) > 50) coverGo((A.coverAt + (dx < 0 ? 1 : stories.length - 1)) % stories.length); }, { passive: true });
}
function coverGo(i) {
  const box = $(".cover", current && current.el); if (!box) return;
  A.coverAt = +i;
  box.querySelectorAll(".slide").forEach(s => s.classList.toggle("on", +s.dataset.i === A.coverAt));
  box.querySelectorAll(".dots button").forEach((d, j) => d.classList.toggle("on", j === A.coverAt));
}
function heroMeta(p) {
  const mb = p.mb || {}, bits = [];
  if (mb.type) bits.push(mb.type === "Group" ? "Band" : mb.type);
  if (mb.area) bits.push(esc(mb.area));
  if (mb.begin) bits.push(mb.begin + (mb.end ? "–" + mb.end : mb.ended ? "–" : " – present"));
  return bits.join(" &middot; ");
}
function drawHero(box, name, kicker) {
  if (!box) return;
  if (!name) { box.className = "hero empty"; box.innerHTML = ""; return; }
  box.dataset.name = name;
  profile(name).then(p => {
    if (box.dataset.name !== name) return;
    const text = (p.wiki && p.wiki.extract) || (p.qobuz && p.qobuz.bio) || "";
    const albums = albumsBy(name);
    const bg = p.hero ? `<img class="hero-img" src="${esc(pic(p.hero, 1600))}" alt="">` : albums.length ? `<img class="hero-img blur" src="${cover(albums[0][4], 300)}" alt="">` : "";
    box.className = "hero";
    box.innerHTML = `${bg}<div class="hero-shade"></div><div class="hero-text"><div class="kicker">${kicker}</div>
      <h1>${hearted(p.qobuz && p.qobuz.name || name, mk("artist", norm(p.qobuz && p.qobuz.name || name), "heart"), `<a href="${artistHref(name)}">`, "</a>")}</h1><div class="meta">${heroMeta(p)}</div>
      ${text ? `<p class="stand">${esc(standfirst(text, 260))}</p>` : ""}
      <div class="acts"><a class="btn" href="${artistHref(name)}">Read about them</a>${albums.length ? `<button class="btn ghost" data-act="shuffleArtist" data-v="${esc(name)}">${icon("shuffle")} Shuffle their albums</button>` : ""}
      ${A.heroPick ? `<button class="btn ghost" data-act="heroBack">Back to the cover story</button>` : ""}</div></div>`;
    const img = $(".hero-img", box); if (img) tint(img, box);
  }).catch(() => { box.className = "hero empty"; });
}
// a record drawn at random, as Discover's lead: its cover, what Wikipedia says of it, and another a tap away
function drawAlbumHero(box, id) {
  const a = A.byId.get(id); if (!box || !a) return;
  box.dataset.name = "album:" + id;
  const paint = review => {
    if (box.dataset.name !== "album:" + id) return;
    box.className = "hero with-cover";
    box.innerHTML = `<img class="hero-img blur" src="${cover(a[4], 300)}" alt=""><div class="hero-shade"></div><img class="hero-cover" src="${cover(a[4], 800)}" alt="">
      <div class="hero-text"><div class="kicker">Picked at random from your shelves</div>
      <h1>${hearted(a[1], mk("album", albumKey(a), "heart"), `<a href="${albumHref(a[0])}">`, "</a>")}</h1>
      <div class="meta"><a href="${artistHref(a[2])}">${esc(a[2])}</a>${a[3] ? " &middot; " + esc(a[3]) : ""}${(a[8] || []).length ? " &middot; " + a[8].map(esc).join(", ") : ""}</div>
      ${review ? `<p class="stand">${esc(standfirst(review, 260))}</p>` : ""}
      <div class="acts"><button class="btn" data-act="playAlbum" data-v="${a[0]}">${icon("play")} Spin it</button><a class="btn ghost" href="${albumHref(a[0])}">The record</a>
      <button class="btn ghost" data-act="surprise">${icon("dice")} Another</button><button class="btn ghost" data-act="heroBack">Back to the cover story</button></div></div>`;
    const img = $(".hero-img", box); if (img) tint(img, box);
  };
  paint("");
  albumData(id).then(d => { if (d.review) paint(d.review); }).catch(() => {});
}
function becauseHtml(p) {
  const sim = ((p.qobuz && p.qobuz.similar) || []).slice();
  if (!sim.length) return "";
  sim.sort((a, b) => (onShelves(b.name) ? 1 : 0) - (onShelves(a.name) ? 1 : 0));
  const name = (p.qobuz && p.qobuz.name) || p.name;
  return section("Because you're listening to " + esc(name), "Kindred spirits", shelf(sim.map(s => face(s.name, s.image, onShelves(s.name) ? "on your shelves" : "new to you"))));
}
function spotlightHtml(p) {
  const name = (p.qobuz && p.qobuz.name) || p.name, text = (p.wiki && p.wiki.extract) || (p.qobuz && p.qobuz.bio) || "";
  return `<section class="sec spot"><a class="spot-pic" href="${artistHref(name)}">${p.hero ? `<img loading="lazy" src="${esc(pic(p.hero, 1600))}" alt="">` : ""}</a>
    <div class="spot-text"><div class="kicker">Artist of the day</div><h2><a href="${artistHref(name)}">${esc(name)}</a></h2><div class="meta">${heroMeta(p)}</div>
    ${dropcap(paras(standfirst(text, 700)).slice(0, 2))}<div class="mini">${albumsBy(name).slice(0, 6).map(a => `<a href="${albumHref(a[0])}"><img loading="lazy" src="${cover(a[4], 150)}" alt=""></a>`).join("")}</div></div></section>`;
}
const REL = { "member of band": ["member of", "members include"], collaboration: ["collaborated in", "a collaboration with"], "is person": ["also performs as", "the person behind"],
  "supporting musician": ["played alongside", "backed by"], subgroup: ["grew out of", "spawned"], founder: ["founded", "founded by"], "vocal supporting musician": ["sang with", "sung with by"],
  "instrumental supporting musician": ["played for", "backed by"], tribute: ["a tribute to", "honoured by"], "named after": ["named after", "gave its name to"] };
function relWords(type, dir) { const r = REL[type]; return r ? (dir === "backward" ? r[1] : r[0]) : String(type || "linked to").replace(/_/g, " "); }
function linkCard(c) {
  return `<div class="link">${face(c.a, "", "", "sm")}<div class="rel"><span>${esc(relWords(c.type, c.dir))}</span>${c.attrs && c.attrs.length ? `<em>${esc(c.attrs.join(", "))}</em>` : ""}</div>${face(c.b, "", "", "sm")}</div>`;
}

/* ───────────────────────── an artist ───────────────────────── */
VIEWS.artist = function (el, name) {
  let drawn = "";
  const draw = p => {
    const sig = JSON.stringify([p.hero, p.qobuz, p.mb, p.wiki, p.photos, p.heard, p.partial]);
    if (sig === drawn) return; // nothing new: the page stays as it is, its pictures and scroll untouched
    drawn = sig;
    const realName = (p.qobuz && p.qobuz.name) || name, mine = albumsBy(name).length ? albumsBy(name) : albumsBy(realName);
    const shows = A.archive.filter(x => norm(x.artist) === norm(realName) || norm(x.artist) === norm(name)); // their Archive favourites stand with their albums
    const text = (p.qobuz && p.qobuz.bio) || (p.wiki && p.wiki.extract) || "";
    const allTags = (p.mb && p.mb.genres) || [], hidden = p.hidden_tags || [];
    const genres = allTags.filter(g => hidden.indexOf(g) < 0).slice(0, 5);
    el.artistTags = { name, all: allTags.slice(0, 16), hidden }; // the page's own: a page kept and shown again keeps its artist
    const owned = new Set(mine.map(a => plain(a[1])));
    const groups = {};
    ((p.qobuz && p.qobuz.releases) || []).forEach(r => { if (!owned.has(plain(r.album))) (groups[r.group] = groups[r.group] || []).push(r); });
    const bg = p.hero ? `<img class="hero-img" src="${esc(pic(p.hero, 1600))}" alt="">` : p.thumb ? `<img class="hero-img blur" src="${esc(pic(p.thumb, 320))}" alt="">`
      : mine.length ? `<img class="hero-img blur" src="${cover(mine[0][4], 300)}" alt="">` : "";
    const rels = {};
    ((p.mb && p.mb.rels) || []).forEach(r => { const w = relWords(r.type, r.dir); (rels[w] = rels[w] || []).some(x => x.name === r.name) || rels[w].push(r); });
    const heard = p.heard || {};
    const log = heard.plays ? `<span class="mast-stat"><b>${heard.plays}</b> ${heard.plays === 1 ? "play" : "plays"}${heard.last ? " &middot; last " + new Date(heard.last * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : ""}</span>` : "";
    el.innerHTML = `${pageBar(esc(realName), ["Artist", mine.length ? `${mine.length} ${mine.length === 1 ? "album" : "albums"} on your shelves` : "Not on your shelves yet"], log, true)}<div class="hero tall">${bg}<div class="hero-shade"></div><button class="pic-edit" data-act="artistPic" aria-label="Change their picture">${icon("edit")}</button><div class="hero-text"><div class="kicker">${heroMeta(p) || "Artist"}</div>
        <h1>${hearted(realName, mk("artist", norm(realName), "heart"))}</h1>${allTags.length ? `<div class="genres">${genres.map(g => `<span>${esc(g)}</span>`).join("")}<button class="g-edit" data-act="artistTags" aria-label="Choose their tags">${icon("edit")}</button></div>` : ""}
        <div class="acts">${mine.length ? `<button class="btn" data-act="shuffleArtist" data-v="${esc(name)}">${icon("shuffle")} Shuffle</button>` : ""}
        ${mine.length ? `<button class="btn ghost" data-act="artistRadio" data-v="${esc(name)}">${icon("radio")} Artist radio</button>` : ""}
        ${mine.length ? `<button class="btn ghost" data-act="playAlbum" data-v="${mine[mine.length - 1][0]}">${icon("play")} Latest on the shelves</button>` : ""}
        <button class="btn ghost" data-act="artistBan" data-v="${esc(realName)}" aria-label="Never play them">${icon("ban")}</button>
        ${on("features", "stations") ? `<button class="btn ghost seed-btn ${isSeed(realName) ? "on" : ""}" data-act="seedSheet" data-v="${esc(realName)}" aria-label="Add to a station">${icon("radio_plus")}</button>` : ""}</div></div></div>
      <div class="cols"><article class="story">${p.partial && !text ? `<p class="dim">Gathering their story&hellip;</p>` : folded(paras(text), 2, realName)}
        ${(p.qobuz || p.wiki) && has("mai") ? `<button class="more-story" data-act="story" data-v="${esc(realName)}">Wikipedia's full story</button><div class="full-story"></div>` : ""}
        ${p.wiki && p.wiki.url ? `<div class="credit">Sources: ${p.qobuz && p.qobuz.name ? "Qobuz, " : ""}Wikipedia${p.mb && p.mb.mbid ? ", MusicBrainz" : ""}</div>` : ""}</article>
      <aside class="side">${heard.plays ? `<div class="box"><div class="kicker">The listening log</div><div class="stat"><b>${heard.plays}</b> plays, <b>${heard.finished}</b> heard through${heard.skipped ? `, <b>${heard.skipped}</b> skipped early` : ""}</div>${heard.last ? `<div class="dim">last ${new Date(heard.last * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</div>` : ""}</div>` : ""}
        ${Object.keys(rels).map(w => `<div class="box"><div class="kicker">${esc(w.charAt(0).toUpperCase() + w.slice(1))}</div>${rels[w].slice(0, 12).map(r => `<a class="rel-name ${onShelves(r.name) ? "own" : ""}" href="${artistHref(r.name)}">${esc(r.name)}${r.begin ? ` <span>${r.begin}${r.end ? "–" + r.end : ""}</span>` : ""}</a>`).join("")}</div>`).join("")}
        ${p.mb && p.mb.homepage ? `<div class="box"><div class="kicker">Elsewhere</div><div class="dim">${esc(p.mb.homepage.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, ""))}</div></div>` : ""}</aside></div>
      ${discography(mine, shows, p)}
      <div id="ar-arch">${archShelf(archArtistCache.get(norm(realName)) && archArtistCache.get(norm(realName)).done)}</div>
      ${Object.keys(groups).map(g => section("On Qobuz, not on your shelves", esc(g), shelf(groups[g].map(r => qCard({ artist: r.artist, album: r.album, cover: r.cover, i: r.i, page: realName }))))).join("")}
      ${p.qobuz && p.qobuz.similar && p.qobuz.similar.length ? section("If you like " + esc(realName), "Similar artists", shelf(p.qobuz.similar.filter(s => !onShelves(s.name)).map(s => face(s.name, s.image, "new to you", "new")).concat(p.qobuz.similar.filter(s => onShelves(s.name)).map(s => face(s.name, s.image, "on your shelves"))))) : ""}
      ${p.photos && p.photos.length > 1 ? section("Pictures", "In the frame", `<div class="photos">${p.photos.map(x => `<img loading="lazy" decoding="async" src="${esc(pic(x.url, 640))}" alt="">`).join("")}</div>`) : ""}
      ${p.partial ? `<p class="dim center">More is on its way from MusicBrainz and Wikipedia&hellip;</p>` : ""}`;
    el.dataset.artist = realName;
    const ap = archiveOf(realName); // their shows, once the plugin has looked (cached; the first look takes seconds)
    ap.then(shows => { ap.done = shows; const box = $("#ar-arch", el); if (box && el.isConnected) box.innerHTML = archShelf(shows); });
    const img = $(".hero-img", el); if (img) tint(img, el);
  };
  // drawn at once from what is already known (the shelves, a profile fetched before), then filled in as the profile comes
  const known = A.profiles.get(norm(name)), info = A.artistInfo.get(norm(name));
  draw(known && known.name ? known : { name: name, partial: true, thumb: info && info[3] });
  let tries = 0;
  const load = () => profile(name).then(p => {
    if (!el.isConnected) return;
    draw(p);
    if (p.partial && tries++ < 40) setTimeout(load, tries < 10 ? 1200 : 4000);
  }).catch(() => { if (!drawn) el.innerHTML = `${pageBar(esc(name), ["Artist"], "", true)}<div class="empty-state"><h1>${esc(name)}</h1><p>Couldn't reach the artist desk.</p></div>`; });
  load();
};
function archShelf(shows) {
  return shows && shows.length ? section("The Internet Archive", `Live on the Archive <span class="count-inline">${shows.length}</span>`, shelf(shows.map(x => archCard(x)))) : "";
}
function qCard(r) {
  const art = r.cover ? `<img loading="lazy" decoding="async" src="${esc(pic(r.cover, 320))}" alt="">` : `<div class="noart">${esc(r.album.slice(0, 1))}</div>`;
  return `<div class="card q" data-act="qobuzSheet" data-v="${esc(JSON.stringify(r))}"><div class="art">${art}<span class="badge">Qobuz</span></div><div class="t">${esc(r.album)}</div><div class="s">${esc(r.artist)}</div></div>`;
}

/* ───────────────────────── the magazine (a mock-up, at #/mag/NAME) ─────────────────────────
   An artist's page as a printed music magazine would run it: a running head, a headline and its standfirst, a framed
   photograph with its caption, the story in two columns with a drop cap and a pull quote, a fact file in the margin,
   and a buyer's guide to their records on the shelves. Not linked from anywhere yet: the artist page stays as it is. */
// the magazine look, on this device: the pages it has its own way of setting (the rest keep theirs, under a running head)
const magOn = () => device.get("look", "classic") === "magazine";
const MAG = {};
function magRun(section) {
  const issue = Math.floor((Date.now() - new Date("2026-01-01").getTime()) / 86400000) + 1;
  const when = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  return `<header class="mag-run"><button class="backbtn" data-act="back" aria-label="Back">${icon("back")}</button><span>Soundsquatch</span><span>${section}</span><span>No. ${issue} &middot; ${esc(when)}</span><button class="mast-search" data-act="searchOpen" aria-label="Search">${icon("search")}</button></header>`;
}
VIEWS.mag = function (el, name) {
  el.innerHTML = `<div class="mag"><p class="dim">Setting the type&hellip;</p></div>`;
  let tries = 0; // a name never asked of is looked up as it opens: drawn again as its story, pictures and records arrive
  const load = () => profile(name).then(p => {
    if (!el.isConnected) return;
    const realName = (p.qobuz && p.qobuz.name) || name, mine = albumsBy(name).length ? albumsBy(name) : albumsBy(realName);
    let text = (p.qobuz && p.qobuz.bio) || (p.wiki && p.wiki.extract) || "";
    const signed = /\n?\s*(?:©|&copy;?)\s*([^/\n]+?)\s*\/\s*TiVo\s*$/.exec(text), writer = signed ? signed[1].trim() : "";
    if (signed) text = text.slice(0, signed.index);
    const list = paras(text).filter(x => x.indexOf("\u00a7 ") !== 0);
    const mb = p.mb || {}, heard = p.heard || {};
    const sentences = text.replace(/\s+/g, " ").match(/[^.!?]+[.!?]+(\s|$)/g) || [];
    const deck = standfirst(list[0] || "", 170);
    const quote = sentences.slice(2).map(x => x.trim()).filter(x => x.length > 70 && x.length < 170).sort((a, b) => b.length - a.length)[0] || "";
    const members = (mb.rels || []).filter(r => r.type === "member of band" && r.dir === "backward").map(r => r.name);
    el.artistTags = { name, all: (mb.genres || []).slice(0, 16), hidden: p.hidden_tags || [] }; // for the pickers: their picture, their tags
    const tags = ((mb.genres || []).filter(g => (p.hidden_tags || []).indexOf(g) < 0)).slice(0, 4);
    // kindred artists, Qobuz's: the ones new to the house first (the point is finding them), then the ones already here
    const sim = (p.qobuz && p.qobuz.similar) || [], like = sim.filter(x => !onShelves(x.name)).concat(sim.filter(x => onShelves(x.name)));
    const shows = A.archive.filter(x => norm(x.artist) === norm(realName) || norm(x.artist) === norm(name));
    const tab = mine.length || shows.length ? store.get("sq-mag-tab", "story") : (el.magTab || "records"); // nothing on the shelves: their records elsewhere first
    // the records by kind, each kind by date: the studio ones on The records, every live one (theirs, and the tapes) on Live
    const yearOf = a => a[3] || +((/^(\d{4})-\d\d-\d\d/.exec(a[1]) || [])[1] || 0); // a tape's year from its dated title
    const byYear = list => list.slice().sort((a, b) => (yearOf(a) || 9999) - (yearOf(b) || 9999));
    const kinds = { album: [], ep: [], comp: [], live: [] };
    mine.forEach(a => kinds[kindOf(a, p.rgs)].push(a));
    const guide = list => `<ol>${byYear(list).map(a => `<li><a href="${albumHref(a[0])}"><img loading="lazy" src="${cover(a[4], 300)}" alt=""><span class="y">${yearOf(a) || "&mdash;"}</span><b>${esc(a[1])}</b><em>${[(a[8] || [])[0] || "", (a[10] || []).length ? (a[10].length + 1) + " pressings" : ""].filter(Boolean).join(" &middot; ")}</em></a></li>`).join("")}</ol>`;
    const studio = [["album", "LPs"], ["ep", "EPs & singles"], ["comp", "Compilations"]].filter(k => kinds[k[0]].length);
    const studioCount = kinds.album.length + kinds.ep.length + kinds.comp.length, liveCount = kinds.live.length + shows.length;
    // theirs on Qobuz, not on the shelves, grouped as Qobuz groups them; each opens the Qobuz sheet (Spin it, Queue, Add to the library)
    const owned = new Set(mine.map(a => plain(a[1]))), away = {};
    ((p.qobuz && p.qobuz.releases) || []).forEach(r => { if (!owned.has(plain(r.album))) (away[r.group] = away[r.group] || []).push(r); });
    const awayHtml = Object.keys(away).map(g => `<div class="mr-k mag-away-k">${esc(g)}</div><ol>${away[g].map(r => `<li><button class="mag-away" data-act="qobuzSheet" data-v="${esc(JSON.stringify({ artist: r.artist, album: r.album, cover: r.cover, i: r.i, page: realName }))}">${r.cover ? `<img loading="lazy" src="${esc(pic(r.cover, 320))}" alt="">` : `<span class="noart"></span>`}<span class="y">Qobuz</span><b>${esc(r.album)}</b><em></em></button></li>`).join("")}</ol>`).join("");
    const credit = /wikimedia/.test(p.hero || "") ? "Wikimedia Commons" : /qobuz/.test(p.hero || "") ? "Qobuz" : /discogs/.test(p.hero || "") ? "Discogs" : "";
    const half = Math.ceil(list.length / 2);
    const body = list.slice(0, Math.max(half, 2)).map((x, i) => i === 0 ? `<p class="dc">${linked(x, realName)}</p>` : `<p>${linked(x, realName)}</p>`).join("")
      + (quote ? `<blockquote class="pull">&ldquo;${esc(quote.replace(/[.]$/, ""))}&rdquo;</blockquote>` : "")
      + list.slice(Math.max(half, 2)).map(x => `<p>${linked(x, realName)}</p>`).join("");
    const fact = (k, v) => v ? `<div class="ff-row"><dt>${k}</dt><dd>${v}</dd></div>` : "";
    el.innerHTML = `<article class="mag">
      ${magRun("The Artists")}
      <div class="mag-dept">Profile</div>
      <h1 class="mag-head">${esc(realName)}</h1>
      ${deck ? `<p class="mag-deck">${esc(deck)}</p>` : ""}
      <div class="mag-by">Words <b>${writer ? esc(writer) + "</b> for <b>AllMusic" : p.qobuz && p.qobuz.bio ? "Qobuz" : "Wikipedia"}</b>${credit ? ` &middot; Photograph <b>${credit}</b>` : ""} &middot; Shelved <b>${mine.length} ${mine.length === 1 ? "record" : "records"}</b></div>
      <nav class="mag-tabs">${[["story", "The story", ""], ["records", "The records", studioCount], ["live", "Live", liveCount]].filter(t => t[0] !== "live" || t[2]).map(t =>
        `<button class="${t[0] === tab ? "on" : ""}" data-act="magTab" data-v="${t[0]}">${t[1]}${t[2] ? ` <span>${t[2]}</span>` : ""}</button>`).join("")}
        <div class="mag-actbar">${mine.length ? `<button data-act="shuffleArtist" data-v="${esc(name)}">${icon("play")} Spin a record</button><button data-act="artistRadio" data-v="${esc(name)}">${icon("radio")} Their radio</button>` : ""}
          ${on("features", "stations") ? `<button class="seed-btn ${isSeed(realName) ? "on" : ""}" data-act="seedSheet" data-v="${esc(realName)}">${icon("radio_plus")} Add to a station</button>` : ""}<button data-act="artistBan" data-v="${esc(realName)}">${icon("ban")} Never play</button>
          ${p.hero ? "" : `<button data-act="artistPic">${icon("person")} Choose a picture</button>`}</div></nav>
      <div class="mag-page" data-tab="story" ${tab === "story" || (tab === "live" && !liveCount) ? "" : "hidden"}>
      ${p.hero ? `<figure class="mag-fig"><button class="pic-edit" data-act="artistPic" aria-label="Change their picture">${icon("edit")}</button><img src="${esc(pic(p.hero, 1600))}" alt=""><figcaption>${esc(realName)}${mb.area ? ", of " + esc(mb.area) : ""}${mb.begin ? `, ${mb.begin}${mb.end ? "–" + mb.end : " to the present"}` : ""}.</figcaption></figure>` : ""}
      <div class="mag-cols">
        <div class="mag-body">${body || `<p class="dim">Their story is still being gathered.</p>`}</div>
        <aside class="mag-side"><div class="ff"><div class="ff-h">Fact file</div><dl>
          ${fact(mb.type === "Person" ? "Born" : "Formed", mb.begin ? esc(mb.begin) + (mb.area ? ", " + esc(mb.area) : "") : "")}
          ${fact(mb.end ? (mb.type === "Person" ? "Died" : "Disbanded") : "", mb.end ? esc(mb.end) : "")}
          ${fact("Members", members.length ? members.slice(0, 6).map(esc).join(", ") + (members.length > 6 ? "…" : "") : "")}
          ${(mb.genres || []).length ? fact("Sounds like", tags.map(esc).join(", ") + ` <button class="g-edit ff-edit" data-act="artistTags" aria-label="Choose their tags">${icon("edit")}</button>`) : ""}
          ${fact("In the house", heard.plays ? `${heard.plays} plays, ${heard.finished} heard through${heard.last ? ", last " + new Date(heard.last * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : ""}` : "Not played yet")}
        </dl></div>
        ${like.length ? `<div class="mag-kin"><div class="ff-h">If you like them</div>${like.slice(0, 12).map(kinRow).join("")}
          ${like.length > 12 ? `<details><summary>${like.length - 12} more</summary>${like.slice(12).map(kinRow).join("")}</details>` : ""}</div>` : ""}
        ${studio.length ? `<div class="mag-recs"><div class="ff-h">The records</div>${studio.map(k => `<div class="mr-k">${k[1]}</div>${byYear(kinds[k[0]]).map(a =>
          `<a class="mr" href="${albumHref(a[0])}"><img loading="lazy" src="${cover(a[4], 150)}" alt=""><span class="y">${yearOf(a) || "&mdash;"}</span><b>${esc(a[1])}</b></a>`).join("")}`).join("")}</div>` : ""}</aside>
      </div></div>
      <div class="mag-page" data-tab="records" ${tab === "records" ? "" : "hidden"}>
      ${studio.length ? `<section class="mag-guide"><div class="mag-dept">Buyer's guide</div>${studio.map(k => `<h2>${k[1]} <span>${kinds[k[0]].length}</span></h2>${guide(kinds[k[0]])}`).join("")}</section>` : `<p class="dim">None of their studio records on the shelves yet.</p>`}
      ${awayHtml ? `<section class="mag-guide"><div class="mag-dept">Beyond the shelves</div><h2>Not on your shelves</h2>${awayHtml}</section>` : ""}</div>
      ${liveCount ? `<div class="mag-page" data-tab="live" ${tab === "live" ? "" : "hidden"}><section class="mag-guide"><div class="mag-dept">On stage</div>
        ${kinds.live.length ? `<h2>On the shelves <span>${kinds.live.length}</span></h2>${guide(kinds.live)}` : ""}
        ${shows.length ? `<h2>From the Internet Archive <span>${shows.length}</span></h2><div class="grid">${shows.map(x => archCard(x)).join("")}</div>` : ""}</section></div>` : ""}
    </article>`;
    if (p.partial && tries++ < 40) setTimeout(load, tries < 10 ? 1200 : 4000);
  }).catch(() => { el.innerHTML = `<div class="mag"><p class="dim">The presses jammed.</p></div>`; });
  load();
};

MAG.artist = (el, name) => VIEWS.mag(el, name);
MAG.discover = el => { A.homeAt = Date.now(); VIEWS.front(el); };
/* the front page as a magazine sets it (a mock-up, at #/front): the nameplate, the day's lead story with its picture and
   an index of the issue beside it, the other stories as shorter pieces, then the departments in columns: the radio, what
   the house is playing, new records, round numbers, records not heard lately; the artist of the day at the foot. */
VIEWS.front = function (el) {
  if (emptyShelves(el)) return;
  el.innerHTML = `<div class="mag"><p class="dim">Going to press&hellip;</p></div>`;
  Promise.all([api("/api/home"), api("/api/cover").catch(() => ({ stories: [] })), A.stations ? Promise.resolve(A.stations) : loadStations().catch(() => null)]).then(r => {
    if (!el.isConnected) return;
    const h = r[0], stories = (r[1].stories || []).filter(st => st.kind !== "night" || on("features", "archive")), st = (A.stations && A.stations.stations) || [];
    const issue = Math.floor((Date.now() - new Date("2026-01-01").getTime()) / 86400000) + 1;
    const date = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    const story = (x, big) => {
      const years = x.years ? cap(inWords(x.years)) + (x.years === 1 ? " year" : " years") : "";
      const k = { day: ["On this day", `${years} ago today`, x.title, x.artist, albumHref(x.album_id), cover(x.art, big ? 1600 : 600)],
        night: ["On this night", `${years} ago tonight`, x.artist, "Live at " + x.venue + (x.place ? ", " + x.place.split(",")[0] : ""), "#/show/" + encodeURIComponent(x.id || ""), x.bg ? pic(x.bg, big ? 1600 : 640) : pic(x.image, 640)],
        record: ["Record of the day", "Not heard lately", x.title, x.artist + (x.year ? ", " + x.year : ""), albumHref(x.album_id), cover(x.art, big ? 1600 : 600)],
        pick: ["Picked at random", "From your shelves", x.title, x.artist + (x.year ? ", " + x.year : ""), albumHref(x.album_id), cover(x.art, big ? 1600 : 600)],
        pickArtist: ["Picked at random", "From your shelves", x.name, (albumsBy(x.name).length) + " records on the shelves", artistHref(x.name), ""],
        born: ["Born on this day", cap(inWords(x.years)) + " today", x.name, x.member ? "Of " + x.artist : "", artistHref(x.member ? x.artist : x.name), x.pic ? pic(x.pic, big ? 1600 : 640) : ""],
        died: ["Remembered", `${years} ago today`, x.name, (x.member ? "Of " + x.artist + " · " : "") + (x.born ? x.born + "–" + x.died : ""), artistHref(x.member ? x.artist : x.name), x.pic ? pic(x.pic, big ? 1600 : 640) : ""] }[x.kind];
      if (!k) return "";
      const text = x.text ? standfirst(x.text, big ? 300 : 150) : x.kind === "night" && x.others ? `One of ${x.others + 1} shows in your Archive collections recorded on this date.` : "";
      return `<article class="fp-story ${big ? "lead" : ""}"><a href="${k[4]}">${k[5] ? `<figure><img src="${esc(k[5])}" alt=""></figure>` : ""}</a>
        <div class="mag-dept">${k[0]}</div><div class="fp-when">${esc(k[1])}</div><h2><a href="${k[4]}">${esc(k[2])}</a></h2><div class="fp-by">${esc(k[3])}</div>${text ? `<p>${esc(text)}</p>` : ""}${x.album_id ? `<button class="fp-spin" data-act="playAlbum" data-v="${x.album_id}">${icon("play")} Spin it</button>` : ""}</article>`;
    };
    const picked = A.heroAlbum && A.byId.get(A.heroAlbum);
    const lead = picked ? { kind: "pick", album_id: picked[0], title: picked[1], artist: picked[2], art: picked[4], year: picked[3], text: "" }
      : A.heroPick ? { kind: "pickArtist", name: A.heroPick } : stories[0];
    const rest = picked || A.heroPick ? stories : stories.slice(1);
    const cards = ids => ids.map(id => A.byId.get(id)).filter(Boolean);
    const mini = (a, sub) => `<a class="fp-mini" href="${albumHref(a[0])}"><img loading="lazy" src="${cover(a[4], 150)}" alt=""><span><b>${esc(a[1])}</b><em>${esc(sub || a[2])}</em></span></a>`;
    const round = [].concat.apply([], (h.round || []).map(g => cards(g.albums).map(a => [g.age, a]))).slice(0, 6);
    const sections = [["radio", "On the radio"], ["playing", "What the house is playing"], ["new", "New records"], ["round", "Round numbers"], ["lately", "Not heard lately"], ["artist", "Artist of the day"]];
    const sec = (dept, title, body, cls) => `<section class="fp-sec ${cls || ""}"><div class="mag-dept">${dept}</div><h3>${title}</h3>${body}</section>`;
    el.innerHTML = `<article class="mag fp">
      <header class="fp-plate"><div class="fp-line"><span>Vol. 1 &middot; No. ${issue}</span><span>${esc(date)}</span><span>${A.albums.length.toLocaleString()} records on the shelves</span></div>
        <h1>Sound<em>squatch</em></h1><div class="fp-line fp-tag"><span>Music for the house</span><button class="mast-search" data-act="searchOpen" aria-label="Search">${icon("search")}</button></div></header>
      <div class="fp-top">${lead ? story(lead, true) : `<p class="dim">No stories today.</p>`}<div class="fp-also">${rest.map(x => story(x, false)).join("")}
        <div class="fp-lucky"><button data-act="surprise">${icon("dice")} A record at random</button><button data-act="pickArtist">${icon("person")} An artist at random</button></div></div></div>
      ${picked || A.heroPick ? `<div class="fp-back"><button data-act="heroBack">Back to today's paper</button></div>` : ""}
      ${newArrivals(1).length ? sec("Just in", `Recently added <a class="fp-all" href="#/albums" data-act="recentAll">All of them</a>`, shelf(newArrivals(20).map(arrivalCard))) : ""}
      ${st.length ? sec("On the radio", "Stations", shelf(st.map(stationCard))) : ""}
      ${h.spotlight ? `<section class="fp-artist" id="fp-artist"><div class="mag-dept">Artist of the day</div></section>` : ""}
      <div class="fp-pair">
        ${(h.rotation || []).length ? sec("What the house is playing", "On rotation", `<div class="fp-faces">${h.rotation.slice(0, 8).map(n => face(n, "", albumsBy(n).length + " on the shelves")).join("")}</div>`) : ""}
        ${(h["new"] || []).length ? sec("New records", "Out lately", `<div class="fp-covers">${h["new"].slice(0, 6).map(newCard).join("")}</div>`) : ""}
      </div>
      ${(h.back || []).length ? sec("Pick up where you left off", "Back to it", shelf(cards(h.back).map(a => albumCard(a)))) : ""}
      ${round.length ? sec("Round numbers", "This month's anniversaries", shelf(round.map(x => `<div class="rn"><span class="rn-age">${x[0]}</span>${albumCard(x[1])}</div>`))) : ""}
      <div id="fp-because"></div>
      ${A.archive.length && on("features", "archive") ? sec("From the Internet Archive", "Live on your shelves", shelf(A.archive.map(x => archCard(x)))) : ""}
      ${(h.rediscover || []).length ? sec("Not heard lately", "Rediscover", `<div class="mosaic">${cards(h.rediscover.slice(0, 5)).map((a, i) => albumCard(a, i === 0 ? "big" : "")).join("")}</div>`) : ""}
      ${(h.connections || []).length ? sec("Who played with whom", "Connections", `<div class="links">${h.connections.slice(0, 6).map(linkCard).join("")}</div>`) : ""}
      ${(h.decade_albums || []).length ? sec("A decade, drawn at random", `The ${h.decade}s`, shelf(cards(h.decade_albums).map(a => albumCard(a)))) : ""}
      ${h.genre ? sec("Genre of the day", `<a href="#/genre/${encodeURIComponent(h.genre)}">${esc(h.genre)}</a>`, shelf(shuffled(A.albums.filter(a => a[4] && (a[8] || []).indexOf(h.genre) >= 0), seeded(h.date || "")).slice(0, 16).map(a => albumCard(a)))) : ""}
    </article>`;
    if (lead && lead.kind === "pickArtist") profile(lead.name).then(p => { // the artist picked: their picture over the lead
      const a = $(".fp-story.lead > a", el), img = p.hero || p.thumb; if (a && img && !a.querySelector("img")) a.innerHTML = `<figure><img src="${esc(pic(img, 1600))}" alt=""></figure>`;
    }).catch(() => {});
    const playing = nowArtist();
    if (playing) profile(playing).then(p => { const box = $("#fp-because", el); if (!box) return; const html = becauseHtml(p); if (html) box.outerHTML = html.replace('<section class="sec', '<section class="sec fp-sec'); }).catch(() => {});
    if (h.spotlight) profile(h.spotlight).then(p => {
      const box = $("#fp-artist", el); if (!box) return;
      const text = (p.qobuz && p.qobuz.bio) || (p.wiki && p.wiki.extract) || "";
      box.insertAdjacentHTML("beforeend", `<a class="fp-artist-body" href="${artistHref(h.spotlight)}">${p.hero ? `<img src="${esc(pic(p.hero, 1600))}" alt="">` : ""}<div class="fp-artist-text"><h2>${esc((p.qobuz && p.qobuz.name) || h.spotlight)}</h2><p>${esc(standfirst(paras(text)[0] || "", 150))}</p><span class="fp-more">Read the profile</span></div></a>`);
    }).catch(() => {});
    leadWords(el, lead);
    settlingStrip(el);
  }).catch(() => { el.innerHTML = `<div class="mag"><p class="dim">The presses jammed.</p></div>`; });
};
MAG.album = function (el, id) {
  const a = A.byId.get(+id) || [+id, "", "", 0, "", 0, "", 0, []];
  const title = a[1], artist = a[2], more = albumsBy(artist).filter(x => x[0] !== a[0] && !x.archive);
  const vers = versionsOf(a), tab = store.get("sq-mag-album-tab", "tracks");
  const pane = (k, html) => `<div class="mag-page" data-tab="${k}" ${tab === k ? "" : "hidden"}>${html}</div>`;
  el.innerHTML = `<article class="mag">${magRun("The Records")}
    <div class="mag-dept mag-kind">The record</div>
    <h1 class="mag-head mag-head-album">${title ? hearted(title, mk("album", albumKey(a), "heart")) : "&hellip;"}</h1>
    <p class="mag-deck mag-album-deck">${artist ? `By <a href="${artistHref(artist)}">${esc(artist)}</a>` : ""}${a[3] ? `, ${a[3]}` : ""}.</p>
    <div class="mag-by">${[a[6] ? `<b>${esc(a[6])}</b>` : "", `<span class="mag-len"></span>`, vers.length > 1 ? `<button class="ver-chip" data-act="versions" data-v="${a[0]}">${vers.length} pressings</button>` : "", a[9] === "qobuz" ? "On Qobuz" : "On the shelves"].filter(Boolean).join(" &middot; ")}</div>
    <div class="mag-album">
      <figure class="mag-cover"><div class="album-art">${a[4] ? `<img src="${cover(a[4], 800)}" alt="">` : `<div class="noart big">${esc((title || "?").slice(0, 1))}</div>`}${title && on("features", "write_files") ? `<button class="art-edit" data-act="artEdit" data-v="${a[0]}" aria-label="Change the cover">${icon("edit")}</button>` : ""}</div></figure>
      <aside class="mag-side"><div class="ff"><div class="ff-h">The particulars</div><dl>
        <div class="ff-row"><dt>Genres</dt><dd class="genres">${(a[8] || []).map(g => `<a href="#/genre/${encodeURIComponent(g)}">${esc(g)}</a>`).join("")}<button class="g-edit${(a[8] || []).length ? "" : " named"}" data-act="genreEdit" data-v="${a[0]}">${icon("edit")}${(a[8] || []).length ? "" : " Add genres"}</button></dd></div>
        ${title ? `<div class="ff-row"><dt>Your marks</dt><dd class="al-marks">${mk("album", albumKey(a), "stars")}${mk("album", albumKey(a), "tags")}</dd></div>` : ""}
      </dl></div>
      <div class="mag-acts"><button data-act="playAlbum" data-v="${a[0]}">${icon("play")} Spin it</button><button data-act="nextAlbum" data-v="${a[0]}">${icon("next_up")} Spin it next</button>
        <button data-act="queueAlbum" data-v="${a[0]}">${icon("queue")} Queue it</button><button data-act="addToPlaylist" data-v="album:${a[0]}">${icon("list")} Add to a playlist</button>
        ${artist && on("features", "stations") ? `<button class="seed-btn ${isSeed(artist) ? "on" : ""}" data-act="seedSheet" data-v="${esc(artist)}">${icon("radio_plus")} Add ${esc(artist)} to a station</button>` : ""}
        <span class="mag-share"></span>
        ${title ? `<button data-act="removeAsk" data-v="${a[0]}">${icon("trash")} Remove from the library</button>` : ""}</div></aside>
    </div>
    <nav class="mag-tabs">${[["tracks", "The tracks"], ["story", "The story"], ["credits", "Credits"]].filter(t => t[0] !== "credits" || on("features", "credits")).map(t =>
      `<button class="${t[0] === tab ? "on" : ""}" data-act="magTab" data-v="${t[0]}" data-store="sq-mag-album-tab">${t[1]}</button>`).join("")}</nav>
    ${pane("tracks", `<div class="tracks mag-tracks loading-rows">${"<div class='trk ph'></div>".repeat(8)}</div>`)}
    ${pane("story", `<div class="mag-body mag-review"><p class="dim">Looking for its story&hellip;</p></div>`)}
    ${pane("credits", `<div class="mag-credits"><p class="dim">Asking after the credits&hellip;</p></div>`)}
    ${more.length ? `<section class="mag-guide"><div class="mag-dept">Also on the shelves</div><h2>More by ${esc(artist)}</h2><ol>${more.slice().sort((x, y) => (x[3] || 9999) - (y[3] || 9999)).map(x =>
      `<li><a href="${albumHref(x[0])}"><img loading="lazy" src="${cover(x[4], 300)}" alt=""><span class="y">${x[3] || "&mdash;"}</span><b>${esc(x[1])}</b><em>${esc((x[8] || [])[0] || "")}</em></a></li>`).join("")}</ol></section>` : ""}
  </article>`;
  const img = $(".mag-cover img", el); if (img) tint(img, el);
  if (title) api("/api/share?album_id=" + a[0]).then(r => { const box = $(".mag-share", el); if (r.url && box && el.isConnected) box.outerHTML = `<button data-act="share" data-v="${esc(JSON.stringify({ title: title + " by " + artist, url: r.url }))}">${icon("share")} Share</button>`; }).catch(() => {});
  profile(artist).then(p => { const k = $(".mag-kind", el); if (k && title) k.textContent = { album: "The LP", ep: "The EP", live: "Live", comp: "The compilation" }[kindOf(a, p.rgs)]; }).catch(() => {});
  albumData(id).then(d => {
    if (!el.isConnected) return;
    const by = d.artist || artist, multi = d.tracks.some(t => t.disc && t.disc !== d.tracks[0].disc), various = d.tracks.some(t => t.artist && norm(t.artist) !== norm(by));
    const total = d.tracks.reduce((s, t) => s + t.duration, 0);
    let disc = null;
    $(".mag-tracks", el).outerHTML = `<div class="tracks mag-tracks">${d.tracks.map((t, i) => {
      const head = multi && t.disc !== disc ? `<div class="disc">Side ${esc(t.disc)}</div>` : ""; disc = t.disc;
      return `${head}<div class="trk" data-act="playTrack" data-v="${d.id}:${i}"><span class="n">${esc(t.n || i + 1)}</span><span class="tt">${esc(t.title)}${various && t.artist ? `<em>${esc(t.artist)}</em>` : ""}</span>${mk("track", trackKey(t), "loved")}<span class="d">${mmss(t.duration)}</span><button class="trk-more" data-act="trackMenu" data-v="${d.id}:${i}" aria-label="More">${icon("more")}</button></div>`;
    }).join("")}</div>`;
    const len = $(".mag-len", el); if (len) len.textContent = `${d.tracks.length} tracks, ${Math.round(total / 60)} minutes`;
    if (!title) { $(".mag-head", el).textContent = d.album; }
    const story = text => {
      const list = paras(text || ""), box = $(".mag-review", el); if (!box) return;
      box.innerHTML = list.length ? list.map((x, i) => `<p${i ? "" : ' class="dc"'}>${linked(x, artist)}</p>`).join("") + `<p class="mag-src">From Wikipedia</p>` : `<p class="dim">No one has written about this one yet.</p>`;
      const deck = $(".mag-album-deck", el); if (deck && list.length) deck.insertAdjacentHTML("beforeend", ` ${esc(standfirst(list[0], 160))}`);
    };
    if (d.review != null) story(d.review); else api("/api/review?id=" + encodeURIComponent(id)).then(r => { if (el.isConnected) story(r.review); }).catch(() => story(""));
    if (on("features", "credits")) creditsFor(a[0]).then(c => { const box = $(".mag-credits", el); if (box && el.isConnected) box.innerHTML = creditsHtml(c) || `<p class="dim">No credits known for it.</p>`; }).catch(() => {});
  }).catch(() => { const t = $(".mag-tracks", el); if (t) t.outerHTML = `<p class="dim">Couldn't load the tracks.</p>`; });
};

/* ───────────────────────── an album ───────────────────────── */
VIEWS.album = function (el, id) {
  // the page is drawn at once from the library's own row; the tracks, the review and kindred artists arrive into it
  const a = A.byId.get(+id) || [+id, "", "", 0, "", 0, "", 0, []];
  const title = a[1], artist = a[2], more = albumsBy(artist).filter(x => x[0] !== a[0]);
  el.innerHTML = `${pageBar(esc(title || "Album"), ["Album", esc(artist)], `<button class="pill" data-act="playAlbum" data-v="${a[0]}" aria-label="Spin it">${icon("play")}<span class="pl">Spin it</span></button>`, true)}<div class="album-bg">${a[4] ? `<img src="${cover(a[4], 150)}" alt="">` : ""}</div><div class="album">
    <div class="album-art">${a[4] ? `<img src="${cover(a[4], 800)}" alt="">` : `<div class="noart big">${esc((title || "?").slice(0, 1))}</div>`}${title && on("features", "write_files") ? `<button class="art-edit" data-act="artEdit" data-v="${a[0]}" aria-label="Change the cover">${icon("edit")}</button>` : ""}</div>
    <div class="album-head"><div class="kicker al-kick">${[a[3] || "", a[6] ? `<span class="q">${esc(a[6])}</span>` : "", versionsOf(a).length > 1 ? `<button class="ver-chip" data-act="versions" data-v="${a[0]}">${versionsOf(a).length} pressings</button>` : ""].filter(Boolean).join(" &middot; ")}</div>
      <h1 class="al-title">${title ? hearted(title, mk("album", albumKey(a), "heart")) : ""}</h1><div class="byline">${artist ? hearted(artist, mk("artist", norm(artist), "heart"), `<a class="by al-by" href="${artistHref(artist)}">`, "</a>") : `<a class="by al-by" href="#/"></a>`}</div>
      ${title ? `<div class="genres">${(a[8] || []).map(g => `<a href="#/genre/${encodeURIComponent(g)}">${esc(g)}</a>`).join("")}${(a[8] || []).length ? `<button class="g-edit" data-act="genreEdit" data-v="${a[0]}" aria-label="Edit genres">${icon("edit")}</button>` : `<button class="g-edit named" data-act="genreEdit" data-v="${a[0]}">${icon("edit")} Add genres</button>`}</div>` : ""}
      ${title ? `<div class="al-marks">${mk("album", albumKey(a), "stars")}${mk("album", albumKey(a), "tags")}</div>` : ""}
      <div class="acts"><button class="btn" data-act="playAlbum" data-v="${a[0]}">${icon("play")} Spin it</button><button class="btn ghost" data-act="nextAlbum" data-v="${a[0]}">${icon("next_up")} Spin it next</button>
      <button class="btn ghost" data-act="queueAlbum" data-v="${a[0]}">${icon("queue")} Queue</button>
      <button class="btn ghost" data-act="addToPlaylist" data-v="album:${a[0]}" aria-label="Add to a playlist">${icon("list")}</button>
      ${title ? `<button class="btn ghost" data-act="removeAsk" data-v="${a[0]}" aria-label="Remove from the library">${icon("trash")}</button>` : ""}</div>
      <div class="tracks loading-rows">${"<div class='trk ph'></div>".repeat(8)}</div></div></div>
    <div id="al-review"></div><div id="al-credits"></div>
    ${more.length ? section("Also on your shelves", "More by " + esc(artist), shelf(more.map(x => albumCard(x)))) : ""}<div id="al-sim"></div>`;
  const img = $(".album-art img", el); if (img) tint(img, el);
  const showReview = text => {
    const review = paras(text), box = $("#al-review", el);
    if (box && review.length) box.outerHTML = `<section class="sec review"><div class="kicker">About the record</div>${folded(review, 3, artist)}<div class="credit">From Wikipedia</div></section>`;
  };
  albumData(id).then(d => {
    if (!el.isConnected) return;
    const by = d.artist || artist, multi = d.tracks.some(t => t.disc && t.disc !== d.tracks[0].disc);
    const variousArtists = d.tracks.some(t => t.artist && norm(t.artist) !== norm(by));
    const total = d.tracks.reduce((s, t) => s + t.duration, 0);
    let disc = null;
    $(".tracks", el).outerHTML = `<div class="tracks">${d.tracks.map((t, i) => {
      const head = multi && t.disc !== disc ? `<div class="disc">Disc ${esc(t.disc)}</div>` : ""; disc = t.disc;
      return `${head}<div class="trk" data-act="playTrack" data-v="${d.id}:${i}"><span class="n">${esc(t.n || i + 1)}</span><span class="tt">${esc(t.title)}${variousArtists && t.artist ? `<em>${esc(t.artist)}</em>` : ""}</span>${mk("track", trackKey(t), "loved")}<span class="d">${mmss(t.duration)}</span><button class="trk-more" data-act="trackMenu" data-v="${d.id}:${i}" aria-label="More">${icon("more")}</button></div>`;
    }).join("")}</div>`;
    $(".al-kick", el).insertAdjacentHTML("beforeend", (a[3] || a[6] ? " &middot; " : "") + d.tracks.length + " tracks &middot; " + Math.round(total / 60) + " min");
    if (!title) { $(".al-title", el).textContent = d.album; $(".al-by", el).textContent = by; $(".al-by", el).setAttribute("href", artistHref(by)); }
    if (title) api("/api/share?album_id=" + a[0]).then(r => { const acts = $(".album-head .acts", el); if (r.url && acts && el.isConnected) { const bin = $('[data-act="removeAsk"]', acts); if (bin) bin.insertAdjacentHTML("beforebegin", shareBtn(title + " by " + artist, r.url)); else acts.insertAdjacentHTML("beforeend", shareBtn(title + " by " + artist, r.url)); } }).catch(() => {});
    if (title && on("features", "credits")) creditsFor(a[0]).then(c => { const box = $("#al-credits", el); if (box && el.isConnected) box.outerHTML = creditsHtml(c); }).catch(() => {});
    if (d.review != null) showReview(d.review);
    else api("/api/review?id=" + encodeURIComponent(id)).then(r => { if (el.isConnected) showReview(r.review); }).catch(() => {});
    profile(by).then(p => {
      const box = $("#al-sim", el), sim = (p.qobuz && p.qobuz.similar) || [];
      if (box && sim.length) box.outerHTML = section("If you like this", "Kindred spirits", shelf(sim.map(s => face(s.name, s.image, onShelves(s.name) ? "on your shelves" : ""))));
    }).catch(() => {});
  }).catch(() => { const t = $(".tracks", el); if (t) t.outerHTML = `<p class="dim">Couldn't load the tracks.</p>`; });
};
// an album's tracks, kept for the session (and asked for as the finger lands on a cover)
const albumCache = new Map();
function albumData(id) {
  id = String(id);
  if (!albumCache.has(id)) albumCache.set(id, api("/api/album?id=" + encodeURIComponent(id)).catch(e => { albumCache.delete(id); throw e; }));
  return albumCache.get(id);
}

/* ───────────────────────── the Internet Archive (Lyrion's ArchiveLMA plugin) ─────────────────────────
   Its favourites stand on the shelves beside the albums (an "Archive" card, a filter on Albums, a Discover shelf); an
   artist's shows from the plugin's collections are on their page. A show opens in a sheet: its setlist, and the plugin's
   own Play, Queue and Favourite, so it plays exactly as it does from the plugin. */
A.archive = [];
function loadArchive() { return api("/api/archive/favorites").then(r => { A.archive = r.shows; }).catch(() => {}); }
// a show as an album row for the Albums page's sorts: [id, title, artist, year, art, rank, quality, artist id, genres] + .archive
// a favourite added since Soundsquatch has been watching leads Recently added (newest first); the older ones, undated, close it
function archRow(x, i) { const r = ["arch:" + i, "Live at " + x.venue, x.artist, +(x.date || "").slice(0, 4) || 0, "", 1e6 + i, "Archive", 0, [], "archive", [], Math.round(x.added || 0)]; r.archive = x; return r; } // [11]: when it was made a favourite
A.shows = {}; // every show a card has been drawn for, by its archive.org identifier: what its page starts from
function archCard(x, cls) {
  const img = x.image ? `<img loading="lazy" decoding="async" src="${esc(x.image)}" alt="">` : `<div class="noart">${esc(x.artist.slice(0, 1))}</div>`;
  if (x.id) A.shows[x.id] = x;
  const open = x.id ? `href="#/show/${encodeURIComponent(x.id)}"` : `data-act="archShow" data-v="${esc(JSON.stringify(x))}"`;
  return `<a class="card q ${cls || ""}" ${open}><div class="art">${img}<span class="badge">Archive</span></div>
    <div class="t">${esc(x.venue ? "Live at " + x.venue : x.title)}</div><div class="s">${esc(x.artist)}${x.date ? " &middot; " + esc(x.date) : ""}</div></a>`;
}

/* a show's own page, laid out as an album's: the picture, what and where, the buttons, the setlist with its lengths, then
   archive.org's notes on it and on the recording, more of the artist's shows, and their albums on the shelves */
VIEWS.show = function (el, id) {
  el.classList.add("v-album"); // an album's page in all but name: its bar, its layout
  let x = A.shows[id] || A.archive.filter(f => f.id === id)[0] || { id: id, artist: "", venue: "", date: "", title: "", image: "", ctx: null };
  const fav = () => A.archive.some(f => f.id === id);
  const draw = () => {
    const name = x.venue ? "Live at " + x.venue : (x.title || "A show");
    el.innerHTML = `${pageBar(esc(name), ["Archive", esc(x.artist)], `<button class="pill" data-act="archDo" data-v="play" aria-label="Spin it">${icon("play")}<span class="pl">Spin it</span></button>`, true)}
      <div class="album-bg">${x.image ? `<img src="${esc(x.image)}" alt="">` : ""}</div><div class="album" data-show="${esc(JSON.stringify(x))}">
      <div class="album-art">${x.image ? `<img src="${esc(x.image)}" alt="">` : `<div class="noart big">${esc((x.artist || "?").slice(0, 1))}</div>`}</div>
      <div class="album-head"><div class="kicker al-kick">${[(x.date || "").slice(0, 4), `<span class="q">Archive</span>`].filter(Boolean).join(" &middot; ")}</div>
        <h1 class="al-title">${esc(name)}</h1>${x.artist ? `<div class="byline">${hearted(x.artist, mk("artist", norm(x.artist), "heart"), `<a class="by al-by" href="${artistHref(x.artist)}">`, "</a>")}</div>` : ""}
        <div class="genres sh-when">${x.date ? `<span>${esc(new Date(x.date + "T12:00").toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" }))}</span>` : ""}</div>
        <div class="acts"><button class="btn" data-act="archDo" data-v="play">${icon("play")} Spin it</button><button class="btn ghost" data-act="archDo" data-v="queue">${icon("queue")} Queue</button>
          <button class="btn ghost arch-fav" data-act="archDo" data-v="${fav() ? "unfav" : "fav"}" aria-label="${fav() ? "On your shelves" : "Add to your shelves"}">${icon(fav() ? "heart_on" : "heart")}</button>
          ${shareBtn(x.artist + (x.venue ? " live at " + x.venue : "") + (x.date ? ", " + x.date : ""), archiveLink(x.image) || "https://archive.org/details/" + id)}</div>
        <div class="tracks loading-rows">${"<div class='trk ph'></div>".repeat(8)}</div></div></div>
      <div id="sh-notes"></div><div id="sh-rec"></div><div id="sh-more"></div><div id="sh-albums"></div>`;
    const img = $(".album-art img", el); if (img) tint(img, el);
  };
  draw();
  api("/api/archive/details?id=" + encodeURIComponent(id)).then(d => {
    if (!el.isConnected || d.error) return;
    if (!x.artist) { x = Object.assign(x, { artist: d.creator, venue: d.venue, date: d.date, title: d.title }); draw(); }
    const total = d.tracks.reduce((n, t) => n + t.length, 0);
    $(".al-kick", el).insertAdjacentHTML("beforeend", ` &middot; ${d.tracks.length} tracks${total ? " &middot; " + Math.round(total / 60) + " min" : ""}`);
    if (d.place) $(".sh-when", el).insertAdjacentHTML("beforeend", `<span>${esc(d.place)}</span>`);
    const lengths = {}; d.tracks.forEach(t => { lengths[t.title.toLowerCase()] = t.length; });
    // the setlist the plugin plays (its order is the one "play from here" counts in), with archive.org's lengths
    const setlist = names => {
      const box = $(".tracks", el); if (!box) return;
      // files named only "Track 02", or by the date: the notes' own setlist, when it has as many songs, names them instead
      const generic = n => /^(track|tr|t)?\s*\d+$/i.test(n.trim()) || /\b(19|20)\d\d\b/.test(n);
      const fromNotes = d.setlist && d.setlist.length === names.length && names.filter(generic).length >= names.length / 2;
      if (fromNotes) names = d.setlist;
      box.outerHTML = `<div class="tracks">${names.map((n, i) => { const len = lengths[n.toLowerCase()] || (names.length === d.tracks.length ? d.tracks[i].length : 0);
        return `<div class="trk" data-act="archDo" data-v="track" data-i="${i}"><span class="n">${i + 1}</span><span class="tt">${esc(n)}</span><span class="d">${len ? mmss(len) : ""}</span></div>`; }).join("")}</div>${fromNotes ? `<div class="credit tracks-note">Titles from the show's notes</div>` : ""}`;
    };
    const withCtx = ctx => { x.ctx = ctx; const h = $("[data-show]", el); if (h) h.dataset.show = JSON.stringify(x);
      api("/api/archive/show", { ctx: ctx, player: A.room }).then(r => setlist(r.tracks.length ? r.tracks : d.tracks.map(t => t.title))).catch(() => setlist(d.tracks.map(t => t.title))); };
    if (x.ctx) withCtx(x.ctx);
    else archiveOf(d.creator).then(shows => { const hit = shows.filter(s => s.id === id)[0]; if (hit) withCtx(hit.ctx); else setlist(d.tracks.map(t => t.title)); });
    // archive.org's notes, unless they are only the setlist again
    const notes = paras(d.notes), titles = {}; d.tracks.forEach(t => { titles[t.title.toLowerCase()] = 1; });
    const repeats = notes.filter(l => titles[l.replace(/^(d\d+)?t?\d+[\s.):-]*/i, "").trim().toLowerCase()]).length;
    if (notes.length && repeats < notes.length * 0.6) $("#sh-notes", el).outerHTML = `<section class="sec review"><div class="kicker">About the show</div>${folded(notes, 3)}<div class="credit">From archive.org</div></section>`;
    const rec = [["Source", d.source], ["Lineage", d.lineage], ["Taper", d.taper], ["Transfer", d.transferer], ["Running time", d.runtime]].filter(r => r[1] && r[1] !== "None");
    if (rec.length) $("#sh-rec", el).outerHTML = section("How it was taped", "The recording", `<dl class="credits">${rec.map(r => `<dt>${r[0]}</dt><dd>${esc(r[1])}</dd>`).join("")}</dl><div class="credit"><a href="${esc(d.url)}" target="_blank" rel="noopener">archive.org/details/${esc(id)}</a></div>`, "", "credits-sec");
    archiveOf(d.creator).then(shows => { const box = $("#sh-more", el), more = shows.filter(s => s.id !== id); if (box && more.length) box.outerHTML = section("From the Internet Archive", `More ${esc(d.creator)} live <span class="count-inline">${more.length}</span>`, shelf(more.slice(0, 40).map(s => archCard(s)))); });
    const mine = albumsBy(d.creator); if (mine.length) $("#sh-albums", el).outerHTML = section("Also on your shelves", "Albums by " + esc(d.creator), shelf(mine.map(a => albumCard(a))));
  }).catch(() => { const t = $(".tracks", el); if (t) t.outerHTML = `<p class="dim">The Archive isn't answering.</p>`; });
};
const archArtistCache = new Map();
function archiveOf(name) {
  const k = norm(name);
  if (!archArtistCache.has(k)) archArtistCache.set(k, api("/api/archive/artist?name=" + encodeURIComponent(name)).then(r => r.shows).catch(() => { archArtistCache.delete(k); return []; }));
  return archArtistCache.get(k);
}
function openArchive(x) {
  const fav = A.archive.some(f => f.title === x.title);
  openSheet(`<div class="qs arch" data-show="${esc(JSON.stringify(x))}">${x.image ? `<img src="${esc(x.image)}" alt="">` : ""}<div><div class="kicker">The Internet Archive</div>
    <h3>${esc(x.venue ? "Live at " + x.venue : x.title)}</h3><a class="dim" href="${artistHref(x.artist)}" data-act="closeSheet">${esc(x.artist)}</a>${x.date ? `<div class="dim">${esc(new Date(x.date + "T12:00").toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" }))}</div>` : ""}
    <div class="acts col"><button class="btn" data-act="archDo" data-v="play">${icon("play")} Spin it in ${esc(roomName(A.room))}</button><button class="btn ghost" data-act="archDo" data-v="queue">${icon("queue")} Queue it</button>
    <button class="btn ghost arch-fav" data-act="archDo" data-v="${fav ? "unfav" : "fav"}">${icon(fav ? "heart_on" : "heart")} ${fav ? "On your shelves" : "Add to your shelves"}</button>${shareBtn(x.artist + (x.venue ? " live at " + x.venue : "") + (x.date ? ", " + x.date : ""), archiveLink(x.image), "wide")}</div></div></div>
    <div class="kicker setlist-h">Setlist</div><div class="setlist"><p class="dim">Asking the Archive&hellip;</p></div>`);
  api("/api/archive/show", { ctx: x.ctx, player: A.room }).then(r => {
    const box = $("#sheet .setlist"); if (!box) return;
    box.innerHTML = r.tracks.length ? r.tracks.map((t, i) => `<button class="trk" data-act="archDo" data-v="track" data-i="${i}"><span class="n">${i + 1}</span><span class="tt">${esc(t)}</span></button>`).join("") : `<p class="dim">No tracks listed.</p>`;
  }).catch(() => { const box = $("#sheet .setlist"); if (box) box.innerHTML = `<p class="dim">The Archive isn't answering.</p>`; });
}

/* ───────────────────────── sharing: a Qobuz album's or an Archive show's public address ─────────────────────────
   The device's own share sheet where the page may use it (only on a secure, https page), else a small one of ours:
   the link, Copy, Messages, Mail. */
function qobuzLink(cover) { const m = decodeURIComponent(cover || "").match(/\/images\/covers\/[^\/]+\/[^\/]+\/([A-Za-z0-9]+)_\d+\.jpg/); return m ? "https://open.qobuz.com/album/" + m[1] : ""; }
function archiveLink(image) { const m = decodeURIComponent(image || "").match(/archive\.org\/services\/img\/([^\/?#]+)/); return m ? "https://archive.org/details/" + m[1] : ""; }
const shareBtn = (title, url, cls) => url ? `<button class="btn ghost share ${cls || ""}" data-act="share" data-v="${esc(JSON.stringify({ title: title, url: url }))}" aria-label="Share">${icon("share")}</button>` : "";
function shareIt(x) {
  if (navigator.share && window.isSecureContext) { navigator.share({ title: x.title, url: x.url }).catch(() => {}); return; }
  const body = encodeURIComponent(x.title + " " + x.url);
  openSheet(`<div class="kicker">Share</div><h3>${esc(x.title)}</h3><input class="share-url" readonly value="${esc(x.url)}">
    <div class="acts col"><button class="btn" data-act="copyLink">Copy link</button><a class="btn ghost" href="sms:&body=${body}">Messages</a>
    <a class="btn ghost" href="mailto:?subject=${encodeURIComponent(x.title)}&body=${encodeURIComponent(x.url)}">Mail</a><button class="btn ghost" data-act="closeSheet">Done</button></div>`);
}

/* ───────────────────────── stations: the chill mix's way, for every bin ───────────────────────── */
A.stations = null;
function loadStations() { return api("/api/stations").then(r => { A.stations = r; return r; }); }
function stationCard(st) {
  return `<div class="card q station" data-act="stationSheet" data-v="${esc(st.key)}"><div class="art"><div class="gm">${st.arts.map(u => `<img loading="lazy" src="${cover(u, 150)}" alt="">`).join("")}</div>
    <div class="st-name">${esc(st.name)}</div></div><div class="s">${esc(st.blurb)}</div></div>`;
}
function openStation(k) {
  const st = (A.stations && A.stations.stations || []).find(x => x.key === k); if (!st) return;
  openSheet(`<div data-station="${esc(st.key)}"><div class="kicker">Station</div><h3>${esc(st.name)}</h3>${st.blurb ? `<div class="dim">${esc(st.blurb)}</div>` : ""}
    <p class="plan-note">Three of its seed artists, nine of their tracks, then the radio carries on with music like them.</p>
    <div class="acts col">${st.seeds.length ? `<button class="btn" data-act="stationGo" data-v="${esc(st.key)}">${icon("radio")} Spin it in ${esc(roomName(A.room))}</button>` : `<p class="dim">Add a seed artist or two to play it.</p>`}</div>
    <div class="kicker seeds-h">Seed artists <span class="count-inline">${st.seeds.length}</span></div>
    <div class="seeds">${st.seeds.map(n => `<span class="seed"><a href="${artistHref(n)}" data-act="closeSheet">${esc(n)}</a><button data-act="seedRemove" data-v="${esc(n)}" aria-label="Take ${esc(n)} off">${icon("close")}</button></span>`).join("")}</div>
    <div class="seed-add"><input id="seed-in" list="seed-list" placeholder="Add an artist from your shelves" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
      <datalist id="seed-list">${A.artists.map(a => `<option value="${esc(a[0])}">`).join("")}</datalist><button class="pill" data-act="seedAdd">Add</button></div>
    <div class="station-foot"><button class="pill" data-act="stationRename">Rename</button><button class="pill danger" data-act="stationDelete">Delete the station</button></div></div>`);
  const input = $("#seed-in"); if (input) input.addEventListener("keydown", e => { if (e.key === "Enter") ACT.seedAdd(); });
}
// an artist among a station's seeds, anywhere: the + is lit
const isSeed = name => !!(A.stations && name && A.stations.stations.some(st => st.seeds.some(x => norm(x) === norm(name))));
function seedSheet(name) {
  const list = (A.stations && A.stations.stations) || [];
  openSheet(`<div class="kicker">Seed of a station</div><h3>${esc(name)}</h3>
    <div class="gpicks" data-artist="${esc(name)}">${list.map(st => `<button class="gpick ${st.seeds.some(x => norm(x) === norm(name)) ? "on" : ""}" data-act="seedToggle" data-v="${esc(st.key)}">${esc(st.name)}</button>`).join("")}</div>
    <div class="seed-add"><input id="st-new" type="text" maxlength="60" placeholder="New station" autocomplete="off" autocorrect="off" spellcheck="false"><button class="btn ghost" data-act="seedNewStation" data-v="${esc(name)}">Add</button></div>
    <p class="plan-note">Lit: they seed it. Tap to add them or take them off. A new station starts with them as its seed.</p><div class="acts col"><button class="btn ghost" data-act="closeSheet">Done</button></div>`);
  $("#st-new").addEventListener("keydown", e => { if (e.key === "Enter") ACT.seedNewStation(name); });
}
function stationEdit(body, words) {
  return api("/api/station-edit", body).then(r => { if (r.error) { toast(r.error); return r; } return loadStations().then(() => { if (words) toast(words); redrawDiscover(); return r; }); });
}
function redrawDiscover() { const v = A.views.get("#/"); if (v && v === current) drawDiscover(v.el); else if (v) { v.el.remove(); A.views.delete("#/"); } }
const newStationCard = () => `<div class="card q station new-station" data-act="stationNew"><div class="art"><div class="st-plus">+</div><div class="st-name">New station</div></div><div class="s">Seeded from artists you choose</div></div>`;

/* ───────────────────────── albums, artists, genres ───────────────────────── */
const SORTS = { added: ["Recently added", (a, b) => (b[11] || 0) - (a[11] || 0) || a[5] - b[5]], // by when each joined the shelves, albums and Archive shows alike artist: ["Artist", (a, b) => byName(a[2], b[2]) || (a[3] - b[3])], title: ["Title", (a, b) => byName(a[1], b[1])],
  year: ["Year", (a, b) => (b[3] - a[3]) || byName(a[2], b[2])] };
function byName(a, b) { a = norm(a).replace(/^the /, ""); b = norm(b).replace(/^the /, ""); return a < b ? -1 : a > b ? 1 : 0; }
VIEWS.albums = function (el) {
  const sort = store.get("sq-sort", "added"), genre = store.get("sq-genre", "");
  const shows = genre === "" || genre === "@archive" ? A.archive.map(archRow) : [];
  if (!A.heard && focusOn()) loadHeard().then(() => { if (current && current.el === el) VIEWS.albums(el); });
  const list = (genre === "@archive" ? [] : A.albums.filter(a => albumIn(a, genre))).concat(shows).filter(focusMatch).sort(SORTS[sort][1]);
  const tags = {}; Object.keys(A.marks.album).forEach(k => A.marks.album[k][2].forEach(t => { tags[t] = 1; }));
  const filters = [["@loved", icon("heart_on") + " Loved"], ["@rated", icon("star_on") + " Four stars and up"]].concat(A.archive.length ? [["@archive", "Live from the Archive"]] : []).concat(A.albums.some(a => (a[10] || []).length) ? [["@versions", "With other pressings"]] : []).concat(Object.keys(tags).sort().map(t => ["#" + t, "#" + esc(t)]));
  const label = genre === "@versions" ? "multi-pressing " : genre === "@loved" ? "loved " : genre === "@rated" ? "four-star " : genre === "@archive" ? "Archive " : genre ? esc(genre) + " " : "";
  const countText = `${list.length.toLocaleString()} ${label}albums${focusOn() ? " in the dig" : ""}`;
  el.innerHTML = `${pageBar("Albums", ["The library", countText],
      `<button class="pill focus-btn ${focusOn() ? "on" : ""}" data-act="focusOpen">${icon("tag")}<span class="pl">Dig${focusOn() ? ` &middot; ${focusOn()}` : ""}</span></button><div class="seg">${Object.keys(SORTS).map(k => `<button class="${k === sort ? "on" : ""}" data-act="sortAlbums" data-v="${k}">${SORTS[k][0]}</button>`).join("")}</div>`, false, "segs grow albums-acts")}
    <div class="toolbar"><div class="chips"><button class="${genre ? "" : "on"}" data-act="genreAlbums" data-v="">Every album</button>${filters.map(f => `<button class="${f[0] === genre ? "on" : ""}" data-act="genreAlbums" data-v="${esc(f[0])}">${f[1]}</button>`).join("")}${focusSaved().map((f, i) => `<button class="saved-focus" data-act="focusUse" data-v="${i}">${icon("tag")} ${esc(f.name)}</button>`).join("")}<a class="chip-link" href="#/removed">Recently removed</a><span class="chip-gap"></span>${A.genres.map(g => `<button class="${g[0] === genre ? "on" : ""}" data-act="genreAlbums" data-v="${esc(g[0])}">${esc(g[0])}</button>`).join("")}</div></div>
    <div class="grid">${list.map(a => albumCard(a)).join("")}</div>`;
};
/* ───────────────────────── Focus: the Albums page's filters, combined ─────────────────────────
   Any of the chosen within a facet, all the facets together: post-rock and slowcore, from the nineties, hi-res, not
   heard in a year. Kept on this device; a focus can be named and kept among the filter chips, and played as a mix. */
const FACETS = [
  ["genre", "Genre", () => genreFamilies().map(f => [f[0], f[0]])],
  ["decade", "Decade", () => Array.from(new Set(A.albums.filter(a => a[3] >= 1900).map(a => a[3] - a[3] % 10))).sort().map(d => [String(d), d + "s"])],
  ["sound", "Sound", () => [["hires", "Hi-res"], ["cd", "CD"], ["lossy", "Lossy"]]],
  ["source", "Plays from", () => [["local", "The shelves"], ["qobuz", "Qobuz"], ["archive", "The Archive"]]],
  ["marks", "Marks", () => [["loved", "Hearted"], ["rated", "Four stars and up"]]],
  ["heard", "Listening", () => [["never", "Never played"], ["year", "Not in a year"], ["lately", "In the last month"]]]];
const FOCUS_TEST = {
  genre: (a, v) => { const fam = v === "Your own" ? ((genreFamilies().find(f => f[0] === v) || [0, []])[1]).map(x => x[0]) : familyOf(v); return (a[8] || []).some(g => fam.indexOf(g) >= 0); },
  decade: (a, v) => a[3] >= 1900 && String(a[3] - a[3] % 10) === v,
  sound: (a, v) => { const q = a[6] || "", m = /^(\d+)\/([\d.]+)/.exec(q); return v === "hires" ? !!m && (+m[1] > 16 || +m[2] > 48) : v === "cd" ? q === "CD" : /^(mp3|aac|ogg|opus|wma)/i.test(q); },
  source: (a, v) => v === "archive" ? !!a.archive : !a.archive && a[9] === v,
  marks: (a, v) => { const m = markOf("album", albumKey(a)); return v === "loved" ? !!m[0] : m[1] >= 4; },
  heard: (a, v) => { const h = (A.heard || {})[albumKey(a)], now = Date.now() / 1000; return v === "never" ? !h : v === "year" ? !h || h[0] < now - 365 * 86400 : !!h && h[0] > now - 30 * 86400; }
};
A.focus = store.get("sq-focus", {});
const focusOn = () => Object.keys(A.focus).filter(f => (A.focus[f] || []).length).length;
const focusMatch = a => Object.keys(A.focus).every(f => !(A.focus[f] || []).length || A.focus[f].some(v => FOCUS_TEST[f](a, v)));
// kept for the whole house (the server's); this device's own, from before, sent up the first time
const focusSaved = () => A.focusesSaved || [];
function loadFocuses() {
  return api("/api/focuses").then(r => {
    A.focusesSaved = r.list || [];
    const mine = store.get("sq-focus-saved", []);
    if (mine.length) { const have = A.focusesSaved.map(f => norm(f.name)); keepFocuses(A.focusesSaved.concat(mine.filter(f => have.indexOf(norm(f.name)) < 0))); store.set("sq-focus-saved", []); }
  }).catch(() => { A.focusesSaved = store.get("sq-focus-saved", []); });
}
function keepFocuses(list) { A.focusesSaved = list; return api("/api/focuses", { list }).catch(() => toast("The server didn't keep that")); }
function loadHeard() { return api("/api/heard-albums").then(h => { A.heard = h; }).catch(() => { A.heard = {}; }); }
function focusList() { return A.albums.filter(focusMatch).concat(A.archive.map(archRow).filter(focusMatch)); }
function openFocus() {
  const n = focusList().length, saved = focusSaved();
  openSheet(`<div class="focus"><div class="kicker">Dig through the shelves</div><h3>${n.toLocaleString()} ${n === 1 ? "album" : "albums"}</h3>
    ${FACETS.map(f => `<div class="facet"><div class="kicker">${f[1]}</div><div class="gpicks">${f[2]().map(o => `<button class="gpick ${(A.focus[f[0]] || []).indexOf(o[0]) >= 0 ? "on" : ""}" data-act="focusPick" data-f="${f[0]}" data-v="${esc(o[0])}">${esc(o[1])}</button>`).join("")}</div></div>`).join("")}
    <div class="acts col"><button class="btn" data-act="focusShow">Show them</button><button class="btn ghost" data-act="focusPlay" ${n ? "" : "disabled"}>${icon("shuffle")} Spin a mix</button>${focusOn() ? `<button class="btn ghost" data-act="focusClear">Clear the dig</button>` : ""}</div>
    ${focusOn() ? `<div class="seed-add"><input id="focus-name" type="text" maxlength="40" placeholder="Name this dig to keep it" autocomplete="off" spellcheck="false"><button class="btn ghost" data-act="focusSave">Keep</button></div>` : ""}
    ${saved.length ? `<div class="kicker facet">Kept digs</div><div class="seeds">${saved.map((f, i) => `<span class="seed"><a href="#/albums" data-act="focusUse" data-v="${i}">${esc(f.name)}</a><button data-act="focusForget" data-v="${i}" aria-label="Forget ${esc(f.name)}">${icon("close")}</button></span>`).join("")}</div>` : ""}</div>`);
  const box = $("#focus-name"); if (box) box.addEventListener("keydown", e => { if (e.key === "Enter") ACT.focusSave(); });
}
function focusChanged() {
  store.set("sq-focus", A.focus);
  const go = () => { const v = A.views.get("#/albums"); if (v) { v.el.remove(); A.views.delete("#/albums"); } if (location.hash === "#/albums") route(); };
  (A.focus.heard && A.focus.heard.length && !A.heard ? loadHeard() : Promise.resolve()).then(go);
}
// an album in a filter: a genre, or @loved, @rated (four stars and up), #tag
function albumIn(a, f) {
  if (!f) return true;
  const m = markOf("album", albumKey(a));
  if (f === "@versions") return (a[10] || []).length > 0;
  if (f === "@loved") return !!m[0];
  if (f === "@rated") return m[1] >= 4;
  if (f.charAt(0) === "#") return m[2].indexOf(f.slice(1)) >= 0;
  return (a[8] || []).indexOf(f) >= 0;
}
VIEWS.artists = function (el) {
  const letters = [];
  const body = A.artists.map(a => {
    const L = (a[0].replace(/^the /i, "").charAt(0).toUpperCase().match(/[A-Z]/) || ["#"])[0];
    const anchor = letters.indexOf(L) < 0 ? (letters.push(L), ` id="L-${L}"`) : "";
    return `<div${anchor} data-n="${esc(norm(a[0]))}">${face(a[0], a[3], a[2] + (a[2] === 1 ? " album" : " albums"))}</div>`;
  }).join("");
  el.innerHTML = `${pageBar("Artists", ["The library", `${A.artists.length.toLocaleString()} album artists`])}
    <div class="letters">${letters.map(L => `<button data-act="letter" data-v="${L}">${L}</button>`).join("")}</div><div class="faces">${body}</div>`;

};
// the house's genres in families, as a record shop files its bins; a genre added by hand files under Your own
const GENRE_FAMILIES = [
  ["Rock", ["Indie Rock", "Post-Rock", "Math Rock", "Slowcore", "Shoegaze", "Art Rock & Prog", "Noise & Experimental", "Psychedelic", "Post-Punk & New Wave", "Punk", "Emo & Post-Hardcore", "Lo-Fi", "Grunge & Garage", "Metal", "Rock"]],
  ["Pop", ["Indie Pop", "Dream Pop", "Chamber Pop", "Pop"]],
  ["Folk & Country", ["Indie Folk", "Folk", "Singer-Songwriter", "Alt-Country & Americana"]],
  ["Soul, Funk & Hip-Hop", ["Soul & R&B", "Funk & Disco", "Hip-Hop"]],
  ["Jazz & Blues", ["Jazz", "Blues"]],
  ["Electronic & Ambient", ["Electronic", "Trip-Hop & Downtempo", "Ambient"]],
  ["Classical", ["Modern Classical", "Classical"]],
  ["Elsewhere", ["Reggae & Dub", "World", "Soundtrack"]]];
function genreFamilies() { // [[family, [[genre, count]…]]…], only the bins with albums in them
  const counts = {}; A.genres.forEach(g => { counts[g[0]] = g[1]; });
  const filed = {}; GENRE_FAMILIES.forEach(f => f[1].forEach(g => { filed[g] = 1; }));
  return GENRE_FAMILIES.map(f => [f[0], f[1].filter(g => counts[g]).map(g => [g, counts[g]])])
    .concat([["Your own", A.genres.filter(g => !filed[g[0]])]]).filter(f => f[1].length);
}
const familyOf = name => (GENRE_FAMILIES.find(f => f[0] === name) || [name, []])[1];
VIEWS.genres = function (el) {
  const tile = (href, name, list, sub) => {
    const four = shuffled(list.filter(a => a[4]), seeded(name)).slice(0, 4);
    return `<a class="gtile" href="${href}"><div class="gm">${four.map(a => `<img loading="lazy" src="${cover(a[4], 200)}" alt="">`).join("")}</div><div class="gt"><h3>${esc(name)}</h3><span>${sub}</span></div></a>`;
  };
  el.innerHTML = `${pageBar("Genres", ["The house's own bins", `${A.genres.length} genres`])}` + genreFamilies().map(f => {
    const all = A.albums.filter(a => (a[8] || []).some(g => f[1].some(x => x[0] === g)));
    return section(`${f[1].length} ${f[1].length === 1 ? "bin" : "bins"} &middot; ${all.length} albums`, `<a href="#/genre/${encodeURIComponent("@" + f[0])}">${esc(f[0])}</a>`,
      `<div class="gtiles">${f[1].map(g => tile(`#/genre/${encodeURIComponent(g[0])}`, g[0], A.albums.filter(a => (a[8] || []).indexOf(g[0]) >= 0), g[1] + " albums")).join("")}</div>`);
  }).join("");
};
VIEWS.genre = function (el, g) {
  const fam = g.charAt(0) === "@" ? (g === "@Your own" ? genreFamilies().filter(f => f[0] === "Your own").map(f => f[1].map(x => x[0]))[0] || [] : familyOf(g.slice(1))) : [g];
  const list = A.albums.filter(a => (a[8] || []).some(x => fam.indexOf(x) >= 0));
  if (g.charAt(0) === "@") g = g.slice(1);
  const counts = {}; list.forEach(a => { counts[a[2]] = (counts[a[2]] || 0) + 1; });
  const top = Object.keys(counts).filter(n => onShelves(n)).sort((a, b) => counts[b] - counts[a]).slice(0, 24);
  el.innerHTML = `${pageBar(esc(g), ["Genre", `${list.length} albums &middot; ${Object.keys(counts).length} artists`], `<button class="pill" data-act="shuffleGenre" data-v="${esc(g)}" aria-label="Spin one at random">${icon("dice")}<span class="pl">Spin one at random</span></button>`, true)}
    ${section("Who's in the bin", "Artists", shelf(top.map(n => face(n, "", counts[n] + (counts[n] === 1 ? " album" : " albums")))))}
    ${section("Newest first", "Albums", `<div class="grid">${list.map(a => albumCard(a)).join("")}</div>`)}`;
};

/* ───────────────────────── credits ─────────────────────────
   Who made each album, from MusicBrainz (/api/credits): the release's own credits and each recording's. Every name opens
   that person's page (#/person/MBID/name): what of theirs is on the shelves, and what else they are credited on. */
const creditCache = new Map();
function creditsFor(id) {
  id = String(id);
  if (!creditCache.has(id)) creditCache.set(id, api("/api/credits?id=" + encodeURIComponent(id)).catch(e => { creditCache.delete(id); throw e; }));
  return creditCache.get(id);
}
// the order a sleeve reads in: who produced and recorded it, who played on it, who made it look as it does
const ROLE_ORDER = ["producer", "co-producer", "executive producer", "additional producer", "recording", "engineer", "audio engineer", "assistant engineer", "additional engineer",
  "mixing", "mastering", "arranger", "conductor", "orchestra", "lead vocals", "vocals", "background vocals", "performer", "programming", "design and illustration", "art direction",
  "design", "graphic design", "illustration", "photography", "liner notes"];
function roleRank(r) { const i = ROLE_ORDER.indexOf(r); return i >= 0 ? i : r.indexOf("vocal") >= 0 ? 15 : ["design", "photo", "art", "liner"].some(w => r.indexOf(w) >= 0) ? 30 : 18; }
const personHref = p => `#/person/${p.mbid}/${encodeURIComponent(p.name)}`;
function personLink(p, extra) { return `<a class="pname ${onShelves(p.name) ? "own" : ""}" href="${personHref(p)}">${esc(p.name)}</a>${extra ? `<span class="ptracks">${extra}</span>` : ""}`; }
function trackList(ts) { return ts.length ? ts.length > 6 ? `${ts.length} tracks` : (ts.length === 1 ? "track " : "tracks ") + ts.join(", ") : ""; }
function creditsHtml(c) {
  if (!c || !c.people || !c.people.length) return "";
  const byRole = {};
  c.people.forEach(p => p.roles.forEach(r => { (byRole[r[0]] = byRole[r[0]] || []).push(personLink(p, trackList(r[1]))); }));
  const roles = Object.keys(byRole).sort((a, b) => roleRank(a) - roleRank(b) || (a < b ? -1 : 1));
  return section("Who made it", "Credits", `<dl class="credits">${roles.map(r => `<dt>${esc(r.charAt(0).toUpperCase() + r.slice(1))}</dt><dd>${byRole[r].join("<br>")}</dd>`).join("")}</dl>
    <div class="credit">${[c.label, (c.date || "").slice(0, 4)].filter(Boolean).map(esc).join(" &middot; ")}${c.label || c.date ? " &middot; " : ""}From MusicBrainz</div>`, "", "credits-sec");
}
VIEWS.person = function (el, arg) {
  const cut = arg.indexOf("/"), mbid = arg.slice(0, cut), name = arg.slice(cut + 1);
  el.innerHTML = `${pageBar(esc(name), ["Credits", "&nbsp;"], "", true)}<div class="hist"><div class="trk ph"></div><div class="trk ph"></div></div>`;
  const ask = local => api(`/api/person?mbid=${encodeURIComponent(mbid)}&name=${encodeURIComponent(name)}${local ? "&local=1" : ""}`);
  // the shelves' part at once from the house's own credits, then the rest from MusicBrainz
  ask(true).then(p => { draw(p); if (p.pending) ask(false).then(draw).catch(() => {}); }).catch(() => { $(".hist", el).innerHTML = `<p class="dim center">MusicBrainz isn't answering.</p>`; });
  function draw(p) {
    if (!el.isConnected) return;
    if (p.error) { $(".hist", el).innerHTML = `<p class="dim center">MusicBrainz doesn't know them.</p>`; return; }
    const meta = [p.type === "Group" ? "Band" : p.type, p.area, p.begin ? p.begin + (p.end ? "–" + p.end : "") : ""].filter(Boolean).map(esc).join(" &middot; ");
    const mine = p.shelves.map(s => [A.byId.get(s.album_id), s.roles]).filter(x => x[0]);
    const rest = p.work.filter(w => !w.owned);
    el.innerHTML = `${pageBar(esc(p.name), [meta || "Credits", `${mine.length} on your shelves &middot; ${p.work.length} credits`],
        p.artist ? `<a class="pill" href="${artistHref(p.artist)}">${icon("person")}<span class="pl">Their own records</span></a>` : "", true)}
      ${p.disambiguation ? `<p class="person-note">${esc(p.disambiguation)}</p>` : ""}
      ${mine.length ? section("In the library", "On your shelves", `<div class="grid">${mine.map(x => albumCard(x[0]).replace('<div class="s">', `<div class="role">${esc(x[1].join(", "))}</div><div class="s">`)).join("")}</div>`) : ""}
      ${rest.length ? section("Beyond the shelves", "Also worked on", `<div class="grid">${rest.map(workCard).join("")}</div>`) : ""}
      ${p.pending ? `<p class="dim center">Asking MusicBrainz what else they worked on&hellip;</p>` : !mine.length && !rest.length ? `<p class="dim center">No other credits on MusicBrainz.</p>` : ""}`;
  }
};
function workCard(w) {
  return `<div class="card q" data-act="findWork" data-v="${esc((w.artist ? w.artist + " " : "") + w.title)}"><div class="art"><div class="noart">${esc(w.title.slice(0, 1))}</div>
    ${w.cover ? `<img loading="lazy" decoding="async" src="${esc(pic(w.cover, 320))}" alt="" onerror="this.remove()">` : ""}</div>
    <div class="role">${esc(w.roles.join(", "))}</div><div class="t">${esc(w.title)}</div><div class="s">${esc(w.artist || "")}${w.date ? (w.artist ? " &middot; " : "") + w.date.slice(0, 4) : ""}</div></div>`;
}
// the credits of the song playing, for Now Playing's Credits tab: its own, then the record's
function npCredits(t) {
  const a = A.albums.find(x => norm(x[1]) === norm(t.album) && norm(x[2]) === norm(t.artist)) || A.albums.find(x => norm(x[1]) === norm(t.album));
  if (!a) return Promise.resolve(`<p class="dim">Credits come with the records on your shelves.</p>`);
  return creditsFor(a[0]).then(c => {
    if (!c || !c.people.length) return `<p class="dim">MusicBrainz has no credits for this record.</p>`;
    const tn = plain(t.title), tr = c.tracks.find(x => plain(x.title) === tn);
    const own = tr ? tr.people : [], whole = [];
    c.people.forEach(p => p.roles.forEach(r => { if (!r[1].length) whole.push([p.name, p.mbid, r[0]]); }));
    const rows = list => list.map(x => `<div class="npc"><span>${esc(x[2])}</span>${personLink({ name: x[0], mbid: x[1] })}</div>`).join("");
    return (own.length ? `<div class="npc-h">This track</div>${rows(own)}` : "") + (whole.length ? `<div class="npc-h">The record</div>${rows(whole)}` : "") || `<p class="dim">No credits for this track.</p>`;
  }).catch(() => `<p class="dim">MusicBrainz isn't answering.</p>`);
}

/* ───────────────────────── playlists: Lyrion's own ───────────────────────── */
function playlistsList() { return api("/api/playlists").then(r => { A.playlists = r.playlists; return r.playlists; }); }
function forgetPlaylists() { Array.from(A.views.keys()).filter(h => h.indexOf("#/playlist") === 0).forEach(h => { const v = A.views.get(h); if (v !== current) { v.el.remove(); A.views.delete(h); } }); }
VIEWS.playlists = function (el) {
  el.innerHTML = `${pageBar("Playlists", ["Lyrion's playlists", "&nbsp;"], `<button class="pill" data-act="plNew" aria-label="New playlist">${icon("list")}<span class="pl">New playlist</span></button>`)}<div class="gtiles"></div>`;
  playlistsList().then(list => {
    $(".mast-line span:last-child", el).innerHTML = `${list.length} ${list.length === 1 ? "playlist" : "playlists"}`;
    $(".gtiles", el).innerHTML = list.length ? list.map(p => `<a class="gtile" href="#/playlist/${p.id}"><div class="gm">${p.arts.map(u => `<img loading="lazy" src="${esc(u)}" alt="">`).join("")}</div>
      <div class="gt"><h3>${esc(p.name.replace(/^Qobuz: /, ""))}</h3><span>${p.count} tracks${p.name.indexOf("Qobuz: ") === 0 ? " &middot; from Qobuz" : ""}</span></div></a>`).join("")
      : `<p class="dim">No playlists yet. Make one with New playlist, save the queue as one from Now Playing, or add an album to one from its page.</p>`;
  }).catch(() => {});
  const kept = focusSaved();
  if (kept.length) (A.heard ? Promise.resolve() : loadHeard()).then(() => {
    if (!el.isConnected) return;
    const was = A.focus;
    el.insertAdjacentHTML("beforeend", section("Albums that fit, kept up to date", "Kept digs", `<div class="gtiles">${kept.map((f, i) => {
      A.focus = f.f; const list = focusList(); A.focus = was;
      const four = shuffled(list.filter(a => a[4]), seeded(f.name)).slice(0, 4);
      return `<div class="gtile focus-tile"><a href="#/albums" data-act="focusUse" data-v="${i}"><div class="gm">${four.map(a => `<img loading="lazy" src="${cover(a[4], 200)}" alt="">`).join("")}</div>
        <div class="gt"><h3>${esc(f.name)}</h3><span>${list.length} albums</span></div></a><button class="chip" data-act="focusMix" data-v="${i}" aria-label="Spin a mix">${icon("play")}</button></div>`;
    }).join("")}</div>`));
  });
};
VIEWS.playlist = function (el, id) {
  const known = (A.playlists || []).find(p => String(p.id) === String(id)), name = known ? known.name : "Playlist";
  el.innerHTML = `${pageBar(esc(name), ["Playlist", "&nbsp;"], `<button class="pill" data-act="playPlaylist" data-v="${id}:0">${icon("play")}<span class="pl">Spin it</span></button>
    <button class="pill" data-act="playlistMenu" data-v="${id}" aria-label="More">${icon("more")}</button>`, true)}<div class="pltracks" data-drag="playlist:${id}"><div class="trk ph"></div><div class="trk ph"></div></div>`;
  api("/api/playlist?id=" + encodeURIComponent(id)).then(r => {
    if (!el.isConnected) return;
    const total = r.tracks.reduce((s, t) => s + t.duration, 0);
    $(".mast-line span:last-child", el).innerHTML = `${r.tracks.length} tracks &middot; ${total >= 3600 ? Math.floor(total / 3600) + " hr " : ""}${Math.round(total % 3600 / 60)} min`;
    $(".pltracks", el).innerHTML = r.tracks.length ? r.tracks.map((t, i) => `<div class="nx plrow" data-i="${i}"><span class="grip">${icon("grip")}</span>
      <button class="nx-go" data-act="playPlaylist" data-v="${id}:${i}">${t.art ? `<img loading="lazy" src="${cover(t.art, 150)}" alt="">` : t.remote_art ? `<img loading="lazy" src="${esc(t.remote_art.charAt(0) === "/" ? t.remote_art : pic(t.remote_art, 160))}" alt="">` : `<span class="noimg"></span>`}
      <span><b>${esc(t.title)}</b><em>${esc(t.artist)}${t.album ? " &middot; " + esc(t.album) : ""}</em></span></button><span class="pd">${mmss(t.duration)}</span>
      <button class="nx-x" data-act="plRemove" data-v="${id}:${i}" aria-label="Remove">${icon("close")}</button></div>`).join("") : `<p class="dim">This playlist is empty.</p>`;
  }).catch(() => { $(".pltracks", el).innerHTML = `<p class="dim">Lyrion didn't answer.</p>`; });
};
function openPlaylistPicker(what) {
  playlistsList().then(list => {
    const own = list.filter(p => p.name.indexOf("Qobuz: ") !== 0);
    openSheet(`<div data-what="${esc(what)}"><div class="kicker">Add to</div><h3>A playlist</h3><div class="rooms">
      <button class="room-go pl-new" data-act="plPick" data-v="">${icon("list")}<span><b>New playlist&hellip;</b><em>name it next</em></span></button>
      ${own.map(p => `<button class="room-go" data-act="plPick" data-v="${p.id}">${icon("list")}<span><b>${esc(p.name)}</b><em>${p.count} tracks</em></span></button>`).join("")}</div></div>`);
  });
}

/* ───────────────────────── recently removed: albums taken off the shelves, and put back ───────────────────────── */
VIEWS.removed = function (el) {
  el.innerHTML = `${pageBar("Recently removed", ["Off the shelves", "files kept in music-removed"], "", true)}<div class="hist"><div class="trk ph"></div></div>`;
  api("/api/removals").then(r => {
    if (!el.isConnected) return;
    $(".hist", el).innerHTML = r.removals.length ? r.removals.map(x => {
      const what = [x.qobuz ? "Qobuz favourite" : "", x.files ? `${x.files} ${x.files === 1 ? "file" : "files"} in music-removed` : ""].filter(Boolean).join(" &middot; ");
      return `<div class="hrow rm"><span class="ht">${new Date(x.at * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>
        ${x.art ? `<img loading="lazy" src="${cover(x.art, 150)}" alt="">` : `<span class="noimg"></span>`}<span class="hw"><b>${esc(x.album)}</b><em>${esc(x.artist)} &middot; ${what || "nothing held"}</em></span>
        ${x.restored ? `<span class="ho">back on the shelves</span>` : `<button class="pill" data-act="restore" data-v="${x.id}">Put back</button>`}</div>`;
    }).join("") : `<p class="dim center">Nothing has been removed.</p>`;
  }).catch(() => { $(".hist", el).innerHTML = `<p class="dim center">The server didn't answer.</p>`; });
};

/* ───────────────────────── settings ─────────────────────────
   The house's (saved on the server, for every screen): connections, features, Discover's sections. This device's own
   (saved here only): the room it starts in, its text size, its lighter drawing, its motion. */
// the connections a house sets; the rest (music folders, removed music, house genres, the Qobuz player) are found
// the connections a house sets; the rest (music folders, removed music, the Qobuz player) are found
const CONN = [["lms_url", "Lyrion", "its address, as the server reaches it", "lms_ok"],
  ["listening_db", "Listening log", "a recorder of the house's own, if there is one; otherwise Soundsquatch keeps the log itself", "listening_ok"]];
const FEATS = [["stations", "Stations", "radio seeded from artists you choose"], ["archive", "Internet Archive", "shows from the ArchiveLMA plugin"],
  ["history", "History", "the History tab, from the listening log"], ["credits", "Credits", "who made each album, from MusicBrainz"], ["lyrics", "Lyrics", "synced lyrics in Now Playing (LRCLIB)"],
  ["write_files", "Change music files", "genres, titles and covers written into the files; Remove from the library moves them to music-removed. Off, genres are Soundsquatch's own and the files are never touched"]];
const PLUGINS = [["qobuz", "Qobuz", "Qobuz's releases and similar artists on artist pages, artists' short biographies, and search beyond your shelves (with a Qobuz subscription)"],
  ["mai", "Music & Artist Information", "album reviews, artists' longer stories and more of their photographs"],
  ["archive", "ArchiveLMA", "live shows from the Internet Archive: your favourites, each artist's shows, and On this night"],
  ["radio", "Don't Stop the Music, with LastMix", "radio that carries on when a queue runs out, and the stations"]];
// a Lyrion that asks for a password: its username and password, under its address (the password is never sent back)
const loginFields = c => `<div class="conn-login"><input data-conn="lms_user" value="${esc(c.connections.lms_user || "")}" placeholder="Lyrion username" autocomplete="off" autocapitalize="off" spellcheck="false">
  <input data-conn="lms_password" type="password" value="" placeholder="${c.lms_password_set ? "password (unchanged)" : "password"}" autocomplete="off"></div>`;
const PLUGIN_FOR = { archive: "ArchiveLMA", stations: "Don't Stop the Music and LastMix" };
const DISC = [["cover", "Cover stories"], ["stations", "Stations"], ["because", "Kindred spirits"], ["rotation", "On rotation"], ["back", "Back to it"], ["new", "New from your artists"],
  ["spotlight", "Artist of the day"], ["fresh", "Fresh on the shelves"], ["rediscover", "Rediscover"], ["loved", "Loved"], ["archive", "Live on your shelves"],
  ["connections", "Connections"], ["beyond", "Beyond the shelves"], ["round", "Round numbers"], ["decade", "A decade"], ["genre", "Genre of the day"]];
const toggle = (act, v, isOn, label, note) => `<button class="set-row toggle ${isOn ? "on" : ""}" data-act="${act}" data-v="${v}"><span><b>${label}</b>${note ? `<em>${note}</em>` : ""}</span><i class="sw"></i></button>`;
VIEWS.settings = function (el) {
  el.innerHTML = `${pageBar("Settings", ["For the house", "and this device"])}<div class="settings"><p class="dim">Asking the server&hellip;</p></div>`;
  // the rooms as Lyrion has them now: a player added since this screen opened is listed too
  Promise.all([api("/api/settings"), lms("", ["players", 0, 50]).then(r => { A.rooms = (r.players_loop || []).filter(p => p.connected); }).catch(() => {})]).then(r => { A.cfg = r[0]; drawSettings(el); }).catch(() => { $(".settings", el).innerHTML = `<p class="dim">The server isn't answering.</p>`; });
};
function drawSettings(el) {
  const c = A.cfg, ok = t => /^(Lyrion |connected|found|a player|made when)/.test(t || "");
  const rooms = A.rooms.filter(p => p.modelname !== "Group"), start = device.get("room", "");
  $(".settings", el).innerHTML = `
    ${c.update ? section("A new version", "Soundsquatch " + esc(c.update.version), `<div class="set-row update"><span><b>It's out</b><em>to update, on the machine it runs on, in its folder: <code>docker compose pull &amp;&amp; docker compose up -d</code>. Everything kept in ./data stays.</em></span><a class="pill" href="${esc(c.update.url)}" target="_blank" rel="noopener">What's new</a></div>`) : ""}
    ${section("For every screen in the house", "Features", FEATS.map(f => NEEDS[f[0]] && !has(NEEDS[f[0]])
      ? `<div class="set-row toggle missing"><span><b>${f[1]}</b><em>needs the ${PLUGIN_FOR[f[0]]} plugin in Lyrion</em></span><i class="sw"></i></div>`
      : toggle("setFeat", f[0], c.features[f[0]], f[1], f[2])).join(""))}
    ${section("For every screen in the house", "Rooms", rooms.map(p => { const r = c.rooms[p.playerid] || {};
        return `<div class="set-row"><span><b>${esc(roomName(p.playerid))}</b><em>${r.name ? esc(p.name) + " in Lyrion" : "as Lyrion names it"}${r.fixed ? " &middot; volume set on the device" : ""}</em></span><button class="pill" data-act="roomEdit" data-v="${p.playerid}">Change</button></div>`; }).join("") || `<p class="dim">No players are connected to Lyrion.</p>`)}
    ${section("For every screen in the house", "Discover", `<div class="set-grid">${DISC.map(d => toggle("setDisc", d[0], c.discover[d[0]], d[1])).join("")}</div>`)}
    <div id="set-bans"></div>
    ${section("For every screen in the house", "Backups", `<p class="plan-note">Each night Soundsquatch keeps a copy of what it can't fetch again (hearts, stars, tags, stations, the never-play list, removals and settings); the last two weeks of them stay on the server.</p>
      <div class="set-row"><span><b>Last copy</b><em id="bk-last">&hellip;</em></span><a class="pill" href="/api/backup" download>${icon("share")}<span class="pl">Download one now</span></a></div>
      <div class="set-row"><span><b>Restore</b><em>from a downloaded copy: what it holds replaces what is here (removals are added to)</em></span><label class="pill bk-restore">Choose a file<input type="file" accept=".json,application/json" hidden></label></div>`)}
    ${section("This device only", "This device", `
      <div class="set-row"><span><b>Starts in</b><em>the room this screen controls when it opens</em></span><select id="set-room"><option value="">the last one used</option>${rooms.map(p => `<option value="${p.playerid}" ${p.playerid === start ? "selected" : ""}>${esc(roomName(p.playerid))}</option>`).join("")}</select></div>
      <div class="set-row"><span><b>Text size</b><em>everything larger or smaller on this screen</em></span><div class="seg">${[[0.9, "Smaller"], [1, "Normal"], [1.1, "Larger"], [1.2, "Largest"]].map(z => `<button class="${z[0] === device.get("zoom", 1) ? "on" : ""}" data-act="setZoom" data-v="${z[0]}">${z[1]}</button>`).join("")}</div></div>
      ${toggle("setDev", "lite", device.get("lite", false), "Lighter drawing", "no frosted glass or big blurs: smoother on a modest machine")}
      ${toggle("setDev", "still", device.get("still", false), "Reduce motion", "no slow zooms or shimmer, and the cover stories don't turn by themselves")}
      <div class="set-row"><span><b>Look</b><em>Classic, or set like a printed music magazine</em></span><div class="seg">${[["classic", "Classic"], ["magazine", "Magazine"]].map(l => `<button class="${(magOn() ? "magazine" : "classic") === l[0] ? "on" : ""}" data-act="setLook" data-v="${l[0]}">${l[1]}</button>`).join("")}</div></div>
      ${toggle("setOsk", "", oskOn(), "On-screen keyboard", "for a screen without a keyboard of its own, such as one on a wall")}`)}
    ${section("For every screen in the house", "Connections", `${CONN.map(k => { const good = !!c.checks[k[3]];
        return `<div class="set-field conn ${good ? "" : "open"}" data-k="${k[0]}"><span><b>${k[1]}</b><em>${k[2]}</em></span>
        <span class="conn-now"><span class="check ${good ? "good" : "bad"}">${esc(c.checks[k[0]] || "")}</span><button class="pill" data-act="connEdit">Change</button></span>
        <input data-conn="${k[0]}" value="${esc(c.connections[k[0]] || "")}" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false">
        ${k[0] === "lms_url" && (c.checks.lms_auth || c.connections.lms_user) ? loginFields(c) : ""}
        </div>`; }).join("")}
      <div class="set-field found"><span><b>Found by itself</b><em>nothing to set</em></span><span class="set-value">Music in ${esc(c.checks.music_dirs || "")} (Lyrion's own folders); removed albums go to ${esc(c.checks.removed_dir || "")}.${c.have && c.have.language && c.have.language !== "EN" ? ` Lyrion speaks ${esc(c.have.language)}: keeping and removing Qobuz albums need it set to English.` : ""}</span></div>
      <div class="acts conn-save"><button class="btn" data-act="saveConn">Save and check</button></div>`)}
    ${section("What Lyrion adds", "Lyrion's plugins", `<p class="plan-note">Soundsquatch needs only Lyrion. Each of these plugins adds to it, and is found by itself; what one would add is left out while it isn't there. Install them from Lyrion's own Settings, under Manage Plugins.</p>
      ${PLUGINS.map(x => `<div class="set-row plugin ${has(x[0]) ? "" : "absent"}"><span><b>${esc(x[1])}</b><em>${x[2]}</em></span><span class="check ${has(x[0]) ? "good" : "bad"}">${has(x[0]) ? "installed" : "not installed"}</span></div>`).join("")}`)}
    ${section("For every screen in the house", "PIN", `<div class="set-row"><span><b>${c.pin ? "A PIN is set" : "No PIN"}</b><em>${c.pin ? "settings and changes to music files ask for it, once on each device" : "anyone on the network can change settings and music files"}</em></span><button class="pill" data-act="pinEdit">${c.pin ? "Change" : "Set one"}</button></div>`)}
    ${section("When something's wrong", "Diagnostics", `<div class="set-row"><span><b>A report to paste where you tell us</b><em>versions, what was found, the last errors; no names, addresses or listening</em></span><button class="pill" data-act="diagnostics">Show it</button></div>`)}
    <p class="dim center set-foot">Soundsquatch ${esc(c.version || "")} &middot; settings for the house are saved on the server; this device's are saved in this browser.</p>`;
  $(".settings", el).classList.toggle("editing", !!el.querySelector(".conn.open"));
  api("/api/backups").then(b => { const e = $("#bk-last", el); if (e) e.textContent = b.last ? new Date(b.last * 1000).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) + ` · ${b.files.length} kept` : "none yet (the first is made tonight)"; }).catch(() => {});
  const file = $(".bk-restore input", el);
  if (file) file.addEventListener("change", () => {
    const f = file.files[0]; if (!f) return;
    if (!confirm(`Restore from ${f.name}? What it holds replaces what is here now.`)) { file.value = ""; return; }
    const rd = new FileReader();
    rd.onload = () => { let data; try { data = JSON.parse(rd.result); } catch (e) { return toast("That isn't a Soundsquatch backup"); }
      api("/api/import", data).then(r => { if (r.error) return toast(r.error); toast(`Restored: ${r.marks} marks, ${r.stations} stations, ${r.bans} never-plays`); loadMarks(); loadStations().catch(() => {}); VIEWS.settings(current.el); }).catch(() => toast("The server didn't take it")); };
    rd.readAsText(f);
  });
  api("/api/bans").then(r => {
    const box = $("#set-bans", el); if (!box) return;
    const row = b => `<span class="ban"><span>${icon("ban")} ${esc(b.label)}</span><button data-act="banLift" data-v="${esc(b.key)}" data-kind="${b.kind}" aria-label="Lift">${icon("close")}</button></span>`;
    const arts = r.bans.filter(b => b.kind === "artist"), tracks = r.bans.filter(b => b.kind === "track");
    box.outerHTML = section("For every screen in the house", `Never play <span class="count-inline">${r.bans.length}</span>`,
      `<p class="plan-note">Kept out of whatever the radio and the stations bring; music you put on yourself plays whole. Ban from Now Playing or a track's menu; lift here.</p>
      ${arts.length ? `<div class="kicker ban-h">Artists</div><div class="bans">${arts.map(row).join("")}</div>` : ""}${tracks.length ? `<div class="kicker ban-h">Tracks</div><div class="bans">${tracks.map(row).join("")}</div>` : ""}`);
  }).catch(() => {});
  $("#set-room", el).addEventListener("change", e => { device.set("room", e.target.value); toast(e.target.value ? `This screen starts in ${roomName(e.target.value)}` : "This screen starts in the last room used"); });
}
function saveSettings(change, words) {
  return api("/api/settings", change).then(r => { A.cfg = r; if (current && current.kind === "settings") drawSettings(current.el); toast(words || "Saved");
    Array.from(A.views.keys()).forEach(h => { const v = A.views.get(h); if (v !== current) { v.el.remove(); A.views.delete(h); } }); applyHouse(); })
    .catch(() => toast("The server didn't save it"));
}
// what the house's settings change outside the pages that ask: the History tab, the Archive's shelf
function applyHouse() {
  const hist = $('#rail a[data-tab="history"]'); if (hist) hist.hidden = !on("features", "history");
  if (!on("features", "archive")) A.archive = [];
}
// this device's settings, put to work: its text size, its drawing, its motion
function applyDevice() {
  const z = device.get("zoom", 1), root = document.documentElement;
  root.style.zoom = z === 1 ? "" : z;
  root.classList.toggle("lite", device.get("lite", false) || /[?&]lite\b/.test(location.search));
  root.classList.toggle("still", device.get("still", false));
  root.classList.toggle("mag", magOn());
}

/* ───────────────────────── history ───────────────────────── */
VIEWS.history = function (el) {
  const days = store.get("sq-hist-days", 7);
  el.innerHTML = `${pageBar("History", ["The listening log", days === 1 ? "today" : `the last ${days} days`],
    `<div class="seg">${[[1, "Today"], [7, "Week"], [30, "Month"]].map(d => `<button class="${d[0] === days ? "on" : ""}" data-act="histDays" data-v="${d[0]}">${d[1]}</button>`).join("")}</div>`, false, "segs")}
    <div class="hist"><div class="trk ph"></div><div class="trk ph"></div><div class="trk ph"></div></div>`;
  api("/api/history?days=" + days).then(r => {
    if (!el.isConnected) return;
    const since = days === 1 ? new Date().setHours(0, 0, 0, 0) / 1000 : 0, plays = r.plays.filter(x => x.t >= since);
    const through = plays.filter(x => x.outcome === "finished").length;
    $(".mast-acts", el).insertAdjacentHTML("afterbegin", plays.length ? `<span class="mast-stat"><b>${plays.length}</b> plays &middot; ${Math.round(through / plays.length * 100)}% heard through</span>` : "");
    if (plays.length) $(".hist", el).insertAdjacentHTML("beforebegin", histStats(plays));
    let day = "";
    $(".hist", el).innerHTML = plays.length ? plays.map(x => {
      const d = new Date(x.t * 1000), label = dayLabel(d), head = label !== day ? `<div class="hist-day">${esc(label)}</div>` : ""; day = label;
      const early = x.outcome === "skipped" && x.played < 45, href = x.album_id ? albumHref(x.album_id) : artistHref(splitArtist(x.artist));
      return `${head}<a class="hrow ${early ? "skip" : ""}" href="${href}"><span class="ht">${d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}</span>
        ${x.art ? `<img loading="lazy" src="${cover(x.art, 150)}" alt="">` : `<span class="noimg"></span>`}<span class="hw"><b>${esc(x.title)}</b><em>${esc(x.artist)}${x.album ? " &middot; " + esc(x.album) : ""}</em></span>
        ${x.url ? `<button class="pill keep-log" data-act="keepLog" data-v="${esc(x.url)}" data-k="${esc(norm(x.artist + "|" + x.album))}" aria-label="Add to the library">${icon("heart")}<span class="pl">Add to library</span></button>` : ""}
        <span class="hr">${esc(roomByName(x.room))}${x.who && x.who !== "household" ? " &middot; " + esc(x.who) : ""}</span><span class="ho">${early ? "skipped at " + mmss(x.played) : x.library || x.album_id ? "" : "beyond the shelves"}</span></a>`;
    }).join("") : `<p class="dim center">Nothing heard ${days === 1 ? "today" : "in that time"}.</p>`;
  }).catch(() => { $(".hist", el).innerHTML = `<p class="dim center">The listening log isn't answering.</p>`; });
};
// what the span's listening comes to: time, plays, artists, tracks, albums, how much came from beyond the shelves, each
// room's hours (a bar each) and the artists most heard
function histStats(plays) {
  const sum = (list, f) => list.reduce((n, x) => n + f(x), 0), uniq = f => { const o = {}; plays.forEach(x => { o[f(x)] = 1; }); return Object.keys(o).length; };
  const secs = sum(plays, x => x.played || 0), beyond = plays.filter(x => !x.library).length;
  const hm = t => t >= 3600 ? Math.floor(t / 3600) + " h " + Math.round(t % 3600 / 60) + " min" : Math.round(t / 60) + " min";
  const rooms = {}; plays.forEach(x => { const r = roomByName(x.room); rooms[r] = (rooms[r] || 0) + (x.played || 0); });
  const roomList = Object.keys(rooms).sort((a, b) => rooms[b] - rooms[a]), top = rooms[roomList[0]] || 1;
  const arts = {}; plays.forEach(x => { if (x.artist) arts[x.artist] = (arts[x.artist] || 0) + (x.played || 0); });
  const best = Object.keys(arts).sort((a, b) => arts[b] - arts[a]).slice(0, 8);
  const tile = (n, w) => `<div class="hs-tile"><b>${n}</b><span>${w}</span></div>`;
  return `<section class="sec hstats"><div class="hs-tiles">${tile(hm(secs), "listened")}${tile(plays.length.toLocaleString(), "plays")}${tile(uniq(x => norm(x.artist)).toLocaleString(), "artists")}
    ${tile(uniq(x => norm(x.artist + "|" + x.title)).toLocaleString(), "tracks")}${tile(uniq(x => norm(x.artist + "|" + x.album)).toLocaleString(), "albums")}${tile(Math.round(beyond / plays.length * 100) + "%", "beyond the shelves")}</div>
    <div class="hs-cols"><div><div class="kicker">By room</div>${roomList.map(r => `<div class="hs-bar"><span class="hs-name">${esc(r)}</span><span class="hs-track"><i style="width:${Math.max(2, rooms[r] / top * 100)}%"></i></span><span class="hs-val">${hm(rooms[r])}</span></div>`).join("")}</div>
    <div><div class="kicker">Most heard</div>${best.map(a => `<a class="hs-bar" href="${artistHref(splitArtist(a))}"><span class="hs-name">${esc(a)}</span><span class="hs-track"><i style="width:${Math.max(2, arts[a] / arts[best[0]] * 100)}%"></i></span><span class="hs-val">${hm(arts[a])}</span></a>`).join("")}</div></div></section>`;
}
// the log keeps Lyrion's name for a room ("Living Room Wiim"); the app's own where it has one
function roomByName(n) { const p = A.rooms.find(r => r.name === n); return p ? roomName(p.playerid) : n; }
function dayLabel(d) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const t = new Date(d); t.setHours(0, 0, 0, 0);
  const n = Math.round((today - t) / 864e5);
  return n === 0 ? "Today" : n === 1 ? "Yesterday" : d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

/* ───────────────────────── search ───────────────────────── */
let searchT, qobuzT, lastQ = "";
VIEWS.search = function (el) {
  el.innerHTML = `${pageBar("Search", [], `<input id="q" type="search" placeholder="An artist, an album, a song, a show" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" value="${esc(lastQ)}"><button class="pill" data-act="searchClear" aria-label="Clear, then close">${icon("close")}</button>`, false, "grow search-bar")}<div id="results"></div>`;
  const q = $("#q", el);
  q.addEventListener("input", () => { clearTimeout(searchT); searchT = setTimeout(() => runSearch(el, q.value), 180); });
  q.addEventListener("keydown", e => { if (e.key === "Escape") ACT.searchClose(); });
  $("#results", el).addEventListener("click", e => { if (e.target.closest("a, [data-act]") && norm(lastQ).length >= 2) remember(lastQ); });
  setTimeout(() => q.focus(), 50);
  runSearch(el, lastQ);
};
// the last few searches, offered when the field is empty
function remember(q) { const r = store.get("sq-recent", []).filter(x => norm(x) !== norm(q)); r.unshift(q.trim()); store.set("sq-recent", r.slice(0, 6)); }
// the nearest names on the shelves to a search that found none there (a letter or two off): "Did you mean", or nothing
function nearNames(n) {
  if (n.length < 4) return ""; // two or three letters are near too much to say
  const dist = (a, b) => { // edits between two strings (two letters swapped is one), given up past three
    if (Math.abs(a.length - b.length) > 3) return 9;
    const d = []; for (let i = 0; i <= a.length; i++) { d.push([i]); for (let j = 1; j <= b.length; j++) d[i].push(i ? 0 : j); }
    for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) {
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d[i][j] = Math.min(d[i][j], d[i - 2][j - 2] + 1);
    }
    return d[a.length][b.length];
  };
  const room = n.length < 8 ? 1 : 2, near = [];
  const consider = (name, href, weight) => { const v = norm(name).replace(/^the /, ""), d = Math.min(dist(n, v), dist(n.replace(/^the /, ""), v)); if (d <= room) near.push([d, name, href, weight]); };
  A.artists.forEach(a => consider(a[0], artistHref(a[0]), a[2]));
  A.albums.forEach(a => consider(a[1], albumHref(a[0]), 0));
  near.sort((x, y) => x[0] - y[0] || y[3] - x[3]); // the nearest, then the artist with more on the shelves
  const picks = near.filter((x, i) => near.findIndex(y => norm(y[1]) === norm(x[1])) === i).slice(0, 6);
  return picks.length ? `<p class="none-line">Did you mean</p><div class="gpicks none-picks">${picks.map(x => `<a class="gpick" href="${x[2]}">${esc(x[1])}</a>`).join("")}</div>` : "";
}
// a search that found nothing anywhere: the nearest names, and what search looks at
function noResults(q, n, askedQobuz) {
  const quips = ["Just crickets here.", "Dead air.", "Not even a B-side.", "The crate's empty.", "Four minutes, thirty-three seconds of nothing.",
    "The needle's in the run-out groove.", "Nobody here but the tape hiss.", "This bin's been picked clean."];
  const quip = quips[Array.from(n).reduce((s, c) => s + c.charCodeAt(0), 0) % quips.length]; // the same line for the same search
  return `<div class="no-results"><div class="kicker">Nothing for &ldquo;${esc(q)}&rdquo;</div><h2>${quip}</h2>${nearNames(n)}
    <p class="dim">Search looks at artists, albums, songs, genres and playlists on your shelves${askedQobuz ? ", and at Qobuz" : has("qobuz") ? "; Qobuz is asked from three letters on" : ""}. Check the spelling, or try fewer words.</p></div>`;
}
function runSearch(el, q) {
  lastQ = q; const n = norm(q), box = $("#results", el);
  clearTimeout(qobuzT);
  if (n.length < 2) { // nothing typed yet: what is playing, and the last searches, a tap away
    const t = curTrack(), recent = store.get("sq-recent", []);
    const now = t && t.artist ? [t.artist, t.album].filter(Boolean) : [];
    box.innerHTML = (now.length ? section("Playing now", "", `<div class="gpicks">${now.map(x => `<button class="gpick" data-act="searchFor" data-v="${esc(x)}">${esc(x)}</button>`).join("")}</div>`) : "") +
      (recent.length ? section("Lately", "", `<div class="gpicks">${recent.map(x => `<button class="gpick" data-act="searchFor" data-v="${esc(x)}">${esc(x)}</button>`).join("")}</div>`) : "");
    return;
  }
  // the name itself first, then a word that starts so ("Low" before "Slow Pulp"), then anywhere in it
  const words = new RegExp("(^|[^a-z0-9])" + n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const fit = (...names) => Math.min.apply(null, names.map(x => { const v = norm(x); return v === n ? 0 : v.indexOf(n) === 0 ? 1 : words.test(v) ? 2 : v.indexOf(n) >= 0 ? 3 : 9; }));
  const artists = A.artists.map(a => [fit(a[0]), a]).filter(x => x[0] < 9).sort((x, y) => x[0] - y[0] || y[1][2] - x[1][2]).map(x => x[1]).slice(0, 24);
  const albums = A.albums.map(a => [Math.min(fit(a[1]), fit(a[2]) + 0.5), a]).filter(x => x[0] < 9).sort((x, y) => x[0] - y[0] || x[1][5] - y[1][5]).map(x => x[1]).slice(0, 40);
  const shows = A.archive.filter(x => norm([x.artist, x.venue, x.title, x.date].join(" ")).indexOf(n) >= 0).slice(0, 24);
  const genres = A.genres.filter(g => norm(g[0]).indexOf(n) >= 0);
  const lists = (A.playlists || []).filter(p => norm(p.name).indexOf(n) >= 0);
  const parts = {
    artists: artists.length ? section("On your shelves", "Artists", shelf(artists.map(a => face(a[0], a[3], a[2] + (a[2] === 1 ? " album" : " albums"))))) : "",
    albums: albums.length ? section("On your shelves", "Albums", `<div class="grid">${albums.map(a => albumCard(a)).join("")}</div>`) : "",
    songs: `<div id="s-tracks"></div>`,
    shows: shows.length ? section("From the Internet Archive", "Live shows", shelf(shows.map(x => archCard(x)))) : "",
    genres: genres.length ? section("The bins", "Genres", `<div class="gpicks">${genres.map(g => `<a class="gpick" href="#/genre/${encodeURIComponent(g[0])}">${esc(g[0])} <span class="dim">${g[1]}</span></a>`).join("")}</div>`) : "",
    lists: lists.length ? section("Yours", "Playlists", `<div class="gpicks">${lists.map(p => `<a class="gpick" href="#/playlist/${p.id}">${esc(p.name)}</a>`).join("")}</div>`) : ""
  };
  // what the page it was opened from is about comes first
  const from = A.searchFrom || "", order = /^(albums|album|genre|genres)$/.test(from) ? ["albums", "artists", "songs", "shows", "genres", "lists"]
    : /^(playlist|playlists)$/.test(from) ? ["lists", "songs", "albums", "artists", "shows", "genres"] : /^show$/.test(from) ? ["shows", "artists", "albums", "songs", "genres", "lists"]
    : ["artists", "albums", "songs", "shows", "genres", "lists"];
  // nothing on the shelves by that name: say so while the songs (and Qobuz) are asked, and if they find nothing either,
  // offer the nearest names on the shelves instead of a blank page
  const local = artists.length + albums.length + shows.length + genres.length + lists.length, asksQobuz = n.length >= 3 && has("qobuz");
  const tally = { found: local, waiting: asksQobuz ? 2 : 1, qobuz: 0 };
  const settle = (found, fromQobuz) => {
    if (lastQ !== q) return;
    tally.found += found; tally.waiting--; if (fromQobuz) tally.qobuz += found;
    const b = $("#s-none", el); if (!b) return;
    if (tally.found > tally.qobuz) return b.remove(); // songs on the shelves after all
    if (tally.qobuz) b.innerHTML = `<p class="none-line">Nothing on your shelves for &ldquo;${esc(q)}&rdquo;.</p>${nearNames(n)}`;
    else if (!tally.waiting) b.innerHTML = noResults(q, n, asksQobuz);
  };
  box.innerHTML = (local ? "" : `<div id="s-none"><p class="none-line">Nothing on your shelves by that name. Looking among the songs${asksQobuz ? " and on Qobuz" : ""}&hellip;</p></div>`)
    + order.map(k => parts[k]).join("") + `<div id="s-qobuz"></div>`;
  lms("", ["titles", 0, 30, "search:" + q, "tags:alJ"]).then(r => {
    const t = (r.titles_loop || []); const b = $("#s-tracks", el);
    settle(lastQ === q ? t.length : 0);
    if (!b || lastQ !== q || !t.length) return;
    b.innerHTML = section("On your shelves", "Songs", `<div class="songs">${t.map(x => `<button class="song" data-act="playSong" data-v="${x.id}">${x.coverid || x.artwork_track_id ? `<img loading="lazy" src="${cover(x.artwork_track_id || x.coverid, 100)}" alt="">` : `<span class="noimg"></span>`}<span><b>${esc(x.title)}</b><em>${esc(x.artist)} &middot; ${esc(x.album)}</em></span></button>`).join("")}</div>`);
  }).catch(() => settle(0));
  if (asksQobuz) qobuzT = setTimeout(() => {
    const b = $("#s-qobuz", el); if (!b) return;
    b.innerHTML = section("Beyond the shelves", "On Qobuz", `<p class="dim">Asking Qobuz&hellip;</p>`);
    api("/api/qobuz", { action: "search", term: q, player: A.room }).then(r => {
      if (lastQ !== q) return;
      const rel = r.releases || [];
      const people = (r.artists || []).filter(x => !onShelves(x.name)); // artists not on the shelves (those on them are above)
      settle(people.length + rel.length, true);
      b.innerHTML = (people.length ? section("Beyond the shelves", "Artists on Qobuz", shelf(people.map(x => face(x.name, x.image, "on Qobuz")))) : "")
        + (rel.length ? section(people.length ? "" : "Beyond the shelves", "Records on Qobuz", shelf(rel.map(x => qCard({ artist: x.artist, album: x.album, cover: x.cover, i: x.i, term: q })))) : "");
    }).catch(() => { b.innerHTML = ""; settle(0, true); });
  }, 700);
}

/* ───────────────────────── playing ───────────────────────── */
function curTrack() { const st = A.st; if (!st) return null; return (st.playlist_loop || [])[0] || st.remoteMeta || null; }
function trackArt(t, s) { if (!t) return ""; if (t.artwork_url) return t.artwork_url.charAt(0) === "/" ? t.artwork_url : pic(t.artwork_url); return t.coverid && String(t.coverid).charAt(0) !== "-" ? cover(t.coverid, s) : t.artwork_track_id ? cover(t.artwork_track_id, s) : ""; }
function send(cmd, words) {
  return lms(A.room, cmd).then(r => { if (words) toast(words); setTimeout(poll, 250); return r; }).catch(() => toast("Lyrion didn't answer"));
}
function inOrder() { return A.st && +A.st["playlist shuffle"] ? lms(A.room, ["playlist", "shuffle", 0]) : Promise.resolve(); }
const ACT = {
  back: () => back(),
  playAlbum: v => { const a = A.byId.get(+v); inOrder().then(() => send(["playlistcontrol", "cmd:load", "album_id:" + v], `Spinning ${a ? a[1] : "the album"} in ${roomName(A.room)}`)); },
  nextAlbum: v => { const a = A.byId.get(+v); send(["playlistcontrol", "cmd:insert", "album_id:" + v], `${a ? a[1] : "The album"} plays next`); },
  queueAlbum: v => { const a = A.byId.get(+v); send(["playlistcontrol", "cmd:add", "album_id:" + v], `${a ? a[1] : "The album"} is queued`); },
  playTrack: v => { const p = v.split(":"); inOrder().then(() => send(["playlistcontrol", "cmd:load", "album_id:" + p[0], "play_index:" + p[1]])); },
  playSong: v => send(["playlistcontrol", "cmd:load", "track_id:" + v], "Playing"),
  shuffleArtist: v => {
    const info = A.artistInfo.get(norm(v)); if (!info) return;
    send(["playlistcontrol", "cmd:load", "artist_id:" + info[1]]).then(() => send(["playlist", "shuffle", 1], `Shuffling ${info[0]} in ${roomName(A.room)}`));
  },
  shuffleGenre: v => { const fam = GENRE_FAMILIES.some(f => f[0] === v) ? familyOf(v) : [v], list = A.albums.filter(a => (a[8] || []).some(x => fam.indexOf(x) >= 0)); if (list.length) ACT.playAlbum(list[Math.floor(Math.random() * list.length)][0]); },
  pickArtist: () => { // a lead story about someone on the shelves, drawn at random; nothing is played
    const withPhoto = A.artists.filter(a => a[3] && norm(a[0]) !== norm(A.heroPick || nowArtist())), pool = withPhoto.length ? withPhoto : A.artists;
    A.heroPick = pool[Math.floor(Math.random() * pool.length)][0]; A.heroAlbum = null;
    if (current && current.kind === "discover") { drawDiscover(current.el); main().scrollTop = 0; }
  },
  coverGo: v => { A.coverHold = Date.now() + 20000; coverGo(v); },
  heroBack: () => { A.heroPick = null; A.heroAlbum = null; if (current && current.kind === "discover") drawDiscover(current.el); },
  surprise: () => { // a record drawn at random leads Discover (another a tap away); opening or playing it is up to you
    const list = A.albums.filter(a => a[4] && a[0] !== A.heroAlbum);
    A.heroAlbum = list[Math.floor(Math.random() * list.length)][0]; A.heroPick = null;
    if (current && current.kind === "discover") { drawDiscover(current.el); main().scrollTop = 0; } else location.hash = "#/";
  },
  sortAlbums: v => { store.set("sq-sort", v); VIEWS.albums(current.el); },
  genreAlbums: v => { store.set("sq-genre", v); VIEWS.albums(current.el); main().scrollTop = 0; },
  letter: v => { const t = document.getElementById("L-" + v); if (t) main().scrollTop = t.offsetTop - 20; },
  story: (v, t) => {
    const box = t.nextElementSibling; t.disabled = true; t.textContent = "Fetching the story…";
    api("/api/story?name=" + encodeURIComponent(v)).then(r => { t.remove(); box.innerHTML = r.story ? prose(paras(r.story), v) : `<p class="dim">Wikipedia has nothing more.</p>`; })
      .catch(() => { t.disabled = false; t.textContent = "Wikipedia's full story"; });
  },
  unfold: (v, t) => { t.previousElementSibling.hidden = false; t.remove(); },
  qobuzSheet: v => openQobuz(JSON.parse(v)),
  qobuz: (v, t) => {
    const r = JSON.parse(t.closest("[data-r]").dataset.r), action = v;
    closeSheet();
    const body = r.term ? { action, term: r.term, index: r.i, player: A.room } : { action: "a" + action, term: r.page || r.artist, index: r.i, album: r.album, player: A.room };
    toast({ play: "Starting it…", queue: "Queueing it…", keep: "Adding it to the library…" }[action]);
    api("/api/qobuz", body).then(o => {
      if (o.error) return toast(o.error);
      toast({ playing: `Spinning ${o.album} in ${roomName(A.room)}`, queued: `${o.album} is queued`, added: `${o.album} joins the library`, already: `${o.album} is in the library already` }[o.result] || "Done");
      setTimeout(poll, 400);
    }).catch(() => toast("Qobuz didn't answer"));
  },
  closeSheet: () => closeSheet(),
  heart: (v, t) => { const m = markAt(t); setMark(m[0], m[1], { heart: !markOf(m[0], m[1])[0] }); },
  rate: (v, t) => { const m = markAt(t), was = markOf(m[0], m[1])[1]; setMark(m[0], m[1], { rating: +v === was ? 0 : +v }); }, // the same star again clears it
  // your own labels for an album (#roadtrip, #sunday), to find them again on the Albums page; the genres are the pencil's
  addTag: (v, t) => {
    const m = markAt(t), have = markOf(m[0], m[1])[2], a = A.albums.find(x => albumKey(x) === m[1]);
    const used = {}; Object.keys(A.marks.album).forEach(k => A.marks.album[k][2].forEach(g => { used[g] = (used[g] || 0) + 1; }));
    const offer = Object.keys(used).filter(g => have.indexOf(g) < 0).sort((x, y) => used[y] - used[x]).slice(0, 24);
    A.tagFor = m;
    openSheet(`<div class="kicker">Your tags</div><h3>${esc(a ? a[1] : "This album")}</h3>
      <p class="plan-note">A tag is your own label (#roadtrip, #sunday morning). Tap one on an album to see every album with it. Tags stay in Soundsquatch; genres are the pencil beside the genres.</p>
      <div class="seed-add"><input id="tag-new" type="text" maxlength="40" placeholder="New tag" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"><button class="btn ghost" data-act="tagAdd">Add</button></div>
      ${offer.length ? `<div class="gpicks">${offer.map(g => `<button class="gpick" data-act="tagAdd" data-v="${esc(g)}">#${esc(g)}</button>`).join("")}</div>` : ""}
      <div class="acts col"><button class="btn ghost" data-act="closeSheet">Done</button></div>`);
    const box = $("#tag-new"); box.addEventListener("keydown", e => { if (e.key === "Enter") ACT.tagAdd(); }); setTimeout(() => box.focus(), 250);
  },
  tagAdd: v => {
    const m = A.tagFor, name = String(v || $("#tag-new").value).trim().replace(/^#/, ""); if (!m || !name) return;
    const have = markOf(m[0], m[1])[2];
    if (have.indexOf(name) < 0) setMark(m[0], m[1], { tags: have.concat([name]) });
    closeSheet(); toast(`Tagged #${name}`);
  },
  untag: (v, t) => { const m = markAt(t); setMark(m[0], m[1], { tags: markOf(m[0], m[1])[2].filter(x => x !== v) }); },
  tagFilter: v => {
    store.set("sq-genre", v.charAt(0) === "@" ? v : "#" + v); closeSheet();
    const view = A.views.get("#/albums"); if (view) { A.views.delete("#/albums"); view.el.remove(); if (current === view) current = null; }
    if (location.hash === "#/albums") route(); else location.hash = "#/albums";
  },
  histDays: v => { store.set("sq-hist-days", +v); VIEWS.history(current.el); },
  newRelease: v => { const r = JSON.parse(v); if (r.qobuz) openQobuz({ artist: r.qobuz.artist, album: r.qobuz.album, cover: r.cover, i: r.qobuz.i, page: r.artist }); else location.hash = artistHref(r.artist); },
  trackMenu: v => openTrackMenu(v),
  // an album's genres, chosen from the house's list: kept here, and written into its files when it has some
  genreEdit: v => {
    api("/api/album-genres?id=" + v).then(r => {
      if (r.error) return toast(r.error);
      const a = A.byId.get(+v) || [];
      openSheet(`<div class="kicker">Genres</div><h3>${esc(a[1] || "")}</h3><div class="dim">${esc(a[2] || "")}</div>
        <div class="gpicks">${r.choices.concat(r.genres.filter(g => r.choices.indexOf(g) < 0)).map(g => `<button class="gpick ${r.genres.indexOf(g) >= 0 ? "on" : ""}" data-act="gpick" data-v="${esc(g)}">${esc(g)}</button>`).join("")}</div>
        <div class="seed-add"><input id="g-new" type="text" maxlength="40" placeholder="Add a genre" autocomplete="off" autocorrect="off" spellcheck="false"><button class="btn ghost" data-act="genreNew">Add</button></div>
        <p class="plan-note">Up to four. A genre you add is offered for every album from then on. Music in Lyrion's folders gets them in its files' genre tags too, and Lyrion looks again; streamed albums keep them here.${r.edited ? " Put back undoes it all: the files' own tags return and the genres are found afresh." : ""}</p>
        <div class="acts col"><button class="btn" data-act="genreSave" data-v="${v}">Save</button>${r.edited ? `<button class="btn ghost" data-act="genreUndo" data-v="${v}">Put back</button>` : ""}<button class="btn ghost" data-act="closeSheet">Not now</button></div>`);
      $("#g-new").addEventListener("keydown", e => { if (e.key === "Enter") ACT.genreNew(); });
    }).catch(() => toast("The server didn't answer"));
  },
  genreNew: () => {
    const box = $("#g-new"), name = box.value.replace(/\s+/g, " ").trim(); if (!name) return;
    const picks = $("#sheet .gpicks"), had = Array.from(picks.querySelectorAll(".gpick")).find(b => b.dataset.v.toLowerCase() === name.toLowerCase());
    if (picks.querySelectorAll(".gpick.on").length >= 4 && !(had && had.classList.contains("on"))) return toast("Four at most");
    if (had) had.classList.add("on");
    else { const b = document.createElement("button"); b.className = "gpick on"; b.dataset.act = "gpick"; b.dataset.v = name; b.textContent = name; picks.appendChild(b); b.scrollIntoView({ block: "nearest" }); }
    box.value = "";
  },
  // a track's title put right in its files (the source had it wrong), with the old one kept to put back
  // a room's own name in the app, and whether its volume is set on the device (no slider)
  settlingWhy: () => {
    const s = A.settling; if (!s) return;
    openSheet(`<div class="kicker">Welcome to Soundsquatch</div><h3>It's getting to know your shelves</h3>
      <p class="plan-note">Your ${s.albums.toLocaleString()} albums are here to play now. What Soundsquatch knows about them comes in the background: each artist's story, photographs, members and kindred spirits; each album's genres, credits and review. It asks MusicBrainz, Wikipedia${has("mai") ? " and Lyrion's Music &amp; Artist Information" : ""} for them, and MusicBrainz answers one question a second.</p>
      <p class="plan-note">For ${s.artists.toLocaleString()} artists that takes <b>about ${timeLeft(s.minutes)}</b>. Pages fill in as it goes, and Discover gets richer through the day.${on("features", "stations") ? " Your stations are made from your own shelves, one for each of their biggest genres, once most of the genres are known." : ""} Nothing needs doing: it carries on with every screen closed.</p>
      <div class="settling settling-in"><span class="settling-t"><b>${s.profiled.toLocaleString()} of ${s.artists.toLocaleString()} artists</b><span>genres for ${(s.albums - s.genres_left).toLocaleString()} of ${s.albums.toLocaleString()} albums, credits for ${(s.albums - s.credits_left).toLocaleString()}</span></span></div>
      ${PLUGINS.some(x => !has(x[0])) ? `<p class="plan-note">Lyrion is without ${PLUGINS.filter(x => !has(x[0])).map(x => esc(x[1])).join(", ")}: what ${PLUGINS.filter(x => !has(x[0])).length === 1 ? "it adds is" : "they add is"} left out. Settings says what each plugin gives.</p>` : ""}
      <div class="acts col"><button class="btn" data-act="closeSheet">Have a look around</button>${PLUGINS.some(x => !has(x[0])) ? `<a class="btn ghost" href="#/settings" data-act="closeSheet">The plugins, in Settings</a>` : ""}</div>`);
  },
  // the diagnostics a tester pastes: shown to read, with a button to copy (the clipboard needs https, so a selection otherwise)
  diagnostics: () => {
    api("/api/diagnostics").then(r => {
      const text = r.text + `\nBrowser: ${navigator.userAgent}\nScreen: ${innerWidth}×${innerHeight}, ${magOn() ? "magazine" : "classic"} look`;
      openSheet(`<div class="kicker">Diagnostics</div><h3>Paste this where you tell us</h3><textarea class="diag" readonly rows="12">${esc(text)}</textarea>
        <div class="acts col"><button class="btn" id="diag-copy">Copy</button><button class="btn ghost" data-act="closeSheet">Done</button></div>`);
      $("#diag-copy").addEventListener("click", () => {
        const box = $("#sheet .diag"), done = () => toast("Copied");
        if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(done).catch(() => {});
        box.focus(); box.select(); box.setSelectionRange(0, text.length);
        try { if (document.execCommand("copy")) done(); else toast("Selected: copy it from there"); } catch (e) { toast("Selected: copy it from there"); }
      });
    }).catch(() => toast("The server didn't answer"));
  },
  roomEdit: v => {
    const p = A.rooms.find(x => x.playerid === v) || {}, r = (A.cfg.rooms || {})[v] || {};
    openSheet(`<div class="kicker">A room</div><h3>${esc(roomName(v))}</h3><div class="dim">${esc(p.name || "")} in Lyrion</div>
      <div class="seed-add"><input id="room-name" type="text" maxlength="40" value="${esc(r.name || "")}" placeholder="${esc(p.name || "")}" autocomplete="off"></div>
      ${toggle("roomFixed", v, !!r.fixed, "Volume set on the device", "a player kept at full volume (a WiiM, an amplifier's input): no volume slider here")}
      <div class="acts col"><button class="btn" data-act="roomSave" data-v="${v}">Save</button><button class="btn ghost" data-act="closeSheet">Not now</button></div>`);
  },
  roomFixed: (v, t) => t.classList.toggle("on"),
  roomSave: v => { const rooms = {}; rooms[v] = { name: $("#room-name").value.trim(), fixed: $("#sheet .toggle").classList.contains("on") }; closeSheet(); saveSettings({ rooms: rooms }, "Saved"); },
  pinEdit: () => {
    openSheet(`<div class="kicker">The house's PIN</div><h3>${A.cfg.pin ? "A new PIN" : "Set a PIN"}</h3>
      <div class="seed-add"><input id="pin-new" type="password" inputmode="numeric" maxlength="20" autocomplete="off" placeholder="four digits or more"><button class="btn" data-act="pinSave">Save</button></div>
      <p class="plan-note">Asked before settings change, or anything is written to the music files. Each device asks once.</p>
      <div class="acts col">${A.cfg.pin ? `<button class="btn ghost" data-act="pinClear">No PIN</button>` : ""}<button class="btn ghost" data-act="closeSheet">Not now</button></div>`);
    $("#pin-new").focus();
  },
  pinSave: () => { const p = $("#pin-new").value.trim(); if (p.length < 4) return toast("Four characters at least"); closeSheet(); saveSettings({ new_pin: p }, "PIN set").then(() => store.set("sq-pin", p)); },
  pinClear: () => { closeSheet(); saveSettings({ new_pin: "" }, "No PIN now"); },
  titleEdit: (v, t) => {
    const album = t.dataset.album;
    api("/api/track-title?id=" + v).then(r => {
      if (r.error) return toast(r.error);
      if (!r.local) return toast("A streamed track's title comes from its service");
      openSheet(`<div class="kicker">Fix the title</div><h3>${esc(r.title)}</h3>
        <div class="seed-add"><input id="title-new" type="text" maxlength="200" value="${esc(r.title)}" autocomplete="off" spellcheck="true"><button class="btn" data-act="titleSave" data-v="${v}" data-album="${esc(album)}">Save</button></div>
        <p class="plan-note">Written into the file (and any other copy of it), and Lyrion looks again. The track keeps its heart and stars.${r.original ? ` It was “${esc(r.original)}” before; Put back returns that.` : ""}</p>
        <div class="acts col">${r.original ? `<button class="btn ghost" data-act="titleUndo" data-v="${v}" data-album="${esc(album)}">Put back “${esc(r.original)}”</button>` : ""}<button class="btn ghost" data-act="closeSheet">Not now</button></div>`);
      $("#title-new").addEventListener("keydown", e => { if (e.key === "Enter") ACT.titleSave(v, $("#sheet [data-act=titleSave]")); });
    }).catch(() => toast("The server didn't answer"));
  },
  titleSave: (v, t) => titleDone(t.dataset.album, { id: +v, title: $("#title-new").value }),
  titleUndo: (v, t) => titleDone(t.dataset.album, { id: +v, undo: true }),
  // a new cover: one found for it (the Cover Art Archive, Apple, Deezer) or a picture from this device
  artEdit: v => {
    const a = A.byId.get(+v) || [];
    A.artFor = +v; A.artPick = null;
    openSheet(`<div class="kicker">The cover</div><h3>${esc(a[1] || "")}</h3><div class="dim">${esc(a[2] || "")}</div>
      <div class="art-picks"><p class="dim">Looking for covers…</p></div>
      <div class="acts col"><button class="btn" data-act="artSave" disabled>Use this cover</button>
      <label class="btn ghost art-own">${icon("grid")} A picture of your own<input id="art-file" type="file" accept="image/*" hidden></label>
      <span id="art-undo"></span><button class="btn ghost" data-act="closeSheet">Not now</button></div>
      <p class="plan-note">Written into the album's files, where Lyrion finds it; the old picture is kept so it can be put back. The new cover takes a minute or two to appear, while Lyrion looks through the files again.</p>`);
    $("#art-file").addEventListener("change", e => artOwn(e.target.files && e.target.files[0]));
    api("/api/art-choices?id=" + v).then(r => {
      const box = $("#sheet .art-picks"); if (!box || A.artFor !== +v) return;
      if (r.error) { box.innerHTML = `<p class="dim">${esc(r.error)}</p>`; return; }
      if (!r.local) { box.innerHTML = `<p class="dim">This album streams from Qobuz, which keeps its own cover.</p>`; $("#sheet [data-act=artSave]").remove(); $("#sheet .art-own").remove(); return; }
      box.innerHTML = r.choices.length ? r.choices.map(c => `<button class="art-pick" data-act="artPick" data-v="${esc(c.full)}" title="${esc(c.source + ": " + c.label)}"><img src="${esc(pic(c.thumb, 300))}" alt="" onerror="this.parentNode.remove()"><span>${esc(c.source)}</span></button>`).join("")
        : `<p class="dim">No covers found for it; a picture of your own will do.</p>`;
      if (r.edited) $("#art-undo").innerHTML = `<button class="btn ghost" data-act="artUndo">Put back the old cover</button>`;
    }).catch(() => { const box = $("#sheet .art-picks"); if (box) box.innerHTML = `<p class="dim">The server didn't answer.</p>`; });
  },
  artPick: (v, t) => {
    Array.from($("#sheet").querySelectorAll(".art-pick.on")).forEach(b => b.classList.remove("on"));
    t.classList.add("on"); A.artPick = { url: v }; $("#sheet [data-act=artSave]").disabled = false;
  },
  artSave: () => { if (A.artPick) artDone(Object.assign({ id: A.artFor }, A.artPick)); },
  artUndo: () => artDone({ id: A.artFor, undo: true }),
  // an artist's picture: one of those Soundsquatch has of them, or one from this device (kept here, not in the files)
  artistPic: () => {
    const t = pageArtist(); if (!t) return;
    const name = t.name; A.picFor = name; A.picPick = null;
    openSheet(`<div class="kicker">Their picture</div><h3>${esc(name)}</h3>
      <div class="art-picks"><p class="dim">Gathering their pictures…</p></div>
      <div class="acts col"><button class="btn" data-act="picSave" disabled>Use this picture</button>
      <label class="btn ghost art-own">${icon("person")} A picture of your own<input id="pic-file" type="file" accept="image/*" hidden></label>
      <span id="pic-reset"></span><button class="btn ghost" data-act="closeSheet">Not now</button></div>
      <p class="plan-note">Shown wherever they appear in Soundsquatch. Kept here; nothing in your files changes.</p>`);
    $("#pic-file").addEventListener("change", e => shrinkPicture(e.target.files && e.target.files[0], data => picDone({ artist: name, data })));
    api("/api/artist-photos?name=" + encodeURIComponent(name)).then(r => {
      const box = $("#sheet .art-picks"); if (!box || A.picFor !== name) return;
      box.innerHTML = r.choices.length ? r.choices.map(u => `<button class="art-pick ${u === r.now ? "on" : ""}" data-act="picPick" data-v="${esc(u)}"><img src="${esc(pic(u, 320))}" alt="" onerror="this.parentNode.remove()"></button>`).join("")
        : `<p class="dim">No pictures of them found; one of your own will do.</p>`;
      if (r.chosen) $("#pic-reset").innerHTML = `<button class="btn ghost" data-act="picReset">Let Soundsquatch choose again</button>`;
    }).catch(() => { const box = $("#sheet .art-picks"); if (box) box.innerHTML = `<p class="dim">The server didn't answer.</p>`; });
  },
  picPick: (v, t) => {
    Array.from($("#sheet").querySelectorAll(".art-pick.on")).forEach(b => b.classList.remove("on"));
    t.classList.add("on"); A.picPick = v; $("#sheet [data-act=picSave]").disabled = false;
  },
  picSave: () => { if (A.picPick) picDone({ artist: A.picFor, url: A.picPick }); },
  picReset: () => picDone({ artist: A.picFor, reset: true }),
  gpick: (v, t) => {
    if (!t.classList.contains("on") && $("#sheet").querySelectorAll(".gpick.on").length >= 4) return toast("Four at most");
    t.classList.toggle("on");
  },
  genreSave: v => genresDone(v, { id: +v, genres: Array.from($("#sheet").querySelectorAll(".gpick.on")).map(b => b.dataset.v) }),
  genreUndo: v => genresDone(v, { id: +v, undo: true }),
  // an artist's tags (MusicBrainz's), each shown or hidden on their page; nothing of theirs is in the files
  artistTags: () => {
    const t = pageArtist(); if (!t) return;
    openSheet(`<div class="kicker">Their tags</div><h3>${esc(t.name)}</h3>
      <div class="gpicks">${t.all.map(g => `<button class="gpick ${t.hidden.indexOf(g) < 0 ? "on" : ""}" data-act="tagPick" data-v="${esc(g)}">${esc(g)}</button>`).join("")}</div>
      <p class="plan-note">The ones lit show on their page (the first five). These come from MusicBrainz; hiding one changes nothing in your files.</p>
      <div class="acts col"><button class="btn" data-act="artistTagsSave">Save</button><button class="btn ghost" data-act="closeSheet">Not now</button></div>`);
  },
  tagPick: (v, t) => t.classList.toggle("on"),
  artistTagsSave: () => {
    const t = pageArtist(), hidden = Array.from($("#sheet").querySelectorAll(".gpick:not(.on)")).map(b => b.dataset.v);
    closeSheet();
    api("/api/artist-tags", { artist: t.name, hidden }).then(r => { if (r.error) return toast(r.error); redraw(); toast("Saved"); }).catch(() => toast("The server didn't answer"));
  },
  banSheet: () => {
    const t = curTrack(); if (!t) return;
    openSheet(`<div class="kicker">Never play</div><h3>${esc(t.title)}</h3><div class="dim">${esc(t.artist || "")}</div>
      <p class="plan-note">Skipped now, and kept out of whatever the radio and the stations bring from now on. Music you put on yourself plays whole. Lift it in Settings.</p>
      <div class="acts col"><button class="btn" data-act="banDo" data-v="track" data-artist="${esc(t.artist || "")}" data-title="${esc(t.title)}">${icon("ban")} Never play this track</button>
      <button class="btn ghost" data-act="banDo" data-v="artist" data-artist="${esc(splitArtist(t.artist || ""))}">${icon("ban")} Never play ${esc(splitArtist(t.artist || ""))}</button><button class="btn ghost" data-act="closeSheet">Not now</button></div>`);
  },
  banDo: (v, t) => {
    closeSheet();
    api("/api/ban", { kind: v, artist: t.dataset.artist, title: t.dataset.title || "", player: A.room }).then(r => {
      if (r.error) return toast(r.error);
      toast(v === "artist" ? `${t.dataset.artist} won't come round again` : `"${t.dataset.title}" won't come round again`); setTimeout(poll, 600);
    }).catch(() => toast("The server didn't answer"));
  },
  banLift: (v, t) => { api("/api/ban", { kind: t.dataset.kind, lift: v }).then(() => { t.closest(".ban").remove(); toast("Lifted"); }); },
  setFeat: v => { const f = {}; f[v] = !A.cfg.features[v];
    if (v === "write_files" && f[v] && !confirm("Let Soundsquatch change your music files? Genres, titles and covers are written into them (what they had before is kept, to put back), and Remove from the library moves an album's files to music-removed. Nothing is ever deleted.")) return; saveSettings({ features: f }, `${v === "home_assistant" ? "Home Assistant" : FEATS.find(x => x[0] === v)[1]} ${f[v] ? "on" : "off"} for the house`)
    .then(() => { if (v === "home_assistant" || v === "stations") loadStations().catch(() => {}); if (v === "home_assistant") setTimeout(() => loadLibrary().catch(() => {}), 4000); }); },
  setDisc: v => { const f = {}; f[v] = !A.cfg.discover[v]; saveSettings({ discover: f }, `${DISC.find(x => x[0] === v)[1]} ${f[v] ? "shown" : "hidden"} on Discover`); },
  connEdit: (v, t) => { t.closest(".conn").classList.add("open"); t.closest(".settings").classList.add("editing"); const i = t.closest(".conn").querySelector("[data-conn]"); if (i) i.focus(); },
  saveConn: () => {
    const conn = {}; document.querySelectorAll("[data-conn]").forEach(i => { conn[i.dataset.conn] = i.value.trim(); });
    saveSettings({ connections: conn }, "Saved; checks below");
  },
  setZoom: v => { device.set("zoom", +v); applyDevice(); if (current && current.kind === "settings") drawSettings(current.el); },
  setDev: v => { device.set(v, !device.get(v, false)); applyDevice(); if (current && current.kind === "settings") drawSettings(current.el); },
  keepLog: (v, t) => {
    const k = t.dataset.k, row = t.closest(".hist") || document;
    t.disabled = true;
    api("/api/keep", { url: v, player: A.room }).then(r => {
      if (r.error) { t.disabled = false; return toast("Couldn't add it: " + r.error); }
      toast(r.result === "already" ? `${r.album || "It"} is in the library already` : `${r.album || "The album"} joins the library; Lyrion shows it in a minute or two`);
      row.querySelectorAll('.keep-log[data-k="' + k.replace(/"/g, '\\"') + '"]').forEach(b => { b.outerHTML = `<span class="kept">${icon("heart_on")}<span class="pl">In the library</span></span>`; });
    }).catch(() => { t.disabled = false; toast("Lyrion didn't answer"); });
  },
  share: v => shareIt(JSON.parse(v)),
  copyLink: () => { // a readonly field selected and copied: works on a plain http page, where the clipboard API does not
    const f = $("#sheet .share-url"); f.removeAttribute("readonly"); f.focus(); f.setSelectionRange(0, f.value.length);
    let ok = false; try { ok = document.execCommand("copy"); } catch (e) {}
    f.setAttribute("readonly", ""); f.blur(); toast(ok ? "Link copied" : "Select the link above and copy it");
  },
  archShow: v => openArchive(JSON.parse(v)),
  archDo: (v, t) => {
    const holder = t.closest("[data-show]") || (current && $("[data-show]", current.el)) || $("#sheet [data-show]");
    const x = JSON.parse(holder.dataset.show), body = { ctx: x.ctx, what: v, player: A.room };
    if (!x.ctx) return toast("Still finding the show in the plugin…");
    if (v === "track") body.index = +t.dataset.i;
    if (v !== "fav" && v !== "unfav") closeSheet();
    toast({ play: "Starting the show…", queue: "Queueing the show…", track: "Starting the show there…", fav: "Putting it on your shelves…", unfav: "Taking it off your shelves…" }[v]);
    api("/api/archive/do", body).then(r => {
      if (r.error) return toast(r.error);
      if (v === "fav" || v === "unfav") {
        loadArchive().then(() => { Array.from(A.views.keys()).forEach(h => { const view = A.views.get(h); if (view !== current) { view.el.remove(); A.views.delete(h); } }); });
        const b = (holder.closest(".view") || document).querySelector(".arch-fav") || $("#sheet .arch-fav");
        if (b) { b.dataset.v = v === "fav" ? "unfav" : "fav"; b.innerHTML = b.closest("#sheet") ? `${icon(v === "fav" ? "heart_on" : "heart")} ${v === "fav" ? "On your shelves" : "Add to your shelves"}` : icon(v === "fav" ? "heart_on" : "heart"); b.setAttribute("aria-label", v === "fav" ? "On your shelves" : "Add to your shelves"); }
        toast(v === "fav" ? "On your shelves (the plugin's favourites)" : "Off your shelves");
      } else { toast(v === "queue" ? "Queued" : `Playing in ${roomName(A.room)}`); setTimeout(poll, 800); }
    }).catch(() => toast("The Archive didn't answer"));
  },
  stationSheet: v => openStation(v),
  seedAdd: () => {
    const input = $("#seed-in"), k = $("#sheet [data-station]").dataset.station, name = (input.value || "").trim(); if (!name) return;
    const known = A.artists.find(a => norm(a[0]) === norm(name));
    stationEdit({ what: "add", key: k, artist: known ? known[0] : name }, known ? "" : `${name} isn't on your shelves: the station will skip it until it is`).then(() => openStation(k));
  },
  // never play an artist, from their page (or lift it): asked first, as it reaches every room
  artistBan: v => {
    api("/api/bans").then(r => {
      const on = (r.bans || []).find(b => b.kind === "artist" && norm(b.label) === norm(v));
      openSheet(`<div class="kicker">Never play</div><h3>${esc(v)}</h3>
        <p class="plan-note">${on ? "They're on the never-play list: the radio and the stations skip them." : "The radio and the stations will skip them in every room from now on, and anything of theirs the radio has queued goes. If they're playing in this room now, it skips ahead. Albums of theirs you put on yourself later still play."}</p>
        <div class="acts col">${on ? `<button class="btn" data-act="banLiftArtist" data-v="${esc(on.key)}">Take them off the list</button>` : `<button class="btn" data-act="banDo" data-v="artist" data-artist="${esc(v)}">${icon("ban")} Never play ${esc(v)}</button>`}
        <button class="btn ghost" data-act="closeSheet">Not now</button></div>`);
    }).catch(() => toast("The server didn't answer"));
  },
  banLiftArtist: v => { closeSheet(); api("/api/ban", { kind: "artist", lift: v }).then(() => toast("Off the never-play list")).catch(() => toast("The server didn't answer")); },
  magTab: (v, t) => {
    const art = t.closest(".mag"); store.set(t.dataset.store || "sq-mag-tab", v); const view = t.closest(".view"); if (view) view.magTab = v;
    art.querySelectorAll(".mag-tabs button").forEach(b => b.classList.toggle("on", b === t));
    art.querySelectorAll(".mag-page").forEach(p => { p.hidden = p.dataset.tab !== v; });
  },
  recentAll: () => { store.set("sq-sort", "added"); store.set("sq-genre", ""); const v = A.views.get("#/albums"); if (v) { v.el.remove(); A.views.delete("#/albums"); } location.hash = "#/albums"; },
  versions: v => {
    const a = A.byId.get(+v); if (!a) return;
    openSheet(`<div class="kicker">Pressings</div><h3>${esc(a[1])}</h3><div class="dim">${esc(a[2])}</div>
      <div class="rooms">${versionsOf(a).map((x, i) => `<a class="room ${x[0] === +v ? "on" : ""}" href="${albumHref(x[0])}" data-act="closeSheet"><span class="room-go">${x[4] ? `<img class="ver-art" src="${cover(x[4], 100)}" alt="">` : icon("disc")}<span><b>${esc(x[1])}</b><em>${[x[3] || "", x[2] ? esc(x[2]) : "", x[5] === "qobuz" ? "on Qobuz" : "on the shelves", i === 0 ? "shown" : ""].filter(Boolean).join(" &middot; ")}</em></span></span></a>`).join("")}</div>
      <p class="plan-note">The best-sounding pressing is the one shown; the others are kept and play from here.</p>`);
  },
  focusOpen: () => { (A.heard ? Promise.resolve() : loadHeard()).then(openFocus); },
  focusPick: (v, t) => {
    const f = t.dataset.f, list = A.focus[f] = A.focus[f] || [], i = list.indexOf(v);
    if (i >= 0) list.splice(i, 1); else list.push(v);
    focusChanged(); openFocus();
  },
  focusShow: () => { closeSheet(); if (location.hash !== "#/albums") location.hash = "#/albums"; main().scrollTop = 0; },
  focusClear: () => { A.focus = {}; focusChanged(); openFocus(); },
  focusPlay: () => {
    const ids = focusList().filter(a => !a.archive).map(a => a[0]), room = A.room; closeSheet();
    if (!ids.length) return toast("Nothing in the dig to play");
    toast("Making a mix…");
    inOrder().then(() => (A.radio[room] ? null : setRadio(true))).then(() => api("/api/play-albums", { ids, player: room }))
      .then(r => { toast(r.error || `A mix from ${ids.length} albums in ${roomName(room)}; the radio carries on`); setTimeout(poll, 500); }).catch(() => toast("The server didn't answer"));
  },
  focusSave: () => {
    const name = ($("#focus-name").value || "").trim(); if (!name) return;
    const saved = focusSaved().filter(f => norm(f.name) !== norm(name)); saved.push({ name, f: JSON.parse(JSON.stringify(A.focus)) });
    keepFocuses(saved); toast(`Dig kept as ${name}, on every screen`); focusChanged(); openFocus();
  },
  focusUse: v => { const f = focusSaved()[+v]; if (!f) return; A.focus = JSON.parse(JSON.stringify(f.f)); closeSheet(); focusChanged(); if (location.hash !== "#/albums") location.hash = "#/albums"; },
  focusForget: v => { const saved = focusSaved().slice(); saved.splice(+v, 1); keepFocuses(saved); focusChanged(); openFocus(); },
  focusMix: v => { const f = focusSaved()[+v]; if (!f) return; const was = A.focus; A.focus = JSON.parse(JSON.stringify(f.f)); (A.focus.heard && !A.heard ? loadHeard() : Promise.resolve()).then(() => { ACT.focusPlay(); A.focus = was; }); },
  signalPath: () => openSignalPath(),
  levelSet: (v, t) => {
    const room = A.room;
    lms(room, ["playerpref", "replayGainMode", v]).then(() => {
      t.parentNode.querySelectorAll("button").forEach(b => b.classList.toggle("on", b === t));
      toast(`Volume levelling ${v === "0" ? "off" : "by " + LEVELS[+v][1].toLowerCase()} in ${roomName(room)}`);
    }).catch(() => toast("Lyrion didn't answer"));
  },
  seedSheet: v => { if (!v) return; (A.stations ? Promise.resolve() : loadStations()).then(() => seedSheet(v)); },
  seedNewStation: v => {
    const title = ($("#st-new").value || "").replace(/\s+/g, " ").trim(); if (!title) return;
    const have = ((A.stations && A.stations.stations) || []).find(st => norm(st.name) === norm(title));
    (have ? Promise.resolve({ key: have.key }) : api("/api/station-edit", { what: "new", name: title })).then(r => {
      if (r.error) return toast(r.error);
      return stationEdit({ what: "add", key: r.key, artist: v }, `${v} seeds ${title}`).then(() => {
        seedSheet(v); Array.from(document.querySelectorAll(".seed-btn")).forEach(b => b.classList.toggle("on", isSeed(b.dataset.v)));
      });
    }).catch(() => toast("The server didn't answer"));
  },
  seedToggle: (v, t) => {
    const name = t.parentNode.dataset.artist, add = !t.classList.contains("on");
    t.classList.toggle("on", add);
    stationEdit({ what: add ? "add" : "remove", key: v, artist: name }, add ? `${name} seeds ${t.textContent}` : `${name} is off ${t.textContent}`).then(() => {
      Array.from(document.querySelectorAll(".seed-btn")).forEach(b => b.classList.toggle("on", isSeed(b.dataset.v)));
    });
  },
  seedRemove: v => { const k = $("#sheet [data-station]").dataset.station; stationEdit({ what: "remove", key: k, artist: v }).then(() => openStation(k)); },
  stationRename: () => {
    const k = $("#sheet [data-station]").dataset.station, st = A.stations.stations.find(x => x.key === k);
    const name = (prompt("Name the station:", st.name) || "").trim(); if (!name) return;
    const blurb = prompt("A line about it (optional):", st.blurb || ""); stationEdit({ what: "rename", key: k, name: name, blurb: blurb == null ? st.blurb : blurb }).then(() => openStation(k));
  },
  stationDelete: () => {
    const k = $("#sheet [data-station]").dataset.station, st = A.stations.stations.find(x => x.key === k);
    if (!confirm(`Delete the ${st.name} station? Its seed artists go with it.`)) return;
    closeSheet(); stationEdit({ what: "delete", key: k }, `${st.name} is gone`);
  },
  stationNew: () => {
    const name = (prompt("Name the new station:") || "").trim(); if (!name) return;
    stationEdit({ what: "new", name: name }).then(r => { if (r && r.key) openStation(r.key); });
  },
  stationGo: v => {
    const st = A.stations.stations.find(x => x.key === v); closeSheet(); toast(`Starting ${st.name} in ${roomName(A.room)}…`);
    api("/api/station", { key: v, player: A.room }).then(r => {
      if (r.error || !r.ok) return toast(r.error || "The station didn't start");
      toast(`${st.name} is on in ${roomName(A.room)}` + (r.seeds && r.seeds.length ? `: ${r.seeds.join(", ")}, then the radio` : ""));
      setTimeout(poll, 600);
    }).catch(() => toast("Home Assistant didn't answer"));
  },
  restore: (v, t) => {
    t.disabled = true; t.textContent = "Putting back…";
    api("/api/restore", { id: +v, player: A.room }).then(r => {
      if (r.error) { toast("Couldn't put it back"); t.disabled = false; t.textContent = "Put back"; return; }
      toast(`${r.album} is going back on the shelves` + (r.kept ? ` (${r.kept} ${r.kept === 1 ? "file was" : "files were"} already there again, left as they are)` : "") + "; Lyrion shows it in a minute or two");
      VIEWS.removed(current.el);
      setTimeout(() => loadLibrary().then(() => Array.from(A.views.keys()).forEach(h => { const view = A.views.get(h); if (view !== current) { view.el.remove(); A.views.delete(h); } })), 90000);
    }).catch(() => { toast("The server didn't answer"); t.disabled = false; t.textContent = "Put back"; });
  },
  // taking an album off the shelves: the first tap says exactly what will happen, the second does it
  removeAsk: v => {
    openSheet(`<div class="kicker">Remove from the library</div><h3>Looking&hellip;</h3>`);
    api("/api/removal?id=" + v).then(r => {
      if (r.error) { closeSheet(); return toast("Couldn't find that album in Lyrion"); }
      const what = [];
      if (r.qobuz) what.push(`Takes it out of your Qobuz favourites.`);
      if (r.files) what.push(`Moves its ${r.files} ${r.files === 1 ? "file" : "files"}${r.copies > 1 ? ` (${r.copies} copies)` : ""} to <b>${esc(r.to)}</b>, out of Lyrion's sight. Nothing is deleted: they can be put back.`);
      if (!what.length) what.push("Lyrion holds nothing for it that this can remove.");
      openSheet(`<div class="kicker">Remove from the library</div><h3>${esc(r.album)}</h3><div class="dim">${esc(r.artist)}</div>
        <ul class="plan">${what.map(w => `<li>${w}</li>`).join("")}${r.versions_left ? `<li>Only this pressing goes: ${r.versions_left === 1 ? "the other pressing stays" : `the other ${r.versions_left} pressings stay`} on the shelves.</li>` : ""}<li>Its hearts, stars and tags are kept.</li></ul>
        <div class="acts col">${r.qobuz || r.files ? `<button class="btn danger-solid" data-act="removeDo" data-v="${v}">${icon("trash")} Remove it</button>` : ""}<button class="btn ghost" data-act="closeSheet">Keep it</button></div>`);
    }).catch(() => { closeSheet(); toast("Lyrion didn't answer"); });
  },
  removeDo: v => {
    const a = A.byId.get(+v); closeSheet(); toast(`Removing ${a ? a[1] : "the album"}…`);
    api("/api/remove", { id: +v, player: A.room }).then(r => {
      if (r.error) return toast("Lyrion wouldn't remove it");
      // the shelves as the server now has them (another version, if any, standing in), every page drawn again when next opened
      loadLibrary().then(() => { Array.from(A.views.keys()).forEach(h => { const view = A.views.get(h); if (view !== current) { view.el.remove(); A.views.delete(h); } }); back(); });
      toast(`${r.album} is off the shelves` + (r.qobuz ? " and out of your Qobuz favourites" : "") + (r.moved ? `; ${r.moved} ${r.moved === 1 ? "file" : "files"} moved to music-removed` : "") + (r.problems.length ? ` (${r.problems[0]})` : ""));
    }).catch(() => toast("Lyrion didn't answer"));
  },
  setLook: v => {
    device.set("look", v); applyDevice();
    Array.from(A.views.keys()).forEach(h => { const view = A.views.get(h); if (view !== current) { view.el.remove(); A.views.delete(h); } }); // every page drawn again in its new look
    if (current && current.kind === "settings") drawSettings(current.el);
    toast(v === "magazine" ? "This screen reads like a magazine now" : "This screen is back to the classic look");
  },
  setOsk: () => { device.set("osk", !oskOn()); if (!oskOn()) oskHide(); if (current && current.kind === "settings") drawSettings(current.el); },
  searchOpen: () => {
    if (current && current.kind === "search") { const q = $("#q"); if (q) q.focus(); return; }
    A.searchFrom = $("#np").hidden ? (current ? current.kind : "") : "np";
    if (!$("#np").hidden) closeNp();
    const s = A.views.get("#/search"); if (s) { s.el.remove(); A.views.delete("#/search"); } // drawn afresh: the order follows where it was opened
    if (!A.playlists) playlistsList().catch(() => {});
    location.hash = "#/search";
  },
  searchClear: () => {
    const q = $("#q");
    if (q && q.value) { q.value = ""; runSearch(current.el, ""); q.focus(); } else ACT.searchClose();
  },
  searchClose: () => { if (history.length > 1 && A.searchFrom !== undefined) history.back(); else location.hash = "#/"; },
  searchFor: v => { const q = $("#q"); if (q) { q.value = v; runSearch(current.el, v); } },
  findWork: v => { lastQ = v; const s = A.views.get("#/search"); if (s) { s.el.remove(); A.views.delete("#/search"); } location.hash = "#/search"; },
  addToPlaylist: v => openPlaylistPicker(v),
  plPick: (v, t) => {
    const what = t.closest("[data-what]").dataset.what.split(":"), body = { playlist_id: v ? +v : null };
    if (!v) { body.name = (prompt("Name the new playlist:") || "").trim(); if (!body.name) return; }
    body[what[0] === "album" ? "album_id" : "track_id"] = +what[1];
    closeSheet();
    api("/api/playlist-add", body).then(r => { if (r.error) return toast("Lyrion wouldn't add it"); toast(`Added ${r.added} ${r.added === 1 ? "track" : "tracks"}${body.name ? " to " + body.name : ""}`); forgetPlaylists(); })
      .catch(() => toast("Lyrion didn't answer"));
  },
  playPlaylist: v => { const p = v.split(":"); inOrder().then(() => send(["playlistcontrol", "cmd:load", "playlist_id:" + p[0], "play_index:" + p[1]], "Spinning the playlist")); },
  plRemove: v => { const p = v.split(":"); api("/api/playlist-do", { what: "remove", playlist_id: +p[0], index: +p[1] }).then(() => { forgetPlaylists(); VIEWS.playlist(current.el, p[0]); }); },
  playlistMenu: v => openSheet(`<div data-pl="${v}"><div class="kicker">Playlist</div><h3>${esc(((A.playlists || []).find(p => String(p.id) === v) || {}).name || "")}</h3>
    <div class="acts col"><button class="btn ghost" data-act="plRename" data-v="${v}">Rename</button><button class="btn ghost danger" data-act="plDelete" data-v="${v}">Delete the playlist</button></div></div>`),
  plRename: v => {
    const name = (prompt("A new name:") || "").trim(); if (!name) return; closeSheet();
    api("/api/playlist-do", { what: "rename", playlist_id: +v, name: name }).then(() => { forgetPlaylists(); (A.playlists || []).forEach(p => { if (String(p.id) === v) p.name = name; }); VIEWS.playlist(current.el, v); });
  },
  plDelete: v => {
    if (!confirm("Delete this playlist? Its tracks stay in the library.")) return; closeSheet();
    api("/api/playlist-do", { what: "delete", playlist_id: +v }).then(() => { forgetPlaylists(); toast("Playlist deleted"); location.hash = "#/playlists"; });
  },
  plNew: () => {
    const name = (prompt("Name the new playlist:") || "").trim(); if (!name) return;
    api("/api/playlist-do", { what: "new", name: name }).then(r => {
      if (r.error && !r.playlist_id) return toast("Lyrion wouldn't make it");
      if (r.error) toast("There's one by that name already: here it is");
      forgetPlaylists(); playlistsList().then(() => { location.hash = "#/playlist/" + r.playlist_id; });
    }).catch(() => toast("Lyrion didn't answer"));
  },
  saveQueue: () => {
    const name = (prompt("Save the queue as a playlist called:") || "").trim(); if (!name) return;
    api("/api/playlist-do", { what: "save", name: name, player: A.room }).then(() => { forgetPlaylists(); toast(`Saved as ${name}`); });
  },
  trackDo: (v, t) => {
    const p = t.closest("[data-track]").dataset.track.split(":");
    albumData(p[0]).then(d => {
      const tr = d.tracks[+p[1]]; closeSheet();
      if (v === "play") ACT.playTrack(p.join(":"));
      else if (v === "next") send(["playlistcontrol", "cmd:insert", "track_id:" + tr.id], `${tr.title} plays next`);
      else if (v === "queue") send(["playlistcontrol", "cmd:add", "track_id:" + tr.id], `${tr.title} is queued`);
      else if (v === "radio") startRadio(tr.id, `Radio from ${tr.title}`);
    });
  },
  // a station of one: the server queues their best songs with a few by artists like them, and the radio carries on from there
  artistRadio: v => {
    const room = A.room, name = (A.artistInfo.get(norm(v)) || [v])[0];
    toast(`Tuning in ${name} radio…`);
    inOrder().then(() => (A.radio[room] ? null : setRadio(true))).then(() => api("/api/artist-radio", { artist: name, player: room })).then(r => {
      if (r.error) return toast(r.error);
      toast(`${name} radio in ${roomName(room)}${r.kin.length ? `, with ${r.kin.slice(0, 3).join(", ")}${r.kin.length > 3 ? " and more" : ""}` : ""}`);
      setTimeout(poll, 500);
    }).catch(() => toast("The server didn't answer"));
  },
  radioToggle: () => setRadio(!A.radio[A.room]),
  repeat: () => { const r = +(A.st && A.st["playlist repeat"]) || 0; send(["playlist", "repeat", r === 0 ? 2 : r === 2 ? 1 : 0], ["Repeat the one track", "Repeat off", "Repeat the queue"][r === 0 ? 2 : r === 2 ? 0 : 1]); },
  npTab: v => { A.npTab = v; store.set("sq-np-tab", v); drawNpSide(); },
  seekTo: v => send(["time", Math.max(0, +v - 0.3)]),
  syncJoin: v => lms(A.room, ["sync", v]).then(() => { toast(`${roomName(v)} joins ${roomName(A.room)}`); setTimeout(openRooms, 500); }),
  syncLeave: v => lms(v, ["sync", "-"]).then(() => { toast(`${roomName(v)} plays on its own again`); setTimeout(openRooms, 500); }),
  moveTo: v => {
    toast(`Moving the music to ${roomName(v)}…`);
    api("/api/move", { from: A.room, to: v }).then(r => {
      if (r.error) return toast(r.error === "nothing to move" ? "Nothing is playing here" : "Lyrion wouldn't move it");
      ACT.room(v); toast(`Now playing in ${roomName(v)}`);
    }).catch(() => toast("Lyrion didn't answer"));
  },
  room: v => { A.room = v; store.set("sq-room", v); closeSheet(); A.st = null; A.curKey = "\u0000"; poll(); },
  rooms: () => openRooms(),
  toggle: () => { if (A.st) { A.st.mode = A.st.mode === "play" ? "pause" : "play"; A.st.time = position(); A.stAt = Date.now(); paintPlayer(); } send(["pause"]); },
  next: () => send(["playlist", "index", "+1"]),
  prev: () => send(A.st && A.st.time > 6 ? ["time", 0] : ["playlist", "index", "-1"]),
  jump: v => send(["playlist", "index", v]),
  drop: v => send(["playlist", "delete", v]),
  shuffleMode: () => send(["playlist", "shuffle", A.st && +A.st["playlist shuffle"] ? 0 : 1]),
  openNp: () => openNp(),
  closeNp: () => closeNp()
};
// what plays, and so needs a room to play in
const PLAYS = /^(playAlbum|nextAlbum|queueAlbum|playTrack|playSong|shuffleArtist|shuffleGenre|stationGo|focusPlay|focusMix|playPlaylist|artistRadio|radioToggle|toggle|next|prev|jump|shuffleMode|repeat|seekTo|trackDo|levelSet|saveQueue)$/;
const playsHere = (act, v) => PLAYS.test(act) || (act === "qobuz" && v !== "keep") || (act === "archDo" && /^(play|queue|next)$/.test(v || ""));
document.addEventListener("click", e => {
  const t = e.target.closest("[data-act]");
  if (!t || !ACT[t.dataset.act]) return;
  e.preventDefault(); e.stopPropagation();
  const act = t.dataset.act, v = t.dataset.v;
  if (!A.room && playsHere(act, v)) return withRoom(() => ACT[act](v, t, e));
  ACT[act](v, t, e);
});
// no room yet (no player was on when this screen opened): Lyrion asked again, and the first player on taken; none, said so
function withRoom(go) {
  lms("", ["players", 0, 50]).then(r => {
    A.rooms = (r.players_loop || []).filter(p => p.connected);
    const p = A.rooms.find(x => x.modelname !== "Group") || A.rooms[0];
    if (!p) return toast("No players are on. Turn on a speaker Lyrion knows, then try again");
    A.room = p.playerid; A.curKey = "\u0000"; poll(); go();
  }).catch(() => toast("Lyrion isn't answering"));
}
// an artist's page asked for as the finger lands, so it is often there by the time the tap ends
document.addEventListener("touchstart", e => {
  const a = e.target.closest && e.target.closest('a[href^="#/"]');
  if (!a) return;
  const h = a.getAttribute("href");
  if (h.indexOf("#/artist/") === 0) profile(decodeURIComponent(h.slice(9))).catch(() => {});
  else if (h.indexOf("#/album/") === 0) albumData(h.slice(8)).catch(() => {});
}, { passive: true });

/* Radio is Lyrion's Don't Stop the Music: when a room's queue runs out it keeps going with more like it (LastMix here). Off
   is provider 0; on is the provider the room had before, else LastMix. */
const DSTM = "plugin.dontstopthemusic:provider";
A.radio = {};
function readRadio(room) { return lms(room, ["playerpref", DSTM, "?"]).then(r => { const v = r._p2; A.radio[room] = v && v !== "0" ? v : ""; if (v && v !== "0") store.set("sq-dstm-" + room, v); return A.radio[room]; }); }
function setRadio(on) {
  const room = A.room, v = on ? store.get("sq-dstm-" + room, "PLUGIN_LASTMIX_DSTM_ITEM") : 0;
  A.radio[room] = on ? v : ""; paintRadio();
  return lms(room, ["playerpref", DSTM, v]).then(() => toast(on ? `Radio on in ${roomName(room)}: when the queue ends, more like it follows` : `Radio off in ${roomName(room)}`));
}
function paintRadio() { document.querySelectorAll(".radio-btn").forEach(b => b.classList.toggle("on", !!A.radio[A.room])); }
// a radio from one track: it plays, and radio is turned on so more like it follows
function startRadio(trackId, words) {
  const go = () => send(["playlistcontrol", "cmd:load", "track_id:" + trackId], words);
  inOrder().then(() => (A.radio[A.room] ? go() : setRadio(true).then(go)));
}
function openTrackMenu(v) {
  const p = v.split(":");
  albumData(p[0]).then(d => {
    const t = d.tracks[+p[1]];
    openSheet(`<div data-track="${esc(v)}"><div class="kicker">${esc(t.artist || d.artist)}</div><h3>${esc(t.title)}</h3><div class="dim">${esc(d.album)}</div>
      <div class="acts col"><button class="btn" data-act="trackDo" data-v="play">${icon("play")} Spin from here</button><button class="btn ghost" data-act="trackDo" data-v="next">${icon("next_up")} Spin it next</button>
      <button class="btn ghost" data-act="trackDo" data-v="queue">${icon("queue")} Add to the queue</button><button class="btn ghost" data-act="addToPlaylist" data-v="track:${t.id}">${icon("list")} Add to a playlist</button>
      <button class="btn ghost" data-act="banDo" data-v="track" data-artist="${esc(t.artist || d.artist)}" data-title="${esc(t.title)}">${icon("ban")} Never play this track</button><button class="btn ghost" data-act="trackDo" data-v="radio">${icon("radio")} Start a radio from it</button>${on("features", "write_files") ? `<button class="btn ghost" data-act="titleEdit" data-v="${t.id}" data-album="${esc(p[0])}">${icon("edit")} Fix the title</button>` : ""}</div>
      <div class="sheet-mark">${mk("track", trackKey(Object.assign({ album: d.album }, t)), "heart")} <span class="dim">Love this track</span></div></div>`);
  });
}
function openSheet(html) { const s = $("#sheet"); s.innerHTML = `<div class="sheet-bg" data-act="closeSheet"></div><div class="sheet-card">${html}</div>`; s.hidden = false; requestAnimationFrame(() => s.classList.add("on")); }
// the page drawn afresh (after an edit to what it shows)
function redraw() {
  const h = location.hash || "#/", view = A.views.get(h);
  if (view) { A.views.delete(h); view.el.remove(); if (current === view) current = null; }
  route();
}
function titleDone(album, body) {
  closeSheet(); toast(body.undo ? "Putting it back…" : "Saving…");
  api("/api/track-title", body).then(r => {
    if (r.error) return toast(r.error);
    // the page shows it at once; Lyrion's own list catches up when its scan is done
    albumData(album).then(d => d.tracks.forEach(x => { if (x.id === body.id) x.title = r.title; })).catch(() => {}).then(loadMarks).then(redraw);
    toast(r.problems.length ? `Not every copy took it: ${r.problems[0]}` : `“${r.title}”, written into ${r.written} ${r.written === 1 ? "file" : "files"}; Lyrion is looking again`);
  }).catch(() => toast("The server didn't answer"));
}
// a picture from the device, made no larger than it needs to be before it is sent
function artOwn(file) { shrinkPicture(file, data => artDone({ id: A.artFor, data })); }
function shrinkPicture(file, done) {
  if (!file) return;
  const img = new Image(), url = URL.createObjectURL(file);
  img.onload = () => {
    const k = Math.min(1, 1600 / Math.max(img.width, img.height)), c = document.createElement("canvas");
    c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); URL.revokeObjectURL(url);
    done(c.toDataURL("image/jpeg", 0.9));
  };
  img.onerror = () => toast("That picture couldn't be read");
  img.src = url;
}
function picDone(body) {
  closeSheet(); toast(body.reset ? "Letting Soundsquatch choose…" : "Saving their picture…");
  api("/api/artist-photo", body).then(r => {
    if (r.error) return toast(r.error);
    A.profiles.delete(norm(body.artist)); redraw(); loadLibrary().catch(() => {});
    toast(body.reset ? "Soundsquatch chooses their picture again" : "Their picture is saved");
  }).catch(() => toast("The server didn't answer"));
}
function artDone(body) {
  const id = body.id;
  closeSheet(); toast(body.undo ? "Putting the old cover back…" : "Writing the new cover…");
  api("/api/art", body).then(r => {
    if (r.error) return toast(r.error);
    toast(r.problems.length ? `${r.written} of ${r.files} files took it; ${r.problems[0]}` : `${body.undo ? "Old cover put back" : "New cover saved"}; it appears in a minute or two, once Lyrion has looked`);
    [35, 95, 245].forEach(s => setTimeout(() => loadLibrary().then(() => { if (current && current.kind === "album" && location.hash === "#/album/" + id) redraw(); }).catch(() => {}), s * 1000));
  }).catch(() => toast("The server didn't answer"));
}
function genresDone(v, body) {
  closeSheet(); toast(body.undo ? "Putting them back…" : "Saving…");
  api("/api/album-genres", body).then(r => {
    if (r.error) return toast(r.error);
    const a = A.byId.get(+v); if (a) a[8] = r.genres;
    redraw();
    toast(r.problems.length ? `Saved, but ${r.problems.length} ${r.problems.length === 1 ? "file" : "files"} wouldn't take it: ${r.problems[0]}`
      : r.written ? `${body.undo ? "Put back" : "Saved"}, and written into ${r.written} ${r.written === 1 ? "file" : "files"}; Lyrion is looking again`
      : body.undo ? "Put back" : "Saved");
    setTimeout(() => loadLibrary().catch(() => {}), 1500);
  }).catch(() => toast("The server didn't answer"));
}
function closeSheet() { const s = $("#sheet"); s.classList.remove("on"); setTimeout(() => { s.hidden = true; s.innerHTML = ""; }, 220); }
function openQobuz(r) {
  openSheet(`<div class="qs" data-r="${esc(JSON.stringify(r))}">${r.cover ? `<img src="${esc(pic(r.cover, 640))}" alt="">` : ""}<div><div class="kicker">On Qobuz</div><h3>${esc(r.album)}</h3><div class="dim">${esc(r.artist)}</div>
    <div class="acts col"><button class="btn" data-act="qobuz" data-v="play">${icon("play")} Spin it in ${esc(roomName(A.room))}</button><button class="btn ghost" data-act="qobuz" data-v="queue">${icon("queue")} Queue it</button>
    <button class="btn ghost" data-act="qobuz" data-v="keep">${icon("heart")} Add to the library</button>${shareBtn(r.album + " by " + r.artist, qobuzLink(r.cover), "wide")}</div></div></div>`);
}
/* Rooms that may play together: only players that tell Lyrion exactly where they are in a song, so it can keep them in
   step. The bridges (CastBridge for Chromecasts, UPnPBridge, AirPlay's RaopBridge) can't (their speakers buffer on their
   own clocks and report no accurate position), and a group with one drifts audibly apart: they can't join or be joined. */
const inStep = p => !!p && !/bridge/i.test(p.modelname || "") && p.modelname !== "Group";
function openRooms() {
  lms("", ["players", 0, 50]).then(r0 => {
    A.rooms = (r0.players_loop || []).filter(p => p.connected);
    const listed = A.rooms.filter(p => p.modelname !== "Group");
    // each room's own state and what it has on, asked of every room at once
    return Promise.all([Promise.resolve(r0), Promise.all(listed.map(p => lms(p.playerid, ["status", "-", 1, "tags:a"]).catch(() => ({})))), readRadio(A.room).catch(() => "")]).then(r => [r0, r[1], listed]);
  }).then(r => {
    const states = {}; r[2].forEach((p, i) => { states[p.playerid] = r[1][i] || {}; });
    const st = states[A.room] || {}, group = [st.sync_master].concat(String(st.sync_slaves || "").split(",")).filter(Boolean), playing = +st.playlist_tracks > 0;
    const here = r[2].filter(p => p.playerid === A.room), others = r[2].filter(p => p.playerid !== A.room);
    openSheet(`<div class="kicker">Play in</div><h3>Rooms</h3><div class="rooms">${here.concat(others).map(p => {
      const me = p.playerid === A.room, joined = group.indexOf(p.playerid) >= 0, s2 = states[p.playerid] || {};
      const t = (s2.playlist_loop || [])[0] || s2.remoteMeta || {}, on = +s2.power !== 0 && p.power;
      const mode = s2.mode === "play" ? "playing" : s2.mode === "pause" && +s2.playlist_tracks ? "paused" : !on ? "off" : +s2.playlist_tracks ? "stopped" : "idle";
      const what = (mode === "playing" || mode === "paused") && t.title ? ` &middot; ${esc(t.title)}${t.artist ? " &mdash; " + esc(t.artist) : ""}` : "";
      const label = (me ? "this room, " : joined ? "with this room, " : "") + mode;
      return `<div class="room ${me ? "on" : ""} st-${mode}"><button class="room-go" data-act="room" data-v="${p.playerid}">${mode === "playing" ? `<span class="eq"><i></i><i></i><i></i></span>` : icon("speaker")}<span><b>${esc(roomName(p.playerid))}</b><em><span class="state">${label}</span>${what}</em></span></button>
        ${me ? "" : `<span class="room-acts">${joined ? `<button data-act="syncLeave" data-v="${p.playerid}" aria-label="Leave">${icon("close")}<span class="lb">Leave</span></button>` : inStep(p) && inStep(here[0]) ? `<button data-act="syncJoin" data-v="${p.playerid}" aria-label="Join">${icon("link")}<span class="lb">Join</span></button>` : ""}
          ${playing && !joined ? `<button data-act="moveTo" data-v="${p.playerid}" aria-label="Move music here">${icon("move")}<span class="lb">Move music here</span></button>` : ""}</span>`}</div>`;
    }).join("")}</div>
    ${here[0] && !inStep(here[0]) ? `<p class="plan-note">${esc(roomName(A.room))} plays through a bridge (a Chromecast or the like), which can't keep in step with other rooms, so it can't be grouped.</p>`
      : r[2].some(p => p.playerid !== A.room && !inStep(p)) ? `<p class="plan-note">Rooms without Join play through a bridge (a Chromecast or the like) and can't keep in step with others.</p>` : ""}
    ${has("radio") ? `<button class="radio-row radio-btn ${A.radio[A.room] ? "on" : ""}" data-act="radioToggle">${icon("radio")}<span><b>Radio in ${esc(roomName(A.room))}</b><em>When the queue runs out, more like it follows</em></span><i class="sw"></i></button>` : ""}`);
  });
}

/* ───────────────────────── the player: the bar along the bottom, and Now Playing over everything ───────────────────────── */
let pollT;
function poll() {
  clearTimeout(pollT);
  if (document.hidden) return;
  const room = A.room;
  // no room (no player on): Lyrion hangs up on a player's status asked of no player, so it's asked how the server is instead
  lms(room, room ? ["status", "-", 12, "tags:aAlKcdjJNtyeuoIrTsq"] : ["serverstatus", 0, 0]).then(st => {
    if (room !== A.room) return;
    A.st = room ? st : {}; A.stAt = Date.now(); paintPlayer();
    if (/[?&]np\b/.test(location.search) && !A.npOnce) { A.npOnce = true; openNp(); } // ?np opens straight onto Now Playing
    if (/[?&]rooms\b/.test(location.search) && !A.roomsOnce) { A.roomsOnce = true; openRooms(); } // ?rooms, onto the rooms
    A.misses = 0; offline(false);
  }).catch(e => { if (++A.misses >= 3) offline(e && e.lyrion ? "Lyrion isn't answering" : "Soundsquatch isn't answering"); })
    .then(() => { pollT = setTimeout(poll, A.misses >= 3 ? 4000 : $("#np").hidden ? 1500 : 1000); });
}
A.misses = 0;
function offline(what) {
  let b = $("#offline");
  if (!what) { if (b) b.remove(); return; }
  if (!b) { b = document.createElement("div"); b.id = "offline"; document.body.appendChild(b); }
  b.textContent = what + ". Trying again…"; // a restart, an update, the power: it comes back by itself
}
document.addEventListener("visibilitychange", () => { if (!document.hidden) { poll(); settleScreen(); } });
// an iPhone's or iPad's home-screen app sometimes opens with the screen measured short (a black band at the foot, taps
// landing off their buttons) until something makes it measure again: so measure again on opening, coming back and turning
document.addEventListener("keydown", e => {
  if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test((e.target || {}).tagName || "")) { e.preventDefault(); ACT.searchOpen(); }
});
function settleScreen() {
  if (!/iPhone|iPad|iPod/.test(navigator.userAgent) && !(navigator.maxTouchPoints > 1 && /Mac/.test(navigator.platform))) return;
  const vp = document.querySelector('meta[name="viewport"]'); if (!vp) return;
  const c = vp.getAttribute("content");
  vp.setAttribute("content", c + ", maximum-scale=1");
  requestAnimationFrame(() => { vp.setAttribute("content", c); window.scrollTo(0, 0); fitFoot(); });
}
// a home-screen app is given the screen less the status bar's height (797 of an iPhone's 844), the rest left empty below
// the tabs: the foot of the page is let down into it by that much
function fitFoot() {
  const root = document.documentElement, portrait = window.innerHeight > window.innerWidth;
  const full = portrait ? Math.max(screen.height, screen.width) : Math.min(screen.height, screen.width), gap = full - window.innerHeight;
  const probe = document.createElement("div"); // drawn under the status bar (a top inset) is when iOS keeps that strip below
  probe.style.cssText = "position:fixed;top:0;left:0;width:1px;visibility:hidden;padding-top:env(safe-area-inset-top,0px)";
  document.body.appendChild(probe); const under = parseFloat(getComputedStyle(probe).paddingTop) > 0; probe.remove();
  const short = !!navigator.standalone && under && gap > 0 && gap < 90;
  root.classList.toggle("vp-short", short);
  root.style.setProperty("--vp-gap", (short ? gap : 0) + "px");
}
window.addEventListener("resize", fitFoot);
// shown inside another page (the wall's paper), touches here never reach it: it is told of them, now and then, so it
// doesn't think the screen is untouched and turn away to its front page or its screensaver
if (window.parent !== window) {
  let toldAt = 0;
  const tell = () => { if (Date.now() - toldAt < 5000) return; toldAt = Date.now(); try { window.parent.postMessage({ soundsquatch: "touch" }, "*"); } catch (e) {} };
  ["pointerdown", "touchstart", "wheel", "keydown"].forEach(t => addEventListener(t, tell, { capture: true, passive: true }));
}
window.addEventListener("pageshow", () => { settleScreen(); setTimeout(settleScreen, 400); });

window.addEventListener("orientationchange", () => setTimeout(settleScreen, 300));
function position() { const st = A.st || {}; return Math.min(+st.duration || 0, (+st.time || 0) + (st.mode === "play" ? (Date.now() - A.stAt) / 1000 : 0)); }
// the rooms playing together: this one first, then those joined to it (Lyrion's sync group, from the room's status)
function groupRooms(st) {
  st = st || A.st || {};
  const ids = [st.sync_master].concat(String(st.sync_slaves || "").split(",")).filter(Boolean);
  return ids.length > 1 ? [A.room].concat(ids.filter(id => id !== A.room)) : [A.room];
}
function groupLabel(st) {
  if (!A.room) return "No players";
  const names = groupRooms(st).map(roomName);
  return names.length < 3 ? names.join(" + ") : names[0] + " + " + (names.length - 1) + " rooms";
}
function paintPlayer() {
  const st = A.st || {}, t = curTrack(), bar = $("#bar"), playing = st.mode === "play";
  const k = t ? (t.id || "") + "|" + (t.title || "") + "|" + (t.artist || "") : "";
  if (k !== A.curKey) {
    const changedArtist = !A.curKey || (A.curKey.split("|")[2] !== (t && t.artist));
    A.curKey = k;
    // three parts, the transport always in the middle: what is playing; the buttons; its quality, the room and the volume
    const right = `<div class="bar-right"><button class="bar-room" data-act="rooms">${icon("speaker")}<span class="room-label">${esc(groupLabel())}</span></button>${t && !fixedVolume(A.room) ? `<input class="vol" type="range" min="0" max="100" aria-label="Volume">` : ""}</div>`;
    bar.innerHTML = t ? `<div class="bar-prog"><i></i></div><div class="bar-left"><button class="bar-art" data-act="openNp">${trackArt(t, 150) ? `<img src="${esc(trackArt(t, 150))}" alt="">` : ""}</button>
      <button class="bar-what" data-act="openNp"><b>${esc(t.title)}</b><em>${esc(t.artist || "")}${t.album ? " &middot; " + esc(t.album) : ""}</em></button><span class="bar-q" data-act="signalPath">${quality(t)}</span></div>
      <div class="bar-ctl"><button data-act="prev" aria-label="Previous">${icon("prev")}</button><button class="pp" data-act="toggle" aria-label="Play or pause"></button><button data-act="next" aria-label="Next">${icon("next")}</button></div>${right}`
      : `<div class="bar-left"><div class="bar-what idle"><b>Nothing playing</b><em>${A.room ? "in " + esc(roomName(A.room)) : "no players are on"}</em></div></div><div class="bar-ctl"></div>${right}`;
    const vol = $(".vol", bar); if (vol) bindVolume(vol);
    const img = $(".bar-art img", bar); if (img) tint(img, document.body);
    if (!$("#np").hidden) drawNp(); // (draws the side too: up next, or the new song's words)
    if (changedArtist && current && current.kind === "discover" && A.home) drawDiscover(current.el);
  }
  const pp = $(".pp", bar); if (pp) pp.innerHTML = icon(playing ? "pause" : "play");
  const label = groupLabel(), together = groupRooms().length > 1;
  document.querySelectorAll(".room-label").forEach(el => { if (el.textContent !== label) el.textContent = label; });
  document.querySelectorAll(".bar-room, .np-room").forEach(el => el.classList.toggle("grouped", together));
  const vol = $(".vol", bar); if (vol && !vol.dragging) vol.value = Math.abs(+st["mixer volume"] || 0);
  const prog = $(".bar-prog i", bar); if (prog) prog.style.width = (st.duration ? position() / st.duration * 100 : 0) + "%";
  if (!$("#np").hidden) paintNp();
}
function bindVolume(input) {
  let t;
  const setv = () => { clearTimeout(t); t = setTimeout(() => lms(A.room, ["mixer", "volume", input.value]), 120); };
  input.addEventListener("input", () => { input.dragging = true; setv(); });
  input.addEventListener("change", () => { input.dragging = false; setv(); });
}
function openNp() { const np = $("#np"); np.hidden = false; drawNp(); requestAnimationFrame(() => np.classList.add("on")); poll(); }
function closeNp() { const np = $("#np"); np.classList.remove("on"); setTimeout(() => { np.hidden = true; }, 300); }
function drawNp() {
  const t = curTrack(), np = $("#np");
  if (!t) { np.innerHTML = `<button class="np-close" data-act="closeNp">${icon("down")}</button><div class="empty-state"><h1>Silence</h1><p>Nothing is playing in ${esc(roomName(A.room))}.</p></div>`; return; }
  const art = trackArt(t, 800), artist = splitArtist(t.artist || ""), libAlbum = A.albums.find(a => norm(a[1]) === norm(t.album) && norm(a[2]) === norm(t.artist));
  np.innerHTML = `<div class="np-bg">${art ? `<img src="${esc(art)}" alt="">` : ""}</div><button class="np-close" data-act="closeNp" aria-label="Close">${icon("down")}</button>
    <div class="np-main"><div class="np-art">${art ? `<img src="${esc(art)}" alt="">` : ""}</div>
      <div class="np-info"><div class="kicker">Now playing in <span class="room-label">${esc(groupLabel())}</span></div><h1>${hearted(t.title, mk("track", trackKey(t), "heart"))}</h1>
        <div class="byline">${artist ? hearted(t.artist || artist, mk("artist", norm(artist), "heart"), `<a class="by" href="${artistHref(artist)}" data-close="1">`, "</a>") : ""}</div>${t.album ? (libAlbum ? `<a class="alb" href="${albumHref(libAlbum[0])}" data-close="1">${esc(t.album)}${t.year && +t.year ? " &middot; " + t.year : ""}</a>` : `<div class="alb">${esc(t.album)}${t.year && +t.year ? " &middot; " + t.year : ""}</div>`) : ""}
        <button class="np-q" data-act="signalPath" aria-label="Playing through">${quality(t)}</button>
        <div class="np-prog"><div class="track"><i></i></div><div class="times"><span class="at"></span><span class="left"></span></div></div>
        <div class="np-ctl"><button class="sm shuf" data-act="shuffleMode" aria-label="Shuffle">${icon("shuffle")}</button><button data-act="prev">${icon("prev")}</button><button class="pp big" data-act="toggle"></button><button data-act="next">${icon("next")}</button><button class="sm rep" data-act="repeat" aria-label="Repeat">${icon("repeat")}<i></i></button></div>
        <div class="np-extra"><button class="pill" data-act="banSheet" aria-label="Never play">${icon("ban")}</button>${has("radio") ? `<button class="pill seed-btn ${isSeed(splitArtist(t.artist || "")) ? "on" : ""}" data-act="seedSheet" data-v="${esc(splitArtist(t.artist || ""))}" aria-label="Add to a station">${icon("radio_plus")}</button><button class="pill radio-btn ${A.radio[A.room] ? "on" : ""}" data-act="radioToggle">${icon("radio")} Radio</button>` : ""}<button class="pill np-room" data-act="rooms">${icon("speaker")} <span class="room-label">${esc(groupLabel())}</span></button>${qobuzLink(t.artwork_url) ? `<button class="pill" data-act="share" data-v="${esc(JSON.stringify({ title: (t.album || t.title) + " by " + (t.artist || ""), url: qobuzLink(t.artwork_url) }))}">${icon("share")} Share</button>` : ""}</div>
        ${fixedVolume(A.room) ? "" : `<div class="np-vol">${icon("vol")}<input class="vol" type="range" min="0" max="100" aria-label="Volume"></div>`}</div>
      <div class="np-side"><div id="np-about"></div><div class="np-tabs"><button data-act="npTab" data-v="next">Up next</button>${on("features", "lyrics") ? `<button data-act="npTab" data-v="lyrics">Lyrics</button>` : ""}${on("features", "credits") ? `<button data-act="npTab" data-v="credits">Credits</button>` : ""}<button class="np-save" data-act="saveQueue">Save queue</button></div><div class="np-next"></div></div></div>`;
  drawNpSide();
  readRadio(A.room).then(paintRadio).catch(() => {});
  if ($(".vol", np)) bindVolume($(".vol", np));
  const img = $(".np-art img", np); if (img) tint(img, np);
  $(".np-prog .track", np).addEventListener("click", e => { const r = e.currentTarget.getBoundingClientRect(), st = A.st || {}; if (st.duration) send(["time", Math.round((e.clientX - r.left) / r.width * st.duration)]); });
  if (artist) whoIs(t.artist || "").then(found => {
    const p = found[1], artist = found[0];
    const box = $("#np-about", np); if (!box || A.curKey.split("|")[2] !== t.artist) return;
    const text = (p.qobuz && p.qobuz.bio) || (p.wiki && p.wiki.extract) || "";
    box.innerHTML = `<a class="np-artist" href="${artistHref(artist)}" data-close="1">${p.thumb || p.hero ? `<img src="${esc(pic(p.thumb || p.hero, 320))}" alt="">` : ""}<div><div class="kicker">About the artist</div><b>${esc((p.qobuz && p.qobuz.name) || artist)}</b>${text ? `<p>${esc(standfirst(text, 300))}</p>` : ""}</div></a>`;
  }).catch(() => {});
  paintNp();
}
// who a track's artist is: the whole name when anyone knows it ("Good Night & Good Morning"), else the first named
// ("A & B" → A); a name never asked of takes a few seconds to look up, waited for
const known = p => !!((p.qobuz && p.qobuz.name) || (p.wiki && p.wiki.extract) || (p.mb && p.mb.mbid));
function whoIs(full) {
  const first = splitArtist(full);
  if (first === full) return profile(full).then(p => [full, p]);
  const ask = n => profile(full).then(p => known(p) || !p.partial || n > 8 ? p : new Promise(r => setTimeout(r, 1500)).then(() => ask(n + 1)));
  return ask(0).then(p => known(p) ? [full, p] : profile(first).then(q => [first, q]));
}
function upNext() {
  const list = ((A.st && A.st.playlist_loop) || []).slice(1);
  return list.length ? list.map(x => `<div class="nx" data-i="${x["playlist index"]}"><span class="grip" aria-label="Drag to reorder">${icon("grip")}</span><button class="nx-go" data-act="jump" data-v="${x["playlist index"]}">${trackArt(x, 100) ? `<img loading="lazy" src="${esc(trackArt(x, 100))}" alt="">` : `<span class="noimg"></span>`}<span><b>${esc(x.title)}</b><em>${esc(x.artist || "")}</em></span></button><button class="nx-x" data-act="drop" data-v="${x["playlist index"]}" aria-label="Remove">${icon("close")}</button></div>`).join("")
    : `<p class="dim">The queue ends here.</p>`;
}
function quality(t) {
  const kind = t.type || "", bits = +t.samplesize || 0, rate = +t.samplerate || 0;
  if (["flc", "wav", "aif", "alc", "wvp", "ape"].indexOf(kind) >= 0) return `<span class="q hi">${(bits || 16) === 16 && rate === 44100 ? "CD quality" : (bits || 16) + "-bit / " + (rate / 1000) + " kHz"}</span>`;
  return t.bitrate ? `<span class="q">${esc(kind.toUpperCase())} ${esc(String(t.bitrate).replace(/kbps.*/i, ""))} kbps</span>` : "";
}
/* ───────────────────────── the signal path ─────────────────────────
   What is playing, from where it comes to the room it plays in: the source and its format, how Lyrion sends it, the
   room's player; and the room's volume levelling (Lyrion's ReplayGain: off, by track, by album, or smart). */
const LEVELS = [["0", "Off"], ["1", "Track"], ["2", "Album"], ["3", "Smart"]];
function openSignalPath() {
  const t = curTrack(), room = A.room; if (!t) return;
  Promise.all([lms("", ["players", 0, 50]), lms(room, ["playerpref", "replayGainMode", "?"])]).then(r => {
    const p = (r[0].players_loop || []).find(x => x.playerid === room) || {}, level = String(r[1]._p2 || "0"), url = t.url || "";
    const from = /^qobuz:/.test(url) ? "Qobuz" : /archive\.org/.test(url) ? "The Internet Archive" : /^file:/.test(url) ? "A file on the server" : /^https?:/.test(url) ? "A stream" : "Lyrion's library";
    const kind = (t.type || "").toUpperCase(), lossless = ["FLC", "WAV", "AIF", "ALC", "WVP", "APE"].indexOf(kind) >= 0;
    const format = lossless ? `${kind === "FLC" ? "FLAC" : kind}, ${(+t.samplesize || 16)}-bit / ${(+t.samplerate || 44100) / 1000} kHz` : `${kind} ${String(t.bitrate || "").replace(/kbps.*/i, "")} kbps`.trim();
    const bridge = /bridge/i.test(p.modelname || ""), device = bridge ? (/cast/i.test(p.modelname) ? "a Chromecast" : "a UPnP player") : (p.modelname || "the player");
    const step = (title, what, note) => `<div class="sp-step"><i></i><div><div class="kicker">${title}</div><b>${what}</b>${note ? `<em>${note}</em>` : ""}</div></div>`;
    openSheet(`<div class="kicker">Playing through</div><h3>${esc(t.title || "")}</h3><div class="dim">${esc(t.artist || "")}</div>
      <div class="sp">${step("Source", esc(from), esc(format) + (lossless ? " &middot; lossless" : " &middot; compressed"))}
      ${step("Lyrion", bridge ? "Streams it to a bridge" : "Streams it to the player", bridge ? `The bridge hands it on to ${device} as its plugin is set up; the bridge can change the format on the way` : "The player decodes it itself")}
      ${step("Room", esc(roomName(room)), esc(p.modelname || ""))}</div>
      <div class="kicker sp-h">Volume levelling in ${esc(roomName(room))}</div>
      <div class="seg sp-seg">${LEVELS.map(l => `<button class="${l[0] === level ? "on" : ""}" data-act="levelSet" data-v="${l[0]}">${l[1]}</button>`).join("")}</div>
      <p class="plan-note">Evens out loudness from the ReplayGain tags in the music. Track: every song alike. Album: an album's own ups and downs kept. Smart: album when an album plays through, track otherwise. Music without the tags plays as it is${bridge ? "; bridges may not apply it" : ""}.</p>`);
  }).catch(() => toast("Lyrion didn't answer"));
}
function paintNp() {
  const np = $("#np"), st = A.st || {}, pos = position();
  const pp = $(".pp", np); if (pp) pp.innerHTML = icon(st.mode === "play" ? "pause" : "play");
  const i = $(".np-prog i", np); if (i) i.style.width = (st.duration ? pos / st.duration * 100 : 0) + "%";
  const at = $(".np-prog .at", np); if (at) at.textContent = mmss(pos);
  const left = $(".np-prog .left", np); if (left) left.textContent = st.duration ? "-" + mmss(st.duration - pos) : "";
  const vol = $(".vol", np); if (vol && !vol.dragging) vol.value = Math.abs(+st["mixer volume"] || 0);
  const sh = $(".shuf", np); if (sh) sh.classList.toggle("on", !!+st["playlist shuffle"]);
  const rp = $(".rep", np), r = +st["playlist repeat"] || 0; if (rp) { rp.classList.toggle("on", r > 0); $("i", rp).textContent = r === 1 ? "1" : ""; }
  if (A.npTab === "next" && !A.dragging) { const nx = $(".np-next", np), html = upNext(); if (nx && nx.dataset.h !== html) { nx.innerHTML = html; nx.dataset.h = html; } }
}
// the side of Now Playing: what is next, or the words
function drawNpSide() {
  const np = $("#np"), box = $(".np-next", np); if (!box) return;
  if ((A.npTab === "lyrics" && !on("features", "lyrics")) || (A.npTab === "credits" && !on("features", "credits"))) A.npTab = "next";
  np.querySelectorAll(".np-tabs button").forEach(b => b.classList.toggle("on", b.dataset.v === A.npTab));
  box.dataset.h = "";
  box.classList.toggle("lyr", A.npTab === "lyrics");
  np.querySelector(".np-save").hidden = A.npTab !== "next";
  if (A.npTab === "next") { paintNp(); return; }
  const t = curTrack(); if (!t) return;
  const k = A.curKey;
  if (A.npTab === "credits") {
    box.innerHTML = `<p class="dim">Looking up who made it&hellip;</p>`;
    npCredits(t).then(html => { if (A.curKey === k && A.npTab === "credits") box.innerHTML = html; });
    return;
  }
  box.innerHTML = `<p class="dim">Finding the words&hellip;</p>`;
  lyricsFor(t).then(l => {
    if (A.curKey !== k || A.npTab !== "lyrics") return;
    if (l.lines.length) box.innerHTML = l.lines.map(x => `<p data-act="seekTo" data-v="${x[0]}" data-t="${x[0]}">${esc(x[1]) || "&nbsp;"}</p>`).join("");
    else if (l.plain) box.innerHTML = paras(l.plain).map(x => `<p class="plain">${esc(x)}</p>`).join("");
    else box.innerHTML = `<p class="dim">${l.instrumental ? "An instrumental: no words to follow." : "No words found for this one."}</p>`;
  });
}
const lyricCache = {};
function lyricsFor(t) {
  const k = (t.artist || "") + "|" + (t.title || "");
  if (!lyricCache[k]) lyricCache[k] = api("/api/lyrics?" + ["artist", "title", "album", "duration"].map(f => f + "=" + encodeURIComponent(t[f] || "")).join("&")).then(r => {
    const lines = []; // "[01:23.45] words" → [83.45, "words"]
    String(r.synced || "").split("\n").forEach(line => { const m = line.match(/^\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)$/); if (m) lines.push([+m[1] * 60 + +m[2], m[3]]); });
    return { lines: lines, plain: r.plain || "", instrumental: r.instrumental };
  }).catch(() => ({ lines: [], plain: "" }));
  return lyricCache[k];
}
// the line being sung, lit and kept in view, four times a second while the words are showing
setInterval(() => {
  const np = $("#np"); if (np.hidden || A.npTab !== "lyrics") return;
  const box = $(".np-next.lyr", np); if (!box) return;
  const pos = position() + 0.25, rows = box.querySelectorAll("p[data-t]");
  let cur = null; for (let i = 0; i < rows.length; i++) { if (+rows[i].dataset.t <= pos) cur = rows[i]; else break; }
  if (cur && !cur.classList.contains("now")) {
    const was = box.querySelector("p.now"); if (was) was.classList.remove("now");
    cur.classList.add("now");
    box.scrollTop = cur.offsetTop - box.clientHeight / 3;
  }
}, 250);
// the queue in Now Playing reorders by dragging a row by its grip
document.addEventListener("pointerdown", e => {
  const g = e.target.closest && e.target.closest(".grip"); if (!g) return;
  e.preventDefault();
  const row = g.closest(".nx"), list = row.parentNode, rows = Array.prototype.slice.call(list.querySelectorAll(".nx"));
  const from = rows.indexOf(row), h = row.offsetHeight, y0 = e.clientY;
  let to = from;
  A.dragging = true; row.classList.add("dragging");
  const move = ev => {
    const dy = ev.clientY - y0; row.style.transform = `translateY(${dy}px)`;
    to = Math.max(0, Math.min(rows.length - 1, from + Math.round(dy / h)));
    rows.forEach((r, i) => { if (r === row) return; const shift = from < to && i > from && i <= to ? -h : from > to && i < from && i >= to ? h : 0; r.style.transform = shift ? `translateY(${shift}px)` : ""; });
  };
  const up = () => {
    document.removeEventListener("pointermove", move); document.removeEventListener("pointerup", up); document.removeEventListener("pointercancel", up);
    rows.forEach(r => { r.style.transform = ""; }); row.classList.remove("dragging"); A.dragging = false;
    if (to === from) return;
    const pl = (list.dataset.drag || "").split(":");
    if (pl[0] === "playlist") api("/api/playlist-do", { what: "move", playlist_id: +pl[1], from: +rows[from].dataset.i, to: +rows[to].dataset.i }).then(() => { forgetPlaylists(); VIEWS.playlist(current.el, pl[1]); });
    else send(["playlist", "move", rows[from].dataset.i, rows[to].dataset.i]);
  };
  document.addEventListener("pointermove", move); document.addEventListener("pointerup", up); document.addEventListener("pointercancel", up);
});
// a link inside Now Playing closes it on the way to the page
document.addEventListener("click", e => { const a = e.target.closest && e.target.closest("[data-close]"); if (a) closeNp(); });

/* ───────────────────────── start ───────────────────────── */
// ?lite: a lighter way of drawing for a modest machine (the wall's Pi): no frosted glass, no large blurs, nothing that
// animates for ever (set by the page that frames it)
if (/[?&]lite\b/.test(location.search)) document.documentElement.classList.add("lite");
function start() {
  document.querySelectorAll("[data-icon]").forEach(i => { i.outerHTML = icon(i.dataset.icon); });
  $("#main").innerHTML = `<div class="loading"><img class="load-logo" src="logo.png" alt=""><div class="mast-name"><span>Sound<em>squatch</em></span></div><p>Taking the records off the shelves&hellip;</p></div>`;
  if (device.get("room", "")) A.room = device.get("room", "");
  applyDevice();
  const house = api("/api/settings").then(c => { A.cfg = c;
    // a new release: said once on each screen, and kept at the top of Settings
    if (c.update && store.get("sq-update-told", "") !== c.update.version) { store.set("sq-update-told", c.update.version); setTimeout(() => toast("Soundsquatch " + c.update.version + " is out: see Settings"), 4000); }
  }).catch(() => {});
  // the room this screen controls: its own choice, else the last used, else the one the house plays in most
  Promise.all([lms("", ["players", 0, 50]), house]).then(r => {
    A.rooms = (r[0].players_loop || []).filter(p => p.connected);
    const home = (A.cfg || {}).home_room;
    if (!A.rooms.some(p => p.playerid === A.room) && A.rooms.length) A.room = (A.rooms.find(p => p.playerid === home) || A.rooms.find(p => p.modelname !== "Group") || A.rooms[0]).playerid;
  }).catch(() => {}).then(poll);
  $("#main").addEventListener("scroll", watchHead, { passive: true });
  Promise.all([loadLibrary(), loadMarks(), loadFocuses(), house, loadArchive(), loadStations().catch(() => null)]).then(() => { applyHouse(); $("#main").innerHTML = ""; route(); window.addEventListener("hashchange", route); })
    .catch(firstRun);
}
// the shelves didn't come: when it's because Lyrion can't be found (a first start, or it has moved), its address asked for
function firstRun() {
  const head = `<img class="load-logo" src="logo.png" alt=""><div class="mast-name"><span>Sound<em>squatch</em></span></div>`;
  const stuck = () => { $("#main").innerHTML = `<div class="loading">${head}<p>The library isn't answering. <button class="btn" onclick="location.reload()">Try again</button></p></div>`; };
  api("/api/settings").then(c => {
    if (c.checks && c.checks.lms_ok) return stuck(); // Lyrion answers: the trouble is elsewhere
    const login = c.checks.lms_auth;
    $("#main").innerHTML = `<div class="loading">${head}<p>${login ? "Lyrion asks for a username and password." : "Soundsquatch can't find Lyrion on the network. Where is it?"}</p>
      <div class="seed-add first-run"><input id="lms-at" type="url" placeholder="192.168.1.20:9000" value="${esc(c.connections.lms_url || "")}" autocomplete="off" autocapitalize="off" spellcheck="false"><button class="btn" id="lms-go">Look there</button></div>
      ${login ? `<div class="first-run">${loginFields(c)}</div>` : ""}
      <p class="dim" id="lms-said">${login ? "" : esc(c.checks.lms_url || "")}</p></div>`;
    const go = () => {
      let u = $("#lms-at").value.trim().replace(/\/+$/, "");
      if (!/^https?:\/\//.test(u)) u = "http://" + u;
      if (!/:\d+$/.test(u)) u += ":9000";
      $("#lms-said").textContent = "Looking…";
      const conn = { lms_url: u }; document.querySelectorAll("#main [data-conn]").forEach(i => { conn[i.dataset.conn] = i.value.trim(); });
      api("/api/settings", { connections: conn }).then(r => { if (r.checks.lms_ok) location.reload(); else if (r.checks.lms_auth && !login) firstRun(); else $("#lms-said").textContent = "Not there: " + r.checks.lms_url; }).catch(stuck);
    };
    $("#lms-go").addEventListener("click", go);
    $("#lms-at").addEventListener("keydown", e => { if (e.key === "Enter") go(); });
  }).catch(stuck);
}
start();

/* ───────────────────────── the on-screen keyboard ─────────────────────────
   For a screen without a keyboard of its own: the wall (shown there with ?lite) unless told otherwise, or any screen whose
   This device setting asks for it. It rises under any text field that takes the focus and types into it; Done is Enter. */
const oskOn = () => device.get("osk", /[?&]lite\b/.test(location.search));
const OSK_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl'", "^zxcvbnm<", "&- .!"];
let oskTarget = null, oskShift = false;
function oskDraw() {
  const label = k => k === "^" ? "⇧" : k === "<" ? "⌫" : k === " " ? "space" : k === "!" ? "Done" : oskShift ? k.toUpperCase() : k;
  $("#osk").innerHTML = OSK_ROWS.map(r => `<div class="osk-row">${r.split("").map(k => `<button class="osk-k${k === " " ? " wide" : k === "!" ? " done" : k === "^" ? (oskShift ? " on" : "") : ""}" data-k="${esc(k)}">${label(k)}</button>`).join("")}</div>`).join("");
}
function oskShow(el) { oskTarget = el; oskShift = false; oskDraw(); $("#osk").hidden = false; document.documentElement.classList.add("osk-up"); }
function oskHide() { oskTarget = null; $("#osk").hidden = true; document.documentElement.classList.remove("osk-up"); }
function oskPress(k) {
  const el = oskTarget; if (!el) return;
  if (k === "^") { oskShift = !oskShift; return oskDraw(); }
  if (k === "!") { el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })); el.blur(); return oskHide(); }
  const a = el.selectionStart == null ? el.value.length : el.selectionStart, b = el.selectionEnd == null ? a : el.selectionEnd;
  if (k === "<") { const from = a === b ? Math.max(0, a - 1) : a; el.value = el.value.slice(0, from) + el.value.slice(b); el.setSelectionRange(from, from); }
  else { const ch = oskShift ? k.toUpperCase() : k; el.value = el.value.slice(0, a) + ch + el.value.slice(b); el.setSelectionRange(a + 1, a + 1); if (oskShift) { oskShift = false; oskDraw(); } }
  el.dispatchEvent(new Event("input", { bubbles: true }));
}
document.addEventListener("focusin", e => { const t = e.target; if (oskOn() && t && t.tagName === "INPUT" && /^(text|search)$/.test(t.type || "text")) oskShow(t); });
document.addEventListener("focusout", () => setTimeout(() => { const a = document.activeElement; if (!(a && a.tagName === "INPUT")) oskHide(); }, 120));
$("#osk").addEventListener("pointerdown", e => { e.preventDefault(); const b = e.target.closest("[data-k]"); if (b) oskPress(b.dataset.k); }); // the field keeps the focus
