"""Music Assistant as Soundsquatch's music server, spoken to as if it were Lyrion (a trial: branch music-assistant).

Soundsquatch asks Lyrion everything through its JSON-RPC (the server's rpc(), the app's /jsonrpc.js). With MA_URL set,
those asks come here instead, and the few Lyrion commands the app and the shelves rely on are answered from Music
Assistant's websocket API (ws://host:8095/ws, a token from its Settings → Profile) in Lyrion's own shapes:
  players, status, playlistcontrol (an album or a track: load, add, insert), playlist (next, previous, a place, clear,
  shuffle), play, pause, stop, mixer volume, time (seek), titles album_id:N (its songs), serverstatus.
Anything else answers {} (as Lyrion does for a plugin that isn't there), so Lyrion-only features stay hidden.

Music Assistant's ids aren't Lyrion's numbers: an album keeps its library number; a song gets a number of our own,
mapped to its uri for as long as the server runs.
"""
import json
import os
import threading
import time
import urllib.parse

import websocket  # websocket-client

MA_URL = os.environ.get("MA_URL", "").rstrip("/")  # http://host:8095 (or set in Settings: configure())
MA_TOKEN_FILE = os.environ.get("MA_TOKEN_FILE", "")
ON = bool(MA_URL)


def configure(url, token_file):
    """Music Assistant's address and token file, from the house's settings: set, it is the music server; empty, Lyrion is."""
    global MA_URL, MA_TOKEN_FILE, ON, _client
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = "http://" + url
    if url and not url.split("//", 1)[1].count(":"):
        url += ":8095"
    if (url, token_file) != (MA_URL, MA_TOKEN_FILE):
        _client = None  # asked again with the new address or token
    MA_URL, MA_TOKEN_FILE, ON = url, token_file, bool(url)


class Client:
    """One connection, asks one at a time (a reply is matched by its message id; events in between are passed over)."""

    def __init__(self, url, token):
        self.url, self.token, self.ws, self.n = url, token, None, 0
        self.lock = threading.Lock()

    def _open(self):
        ws = websocket.create_connection(self.url.replace("http", "ws", 1) + "/ws", timeout=30)
        ws.recv()  # the server's hello
        self.ws = ws
        if self._ask("auth", token=self.token).get("error_code"):
            raise RuntimeError("Music Assistant refused the token")

    def _ask(self, command, **args):
        self.n += 1
        mid = str(self.n)
        self.ws.send(json.dumps({"message_id": mid, "command": command, "args": args}))
        while True:
            got = json.loads(self.ws.recv())
            if got.get("message_id") == mid:
                return got

    def call(self, command, **args):
        with self.lock:
            for attempt in (0, 1):
                try:
                    if not self.ws:
                        self._open()
                    got = self._ask(command, **args)
                    if got.get("error_code"):
                        raise RuntimeError(f"{command}: {got.get('details')}")
                    return got.get("result")
                except (websocket.WebSocketException, OSError):
                    self.ws = None
                    if attempt:
                        raise


_client = None


def check():
    """For Settings: (ok, what it says)."""
    try:
        info = client().call("info") or {}
        n = client().call("music/albums/count") or 0
        return True, f"Music Assistant {info.get('server_version', '')}, {n:,} albums"
    except Exception as e:
        msg = str(e)
        return False, "the token isn't accepted" if "token" in msg.lower() or "auth" in msg.lower() else f"not answering ({type(e).__name__})"


def client():
    global _client
    if _client is None:
        try:
            token = open(MA_TOKEN_FILE).read().strip() if MA_TOKEN_FILE else os.environ.get("MA_TOKEN", "")
        except OSError:
            token = ""
        _client = Client(MA_URL, token)
    return _client


# ───────────────────────── ids: songs get numbers of our own ─────────────────────────
_ids, _uris, _id_lock = {}, {}, threading.Lock()


def song_id(uri):
    with _id_lock:
        if uri not in _ids:
            _ids[uri] = len(_ids) + 1
            _uris[_ids[uri]] = uri
        return _ids[uri]


def picture(item, size=600):
    """An item's cover as an address the server's picture proxy can fetch: the service's own, else Music Assistant's
    image proxy (local files' covers)."""
    for im in (item.get("metadata") or {}).get("images") or []:
        if im.get("type") != "thumb":
            continue
        if im.get("remotely_accessible") and str(im.get("path", "")).startswith("http"):
            return im["path"]
        if im.get("proxy_id"):  # its image proxy, by the picture's own id (sizes: 0, 80, 160, 256, 512, 1024)
            return f"{MA_URL}/imageproxy/{im['proxy_id']}?size=1024"
        return f"{MA_URL}/imageproxy?" + urllib.parse.urlencode({"path": urllib.parse.quote(im.get("path", ""), safe=""), "provider": im.get("provider", ""), "size": 1024})
    return ""


def best_format(item):
    fmts = [m.get("audio_format") or {} for m in item.get("provider_mappings") or []]
    return max(fmts, key=lambda f: (f.get("bit_depth") or 0, f.get("sample_rate") or 0), default={})


def quality_words(f):
    if not f.get("sample_rate"):
        return ""
    return f"{f.get('bit_depth') or 16}/{float(f['sample_rate']) / 1000:g}"


def source_of(item):
    doms = {m.get("provider_domain") for m in item.get("provider_mappings") or []}
    return "local" if doms & {"filesystem_local", "filesystem_smb", "filesystem_nfs"} else (sorted(doms - {"library"}) or ["local"])[0]


def artist_names(item):
    return " & ".join(a.get("name", "") for a in item.get("artists") or [] if a.get("name"))


# ───────────────────────── the shelves ─────────────────────────
def library_rows():
    """Every album in Music Assistant's library as the shelves' rows: [id, title, artist, year, cover, rank, quality,
    artist id, genres, source, versions, when added], newest first (it gives the order, not the dates)."""
    albums, step = [], 500
    while True:
        got = client().call("music/albums/library_items", limit=step, offset=len(albums), order_by="timestamp_added_desc") or []
        albums += got
        if len(got) < step:
            break
    DEAD.clear()
    for a in albums:  # nothing playable (the service stopped streaming it): not on the shelves, but listed as gone
        if not any(m.get("available") for m in a.get("provider_mappings") or []):
            DEAD.append({"id": a["item_id"], "artist": (a.get("artists") or [{}])[0].get("name", ""), "title": a.get("name") or "",
                         "year": int(a.get("year") or 0), "art": picture(a), "source": source_of(a)})
    albums = [a for a in albums if any(m.get("available") for m in a.get("provider_mappings") or [])]
    rows = []
    for rank, a in enumerate(albums):
        first = (a.get("artists") or [{}])[0]  # the album's first artist, as Soundsquatch files albums
        rows.append([int(a["item_id"]), a.get("name") or "", first.get("name") or "", int(a.get("year") or 0), picture(a), rank,
                     quality_words(best_format(a)), int(first.get("item_id") or 0) if str(first.get("item_id", "")).isdigit() else 0,
                     [], source_of(a), [], 0])  # when added: Music Assistant says only the order (its rank)
    return rows


DEAD = []  # the library's albums with no playable copy left: the Gone list's


def drop_dead(item_id):
    """A dead album taken out of Music Assistant's library (once another edition has taken its place, or it is let go)."""
    client().call("music/library/remove_item", media_type="album", library_item_id=str(item_id))


def album_songs(album_id):
    return client().call("music/albums/album_tracks", item_id=str(album_id), provider_instance_id_or_domain="library") or []


# ───────────────────────── Lyrion's commands, answered ─────────────────────────
def _args(cmd):
    """Lyrion's tagged words (album_id:5) and the plain ones apart."""
    tagged, plain = {}, []
    for w in cmd:
        w = str(w)
        k, sep, v = w.partition(":")
        if sep and k.replace("_", "").isalpha() and not w.startswith("http"):
            tagged[k] = v
        else:
            plain.append(w)
    return tagged, plain


def _player(pid):
    return next((p for p in client().call("players/all") or [] if p.get("player_id") == pid), None)


def _track_row(item, index=None):
    """A queue item or an album song, as a status/titles row."""
    media = item.get("media_item") or item
    album = media.get("album") or {}
    f = best_format(media)
    row = {"id": song_id(media.get("uri") or ""), "title": media.get("name") or item.get("name") or "",
           "artist": artist_names(media), "album": album.get("name") or "", "duration": float(media.get("duration") or item.get("duration") or 0),
           "artwork_url": picture(media) or picture(album), "url": media.get("uri") or "", "album_id": album.get("item_id") or "",
           "tracknum": media.get("track_number") or "", "disc": media.get("disc_number") or "", "year": album.get("year") or "",
           "samplerate": str(int(f.get("sample_rate") or 0)), "samplesize": str(f.get("bit_depth") or ""), "type": f.get("content_type") or ""}
    if index is not None:
        row["playlist index"] = index
    return row


def artist_uris(names):
    """The library's artists by these names: their Music Assistant addresses (library://artist/N)."""
    out = []
    for n in names:
        got = client().call("music/search", search_query=n, media_types=["artist"], limit=5, library_only=True) or {}
        a = next((a for a in got.get("artists") or [] if _norm(a.get("name")) == _norm(n)), None)
        if a:
            out.append(a["uri"])
    return out


def radio(player, names):
    """A station from these artists: Music Assistant's radio mode plays them and carries on with more like them, and the
    room's own radio (its Don't Stop the Music) keeps it going when the queue ends."""
    uris = artist_uris(names)
    if not uris:
        return []
    client().call("player_queues/play_media", queue_id=player, media=uris, option="replace", radio_mode=True)
    client().call("player_queues/dont_stop_the_music", queue_id=player, dont_stop_the_music_enabled=True)
    return uris


def move_queue(src, dst):
    """What one room plays, handed to another (Music Assistant moves the whole queue and the place in it)."""
    client().call("player_queues/transfer", source_queue_id=src, target_queue_id=dst, auto_play=True)
    return {"ok": True}


def players():
    out = []
    for p in client().call("players/all") or []:
        if p.get("type") == "group" and not p.get("group_members"):
            continue
        out.append({"playerid": p["player_id"], "name": p.get("display_name") or p.get("name") or "", "connected": int(bool(p.get("available"))),
                    "power": int(bool(p.get("powered"))), "isplaying": int(p.get("state") == "playing"), "model": p.get("provider") or "",
                    "canpoweroff": 1, "isplayer": 1})
    return {"count": len(out), "players_loop": out}


def status(pid, start, count):
    p, q = _player(pid), client().call("player_queues/get", queue_id=pid) or {}
    if not p:
        return {}
    cur = q.get("current_index")
    st = {"mode": {"playing": "play", "paused": "pause"}.get(q.get("state") or p.get("state"), "stop"), "time": float(q.get("elapsed_time") or 0),
          "power": int(bool(p.get("powered"))), "mixer volume": int(p.get("volume_level") or 0), "player_name": p.get("display_name") or "",
          "playlist shuffle": int(bool(q.get("shuffle_enabled"))), "playlist repeat": {"off": 0, "one": 1, "all": 2}.get(q.get("repeat_mode"), 0),
          "playlist_tracks": int(q.get("items") or 0), "can_seek": 1}
    if cur is not None:
        st["playlist_cur_index"] = cur
    members = [m for m in p.get("group_members") or [] if m]
    if p.get("synced_to"):  # following another room: that room leads
        lead = _player(p["synced_to"]) or {}
        members = [p["synced_to"]] + [m for m in lead.get("group_members") or [] if m and m != p["synced_to"]]
    if len(members) > 1:
        st["sync_master"], st["sync_slaves"] = members[0], ",".join(members[1:])
    first = cur if start == "-" and cur is not None else int(start) if str(start).isdigit() else 0
    if st["playlist_tracks"]:
        items = client().call("player_queues/items", queue_id=pid, limit=max(1, int(count)), offset=first) or []
        st["playlist_loop"] = [_track_row(it, first + i) for i, it in enumerate(items)]
        if st["playlist_loop"] and cur is not None and first == cur:
            st["duration"] = st["playlist_loop"][0]["duration"]
    return st


def snapshot():
    """Every room's state and song in one ask (the listening log looks every couple of seconds): {room: (mode, uri)}."""
    out = {}
    for q in client().call("player_queues/all") or []:
        item = (q.get("current_item") or {}).get("media_item") or {}
        mode = {"playing": "play", "paused": "pause"}.get(q.get("state"), "stop")
        out[q["queue_id"]] = (mode, item.get("uri") or "" if mode != "stop" else "")
    return out


HEARD = None  # the listening log's ear, for the commands Soundsquatch itself sends (a skip, a new album)


def lms(pid, cmd):
    """One Lyrion command, answered from Music Assistant ({} where it has nothing like it)."""
    cmd = [str(c) for c in cmd]
    if not cmd:
        return {}
    if HEARD and pid and cmd[0] in ("playlist", "playlistcontrol") and len(cmd) > 1 and cmd[1] != "?" and cmd[1] not in ("shuffle", "repeat"):
        HEARD(pid, " ".join(cmd))  # heard as Lyrion's stream would tell it: "playlist index +1", "playlistcontrol cmd:load …"
    tagged, plain = _args(cmd)
    c = client()
    head = plain[0] if plain else ""
    try:
        if head == "players":
            return players()
        if head == "serverstatus":
            n = c.call("music/albums/count", favorite_only=False) or 0
            return {"lastscan": "0", "info total albums": n, "player count": players()["count"], "version": "Music Assistant"}
        if head == "status":
            return status(pid, plain[1] if len(plain) > 1 else "-", plain[2] if len(plain) > 2 else 1)
        if head == "titles" and tagged.get("album_id"):
            songs = album_songs(tagged["album_id"])
            return {"count": len(songs), "titles_loop": [_track_row(s) for s in songs]}
        if head == "playlistcontrol":
            how = {"load": "replace", "add": "add", "insert": "next"}.get(tagged.get("cmd"), "replace")
            if tagged.get("album_id"):
                media = f"library://album/{tagged['album_id']}"
            elif tagged.get("track_id"):  # one song, or several (track_id:1,2,3)
                media = [_uris[int(t)] for t in tagged["track_id"].split(",") if t.isdigit() and int(t) in _uris]
                if not media:
                    return {}
                media = media[0] if len(media) == 1 else media
            else:
                return {}
            c.call("player_queues/play_media", queue_id=pid, media=media, option=how)
            if how == "replace" and tagged.get("play_index", "0") not in ("", "0"):
                c.call("player_queues/play_index", queue_id=pid, index=int(tagged["play_index"]))
            return {"count": 1}
        if head == "playlist" and len(plain) > 1:
            what = plain[1]
            if what == "index" and len(plain) > 2:
                v = plain[2]
                if v in ("+1", "-1"):
                    c.call("player_queues/next" if v == "+1" else "player_queues/previous", queue_id=pid)
                else:
                    c.call("player_queues/play_index", queue_id=pid, index=int(v))
            elif what == "clear":
                c.call("player_queues/clear", queue_id=pid)
            elif what == "delete" and len(plain) > 2:
                c.call("player_queues/delete_item", queue_id=pid, item_id_or_index=int(plain[2]))
            elif what == "move" and len(plain) > 3:
                frm, to = int(plain[2]), int(plain[3])
                item = (c.call("player_queues/items", queue_id=pid, limit=1, offset=frm) or [{}])[0]
                if item.get("queue_item_id"):
                    c.call("player_queues/move_item", queue_id=pid, queue_item_id=item["queue_item_id"], pos_shift=to - frm)
            elif what == "repeat" and len(plain) > 2:
                c.call("player_queues/repeat", queue_id=pid, repeat_mode={"0": "off", "1": "one", "2": "all"}.get(plain[2], "off"))
            elif what == "shuffle":
                c.call("player_queues/shuffle", queue_id=pid, shuffle_enabled=(plain[2] if len(plain) > 2 else "1") != "0")
            return {}
        if head in ("play", "stop"):
            c.call(f"player_queues/{head}", queue_id=pid)
            return {}
        if head == "pause":
            c.call("player_queues/pause" if (plain[1] if len(plain) > 1 else "") == "1" else "player_queues/play_pause", queue_id=pid)
            return {}
        if head == "mixer" and len(plain) > 2 and plain[1] == "volume":
            v = plain[2]
            p = _player(pid) or {}
            level = int(p.get("volume_level") or 0) + int(v) if v[0] in "+-" else int(float(v))
            c.call("players/cmd/volume_set", player_id=pid, volume_level=max(0, min(100, level)))
            return {}
        if head == "playerpref" and len(plain) > 2 and "dontstopthemusic" in plain[1]:  # the room's radio: Music Assistant's own
            if plain[2] == "?":
                q = c.call("player_queues/get", queue_id=pid) or {}
                return {"_p2": "1" if q.get("dont_stop_the_music_enabled") else "0"}
            c.call("player_queues/dont_stop_the_music", queue_id=pid, dont_stop_the_music_enabled=plain[2] not in ("0", ""))
            return {}
        if head == "power" and len(plain) > 1 and plain[1] in ("0", "1"):
            c.call("players/cmd/power", player_id=pid, powered=plain[1] == "1")
            return {}
        if head == "sync" and len(plain) > 1:
            if plain[1] == "-":  # this room plays on its own again
                c.call("players/cmd/ungroup", player_id=pid)
            else:  # the room named joins this one
                c.call("players/cmd/set_members", target_player=pid, player_ids_to_add=[plain[1]])
            return {}
        if head == "time" and len(plain) > 1 and plain[1] != "?":
            c.call("player_queues/seek", queue_id=pid, position=int(float(plain[1])))
            return {}
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e} [{pid[:8]} {' '.join(cmd)}]"[:300]}
    return {}


# ───────────────────────── Music Assistant's own settings ─────────────────────────
# Its settings describe themselves (key, type, label, options, range, category, advanced, depends_on), so the app draws
# them as its own screens: the music sources, players, plugins and metadata providers, and the core's parts.
KINDS = {"music": "Music sources", "player": "Kinds of speaker", "plugin": "Plugins", "metadata": "Where pictures and stories come from", "audio_analysis": "Listening to the audio"}


def config_overview():
    """Everything that has settings, by kind: [{kind, title, items: [{id, name, enabled, status, error}]}]."""
    c = client()
    groups = {k: [] for k in KINDS}
    for p in c.call("config/providers") or []:
        groups.setdefault(p.get("type") or "other", []).append({"kind": "provider", "id": p["instance_id"], "domain": p.get("domain"),
                                                               "name": p.get("name") or p.get("default_name") or p.get("domain"),
                                                               "enabled": bool(p.get("enabled", True)), "error": p.get("last_error") or ""})
    players = [{"kind": "player", "id": p["player_id"], "name": p.get("name") or p.get("default_name") or p["player_id"], "provider": p.get("provider"),
                "enabled": bool(p.get("enabled", True))} for p in c.call("config/players") or []]
    core = [{"kind": "core", "id": x.get("domain"), "name": (x.get("domain") or "").replace("_", " ").capitalize()} for x in c.call("config/core") or []]
    out = [{"kind": k, "title": KINDS.get(k, k.replace("_", " ").capitalize()), "items": sorted(v, key=lambda x: x["name"].lower())} for k, v in groups.items() if v]
    out.insert(1, {"kind": "players", "title": "Rooms and speakers", "items": sorted(players, key=lambda x: x["name"].lower())})
    out.append({"kind": "core", "title": "Music Assistant itself", "items": core})
    return out


def _entries(full):
    vals = full.get("values") or {}
    rows = list(vals.values()) if isinstance(vals, dict) else list(vals)
    keep = ("key", "type", "label", "description", "value", "default_value", "options", "range", "required", "category", "advanced", "hidden",
            "depends_on", "depends_on_value", "multi_value", "action", "action_label", "help_link")
    return [{k: e.get(k) for k in keep} for e in rows if not e.get("hidden")]


def config_get(kind, ident):
    """One thing's settings: {kind, id, name, entries: [...]} (a secret's value is never sent: only whether it is set)."""
    c = client()
    if kind == "provider":
        full = c.call("config/providers/get", instance_id=ident)
    elif kind == "player":
        full = c.call("config/players/get", player_id=ident)
    elif kind == "core":
        full = c.call("config/core/get", domain=ident)
    else:
        return {"error": "unknown"}
    entries = _entries(full or {})
    for e in entries:
        if e["type"] == "secure_string":
            e["is_set"], e["value"], e["default_value"] = bool(e.get("value")), None, None
    name = (full or {}).get("name") or (full or {}).get("default_name") or ident
    return {"kind": kind, "id": ident, "name": name, "domain": (full or {}).get("domain") or (full or {}).get("provider") or "", "entries": entries}


def config_save(kind, ident, values):
    """Changed values saved (only the keys sent; a secret left empty keeps what it had)."""
    values = {k: v for k, v in (values or {}).items() if not (isinstance(v, str) and v == "" and k.endswith(("password", "token", "key", "secret")))}
    c = client()
    if kind == "provider":
        full = c.call("config/providers/get", instance_id=ident) or {}
        return c.call("config/providers/save", provider_domain=full.get("domain"), values=values, instance_id=ident)
    if kind == "player":
        return c.call("config/players/save", player_id=ident, values=values)
    if kind == "core":
        return c.call("config/core/save", domain=ident, values=values)
    raise ValueError("unknown")


def config_action(kind, ident, action, values=None):
    """An action button (Refresh Recommendations, say): Music Assistant runs it as it builds the settings again."""
    c = client()
    if kind == "provider":
        full = c.call("config/providers/get", instance_id=ident) or {}
        return c.call("config/providers/get_entries", provider_domain=full.get("domain"), instance_id=ident, action=action, values=values or {})
    if kind == "core":
        return c.call("config/core/get_entries", domain=ident, action=action, values=values or {})
    raise ValueError("unknown")


# ───────────────────────── beyond the shelves: Music Assistant's own search, as a streaming service ─────────────────────────
STREAMING_SKIP = {"library", "builtin", "ambient_sounds", "filesystem_local", "filesystem_smb", "filesystem_nfs", "radiobrowser", "tunein"}


def _norm(t):
    import re
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\s*[(\[].*$", "", (t or "").lower()).replace("&", "and"))


class Service:
    """Search, artists' releases, play, queue and add to the library, through Music Assistant itself: whatever services it
    has (Qobuz, Spotify, TIDAL, Plex, …) answer together, so Soundsquatch needs no plugin of its own for any of them.
    Its label is the first streaming service Music Assistant has (Qobuz, say); a search's results are kept for a while,
    so an ask by its number (play the 3rd) means the same release it showed."""
    key, scheme = "ma", "ma"

    def __init__(self):
        self.found = {}  # term → (when, albums)

    @property
    def label(self):
        names = [p.get("name") or p.get("domain") for p in client().call("providers") or []
                 if p.get("type") == "music" and p.get("domain") not in STREAMING_SKIP]
        return names[0] if names else "streaming"

    def available(self, can=None, player=""):
        return ON

    def _albums(self, term):
        import time as _t
        hit = self.found.get(term)
        if hit and _t.time() - hit[0] < 1800:
            return hit[1]
        got = client().call("music/search", search_query=term, media_types=["album"], limit=40) or {}
        albums = [a for a in got.get("albums") or [] if a.get("is_playable", True)]
        self.found[term] = (_t.time(), albums)
        return albums

    @staticmethod
    def _row(a):
        return ((a.get("artists") or [{}])[0].get("name", ""), a.get("name") or "", picture(a))

    def search(self, term, player=""):
        return [self._row(a) for a in self._albums(term)]

    def _streaming_artist(self, name):
        """The artist on a streaming service (through the library's link to it, or the search's own), as (item_id, provider)."""
        got = client().call("music/search", search_query=name, media_types=["artist"], limit=10) or {}
        for a in got.get("artists") or []:
            if _norm(a.get("name")) != _norm(name):
                continue
            if a.get("provider") not in ("library",) and (a.get("provider") or "").split("--")[0] not in STREAMING_SKIP:
                return a["item_id"], a["provider"], a
            for m in a.get("provider_mappings") or []:
                if m.get("provider_domain") not in STREAMING_SKIP:
                    return m["item_id"], m["provider_instance"], a
        return None, None, None

    def _releases(self, name):
        aid, prov, art = self._streaming_artist(name)
        if not aid:
            return None, []
        al = client().call("music/artists/artist_albums", item_id=aid, provider_instance_id_or_domain=prov, in_library_only=False) or []
        kind = {"album": "Albums", "single": "Singles & EPs", "ep": "Singles & EPs", "compilation": "Compilations", "live": "Live"}
        rels = [{"group": kind.get(a.get("album_type"), "Albums"), "artist": (a.get("artists") or [{}])[0].get("name", name), "album": a.get("name") or "",
                 "cover": picture(a), "year": a.get("year") or 0, "_a": a} for a in al]
        return art, rels

    def sheet(self, name, player=""):
        art, rels = self._releases(name)
        if not art:
            return {"error": "no such artist on " + self.label}
        return {"name": art.get("name") or name, "bio": "", "photo": picture(art), "heard": {},
                "releases": [dict({k: v for k, v in r.items() if k != "_a"}, i=i) for i, r in enumerate(rels)], "similar": []}

    def _pick(self, req):
        term, i = (req.get("term") or "").strip()[:120], int(req.get("index") or 0)
        if (req.get("action") or "").startswith("a"):
            rels = self._releases(term)[1]
            r = next((r for r in rels if r["album"] == req.get("album")), None) or (rels[i] if i < len(rels) else None)
            return r["_a"] if r else None
        found = self._albums(term)
        return found[i] if i < len(found) else None

    def _play(self, player, media, how, start=None):
        client().call("player_queues/play_media", queue_id=player, media=media, option=how)
        if start:
            client().call("player_queues/play_index", queue_id=player, index=int(start))

    def keep(self, album):
        """An album added to Music Assistant's library (with 2-way sync on, to the service's favourites too)."""
        if album.get("provider") == "library" or any(m.get("in_library") for m in album.get("provider_mappings") or []):
            return "already"
        client().call("music/library/add_item", item=album)
        return "added"

    def act(self, req, player):
        action = req.get("action")
        if action == "search":
            got = client().call("music/search", search_query=req.get("term"), media_types=["artist"], limit=12) or {}
            return {"releases": [{"i": i, "artist": a, "album": t, "cover": c} for i, (a, t, c) in enumerate(self.search(req.get("term")))],
                    "artists": [{"name": x.get("name"), "image": picture(x)} for x in got.get("artists") or [] if x.get("name")]}
        album = self._pick(req)
        if not album:
            return {"error": f"{self.label} no longer lists that release"}
        name, artist = album.get("name") or "", (album.get("artists") or [{}])[0].get("name", "")
        verb = action[1:] if action in ("aplay", "aqueue", "akeep") else action
        if verb in ("play", "queue"):
            self._play(player, album["uri"], "replace" if verb == "play" else "add")
            return {"result": "playing" if verb == "play" else "queued", "album": name, "artist": artist}
        if verb == "keep":
            return {"result": self.keep(album), "album": name, "artist": artist, "year": album.get("year") or 0, "cover": picture(album)}
        return {"error": "unknown command"}

    def release(self, artist, title, want, player=""):
        term = f"{artist} {title}".strip()[:120]
        found = self._albums(term)
        fit = lambda a: (_norm(a.get("name")) == _norm(title)) * (2 if not artist or _norm((a.get("artists") or [{}])[0].get("name")) == _norm(artist) else 1)
        best = max(range(len(found)), key=lambda n: fit(found[n]), default=None)
        if best is None or not fit(found[best]):
            return None
        a = found[best]
        songs = client().call("music/albums/album_tracks", item_id=a["item_id"], provider_instance_id_or_domain=a["provider"]) or []
        secs = sum(int(s.get("duration") or 0) for s in songs)
        return {"artist": (a.get("artists") or [{}])[0].get("name", artist), "album": a.get("name") or title, "cover": picture(a), "term": term, "i": best,
                "details": {"length": f"{secs // 3600}:{secs % 3600 // 60:02d}:{secs % 60:02d}" if secs else ""},
                "tracks": [{"n": s.get("track_number") or n + 1, "title": s.get("name") or "", "k": n} for n, s in enumerate(songs)],
                "year": a.get("year") or "", "kept": a.get("provider") == "library" or any(m.get("in_library") for m in a.get("provider_mappings") or [])}

    def play_release(self, term, i, track, how, player):
        found = self._albums(term)
        if i >= len(found):
            return {"error": f"{self.label} no longer lists that release"}
        self._play(player, found[i]["uri"], "replace" if how == "play" else "next" if how == "insert" else "add", track)
        return {"result": "playing"}

    def album_of_uri(self, uri):
        t = client().call("music/item_by_uri", uri=uri) or {}
        return t.get("album") or {}

    def keep_track(self, player, url):
        album = self.album_of_uri(url)
        if not album:
            return {"error": "Music Assistant didn't say which album that is from"}
        full = client().call("music/item_by_uri", uri=album.get("uri")) or album
        return {"album": full.get("name") or "", "artist": (full.get("artists") or [{}])[0].get("name", ""), "result": self.keep(full), "cover": picture(full)}

    def unkeep_track(self, player, url):
        album = self.album_of_uri(url)
        lib = next((m for m in album.get("provider_mappings") or [] if m.get("provider_domain") == "library"), None)
        if album.get("provider") == "library" or lib:
            client().call("music/library/remove_item", media_type="album", library_item_id=album.get("item_id") if album.get("provider") == "library" else lib["item_id"])
            return True
        return False

    def link(self, player, url):
        album = self.album_of_uri(url)
        return next((m.get("url") for m in album.get("provider_mappings") or [] if m.get("url")), "")


SERVICE = Service()


def browse(path=None):
    """One level of Music Assistant's browse tree (each source's own: Qobuz's Artists, Albums, Playlists…): [{name, kind,
    path, uri, image, sub}], the way back ("..") left out."""
    out = []
    for x in client().call("music/browse", path=path or None) or []:
        if x.get("name") == ".." or x.get("path") == "root":
            continue
        kind = x.get("media_type") or "folder"
        sub = artist_names(x) if kind in ("album", "track") else (x.get("owner") or "") if kind == "playlist" else ""
        out.append({"name": x.get("name") or "", "kind": kind, "path": x.get("path") or "", "uri": x.get("uri") or "", "image": picture(x), "sub": sub,
                    "year": x.get("year") or 0})
    return out


def play_uri(player, uri, how="play"):
    """Anything Music Assistant can play (a song, a playlist, a radio station), played, next, or at the end."""
    client().call("player_queues/play_media", queue_id=player, media=uri, option={"play": "replace", "next": "next", "add": "add"}.get(how, "replace"))
    return {"ok": True}


if __name__ == "__main__":  # a look from the command line: python3 backend_ma.py
    rows = library_rows()
    print(len(rows), "albums; newest:", [r[1:4] + [r[6], r[9]] for r in rows[:3]])
    print([(p["name"], p["isplaying"]) for p in players()["players_loop"]])
