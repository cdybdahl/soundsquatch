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

MA_URL = os.environ.get("MA_URL", "").rstrip("/")  # http://host:8095
MA_TOKEN_FILE = os.environ.get("MA_TOKEN_FILE", "")
ON = bool(MA_URL)


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


def client():
    global _client
    if _client is None:
        token = open(MA_TOKEN_FILE).read().strip() if MA_TOKEN_FILE else os.environ.get("MA_TOKEN", "")
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
    albums = [a for a in albums if any(m.get("available") for m in a.get("provider_mappings") or [])]  # nothing playable: not on the shelves
    rows = []
    for rank, a in enumerate(albums):
        first = (a.get("artists") or [{}])[0]  # the album's first artist, as Soundsquatch files albums
        rows.append([int(a["item_id"]), a.get("name") or "", first.get("name") or "", int(a.get("year") or 0), picture(a), rank,
                     quality_words(best_format(a)), int(first.get("item_id") or 0) if str(first.get("item_id", "")).isdigit() else 0,
                     [], source_of(a), [], 0])  # when added: Music Assistant says only the order (its rank)
    return rows


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
    first = cur if start == "-" and cur is not None else int(start) if str(start).isdigit() else 0
    if st["playlist_tracks"]:
        items = client().call("player_queues/items", queue_id=pid, limit=max(1, int(count)), offset=first) or []
        st["playlist_loop"] = [_track_row(it, first + i) for i, it in enumerate(items)]
        if st["playlist_loop"] and cur is not None and first == cur:
            st["duration"] = st["playlist_loop"][0]["duration"]
    return st


def lms(pid, cmd):
    """One Lyrion command, answered from Music Assistant ({} where it has nothing like it)."""
    cmd = [str(c) for c in cmd]
    if not cmd:
        return {}
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
            elif tagged.get("track_id") and int(tagged["track_id"]) in _uris:
                media = _uris[int(tagged["track_id"])]
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
        if head == "time" and len(plain) > 1 and plain[1] != "?":
            c.call("player_queues/seek", queue_id=pid, position=int(float(plain[1])))
            return {}
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e} [{pid[:8]} {' '.join(cmd)}]"[:300]}
    return {}


if __name__ == "__main__":  # a look from the command line: python3 backend_ma.py
    rows = library_rows()
    print(len(rows), "albums; newest:", [r[1:4] + [r[6], r[9]] for r in rows[:3]])
    print([(p["name"], p["isplaying"]) for p in players()["players_loop"]])
