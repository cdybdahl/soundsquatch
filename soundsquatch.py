#!/usr/bin/env python3
"""Soundsquatch: the iPad's music app, served from sasquatch-server beside Lyrion, which stays the player and the library.

Runs in its container (Dockerfile; its data in SOUNDSQUATCH_DATA), with lms_qobuz.py, lms_keep_album.py and
library.py, whose helpers it uses. One address serves:

  GET  /                     the app (app/index.html; app.js and app.css stamped with their fingerprints, so a change reloads)
  POST /jsonrpc.js           Lyrion's own JSON-RPC, passed through: playing, the queue, volume, status, searching the library
  GET  /music/…, /imageproxy/…   Lyrion's covers, passed through
  GET  /img?u=URL            a picture from Qobuz, Wikipedia or Discogs, fetched once and kept (IMG_CACHE): the iPad
                             never asks those sites itself, and the page may read its colours
  GET  /api/library          every album (the best copy of each, as library.py dedupes them) with the house's
                             genres, and every album artist with their picture when the crawler has one
  GET  /api/artist?name=     an artist's profile (below); one never fetched is fetched there and then, Qobuz first, the
                             rest following ("partial": true until it has)
  GET  /api/album?id=        an album's tracks and review (Wikipedia's, through Music & Artist Information)
  GET  /api/story?name=      an artist's longer story (Wikipedia, through Music & Artist Information)
  GET  /api/home             what the Discover page is built from: the log's rotation, rediscoveries, the artist of the
                             day, connections between artists on the shelves, artists beyond them
  POST /api/qobuz            {action, term, player, index}: lms_qobuz.py's search, play, queue and keep, and aplay, aqueue
                             and akeep for an artist's releases
  GET  /api/crawl            how far the crawler has got

The crawler keeps a profile of every album artist on the shelves and of whatever any room plays (it looks every 20 s,
the next few in each queue included), in cache.db, a month at a time:

  qobuz   Qobuz's short biography, picture, releases (only the artist's own: lms_qobuz.py asks MusicBrainz) and similar artists
  mb      MusicBrainz: group or person, where from, active years, genres, and their relations (members, bands, projects)
  wiki    Wikipedia's summary and portrait (through Wikidata, from MusicBrainz's link to it)
  photos  Discogs's photographs (through Music & Artist Information)

What leaves the house: artist names and album titles, asked of Qobuz (through Lyrion's plugin, as the Music page already
does), MusicBrainz, Wikidata/Wikipedia and Discogs. Nothing about who listens or when.

Standard library only (Python 3.10 on the server).
"""
import gzip
import hashlib
import hmac
import io
import json
import os
import random
import re
import socket
import sqlite3
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("SOUNDSQUATCH_DATA", HERE)  # what it keeps: beside the script on a plain install, a volume in Docker
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("MB_CACHE", os.path.join(DATA, "mb"))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, "vendor"))  # mutagen, for genre tags (install.sh puts it there)
import lms_keep_album  # noqa: E402
import lms_qobuz  # noqa: E402
import streaming  # noqa: E402
from library import copies, quality  # noqa: E402
import genres as house_genres  # noqa: E402
import turntable  # noqa: E402
from PIL import Image  # noqa: E402  (python3-pil, already on the server)

LMS = os.environ.get("LMS_URL", "http://127.0.0.1:9000")  # where it looks first; found on the network when not there (find_lms)
BIND = os.environ.get("MUSIC_APP_BIND", "0.0.0.0")
PORT = int(os.environ.get("MUSIC_APP_PORT", "8097"))
APP = os.path.join(HERE, "app")
DB = os.environ.get("MUSIC_APP_DB", os.path.join(DATA, "cache.db"))
IMG_CACHE = os.environ.get("IMG_CACHE", os.path.join(DATA, "img"))
ART_KEPT = os.path.join(DATA, "art-originals")
ARTIST_PICS = os.path.join(DATA, "artist-photos")  # pictures of artists sent from the house's own devices
chosen_photos = {}  # artist key → the picture chosen for them by hand: {"url": one of theirs} or {"file": one sent}  # the pictures albums carried before a new cover replaced them, to put back
IMG_CAP = 2 * 1024 ** 3  # bytes of pictures kept; the least recently used go first
COVERS = os.environ.get("COVER_CACHE", os.path.join(DATA, "covers"))  # every album's cover, at each size the app asks for
COVER_SIZES = (150, 300, 600, 800, 1600)  # 1600 for the full-width cover spreads, fetched on its own
PICTURE_WIDTHS = (160, 320, 640, 1600)  # what /img shrinks pictures to: faces, cards, the spotlight, heroes
LOG_DB = os.environ.get("LISTENING_DB", os.path.join(DATA, "listening.db"))
PLAYER = os.environ.get("QOBUZ_PLAYER", "")  # the player the Qobuz plugin answers on behalf of (any will do; read_music_dirs finds one)
STALE = 30 * 86400  # a profile is fetched again after a month
RETRY = 86400  # a profile missing a part tries for it again after a day
PICTURE_HOSTS = ("archive.org", "static.qobuz.com", "upload.wikimedia.org", "thumb.wikimedia.org", "i.discogs.com", "img.discogs.com", "coverartarchive.org",
                 "is1-ssl.mzstatic.com", "is2-ssl.mzstatic.com", "is3-ssl.mzstatic.com", "is4-ssl.mzstatic.com", "is5-ssl.mzstatic.com",  # Apple's covers
                 "cdn-images.dzcdn.net", "e-cdns-images.dzcdn.net",  # Deezer's
                 "resources.tidal.com")  # TIDAL's
LRCLIB = "https://lrclib.net/api/"  # lyrics, synced where it has them; free and keyless
MUSIC_DIRS = ["/share/music"]  # Lyrion's media folders, as Lyrion has them (asked with each look at the library)
CAPTURE_DIR = os.environ.get("CAPTURE_DIR", "")  # the turntable's songs, one folder a record (default: "From vinyl" in the music folder, so the library has them)
TURNTABLE_PORT = int(os.environ.get("TURNTABLE_PORT", "8095"))  # where the listener on the Pi sends the record-out
REMOVED_DIR = os.environ.get("REMOVED_DIR", "/share/music-removed")  # where removed albums' files go: outside the scan, never deleted
HA_URL = os.environ.get("HA_URL", "")
DISCOGS_TOKEN = os.path.join(DATA, ".discogs_token")  # the house's Discogs token, for its record collection: never sent back
HA_TOKEN = os.environ.get("HA_TOKEN_FILE", os.path.join(DATA, ".ha_token"))  # Soundsquatch's own long-lived token (stations)
AUDIO = (".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".aif", ".aiff", ".alac", ".ape", ".wv", ".dsf", ".dff")  # the playlist a room's music is saved to on its way to another room
VERSION = "0.12.0 beta"  # the release tag is v + its number
AGENT = {"User-Agent": f"Soundsquatch/{VERSION.split()[0]} (a home music app; https://github.com/cdybdahl/soundsquatch)"}
NOT_ARTISTS = {"various artists", "various", "unknown artist", "unknown", ""}

# ───────────────────────── settings: settings.json beside the script, today's values the defaults ─────────────────────────
SETTINGS_FILE = os.environ.get("SETTINGS_FILE", os.path.join(DATA, "settings.json"))
DISCOVER_SECTIONS = ["cover", "stations", "because", "rotation", "back", "new", "spotlight", "fresh", "rediscover", "loved", "archive", "listenlater", "lbfresh", "pitchfork", "connections", "beyond", "round", "decade", "genre", "vinyl"]
DEFAULTS = {
    "connections": {"lms_url": LMS, "ha_url": HA_URL, "listening_db": LOG_DB, "lms_user": "", "lms_password": ""},  # a login only for a Lyrion that asks for one
    "features": {"home_assistant": bool(HA_URL), "stations": True, "archive": True, "history": True, "credits": True, "lyrics": True,
                 "write_files": False,  # changing music files (genres, titles, covers, removing): off until the house says so
                 "turntable_capture": False,  # each song the turntable plays kept as a file (in CAPTURE_DIR, outside the library)
                 "prefer_captured": True},  # an album with a take from the turntable shows and spins that take first
    "discover": {k: True for k in DISCOVER_SECTIONS},
    "house": {"rooms": {}, "pin": "", "discover_order": [], "turntable_lid": "", "turntable_room": "", "scrobble_url": ""},  # scrobble_url: a ListenBrainz-style API the plays go to ("" none)  # turntable_lid: Home Assistant's sensor, on (open) while a record plays  # rooms: player id → {"name": the app's own, "fixed": volume set on the device}; pin: a hash
}
settings = json.loads(json.dumps(DEFAULTS))
NEEDS = {"archive": "archive", "stations": "radio"}  # a feature that needs a Lyrion plugin, by HAVE's name for it
HAVE = {}  # what this Lyrion has (detect): qobuz, archive, mai (Music & Artist Information), radio (Don't Stop the Music with LastMix),
# listenlater (Listen Later's add), ll_shelf, lbf, pfr (Listen Later's, ListenBrainz Fresh Releases' and Pitchfork Reviews' home shelves)


ERRORS = deque(maxlen=25)  # the last things that went wrong, for the diagnostics a tester sends


def note_error(text):
    crawl_state["last_error"] = text
    ERRORS.append(time.strftime("%Y-%m-%d %H:%M ") + text)
    print("error: " + text, flush=True)  # and in the container's log


LMS_LOGIN = urllib.request.HTTPPasswordMgrWithPriorAuth()  # Lyrion's username and password, when it asks for them
urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(LMS_LOGIN)))


def cli_login():
    """The line a Lyrion that asks for a password wants first on its command line, else none."""
    c = settings["connections"]
    return f"login {urllib.parse.quote(c['lms_user'])} {urllib.parse.quote(c['lms_password'])}\n".encode() if c.get("lms_user") else b""


def feature(name):
    """A feature at work: switched on for the house, and its plugin there (as far as is known)."""
    return bool(settings["features"].get(name)) and HAVE.get(NEEDS.get(name, ""), True) is not False


def detect():
    """The Lyrion plugins Soundsquatch leans on, each asked whether it answers; what is missing is left out (the app hides
    it, the crawler doesn't ask it). Also Lyrion's language: the Qobuz plugin's menus are read by position where they can
    be, but keeping and removing Qobuz albums still finds its menu items by their English names."""
    def can(*cmd):
        return bool(int(rpc("", "can", *cmd, "?", timeout=5).get("_can") or 0))

    def plugin(name):
        return rpc("", "pref", f"plugin.state:{name}", "?", timeout=5).get("_p2") == "enabled"
    try:
        # CrystalGipsy's plugins: their Material home shelves (flat, playable by item id) and Listen Later's own add command
        HAVE.update(listenlater=can("listenlater", "add"), ll_shelf=can("LLHome", "items"), lbf=can("LBFForYou", "items"),
                    pfr=can("PFRBnm", "items"), ratings=can("ratingslight", "ratealbum"))  # Ratings Light 3.2 on: track ratings are Lyrion's
        HAVE.update(**{x.key: bool(x.available(can)) for x in streaming.ALL})
        HAVE.update(qobuz=can("qobuz", "items"), archive=can("archivelma", "items"), mai=can("musicartistinfo", "biography"),
                    radio=plugin("DontStopTheMusic") and plugin("LastMix"), language=rpc("", "pref", "language", "?", timeout=5).get("_p2") or "EN",
                    mai_lang=rpc("", "pref", "plugin.musicartistinfo:preferredLanguage", "?", timeout=5).get("_p2") or "")
    except Exception:
        pass  # Lyrion not answering: as it was
    if svc():
        qobuz_arrived()
    return HAVE


def svc():
    """The streaming service Lyrion has a plugin for (Qobuz first, when it has both), or None."""
    return next((x for x in streaming.ALL if HAVE.get(x.key)), None)


def qobuz_arrived():
    """Profiles built while there was no Qobuz kept an empty Qobuz part, and kept it for a month: once Qobuz answers,
    those parts are dropped so the crawler fetches them (an artist page shows Qobuz's albums within the hour, not next month)."""
    stale = [k for k, (d, f, comp) in list(profiles.items()) if d is not None and d.get("qobuz") == {}]
    if not stale:
        return
    with db_lock, db() as c:
        for k in stale:
            d, f, comp = profiles[k]
            d = {p: v for p, v in d.items() if p != "qobuz"}
            d.get("_tried", {}).pop("qobuz", None)
            profiles[k] = (d, f, 0)
            c.execute("update artists set data = ?, complete = 0 where k = ?", (json.dumps(d, ensure_ascii=False), k))
    payload["version"] += 1


def find_lms():
    """Lyrion on the network, found as its players find it: a discovery broadcast on port 3483, answered with its web
    port (the reply's JSON field). The address, or None."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(3)
        s.sendto(b"eJSON\0", ("255.255.255.255", 3483))
        data, (ip, _) = s.recvfrom(1024)
        i, port = 1, "9000"
        while i + 5 <= len(data):
            tag, n = data[i:i + 4], data[i + 4]
            if tag == b"JSON":
                port = data[i + 5:i + 5 + n].decode() or port
            i += 5 + n
        return f"http://{ip}:{port}"
    except OSError:
        return None
    finally:
        s.close()


def reach_lms():
    """At the start: Lyrion where the settings say, else where it is found; a found address is kept in the settings. An
    address the house set itself (in Settings, or LMS_URL) is kept even when Lyrion isn't answering there (it may only be starting)."""
    try:
        rpc("", "serverstatus", "0", "0", timeout=5)
        return
    except urllib.error.HTTPError:
        return  # it's there (asking for a password, say): the first screen asks for what it wants
    except Exception:
        pass
    if settings.get("found_by_hand") or os.environ.get("LMS_URL"):
        return  # an address the house gave (here or in compose's LMS_URL): Lyrion may only be starting, as it is after a reboot
    found = find_lms()
    if found and found != LMS:
        save_settings({"connections": {"lms_url": found}, "found": True})


RECORDER = {"built_in": False}


def start_recorder():
    """The listening log: when a recorder of the house's own is keeping one (its database written in the last two days),
    Soundsquatch reads that; otherwise it records one itself (listening.py, beside it), with no steward."""
    global LOG_DB
    try:
        if os.path.exists(LOG_DB) and time.time() - os.path.getmtime(LOG_DB) < 2 * 86400 and os.path.abspath(LOG_DB) != os.path.join(DATA, "listening.db"):
            return
    except OSError:
        pass
    LOG_DB = os.path.join(DATA, "listening.db")
    host = urllib.parse.urlparse(LMS).hostname or "127.0.0.1"
    os.environ.update(LISTENING_DB=LOG_DB, LMS_HOST=host, LMS_WEB_PORT=str(urllib.parse.urlparse(LMS).port or 9000), LMS_CLI_PORT=str(cli_port()), STEWARD_PLAYERS="")
    import listening
    threading.Thread(target=listening.listen, name="recorder", daemon=True).start()
    threading.Thread(target=listening.settling, name="recorder-settle", daemon=True).start()
    RECORDER["built_in"] = True


def apply_settings():
    """The settings put to work: the module's own values (read where they are used, so nothing needs restarting)."""
    global LMS, HA_URL, LOG_DB
    c = settings["connections"]
    LMS, HA_URL, LOG_DB = c["lms_url"].rstrip("/"), c["ha_url"].rstrip("/"), c["listening_db"]
    lms_keep_album.LMS = LMS + "/jsonrpc.js"  # the Qobuz and keeping helpers talk to Lyrion through it
    if c.get("lms_user"):  # every request to Lyrion carries the login (urllib's opener, for this address only)
        LMS_LOGIN.add_password(None, LMS, c["lms_user"], c["lms_password"], is_authenticated=True)
    os.environ["LMS_LOGIN"] = cli_login().decode()  # the recorder's event line logs in too


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    for group, values in DEFAULTS.items():
        settings[group] = dict(values, **{k: v for k, v in (saved.get(group) or {}).items() if k in values})
    settings["found_by_hand"] = bool(saved.get("found_by_hand", "connections" in saved))  # settings from before it was noted: set by hand
    apply_settings()
    read_music_dirs()


def check_settings():
    """What each connection finds, for the Settings page; and what Soundsquatch has worked out for itself."""
    out = {}
    try:
        st = rpc("", "serverstatus", "0", "0", timeout=5)
        out["lms_url"] = f"Lyrion {st.get('version', '')}, {st.get('info total albums', 0)} albums"
        out["lms_ok"] = True
    except urllib.error.HTTPError as e:
        out["lms_url"] = "asks for a username and password" if e.code == 401 else f"not answering (HTTP {e.code})"
        out["lms_auth"] = e.code == 401
    except Exception as e:
        out["lms_url"] = f"not answering ({type(e).__name__})"
    try:
        if not settings["features"]["home_assistant"] or not HA_URL:
            raise RuntimeError("off")
        with open(HA_TOKEN) as f:
            token = f.read().strip()
        req = urllib.request.Request(HA_URL + "/api/", headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=5) as r:
            out["ha_url"] = "connected" if r.status == 200 else f"HTTP {r.status}"
            out["ha_ok"] = r.status == 200
    except RuntimeError:
        out["ha_url"] = "switched off"
    except OSError as e:
        out["ha_url"] = "no token yet: stations need one" if isinstance(e, FileNotFoundError) else f"not connected ({type(e).__name__})"
    out["listening_db"] = "Soundsquatch is keeping it itself" if RECORDER["built_in"] else "found: the house's own recorder keeps it" if os.path.exists(LOG_DB) else "not found"
    out["listening_ok"] = os.path.exists(LOG_DB)
    read_music_dirs()
    out["music_dirs"] = ", ".join(MUSIC_DIRS)
    out["removed_dir"] = REMOVED_DIR
    if out.get("lms_ok"):
        detect()
    return out


def home_room():
    """The room this house plays in most (the log's last month), for a screen that hasn't chosen one."""
    try:
        c = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        row = c.execute("select player from plays where started > ? group by player order by count(*) desc limit 1", (time.time() - 30 * 86400,)).fetchone()
        c.close()
        return row[0] if row else ""
    except Exception:
        return ""


UPDATE = {}  # the newest release on GitHub, if it's newer than this one: asked once a day


def update_loop():
    while True:
        try:
            r = get_json("https://api.github.com/repos/cdybdahl/soundsquatch/releases/latest")
            num = lambda v: tuple(int(x) for x in re.findall(r"\d+", v))
            UPDATE.clear()
            if num(r["tag_name"]) > num(VERSION.split()[0]):
                UPDATE.update(version=r["tag_name"].lstrip("v"), url=r["html_url"])
        except Exception:
            pass  # offline, or no release yet: asked again tomorrow
        time.sleep(86400)


# ───────────────────────── the records on the shelf: the house's Discogs collection ─────────────────────────
DISCOGS = "https://api.discogs.com"
discogs_now = threading.Event()  # set when a token is saved: read the collection now, not tomorrow


def discogs_token():
    try:
        with open(DISCOGS_TOKEN) as f:
            return f.read().strip()
    except OSError:
        return ""


def discogs_get(path, token):
    req = urllib.request.Request(DISCOGS + path, headers=dict(AGENT, Authorization="Discogs token=" + token, Accept="application/json"))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def discogs_sync():
    """The collection, every folder, a page of 100 at a time (Discogs allows 60 asks a minute): kept as the house's
    physical records, [release id, title, artist, year, cover, format, label and number, when added, {details}]."""
    token = discogs_token()
    if not token:
        kv_set("discogs", {})
        return
    try:
        user = discogs_get("/oauth/identity", token)["username"]
        recs, page, seen = [], 1, set()
        while True:
            got = discogs_get(f"/users/{urllib.parse.quote(user)}/collection/folders/0/releases?per_page=100&page={page}&sort=added&sort_order=desc", token)
            for r in got.get("releases", []):
                b = r.get("basic_information") or {}
                if b.get("id") in seen:
                    continue  # a second copy of the same pressing
                seen.add(b.get("id"))
                fmt = (b.get("formats") or [{}])[0]
                words = " ".join([fmt.get("name") or ""] + [d for d in fmt.get("descriptions") or [] if d in ("LP", "EP", '7"', '10"', '12"', "Single", "Album", "Compilation", "Mini-Album")][:2])
                if fmt.get("qty") and str(fmt["qty"]) not in ("", "1"):
                    words = f"{fmt['qty']}× " + words
                label = (b.get("labels") or [{}])[0]
                artist = ", ".join(re.sub(r" \(\d+\)$", "", a.get("name") or "") for a in b.get("artists") or [] if a.get("name")) or "Various"
                descs = [d for f in b.get("formats") or [] for d in f.get("descriptions") or []]
                recs.append([b.get("id"), b.get("title") or "", artist, int(b.get("year") or 0), b.get("cover_image") or b.get("thumb") or "",
                             words.strip(), " ".join(x for x in (label.get("name"), label.get("catno")) if x and x != "none"), (r.get("date_added") or "")[:10],
                             {"g": b.get("genres") or [], "s": b.get("styles") or [], "d": descs, "t": ", ".join(f.get("text") or "" for f in b.get("formats") or [] if f.get("text")),
                              "box": any(f.get("name") == "Box Set" for f in b.get("formats") or []), "r": r.get("rating") or 0,
                              "i": r.get("instance_id"), "f": r.get("folder_id"), "ln": label.get("name") or "", "n": {str(n.get("field_id")): n.get("value") for n in r.get("notes") or []}}])
            if page >= (got.get("pagination") or {}).get("pages", 1):
                break
            page += 1
            time.sleep(1.2)
        fields = [{"id": f.get("id"), "name": f.get("name") or ""} for f in discogs_get(f"/users/{urllib.parse.quote(user)}/collection/fields", token).get("fields") or []]
        kv_set("discogs", {"user": user, "at": int(time.time()), "records": recs, "fields": fields})
        payload["version"] += 1  # the shelves' payload carries them
    except urllib.error.HTTPError as e:
        kv_set("discogs", dict(kv_get("discogs", {}) or {}, error="the token wasn't accepted" if e.code == 401 else f"Discogs answered {e.code}"))
    except Exception as e:
        note_error(f"discogs: {e}")


def discogs_loop():
    while True:
        discogs_sync()
        discogs_now.wait(86400)
        discogs_now.clear()


# ───────────────────────── scrobbles: what the house plays, sent on to a scrobble server of its choosing ─────────────────────────
# Any server that takes ListenBrainz's API: ListenBrainz itself, or one of the house's own (Maloja, Koito). Each play the
# listening log writes is sent once it counts as a listen by last.fm's rule (half the track or four minutes, and the
# track at least 30 seconds long). The first time, everything the log already holds goes too.
SCROBBLE_TOKEN = os.path.join(DATA, ".scrobble_token")  # the server's token for Soundsquatch: never sent back
scrobble_now = threading.Event()  # set when the address or token changes: send now, not in a minute
scrobble_lock = threading.Lock()


def scrobble_token():
    try:
        with open(SCROBBLE_TOKEN) as f:
            return f.read().strip()
    except OSError:
        return ""


def scrobble_base():
    """The API's address as given ("…/apis/listenbrainz" for Maloja, "https://api.listenbrainz.org"), without a closing /1."""
    return re.sub(r"/1$", "", (settings["house"].get("scrobble_url") or "").strip().rstrip("/"))


def scrobble_call(method, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(AGENT, Authorization="token " + token)  # lower case: Maloja wants it so, and ListenBrainz doesn't mind
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(scrobble_base() + "/1/" + method, data, headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def scrobble_counts(played, duration):
    if duration:
        return duration >= 30 and played >= min(240, duration / 2)
    return played >= 240  # length unknown: four minutes heard


def scrobble_pass():
    """Send what the log has written since the last pass, oldest first. A server that turns one away stops the pass
    where it is, so nothing is skipped; a play at a second the server already has goes a second later (two rooms)."""
    token, base = scrobble_token(), scrobble_base()
    if not token or not base:
        return
    with scrobble_lock:
        st = kv_get("scrobble", {}) or {}
        if st.get("log") != os.path.abspath(LOG_DB) or st.get("base") != base:
            st = {"log": os.path.abspath(LOG_DB), "base": base, "cursor": 0, "sent": 0, "since": time.time()}  # a new server (or log): all of it
        if st["cursor"] == 0 or st.get("error"):  # a new server, or one that failed: is the token good? (ListenBrainz answers 200 either way)
            try:
                if not scrobble_call("validate-token", token).get("valid", True):
                    raise urllib.error.HTTPError(base, 401, "invalid token", None, None)
            except urllib.error.HTTPError as e:
                st.update(error="the token isn't accepted" if e.code in (401, 403) else f"the server said HTTP {e.code}", checked=time.time())
                kv_set("scrobble", st)
                return
            except OSError as e:
                st.update(error=f"not answering ({type(e).__name__})", checked=time.time())
                kv_set("scrobble", st)
                return
            st["error"] = ""
        c = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        rows = c.execute("select id, started, played, duration, title, artist, album, url from plays where id > ? order by id limit 200", (st["cursor"],)).fetchall()
        recent = [tuple(r) for r in c.execute("select url, started from plays where id <= ? order by id desc limit 10", (st["cursor"],))]
        c.close()
        try:
            for pid, started, played, duration, title, artist, album, url in rows:
                same = any(u == url and abs(s - started) < 10 for u, s in recent)  # rooms playing together: one listen
                recent = [(url, started)] + recent[:9]
                if not same and title and (artist or "").strip().lower() not in NOT_ARTISTS and scrobble_counts(played or 0, duration or 0):
                    meta = {"artist_name": artist, "track_name": title, "additional_info": {"submission_client": "Soundsquatch", "submission_client_version": VERSION.split()[0]}}
                    if album:
                        meta["release_name"] = album
                    if duration:
                        meta["additional_info"]["duration"] = int(duration)
                    for nudge in range(5):
                        try:
                            scrobble_call("submit-listens", token, {"listen_type": "import", "payload": [{"listened_at": int(started) + nudge, "track_metadata": meta}]})
                            break
                        except urllib.error.HTTPError as e:
                            if e.code != 409 or nudge == 4:
                                raise
                    st["sent"] += 1
                    st["last"] = time.time()
                st["cursor"] = pid
            st["error"] = ""
        except urllib.error.HTTPError as e:
            st["error"] = "the token isn't accepted" if e.code in (401, 403) else f"the server said HTTP {e.code}"
        except OSError as e:
            st["error"] = f"not answering ({type(e).__name__})"
        st["checked"] = time.time()
        kv_set("scrobble", st)
    if len(rows) == 200 and not st["error"]:
        scrobble_now.set()  # more to send: straight on


def scrobble_loop():
    while True:
        try:
            scrobble_pass()
        except Exception as e:
            note_error(f"scrobbles: {type(e).__name__}: {e}")
        scrobble_now.wait(60)
        scrobble_now.clear()


def scrobble_for_settings():
    st = kv_get("scrobble", {}) or {}
    on = bool(scrobble_base() and scrobble_token())
    return {"url": settings["house"].get("scrobble_url") or "", "set": bool(scrobble_token()), "on": on,
            "sent": st.get("sent", 0) if on else 0, "last": st.get("last") if on else None, "error": st.get("error", "") if on else ""}


def physical_records(albums):
    """The collection beside the shelves: each record with the shelves' album it matches (0 for one on vinyl only) and,
    last, what Discogs says of it (genres, styles, the pressing's descriptions and notes, a box set, the house's rating)."""
    d = kv_get("discogs", {}) or {}
    by = {}
    for a in albums:
        by.setdefault((loose_artist(a[2]), lms_qobuz.plain(a[1])), a[0])
    return [r[:8] + [by.get((loose_artist(r[2]), lms_qobuz.plain(r[1])), 0), r[8] if len(r) > 8 else {}] for r in d.get("records", [])]


def loose_artist(name):
    """An artist's name however it's punctuated, and without Discogs's number for a namesake ("Low (3)"): Godspeed You!
    Black Emperor and Godspeed You Black Emperor are one band."""
    return re.sub(r"[^a-z0-9]", "", key(re.sub(r"\s*\(\d+\)$", "", name or "")).replace("&", "and"))


def qobuz_has(artist, title):
    """Whether Qobuz has a record (by that artist, or the first of those named, of that title whatever the edition or
    however its subtitle is set): True, False, or None when it couldn't be asked."""
    names = [re.sub(r"\s*\(\d+\)$", "", n).strip() for n in re.split(r",\s*", artist or "") if n.strip()] or [""]
    edition = r"\s*(?:[-\u2013:]\s*)?(?:\d{2,4}\s*)?(?:(?:super\s+)?deluxe|remaster(?:ed)?|expanded|anniversary|reissue)\b.*$"
    tidy = lambda t: lms_qobuz.plain(re.sub(edition, "", re.sub(r"[(\[]", " ", re.sub(r"[)\]]", " ", t or "")), flags=re.I)) or lms_qobuz.plain(t or "")
    want = tidy(title)
    same_t = lambda t: t == want or (min(len(t), len(want)) > 3 and (t.startswith(want) or want.startswith(t)))
    same_a = lambda a: any(lms_qobuz.same_name(a, n) or (loose_artist(a) and loose_artist(n) and (loose_artist(a) in loose_artist(n) or loose_artist(n) in loose_artist(a))) for n in names)
    try:
        found = svc().search(f"{names[0]} {re.sub(r'[(][^)]*[)]', '', title or '')}".strip()[:120], PLAYER)
    except Exception:
        return None
    return any(same_t(tidy(t)) and same_a(a) for a, t, _ in found)


def vinyl_qobuz_loop():
    """For the Vinyl page's To capture: which records on the shelf with nothing digital Qobuz has, so the ones it doesn't
    (capture them, or hear them only on the turntable) come first. Each asked once, and again after three months."""
    time.sleep(60)
    while True:
        try:
            if svc() and lms_qobuz.PLAYER.match(PLAYER or ""):
                known = kv_get("vinyl-qobuz", {}) or {}
                stale = lambda k: not k or time.time() - k[1] > 90 * 86400 or (not k[0] and len(k) < 3)  # a "no" before the looser match: asked again
                for r in [r for r in physical_now()[1] if not r[8] and stale(known.get(str(r[0])))][:300]:
                    has = qobuz_has(r[2], r[1])
                    if has is not None:
                        known[str(r[0])] = [has, time.time(), 2]
                        kv_set("vinyl-qobuz", known)
                    time.sleep(2)
        except Exception as e:
            note_error(f"records on Qobuz: {type(e).__name__}: {e}"[:200])
        time.sleep(6 * 3600)


def settings_for_app():
    checks = check_settings()
    conn = dict(settings["connections"], lms_password="")  # the password is never sent back
    return {"connections": conn, "lms_password_set": bool(settings["connections"]["lms_password"]), "features": settings["features"], "discover": settings["discover"], "discover_order": settings["house"]["discover_order"],
            "rooms": settings["house"]["rooms"], "pin": bool(settings["house"]["pin"]), "home_room": home_room(), "version": VERSION, "update": UPDATE or None,
            "turntable": turntable_for_settings(), "scrobble": scrobble_for_settings(), "discogs": dict({k: v for k, v in (kv_get("discogs", {}) or {}).items() if k != "records"}, set=bool(discogs_token()), records=len((kv_get("discogs", {}) or {}).get("records", []))),
            "have": dict(HAVE, ratings=HAVE.get("ratings") and ratings_ready()),
            "service": {"key": svc().key, "label": svc().label} if svc() else None, "token_set": os.path.exists(HA_TOKEN), "checks": checks}


def pin_hash(pin):
    return hashlib.sha256(("soundsquatch|" + str(pin)).encode()).hexdigest()


PIN_MISSES = deque(maxlen=5)  # when the last wrong PINs were given: five in a minute and the next waits out the minute


def pin_ok(given):
    """No PIN set, or the one given (the app sends it with each request that changes the house's settings or files)."""
    if not settings["house"]["pin"]:
        return True
    if len(PIN_MISSES) == PIN_MISSES.maxlen and time.time() - PIN_MISSES[0] < 60:
        return False  # guessing: none is tried until the minute is out
    if hmac.compare_digest(pin_hash(given or ""), settings["house"]["pin"]):
        return True
    PIN_MISSES.append(time.time())
    return False


def save_settings(req):
    """Settings from the page: only known keys, of the right kind; a Home Assistant token is written to its own file and
    never sent back. Rooms' names and fixed volumes as given; a PIN kept only as its hash ("" clears it)."""
    for group in ("connections", "features", "discover"):
        for k, v in (req.get(group) or {}).items():
            if k == "lms_password" and not v and (req.get(group) or {}).get("lms_user"):
                continue  # left blank: the password as it was
            if k in DEFAULTS[group] and isinstance(v, type(DEFAULTS[group][k])):
                settings[group][k] = v.strip()[:500] if isinstance(v, str) else v
    if (req.get("connections") or {}).get("lms_url") and not req.get("found"):
        settings["found_by_hand"] = True  # set on the Settings page or the first-start screen: never replaced by one found
    for pid, r in (req.get("rooms") or {}).items():
        if lms_qobuz.PLAYER.match(pid) and isinstance(r, dict):
            room = {"name": re.sub(r"\s+", " ", str(r.get("name") or "")).strip()[:40], "fixed": bool(r.get("fixed"))}
            if room["name"] or room["fixed"]:
                settings["house"]["rooms"][pid] = room
            else:
                settings["house"]["rooms"].pop(pid, None)
    if isinstance(req.get("discover_order"), list):  # Discover's sections in the house's order ([] the looks' own)
        order = [k for k in req["discover_order"] if k in DISCOVER_SECTIONS]
        settings["house"]["discover_order"] = list(dict.fromkeys(order))
    if isinstance(req.get("new_pin"), str):
        settings["house"]["pin"] = pin_hash(req["new_pin"].strip()) if req["new_pin"].strip() else ""
    if isinstance(req.get("turntable_room"), str) and (lms_qobuz.PLAYER.match(req["turntable_room"]) or not req["turntable_room"]):
        settings["house"]["turntable_room"] = req["turntable_room"]
    if isinstance(req.get("turntable_lid"), str) and re.match(r"^(binary_sensor|input_boolean|switch)\.[a-z0-9_]+$|^$", req["turntable_lid"].strip()):
        settings["house"]["turntable_lid"] = req["turntable_lid"].strip()
    if isinstance(req.get("discogs_token"), str):  # "" disconnects
        t = re.sub(r"\s", "", req["discogs_token"])[:200]
        if t:
            with open(DISCOGS_TOKEN + ".tmp", "w") as f:
                f.write(t)
            os.chmod(DISCOGS_TOKEN + ".tmp", 0o600)
            os.replace(DISCOGS_TOKEN + ".tmp", DISCOGS_TOKEN)
        elif os.path.exists(DISCOGS_TOKEN):
            os.remove(DISCOGS_TOKEN)
        discogs_sync()  # at once, so the page says what it found
    if isinstance(req.get("scrobble_url"), str) and re.match(r"^(https?://\S{1,300})?$", req["scrobble_url"].strip()):
        settings["house"]["scrobble_url"] = req["scrobble_url"].strip()
        if isinstance(req.get("scrobble_token"), str) and req["scrobble_token"].strip():
            with open(SCROBBLE_TOKEN + ".tmp", "w") as f:
                f.write(re.sub(r"\s", "", req["scrobble_token"])[:300])
            os.chmod(SCROBBLE_TOKEN + ".tmp", 0o600)
            os.replace(SCROBBLE_TOKEN + ".tmp", SCROBBLE_TOKEN)
        elif not settings["house"]["scrobble_url"] and os.path.exists(SCROBBLE_TOKEN):
            os.remove(SCROBBLE_TOKEN)  # no address: disconnected
        scrobble_now.set()
    token = (req.get("ha_token") or "").strip()
    if token:
        with open(HA_TOKEN + ".tmp", "w") as f:
            f.write(token)
        os.chmod(HA_TOKEN + ".tmp", 0o600)
        os.replace(HA_TOKEN + ".tmp", HA_TOKEN)
    with open(SETTINGS_FILE + ".tmp", "w") as f:
        json.dump(dict({g: settings[g] for g in DEFAULTS}, found_by_hand=bool(settings.get("found_by_hand"))), f, indent=1)
    os.chmod(SETTINGS_FILE + ".tmp", 0o600)
    os.replace(SETTINGS_FILE + ".tmp", SETTINGS_FILE)
    apply_settings()
    library["scan"] = None
    threading.Thread(target=lambda: load_library(force=True), daemon=True).start()
    return dict(settings_for_app(), ok=True)

db_lock = threading.Lock()
mb_lock = threading.Lock()
library = {"albums": [], "artists": {}, "etag": "", "scan": None}
lib_lock = threading.Lock()
wanted = deque()  # artists asked for ahead of the shelves: playing now, opened in the app
wanted_set = set()
profiles = {}  # cache.db's artists, held in memory: key → (profile, fetched, complete)
urgent = [0]  # artists being fetched because someone is looking at them: the crawler waits its turn at MusicBrainz
building = set()
payload = {"version": 0, "built": -1, "body": None, "etag": ""}
heard_cache = {}
crawl_state = {"done": 0, "total": 0, "current": "", "errors": 0, "started": time.time()}


def key(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


# ───────────────────────── storage ─────────────────────────
def db():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("pragma journal_mode=wal")
    return c


def setup():
    with db_lock, db() as c:
        c.execute("create table if not exists artists (k text primary key, name text, data text, fetched real, complete integer)")
        c.execute("create table if not exists albums (k text primary key, data text, fetched real)")  # reviews, by copies(artist, album)
        c.execute("create table if not exists tracks (id integer primary key, scan text, data text)")  # an album's tracks, as of a library scan
        c.execute("create table if not exists stories (k text primary key, story text, fetched real)")
        c.execute("create table if not exists stations (key text primary key, name text, blurb text, seeds text, pos integer)")
        c.execute("create table if not exists kv (k text primary key, v text)")
        c.execute("create table if not exists bans (kind text, k text, label text, at real, primary key (kind, k))")  # never play: artists, tracks
        c.execute("create table if not exists album_genres (k text primary key, genres text, source text, fetched real)")  # by copies(artist, album)
        c.execute("create table if not exists life_dates (mbid text primary key, name text, born text, died text, wikidata text, fetched real)")  # the shelves' people: solo artists and bands' members
        c.execute("create table if not exists tag_edits (path text, field text, original text, at real, primary key (path, field))")  # a file's tags before Soundsquatch first changed them
        c.execute("create table if not exists marks (kind text, k text, heart integer, rating integer, tags text, at real, primary key (kind, k))")  # hearts, stars, tags
        c.execute("create table if not exists lyrics (k text primary key, data text, fetched real)")
        c.execute("create table if not exists credits (k text primary key, data text, fetched real)")  # an album's people, by copies(artist, album)
        c.execute("create table if not exists removals (at real, album text, artist text, data text)")  # what was taken off the shelves, to put back
        c.execute("create table if not exists archive_details (id text primary key, data text, fetched real)")  # archive.org's metadata for a show
        c.execute("create table if not exists archive_seen (identifier text primary key, first_seen real)")  # when an Archive favourite first appeared
        c.execute("create table if not exists persons (mbid text primary key, data text, fetched real)")  # what a person worked on, beyond the shelves
        for k, data, fetched, complete in c.execute("select k, data, fetched, complete from artists"):
            d = json.loads(data)
            profiles[k] = (d, fetched, int(all(p in d for p in PARTS)))  # a part added since makes a profile incomplete again


def get_profile(name):
    return profiles.get(key(name), (None, 0, 0))


def put_profile(name, data, complete):
    now = time.time()
    profiles[key(name)] = (data, now, int(complete))
    payload["version"] += 1
    with db_lock, db() as c:
        c.execute("insert or replace into artists values (?,?,?,?,?)", (key(name), name, json.dumps(data, ensure_ascii=False), now, int(complete)))


# ───────────────────────── Lyrion ─────────────────────────
def rpc(player, *cmd, timeout=30):
    body = json.dumps({"id": 1, "method": "slim.request", "params": [player, [str(x) for x in cmd]]}).encode()
    req = urllib.request.Request(LMS + "/jsonrpc.js", body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r).get("result") or {}


# ───────────────────────── genres: the house's own, found for every album ─────────────────────────
def old_key(artist, title):  # how the Deepvalley Times' genres file keys an album
    return re.sub(r"[^a-z0-9|]+", "", (artist + "|" + title).lower())


def import_genres():
    """Once: the genres the house already has (the Deepvalley Times' file, from Home Assistant), so nothing is looked up again."""
    with db() as c:
        if c.execute("select count(*) from album_genres").fetchone()[0]:
            return
    if not HA_URL or not settings["features"]["home_assistant"]:
        return
    try:
        with urllib.request.urlopen(HA_URL + "/local/music-genres.json", timeout=15) as r:
            old = json.load(r).get("albums") or {}
    except Exception:
        return
    with lib_lock:
        albums = list(library["albums"])
    rows = [(copies(a[2], a[1]), json.dumps(old[old_key(a[2], a[1])]), "imported", time.time()) for a in albums if old_key(a[2], a[1]) in old]
    with db_lock, db() as c:
        c.executemany("insert or replace into album_genres values (?,?,?,?)", rows)
    crawl_state["genres_imported"] = len(rows)
    load_library(force=True)  # the shelves with their genres


def genres_for(a):
    """An album's genres from MusicBrainz: its release group's tags, else the artist's (from their profile, else asked)."""
    plain = (re.sub(r"\s*[(\[].*?[)\]]", "", a[1]).strip() or a[1]).replace('"', "")
    found = mb_get("release-group", query=f'releasegroup:"{plain}" AND artist:"{a[2].replace(chr(34), "")}"', limit=3).get("release-groups") or []
    if found and int(found[0].get("score") or 0) >= 90:
        g = house_genres.pick([[t["name"], t.get("count", 0)] for t in found[0].get("tags") or []])
        if g:
            return g, "album"
    d = profiles.get(key(a[2]), ({},))[0] or {}
    tags = [[t, 1] for t in (d.get("mb") or {}).get("genres") or []]
    if not tags and (d.get("mb") or {}).get("mbid"):
        got = mb_get(f"artist/{d['mb']['mbid']}", inc="tags")
        tags = [[t["name"], t.get("count", 0)] for t in got.get("tags") or []]
    g = house_genres.pick(tags)
    return g, "artist" if g else "none"


def genres_loop():
    """Genres for every album that has none yet (new ones as they come), a few at a time behind the other passes; an album
    MusicBrainz knows nothing of is asked again after a month."""
    time.sleep(90)
    while True:
        try:
            import_genres()
            with db() as c:
                have = {k: f for k, f, source in c.execute("select k, fetched, source from album_genres") if source != "edited"}
                mine = {k for (k,) in c.execute("select k from album_genres where source = 'edited'")}  # set by hand: never guessed again
            with lib_lock:
                todo = [a for a in library["albums"] if key(a[2]) not in NOT_ARTISTS and copies(a[2], a[1]) not in mine and
                        (copies(a[2], a[1]) not in have or (have[copies(a[2], a[1])] < time.time() - STALE and not a[8]))]
            crawl_state["genres_left"] = len(todo)
            if not todo:
                time.sleep(3600)
                continue
            for a in todo[:20]:
                try:
                    g, source = genres_for(a)
                except Exception:
                    continue
                with db_lock, db() as c:
                    c.execute("insert or replace into album_genres values (?,?,?,?)", (copies(a[2], a[1]), json.dumps(g), source, time.time()))
                if g:
                    with lib_lock:
                        for row in library["albums"]:
                            if row[0] == a[0]:
                                row[8] = g
                        library["etag"] = hashlib.sha1(json.dumps([library["albums"], library["scan"]]).encode()).hexdigest()[:16]
                crawl_state["genres_left"] -= 1
                time.sleep(2)
        except Exception as e:
            note_error(f"genres: {type(e).__name__}: {e}"[:200])
            time.sleep(60)


def file_genres(path, genres=None):
    """A music file's genre tag: read (genres None), or written as these. Mutagen's plain view of the tag, so mp3, flac, m4a
    and ogg alike; an mp3's ID3 is saved as 2.4, which keeps several genres apart."""
    import mutagen
    f = mutagen.File(path, easy=True)
    if f is None:
        raise ValueError("not a music file")
    if genres is None:
        return list((f.tags or {}).get("genre") or [])
    if f.tags is None:
        f.add_tags()
    if genres:
        f["genre"] = list(genres)
    elif "genre" in f.tags:
        del f["genre"]
    f.save()


def file_tag(path, field, value=None):
    """One plain tag of a music file (title, album, …): read (value None), or written."""
    import mutagen
    f = mutagen.File(path, easy=True)
    if f is None:
        raise ValueError("not a music file")
    if value is None:
        return ((f.tags or {}).get(field) or [""])[0]
    if f.tags is None:
        f.add_tags()
    f[field] = [value]
    f.save()


def track_files(track_id):
    """A track's file and the same track in every other copy of its album (same disc and number): (track, [paths])."""
    t = (rpc("", "titles", "0", "1", f"track_id:{int(track_id)}", "tags:ualetiJ").get("titles_loop") or [None])[0]
    if not t:
        return None, []
    paths = [file_path(t.get("url") or "")]
    with lib_lock:
        a = next((r for r in library["albums"] if copies(r[2], r[1]) == copies(t.get("albumartist") or t.get("artist") or "", t.get("album") or "")), None)
    if a:
        for i, _ in copies_of(a[0])[1]:
            for o in rpc("", "titles", "0", "500", f"album_id:{i}", "tags:uti").get("titles_loop") or []:
                if (o.get("tracknum"), o.get("disc")) == (t.get("tracknum"), t.get("disc")) and track_word(o.get("title")) == track_word(t.get("title")):
                    paths.append(file_path(o.get("url") or ""))
    return t, [f for f in dict.fromkeys(paths) if f and placed(f)[0] and os.path.isfile(f)]


def track_word(title):  # a title as a track's mark knows it (the app's trackKey)
    return re.sub(r"[^a-z0-9]", "", re.sub(r"[(\[].*?[)\]]", "", str(title or "").lower()))


def track_title_info(track_id):
    t, files = track_files(track_id)
    if not t:
        return {"error": "no such track"}
    with db() as c:
        row = c.execute("select original from tag_edits where path = ? and field = 'title'", (files[0],)).fetchone() if files else None
    return {"title": t.get("title") or "", "local": bool(files), "original": json.loads(row[0]) if row else None}


def track_title_edit(req):
    """A track's title put right in its files (every copy of it), the old title kept so it can be put back; its heart and
    stars follow it to the new title, and Lyrion looks again. Streamed tracks have no files to change."""
    t, files = track_files(req.get("id") or 0)
    if not t:
        return {"error": "no such track"}
    if not files:
        return {"error": "a streamed track's title comes from its service"}
    if not settings["features"]["write_files"]:
        return {"error": "Changing music files is switched off (Settings, Features)"}
    undo, old = bool(req.get("undo")), t.get("title") or ""
    with db() as c:
        kept = {p: json.loads(o) for p, o in c.execute(f"select path, original from tag_edits where field = 'title' and path in ({','.join('?' * len(files))})", files)}
    new = (kept.get(files[0]) if undo else re.sub(r"\s+", " ", str(req.get("title") or "")).strip()[:200])
    if not new:
        return {"error": "nothing to put back" if undo else "a title, please"}
    written, problems = 0, []
    for f in files:
        try:
            if not undo and f not in kept:
                with db_lock, db() as c:
                    c.execute("insert or ignore into tag_edits values (?,?,?,?)", (f, "title", json.dumps(file_tag(f, "title")), time.time()))
            file_tag(f, "title", kept.get(f, new) if undo else new)
            if undo:
                with db_lock, db() as c:
                    c.execute("delete from tag_edits where path = ? and field = 'title'", (f,))
            written += 1
        except Exception as e:
            problems.append(f"{os.path.basename(f)}: {type(e).__name__}: {e}"[:160])
    base = copies(t.get("artist") or "", t.get("album") or "") + "|"
    if written and track_word(old) != track_word(new):
        with db_lock, db() as c:  # the track's heart and stars go with it
            c.execute("update or replace marks set k = ? where kind = 'track' and k = ?", (base + track_word(new), base + track_word(old)))
    with db_lock, db() as c:
        c.execute("delete from tracks where data like ?", (f'%"id": {int(t["id"])},%',))  # its album's track list asked of Lyrion again
    if written:
        rpc("", "rescan")
    return {"ok": True, "title": new, "written": written, "problems": problems[:5]}


# ───────────────────────── an album's cover, replaced ─────────────────────────
def get_json(url, timeout=12):
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=timeout) as r:
        return json.load(r)


def art_choices(album_id):
    """Covers to choose from for an album: the Cover Art Archive's (by MusicBrainz), Apple's and Deezer's; each a small
    picture to show and a large one to use. And whether the album has files to carry one, and has had its cover replaced."""
    a, found = copies_of(int(album_id or 0))
    if not a:
        return {"error": "no such album"}
    files = [f for _, urls in found for f in map(file_path, urls) if f and placed(f)[0] and os.path.isfile(f)]
    plain = re.sub(r"\s*[(\[].*?[)\]]", "", a[1]).strip() or a[1]
    out = []
    try:
        for rg in mb_get("release-group", query=f'releasegroup:"{plain.replace(chr(34), "")}" AND artist:"{a[2].replace(chr(34), "")}"', limit=3).get("release-groups") or []:
            if int(rg.get("score") or 0) >= 80:
                base = f"https://coverartarchive.org/release-group/{rg['id']}/front"
                out.append({"thumb": base + "-250", "full": base + "-1200", "source": "Cover Art Archive", "label": rg.get("title") or ""})
    except Exception:
        pass
    try:
        for r in get_json("https://itunes.apple.com/search?" + urllib.parse.urlencode({"term": f"{a[2]} {plain}", "entity": "album", "limit": 6})).get("results") or []:
            if key(r.get("artistName") or "") == key(a[2]) and r.get("artworkUrl100"):
                out.append({"thumb": r["artworkUrl100"].replace("100x100bb", "300x300bb"), "full": r["artworkUrl100"].replace("100x100bb", "1200x1200bb"),
                            "source": "Apple", "label": r.get("collectionName") or ""})
    except Exception:
        pass
    try:
        for r in get_json("https://api.deezer.com/search/album?" + urllib.parse.urlencode({"q": f'artist:"{a[2]}" album:"{plain}"', "limit": 6})).get("data") or []:
            if key((r.get("artist") or {}).get("name") or "") == key(a[2]) and r.get("cover_xl"):
                out.append({"thumb": r.get("cover_medium") or r["cover_xl"], "full": r["cover_xl"], "source": "Deezer", "label": r.get("title") or ""})
    except Exception:
        pass
    with db() as c:
        edited = bool(files) and bool(c.execute(f"select 1 from tag_edits where field = 'cover' and path in ({','.join('?' * len(files))}) limit 1", files).fetchone())
    return {"choices": out, "local": bool(files), "edited": edited}


def file_picture(path, data=None, mime="image/jpeg", remove=False):
    """A music file's front cover: read ((bytes, type) or None), written (data), or taken out (remove)."""
    import mutagen
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4, MP4Cover
    f = mutagen.File(path)
    if isinstance(f, MP3):
        if data is None and not remove:
            pics = (f.tags.getall("APIC") if f.tags else [])
            pics.sort(key=lambda p: p.type != 3)
            return (pics[0].data, pics[0].mime) if pics else None
        if f.tags is None:
            f.add_tags()
        version = f.tags.version[1] if f.tags.version[1] in (3, 4) else 4
        f.tags.delall("APIC")
        if data is not None:
            f.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        f.save(v2_version=version)
    elif isinstance(f, FLAC):
        if data is None and not remove:
            pics = sorted(f.pictures, key=lambda p: p.type != 3)
            return (pics[0].data, pics[0].mime) if pics else None
        f.clear_pictures()
        if data is not None:
            im = Image.open(io.BytesIO(data))
            p = Picture()
            p.type, p.mime, p.data, p.width, p.height, p.depth = 3, mime, data, im.width, im.height, 24
            f.add_picture(p)
        f.save()
    elif isinstance(f, MP4):
        if data is None and not remove:
            got = (f.tags or {}).get("covr") or []
            return (bytes(got[0]), "image/png" if got[0].imageformat == MP4Cover.FORMAT_PNG else "image/jpeg") if got else None
        if f.tags is None:
            f.add_tags()
        if data is not None:
            f.tags["covr"] = [MP4Cover(data, imageformat=MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG)]
        elif "covr" in f.tags:
            del f.tags["covr"]
        f.save()
    else:
        raise ValueError("this kind of file can't carry a cover here")


def artist_photo_choices(name):
    """The pictures of an artist Soundsquatch has (Wikipedia's, Qobuz's, Discogs's) and whether one was chosen by hand."""
    d = get_profile(name)[0] or {}
    w, q = d.get("wiki") or {}, (d.get("qobuz") or {}).get("photo") or ""
    urls = [w.get("image", "").split("?")[0], q] + [p["url"] for p in d.get("photos") or []]
    return {"choices": [u for u in dict.fromkeys(urls) if u], "chosen": chosen_photos.get(key(name)), "now": pick_photo(dict(d, name=name))}


def artist_photo_edit(req):
    """An artist's picture chosen by hand: one of theirs ({"url"}), one sent from a device ({"data"}, base64), or the
    choice undone ({"reset": true}). Soundsquatch's alone: nothing in the music files holds an artist's picture."""
    name = (req.get("artist") or "").strip()
    k = key(name)
    if not k:
        return {"error": "no artist"}
    was = chosen_photos.get(k) or {}
    if req.get("reset"):
        chosen_photos.pop(k, None)
    elif req.get("url"):
        url = str(req["url"])
        if not url.startswith("https://") or (urllib.parse.urlparse(url).hostname or "") not in PICTURE_HOSTS:
            return {"error": "not a picture from a known site"}
        chosen_photos[k] = {"url": url}
    elif req.get("data"):
        import base64
        im = Image.open(io.BytesIO(base64.b64decode(re.sub(r"^data:[^,]*,", "", str(req["data"]))))).convert("RGB")
        os.makedirs(ARTIST_PICS, exist_ok=True)
        name_on_disk = f"{re.sub(r'[^a-z0-9]', '', k)[:60] or 'artist'}-{int(time.time())}.jpg"
        for size, suffix in ((1920, ""), (320, "-320")):
            copy = im.copy()
            copy.thumbnail((size, size * 2), Image.LANCZOS)
            buf = io.BytesIO()
            copy.save(buf, "JPEG", quality=88, optimize=True, progressive=True)
            save(os.path.join(ARTIST_PICS, name_on_disk.replace(".jpg", suffix + ".jpg")), buf.getvalue())
        chosen_photos[k] = {"file": name_on_disk}
    else:
        return {"error": "no picture"}
    if was.get("file") and chosen_photos.get(k) != was:  # a picture sent before and now replaced: its files go (they are Soundsquatch's own)
        for suffix in ("", "-320"):
            try:
                os.remove(os.path.join(ARTIST_PICS, was["file"].replace(".jpg", suffix + ".jpg")))
            except OSError:
                pass
    kv_set("artist-photos", chosen_photos)
    with lib_lock:
        library["etag"] = hashlib.sha1((library.get("etag") or "").encode() + str(time.time()).encode()).hexdigest()[:16]
    return {"ok": True, "chosen": chosen_photos.get(k)}


def album_art_edit(req):
    """A new cover for an album, written into every file of every copy of it (where Lyrion finds it), and Lyrion asked
    to look again. The picture each file carried before is kept once (in art-originals/) so {"undo": true} puts it back.
    The picture is a chosen one's address (from art_choices) or one sent from the device (base64)."""
    a, found = copies_of(int(req.get("id") or 0))
    if not a:
        return {"error": "no such album"}
    files = [f for _, urls in found for f in map(file_path, urls) if f and placed(f)[0] and os.path.isfile(f)]
    if not files:
        return {"error": "a streamed album keeps its service's cover"}
    if not settings["features"]["write_files"]:
        return {"error": "Changing music files is switched off (Settings, Features)"}
    undo, data = bool(req.get("undo")), None
    if not undo:
        if req.get("url"):
            url = str(req["url"])
            if not url.startswith("https://") or (urllib.parse.urlparse(url).hostname or "") not in PICTURE_HOSTS:
                return {"error": "not a picture from a known site"}
            with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=30) as r:
                data = r.read(20 * 1024 * 1024)
        elif req.get("data"):
            import base64
            data = base64.b64decode(re.sub(r"^data:[^,]*,", "", str(req["data"])))
        else:
            return {"error": "no picture"}
        im = Image.open(io.BytesIO(data)).convert("RGB")  # whatever it was: a JPEG of at most 1400 pixels
        im.thumbnail((1400, 1400), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90, optimize=True)
        data = buf.getvalue()
    written, problems = 0, []
    os.makedirs(ART_KEPT, exist_ok=True)
    for f in files:
        try:
            with db() as c:
                row = c.execute("select original from tag_edits where path = ? and field = 'cover'", (f,)).fetchone()
            if undo:
                if row is None:
                    continue
                was = json.loads(row[0])
                if was:
                    with open(os.path.join(ART_KEPT, was["keep"]), "rb") as kf:
                        file_picture(f, kf.read(), was["mime"])
                else:
                    file_picture(f, remove=True)
                with db_lock, db() as c:
                    c.execute("delete from tag_edits where path = ? and field = 'cover'", (f,))
            else:
                if row is None:
                    old = file_picture(f)
                    was = None
                    if old:
                        name = hashlib.sha1(old[0]).hexdigest() + (".png" if old[1] == "image/png" else ".jpg")
                        if not os.path.exists(os.path.join(ART_KEPT, name)):
                            save(os.path.join(ART_KEPT, name), old[0])
                        was = {"keep": name, "mime": old[1] or "image/jpeg"}
                    with db_lock, db() as c:
                        c.execute("insert or ignore into tag_edits values (?,?,?,?)", (f, "cover", json.dumps(was), time.time()))
                file_picture(f, data)
            written += 1
        except Exception as e:
            problems.append(f"{os.path.basename(f)}: {type(e).__name__}: {e}"[:160])
    if written:
        rpc("", "rescan")
        for wait in (30, 90, 240):  # the shelves take the new cover once Lyrion has looked
            threading.Timer(wait, lambda: load_library(force=True)).start()
    return {"ok": True, "written": written, "files": len(files), "problems": problems[:5]}


def set_album_genres(a, genres, source):
    """An album's genres on the shelves at once, every copy of it."""
    k = copies(a[2], a[1])
    with db_lock, db() as c:
        if source is None:
            c.execute("delete from album_genres where k = ?", (k,))  # the genres loop finds them again
        else:
            c.execute("insert or replace into album_genres values (?,?,?,?)", (k, json.dumps(genres), source, time.time()))
    with lib_lock:
        for row in library["albums"]:
            if copies(row[2], row[1]) == k:
                row[8] = list(genres)
        library["etag"] = hashlib.sha1(json.dumps([library["albums"], library["scan"]]).encode()).hexdigest()[:16]


def album_genres_edit(req):
    """Genres set by hand for an album: kept by Soundsquatch (never guessed again) and, for music in Lyrion's folders,
    written into the files' genre tags and Lyrion asked to look again. Each file's tag as it was before Soundsquatch first
    changed it is kept, so {"undo": true} puts every file back and lets the genres be found afresh. Qobuz albums have no
    files: their genres are Soundsquatch's alone."""
    a, found = copies_of(int(req.get("id") or 0))
    if not a:
        return {"error": "no such album"}
    undo = bool(req.get("undo"))
    genres = [] if undo else [g for g in dict.fromkeys(re.sub(r"\s+", " ", str(x)).strip()[:40] for x in req.get("genres") or []) if g][:4]
    files = [f for _, urls in found for f in map(file_path, urls) if f and placed(f)[0] and os.path.isfile(f)]
    if not settings["features"]["write_files"]:
        files = []  # Soundsquatch's own, as a streamed album's are (any files changed before are put back by undo, below)
        if undo:
            with db() as c:
                files = [p for (p,) in c.execute("select path from tag_edits where field = 'genre'") if p in
                         {f for _, urls in found for f in map(file_path, urls) if f}]
    written, problems = 0, []
    for f in files:
        try:
            with db() as c:
                row = c.execute("select original from tag_edits where path = ? and field = 'genre'", (f,)).fetchone()
            if undo:
                if row is None:
                    continue
                file_genres(f, json.loads(row[0]))
                with db_lock, db() as c:
                    c.execute("delete from tag_edits where path = ? and field = 'genre'", (f,))
            else:
                if row is None:
                    was = file_genres(f)
                    with db_lock, db() as c:
                        c.execute("insert or ignore into tag_edits values (?,?,?,?)", (f, "genre", json.dumps(was), time.time()))
                file_genres(f, genres)
            written += 1
        except Exception as e:
            problems.append(f"{os.path.basename(f)}: {type(e).__name__}: {e}"[:160])
    set_album_genres(a, genres, None if undo else "edited")
    if written:
        rpc("", "rescan")  # Lyrion looks for changed files
    return {"ok": True, "genres": genres, "files": len(files), "written": written, "problems": problems[:5], "local": bool(files)}


def album_genres_info(album_id):
    """For the genre editor: the house's genres to choose from, the album's, and whether they were set by hand."""
    a = album_row(album_id)
    if not a:
        return {"error": "no such album"}
    with db() as c:
        row = c.execute("select source from album_genres where k = ?", (copies(a[2], a[1]),)).fetchone()
    return {"genres": a[8], "edited": bool(row and row[0] == "edited"), "choices": genre_choices()}


def genre_choices():
    """The house's list, then the genres added by hand (each offered for every album once it is on one)."""
    names = [n for n, _ in house_genres.GENRES]
    with db() as c:
        added = sorted({g for (gs,) in c.execute("select genres from album_genres where source = 'edited'") for g in json.loads(gs)} - set(names), key=str.lower)
    return names + added


def artist_tags_edit(req):
    """An artist's tags (MusicBrainz's) hidden on their page, or shown again; Soundsquatch's alone, as nothing in the files holds them."""
    k = key(req.get("artist") or "")
    if not k:
        return {"error": "no artist"}
    hidden = kv_get("hidden-tags", {})
    hidden[k] = sorted(set(req.get("hidden") or []))
    if not hidden[k]:
        del hidden[k]
    kv_set("hidden-tags", hidden)
    return {"ok": True, "hidden": hidden.get(k, [])}


def genres_file():
    """The genres as the Deepvalley Times' file has them (its Music Scene can read them from here)."""
    with lib_lock:
        albums = list(library["albums"])
    out = {old_key(a[2], a[1]): a[8] for a in albums if a[8]}
    names = [n for n, _ in house_genres.GENRES if any(n in v for v in out.values())]
    return {"genres": names, "albums": out}


EDITION = r"\b(remaster(ed)?|deluxe|edition|anniversary|expanded|reissue|bonus|version|legacy|collector'?s)\b"


def fold(artist, album):
    """Versions of one album as one: "Mogwai Young Team (Remastered)", "Young Team (Deluxe Edition)" and "Young Team - 2008
    Remaster" are all Young Team (the artist's name before the title, editions and remasters set aside)."""
    t = re.sub(r"^\s*" + re.escape(artist) + r"\s*[-:–]?\s+", "", album, flags=re.I) or album
    t = re.sub(r"\s+[-–]\s+[^-–]*" + EDITION + r".*$", "", t, flags=re.I)  # "Young Team - 2008 Remaster"; a colon is the title's own ("Orphans: Brawlers…")
    return copies(artist, t) if copies("", t).strip("|") else copies(artist, album)


def fold_keys(entries):
    """Each album's version group: its folded title, split by year only when plain (non-edition) albums of that title came
    out in different years (American Football's three American Footballs); editions then join the earliest of them."""
    groups = {}
    for e in entries:
        groups.setdefault(fold(e[2], e[1]), []).append(e)
    out = {}
    for k, es in groups.items():
        years = sorted({e[3] for e in es if e[3] and not re.search(EDITION, e[1], re.I)})
        for e in es:
            if len(years) < 2:
                out[e[0]] = k
            else:
                y = e[3] if e[3] in years and not re.search(EDITION, e[1], re.I) else years[0]
                out[e[0]] = f"{k}|{y}"
    return out


def load_library(force=False):
    """The shelves, as the Music page has them: one album a title (its best copy), newest first, with the house's genres."""
    status = rpc("", "serverstatus", "0", "0")
    scan = (status.get("lastscan"), status.get("info total albums"))
    if not force and scan == library["scan"] and library["albums"]:
        return
    total = int(status.get("info total albums") or 0)
    found = sorted(rpc("", "albums", "0", str(total + 50), "tags:lajyS", timeout=120).get("albums_loop", []), key=lambda a: -int(a["id"]))
    tracks, step = [], 25000  # a page at a time: a large library in one answer is more than Lyrion likes to build
    while True:
        got = rpc("", "titles", str(len(tracks)), str(step), "tags:eoIrTuD", timeout=180).get("titles_loop", [])
        tracks += got
        if len(got) < step:
            break
    by_album, streamed, added, captured = {}, {}, {}, set()  # streamed: album → the service it streams from
    cap = urllib.parse.quote(capture_dir())  # the turntable's own recordings: versions of their own ("Your vinyl")
    for t in tracks:
        if cap in (t.get("url") or ""):
            captured.add(str(t.get("album_id")))
        added[str(t.get("album_id"))] = max(added.get(str(t.get("album_id")), 0), int(float(t.get("addedTime") or 0)))  # when it joined the shelves
        by_album.setdefault(str(t.get("album_id")), Counter())[quality(t)] += 1
        if not (t.get("url") or "").startswith("file:"):
            streamed[str(t.get("album_id"))] = (streaming.by_url(t.get("url")) or streaming.ALL[0]).key
    best, versions, rows = {}, {}, []
    for rank, a in enumerate(found):
        q = by_album.get(str(a["id"]))
        qkey, words = q.most_common(1)[0][0] if q else ((0, 0, 0), "")
        rows.append((rank, qkey, [int(a["id"]), a.get("album") or "", a.get("artist") or "", int(a.get("year") or 0), a.get("artwork_track_id") or "", rank, words, int(a.get("artist_id") or 0)]))
    keys = fold_keys([r[2] for r in rows])
    for rank, qkey, entry in rows:
        k = keys[entry[0]]  # every version of it under one name: the best copy shows, the others are its versions
        versions.setdefault(k, []).append((qkey, entry))
        ours = str(entry[0]) in captured
        # the house's own record first when the house says so; otherwise its recording never displaces the master on a tie
        qkey = (ours, qkey) if settings["features"].get("prefer_captured") else (qkey, not ours)
        if k not in best or qkey > best[k][0]:
            if k in best:
                entry[5] = min(rank, best[k][1][5])
            best[k] = (qkey, entry)
        else:
            best[k][1][5] = min(rank, best[k][1][5])
    albums = sorted((e for _, e in best.values()), key=lambda e: e[5])
    with db() as c:
        genres = {k: json.loads(g) for k, g in c.execute("select k, genres from album_genres")}
    for e in albums:
        e.append(genres.get(copies(e[2], e[1]), []))
        src = lambda i: "vinyl" if str(i) in captured else streamed[str(i)] if str(i) in streamed else "local"
        e.append(src(e[0]))  # [9] where it plays from: the shelves, Qobuz, or the turntable's own recording
        k = keys[e[0]]  # [10] its other versions: [id, title, quality, year, art, source], best first
        e.append([[v[0], v[1], v[6], v[3], v[4], src(v[0]), added.get(str(v[0]), 0)]
                  for _, v in sorted(versions.get(k, []), key=lambda x: x[0], reverse=True) if v[0] != e[0]])
        e.append(max([added.get(str(e[0]), 0)] + [v[6] for v in e[10]]))  # [11] when it (or a pressing of it) joined the shelves
    artists = {}
    for e in albums:
        if key(e[2]) in NOT_ARTISTS:
            continue
        a = artists.setdefault(key(e[2]), {"name": e[2], "id": e[7], "albums": 0, "rank": e[5]})
        a["albums"] += 1
    with lib_lock:
        library.update(albums=albums, artists=artists, scan=scan, genres=genres)
        library["etag"] = hashlib.sha1(json.dumps([albums, scan]).encode()).hexdigest()[:16]
    crawl_state["total"] = len(artists)


def library_payload():
    """The library for the app, with each artist's picture and kind from their profile when there is one: gzipped, with its
    ETag, made again only when the library or a profile has changed (and at most every half minute for profiles alone)."""
    stamp = (library["etag"], payload["version"])
    if payload["body"] and payload["built"] == stamp:
        return payload["body"], payload["etag"]
    if payload["body"] and payload["built"][0] == library["etag"] and time.time() - payload.get("at", 0) < 30:
        return payload["body"], payload["etag"]
    with lib_lock:
        albums, artists = library["albums"], dict(library["artists"])
    out = []
    for k, a in sorted(artists.items(), key=lambda x: re.sub(r"^the ", "", x[0])):
        d = profiles.get(k, ({},))[0] or {}
        out.append([a["name"], a["id"], a["albums"], pick_photo(d, "thumb") if d else "", (d.get("mb") or {}).get("type") or ""])
    body = json.dumps({"albums": albums, "artists": out, "physical": physical_records(albums)}, ensure_ascii=False, separators=(",", ":")).encode()
    payload.update(body=gzip.compress(body, 6), built=stamp, at=time.time(), etag='"' + hashlib.sha1(body).hexdigest()[:16] + '"')
    return payload["body"], payload["etag"]


# ───────────────────────── the profile ─────────────────────────
def mb_get(path, **query):
    """MusicBrainz, a request a second across every thread (lms_qobuz.py's own calls come through here too). It answers
    503 when busy: asked again, a little later each time. The crawler stands aside while someone is waiting on an artist."""
    url = lms_qobuz.MB + path + "?" + urllib.parse.urlencode(dict(query, fmt="json"))
    while threading.current_thread().name in ("crawler", "credits") and urgent[0]:
        time.sleep(0.2)
    for wait in (3, 10, 30, None):
        with mb_lock:
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=lms_qobuz.MB_AGENT), timeout=20) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code != 503 or wait is None:
                    raise
            finally:
                time.sleep(1.05)
        time.sleep(wait)


lms_qobuz.mb_get = mb_get


def get_json(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=dict(AGENT, Accept="application/json")), timeout=timeout) as r:
        return json.load(r)


def part_qobuz(name):
    """The artist's sheet on the streaming service (kept as the profile's "qobuz" part, whichever service it is)."""
    if not svc():
        return {}  # no service: the profile goes on without it
    sheet = svc().sheet(name, PLAYER)
    if sheet.get("error"):
        return None
    sheet.pop("heard", None)  # live, from the log, when the app asks
    sheet["service"] = svc().key
    sheet["photo"] = sheet.get("photo", "").replace("/covers/medium/", "/covers/large/")
    return sheet


def part_mb(name, qobuz=None):
    """MusicBrainz's entry for the artist: the one of that name whose releases best match the shelves, then Qobuz's
    albums (as lms_qobuz.py chooses), with where they are from, their years, their genres and the people and groups they
    are tied to. Namesakes none of whose releases match: none of them (better no story than someone else's)."""
    candidates = lms_qobuz.mb_releases(name)
    if not candidates:
        return {}
    own = lms_qobuz.shelved(name)
    theirs = set().union(*[lms_qobuz.sides(r["album"]) for r in (qobuz or {}).get("releases", [])]) if qobuz else set()
    score = lambda c: (len(c[2] & own), len(c[2] & theirs))
    best = max(candidates, key=score)
    if len(candidates) > 1 and sum(score(best)) == 0:
        return {}
    a = mb_get(f"artist/{best[0]}", inc="artist-rels+url-rels+genres")
    rels, links = [], {}
    for r in a.get("relations", []):
        if r.get("target-type") == "artist" and r.get("artist"):
            rels.append({"type": r.get("type"), "dir": r.get("direction"), "name": r["artist"].get("name"), "mbid": r["artist"].get("id"),
                         "begin": (r.get("begin") or "")[:4], "end": (r.get("end") or "")[:4], "ended": bool(r.get("ended")),
                         "attrs": [x for x in r.get("attributes", []) if x not in ("original",)][:3]})
        elif r.get("target-type") == "url":
            links.setdefault(r.get("type"), (r.get("url") or {}).get("resource"))
    life = a.get("life-span") or {}
    area = (a.get("begin-area") or {}).get("name") or (a.get("area") or {}).get("name") or ""
    country = (a.get("area") or {}).get("name") or ""
    genres = [g["name"] for g in sorted(a.get("genres", []), key=lambda g: -g.get("count", 0))[:6]]
    return {"mbid": a.get("id"), "type": a.get("type") or "", "area": area, "country": country if country != area else "",
            "begin": (life.get("begin") or "")[:4], "end": (life.get("end") or "")[:4], "ended": bool(life.get("ended")),
            "disambiguation": a.get("disambiguation") or "", "genres": genres, "rels": rels[:60],
            "wikidata": links.get("wikidata") or "", "homepage": links.get("official homepage") or "", "bandcamp": links.get("bandcamp") or ""}


def part_wiki(mb):
    """Wikipedia's summary and portrait, from MusicBrainz's link to Wikidata."""
    q = (mb or {}).get("wikidata", "").rstrip("/").split("/")[-1]
    if not q.startswith("Q"):
        return {}
    ent = get_json(f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={q}&props=sitelinks&sitefilter=enwiki&format=json")
    title = (((ent.get("entities") or {}).get(q) or {}).get("sitelinks") or {}).get("enwiki", {}).get("title")
    if not title:
        return {}
    s = get_json("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"), safe=""))
    img = (s.get("originalimage") or {})
    return {"title": title, "extract": s.get("extract") or "", "image": img.get("source") or "", "w": img.get("width") or 0, "h": img.get("height") or 0,
            "thumb": (s.get("thumbnail") or {}).get("source") or "", "url": ((s.get("content_urls") or {}).get("desktop") or {}).get("page") or ""}


def part_photos(name, mb=None):
    if HAVE.get("mai") is False:
        return []
    mbid = (mb or {}).get("mbid") or ""  # their MusicBrainz id: a namesake's photographs don't come instead
    got = rpc("", "musicartistinfo", "artistphotos", f"artist:{name}", *([f"mbid:{mbid}"] if mbid else []), timeout=25).get("item_loop") or []
    return [{"url": p["url"], "w": int(p.get("width") or 0), "h": int(p.get("height") or 0)} for p in got if p.get("url")][:12]


PARTS = ("qobuz", "mb", "wiki", "photos", "rgs")


def part_rgs(mb):
    """The artist's release groups on MusicBrainz with their dates, newest first (for New from your artists)."""
    if not (mb or {}).get("mbid"):
        return None
    got = mb_get("release-group", artist=mb["mbid"], limit=100, type="album|ep")
    out = [{"id": g["id"], "title": g.get("title") or "", "date": g.get("first-release-date") or "", "type": g.get("primary-type") or "",
            "extra": g.get("secondary-types") or []} for g in got.get("release-groups", [])]
    return sorted(out, key=lambda g: g["date"], reverse=True)[:100]  # enough to know every record on the shelves by its kind


def build(name, only=None):
    """Fetches the parts of an artist's profile it lacks (or all, when stale), keeping what it has if a part fails. The
    photographs (through Music & Artist Information) outlast a stale profile: found once, they are kept; an artist with
    none is asked again after two weeks (NOTHING_AGAIN)."""
    have, fetched, complete = get_profile(name)
    d = dict(have) if have else {"name": name}
    if have and time.time() - fetched > STALE:
        d = {"name": name}
        if "photos" in have and (have["photos"] or time.time() - have.get("_photos_at", fetched) < NOTHING_AGAIN):
            d.update(photos=have["photos"], _photos_at=have.get("_photos_at", fetched))
    missing = [p for p in PARTS if p not in d and (only is None or p in only)]
    for p in missing:
        try:
            if p == "qobuz":
                got = part_qobuz(name)
            elif p == "mb":
                got = part_mb(name, d.get("qobuz"))
            elif p == "wiki":
                got = part_wiki(d.get("mb")) if "mb" in d else None
            elif p == "rgs":
                got = part_rgs(d.get("mb")) if "mb" in d else None
            else:
                got = part_photos(name, d.get("mb"))
                d["_photos_at"] = time.time()
            if got is not None:
                d[p] = got
            else:
                d.setdefault("_tried", {})[p] = time.time()  # nothing to be had: not asked again for a day
        except Exception as e:
            d.setdefault("_tried", {})[p] = time.time()
            crawl_state["errors"] += 1
            note_error(f"{name} {p}: {type(e).__name__}: {e}"[:200])
        if p == "qobuz" and "qobuz" in d and only is None:
            put_profile(name, d, False)  # the app can show this much while the rest comes
    put_profile(name, d, all(p in d for p in PARTS))
    for url, width in ((pick_photo(d), 1600), (pick_photo(d, "thumb"), 320)):  # the pictures the app will ask for, ready
        try:
            if url:
                picture(url, width)
        except Exception:
            pass
    return d


def shared_name(name):
    """Whether MusicBrainz knows more than one artist by this name (from the lookups already kept; unknown counts as no)."""
    path = os.path.join(lms_qobuz.MB_CACHE, hashlib.sha1(name.lower().encode()).hexdigest() + ".json")
    try:
        with open(path) as f:
            return len(json.load(f)) > 1
    except (OSError, ValueError):
        return False


def pick_photo(d, size="hero"):
    """The best picture of the artist: the one chosen by hand; else Wikipedia's portrait (found through MusicBrainz, so
    theirs for certain; a landscape one for the hero), then Qobuz's (the Qobuz artist whose albums are on the shelves),
    then Discogs's, which are found by name alone: not when MusicBrainz knows others by that name (Shift the New York
    band got an electronic duo's), better the album's cover than a stranger's face."""
    mine = chosen_photos.get(key(d.get("name") or ""))
    if mine:
        if mine.get("file"):
            return "/artist-photo/" + (mine["file"].replace(".jpg", "-320.jpg") if size == "thumb" else mine["file"])
        return mine["url"]
    w = d.get("wiki") or {}
    q = (d.get("qobuz") or {}).get("photo") or ""
    photos = [] if shared_name(d.get("name") or "") else d.get("photos") or []
    if size == "thumb":
        return q or w.get("thumb") or (photos[0]["url"] if photos else "")
    if w.get("image") and w.get("w", 0) >= 500:
        img = w["image"].split("?")[0]
        if w.get("w", 0) > 1800:  # Wikipedia's own resizer, at 1920 pixels (one of the widths it keeps): …/thumb/a/ab/F.jpg/3840px-F.jpg, or made so from the original
            if re.search(r"/thumb/.*/\d+px-[^/]+$", img):
                img = re.sub(r"/\d+px-([^/]+)$", r"/1920px-\1", img)
            elif "/commons/" in img and not img.lower().endswith(".svg"):
                img = img.replace("/commons/", "/commons/thumb/", 1) + "/1920px-" + img.rsplit("/", 1)[1]
        return img
    big = [p for p in photos if p["w"] >= 500]
    return q or (big[0]["url"] if big else "") or w.get("image") or (photos[0]["url"] if photos else "")


def heard(name):
    """What the listening log has heard of the artist (read straight from its database, which sits on the same disk), kept a minute."""
    hit = heard_cache.get(key(name))
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    try:
        c = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        rows = c.execute("select outcome, started, played from plays where lower(artist) = ?", (key(name),)).fetchall()
        c.close()
    except Exception:
        return {}
    out = {"plays": len(rows), "finished": sum(1 for r in rows if r[0] == "finished"),
           "skipped": sum(1 for r in rows if r[0] == "skipped" and (r[2] or 0) < 45), "last": round(max((r[1] for r in rows), default=0))}
    heard_cache[key(name)] = (time.time(), out)
    return out


def build_now(name):
    """An artist someone is looking at, fetched at once on a thread of its own, ahead of the crawler."""
    k = key(name)
    if k in building:
        return
    building.add(k)

    def go():
        urgent[0] += 1
        try:
            build(name)
        except Exception:
            pass
        finally:
            urgent[0] -= 1
            building.discard(k)
    threading.Thread(target=go, name="urgent", daemon=True).start()


def profile_for_app(name):
    """The profile as it is now; one never fetched comes back at once with only its name, the app asking again shortly."""
    d, fetched, complete = get_profile(name)
    if d is None:
        build_now(name)
        d = {"name": name}
    elif not complete and time.time() - fetched > RETRY:
        build_now(name)
    out = dict(d)
    out["hero"] = pick_photo(d)
    out["thumb"] = pick_photo(d, "thumb")
    out["partial"] = not all(p in d for p in PARTS) and (key(name) in building or "qobuz" not in d)
    out["heard"] = heard(d.get("qobuz", {}).get("name") or name)
    out["hidden_tags"] = kv_get("hidden-tags", {}).get(key(name), [])
    if shared_name(d.get("name") or name):  # Discogs's pictures, found by name, may be a namesake's: not shown
        out["photos"] = []
    return out


def want(name, front=False):
    k = key(name)
    if k in NOT_ARTISTS or k in wanted_set:
        return
    wanted_set.add(k)
    (wanted.appendleft if front else wanted.append)(name)


# ───────────────────────── the crawler ─────────────────────────
def crawler():
    """Profiles for whatever is wanted first, then the shelves' artists, least recently fetched first; then waits."""
    while True:
        try:
            if wanted:
                name = wanted.popleft()
                wanted_set.discard(key(name))
            else:
                name = next_on_shelves()
            if not name:
                time.sleep(30)
                continue
            crawl_state["current"] = name
            build(name)
            crawl_state["current"] = ""
            time.sleep(3)  # likewise for the artists' photos
        except Exception as e:
            crawl_state["errors"] += 1
            note_error(f"{type(e).__name__}: {e}"[:200])
            time.sleep(10)


def diagnostics():
    """What a tester pastes when something goes wrong: versions, what was found, how far it has got, the last errors.
    No addresses, names or listening."""
    st = {}
    try:
        st = rpc("", "serverstatus", "0", "0", timeout=5)
    except Exception as e:
        st = {"error": type(e).__name__}
    s = settling()
    with lib_lock:
        versions = sum(len(a[10]) for a in library["albums"] if len(a) > 10)
    try:
        groups = sum(1 for p in rpc("", "players", "0", "100", timeout=5).get("players_loop") or [] if p.get("model") == "group" or p.get("modelname") == "Group")
    except Exception:
        groups = "?"
    # Lyrion's My Music settings: which roles count as artists, release types (for how its own browsing looks)
    prefs = ("useUnifiedArtistsList", "trackartistInArtists", "bandInArtists", "composerInArtists", "conductorInArtists", "useTPE2AsAlbumArtist",
             "variousArtistAutoIdentification", "groupArtistAlbumsByReleaseType", "ignoreReleaseTypes", "cleanupReleaseTypes", "groupdiscs", "splitList")
    try:
        my_music = ", ".join(f"{p} {rpc('', 'pref', p, '?', timeout=5).get('_p2', '?')}" for p in prefs)
    except Exception as e:
        my_music = type(e).__name__
    with db() as c:
        tally = {"found": 0, "none": 0, "another": 0}
        for (d,) in c.execute("select data from albums"):
            d = json.loads(d)
            tally["found" if d.get("review") else d.get("why") or "none"] = tally.get("found" if d.get("review") else d.get("why") or "none", 0) + 1
    pieces = f"{tally['found']} found, {tally['none']} none, {tally['another']} about another record, {MAI_FAILED[0]} failed since the start"
    lines = [f"Soundsquatch {VERSION}, Python {sys.version.split()[0]}, {'Docker' if os.path.exists('/.dockerenv') else 'no Docker'}",
             f"Lyrion {st.get('version', st.get('error', '?'))}, language {HAVE.get('language', '?')}, {st.get('player count', '?')} players, login {'yes' if settings['connections']['lms_user'] else 'no'}",
             "Plugins: " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in HAVE.items() if k not in ("language", "mai_lang")),
             f"Library: {s['albums']} albums (+{versions} other versions), {s['artists']} artists; profiled {s['profiled']}, genres to find {s['genres_left']}, credits to find {s['credits_left']}",
             f"Lyrion counts {st.get('info total albums', '?')} albums, {st.get('info total artists', '?')} artists; group players {groups}",
             f"My Music: {my_music}",
             f"Write-ups: {pieces}; Music & Artist Information asked in {', '.join(mai_langs())}{' (its own setting)' if HAVE.get('mai_lang') else ''}",
             "Features at work: " + ", ".join(k for k in settings["features"] if feature(k)),
             f"Listening log: {'its own' if RECORDER['built_in'] else 'the house recorder'}; PIN {'set' if settings['house']['pin'] else 'none'}; music folders {len(MUSIC_DIRS)}",
             f"Crawl: {crawl_state.get('errors', 0)} errors since {time.strftime('%Y-%m-%d %H:%M', time.localtime(crawl_state['started']))}",
             "Last errors:"]
    return "\n".join(lines + (["  " + e for e in list(ERRORS)[-12:]] or ["  none"]))


def settling():
    """How far Soundsquatch has got with what it gathers about the shelves (a new house's first hours): artists profiled,
    albums with genres and credits, and a rough time left. MusicBrainz, one question a second, sets the pace: an artist
    takes about nine, an album's genres one or two, its credits about three. Settled when only a stray few are left."""
    with lib_lock:
        names = list(library["artists"])
        shelf = [copies(a[2], a[1]) for a in library["albums"] if key(a[2]) not in NOT_ARTISTS]
        albums = len(library["albums"])
    # an artist is done when every part of their profile is there or was looked for and isn't to be had (no Wikipedia page)
    tried = lambda d: d is not None and all(p in d or p in d.get("_tried", {}) for p in PARTS)
    profiled = sum(1 for k in names if tried(profiles.get(k, (None,))[0]))
    with db() as c:
        have_genres = {k for (k,) in c.execute("select k from album_genres")}
        have_credits = {k for (k,) in c.execute("select k from credits")}
    genres_left = sum(1 for k in shelf if k not in have_genres)
    credits_left = sum(1 for k in shelf if k not in have_credits) if settings["features"]["credits"] else 0
    left = (len(names) - profiled) * 9 + genres_left * 1.5 + credits_left * 3
    few = lambda n, of: n <= max(3, of * 0.02)
    return {"artists": len(names), "profiled": profiled, "albums": albums, "genres_left": genres_left, "credits_left": credits_left,
            "minutes": round(left / 60), "settled": bool(names) and few(len(names) - profiled, len(names)) and few(genres_left, albums) and few(credits_left, albums)}


def next_on_shelves():
    with lib_lock:
        names = [(a["rank"], a["name"]) for a in library["artists"].values()]
    now = time.time()
    done = 0
    todo = []
    for rank, n in names:
        d, f, comp = get_profile(n)
        tried = (d or {}).get("_tried", {})
        fresh = d is not None and now - f < STALE and all(p in d or now - tried.get(p, 0) < RETRY for p in PARTS)
        if fresh:
            done += 1
        else:
            todo.append((0 if not f else 1, rank, n))  # never fetched first, newest additions first
    crawl_state["done"] = done
    return min(todo)[2] if todo else None


def watcher():
    """Every 20 s, what each room is playing and the next few in its queue: their artists go to the front of the crawl."""
    while True:
        try:
            players = rpc("", "players", "0", "50").get("players_loop") or []
            for p in players:
                if not p.get("connected"):
                    continue
                st = rpc(p["playerid"], "status", "-", "4", "tags:a")
                for t in st.get("playlist_loop") or []:
                    for a in split_artists(t.get("artist") or ""):
                        d, f, comp = get_profile(a)
                        if d is None or (not comp and time.time() - f > RETRY) or time.time() - f > STALE:
                            want(a, front=True)
        except Exception:
            pass
        time.sleep(20)


def split_artists(s):
    """ "A & B", "A, B", "A feat. B": the first named is the one profiled (the band, usually), unless the whole is known."""
    s = s.strip()
    if not s:
        return []
    with lib_lock:
        if key(s) in library["artists"]:
            return [s]
    first = re.split(r"\s+(?:feat\.?|ft\.?|featuring|with|&|and|x|vs\.?)\s+|\s*[,;/]\s*", s, flags=re.I)[0].strip()
    return [first] if first else [s]


def library_loop():
    while True:
        try:
            load_library()
        except Exception as e:
            note_error(f"library: {type(e).__name__}: {e}"[:200])
        time.sleep(3600)  # a safety net only: Lyrion says when a scan is done (radio_events), and the shelves are read then


# ───────────────────────── albums, stories, home ─────────────────────────
def album_tracks(album_id):
    """An album's tracks, kept until the library is next scanned."""
    scan = str(library["scan"])
    with db() as c:
        got = c.execute("select data from tracks where id = ? and scan = ?", (album_id, scan)).fetchone()
    if got:
        return json.loads(got[0])
    found = rpc("", "titles", "0", "300", f"album_id:{album_id}", "sort:tracknum", "tags:atdyJoTIrsiqA", timeout=20).get("titles_loop") or []
    out = [{"id": t.get("id"), "n": t.get("tracknum") or "", "disc": t.get("disc") or "", "title": t.get("title") or "", "artist": t.get("artist") or "",
            "album": t.get("album") or "", "duration": float(t.get("duration") or 0), "composer": t.get("composer") or "", "year": t.get("year") or ""} for t in found]
    with db_lock, db() as c:
        c.execute("insert or replace into tracks values (?,?,?)", (album_id, scan, json.dumps(out, ensure_ascii=False)))
    return out


def about_another(review, artist, title=""):
    """Whether Wikipedia's piece is about someone else's record of that name: its opening names the maker ("…is the
    eleventh studio album by the English musician David Bowie"), and none of its "album by …" says this artist (nor "of
    the same name"), or it opens on another title. Low's EP Low got Bowie's Low."""
    import unicodedata
    plain = lambda t: re.sub(r"[^a-z0-9]", "", "".join(c for c in unicodedata.normalize("NFKD", t.lower().replace("&", "and")) if not unicodedata.combining(c)))
    text = re.sub(r"\s+", " ", review or "")[:600]
    # the piece opens on another record's name: SAULT's 10 got their Air ("Air is the sixth studio album by…")
    opening = re.match(r"(.{1,120}?)\s+(?:is|was)\s+(?:the|an?)\b", text)
    if opening and title.strip():
        named, want = (re.sub(r"^the", "", plain(t)) for t in (opening.group(1), re.sub(r"\s*[(\[].*$", "", title)))
        self_titled = named == re.sub(r"^the", "", plain(artist)) and re.match(r".{0,160}?\b(?:is|was) the [^.]{0,60}\balbum\b", text)
        if named and want and want not in named and named not in want and not self_titled:  # (Peter Gabriel's III: "Peter Gabriel is the third…")
            return True
    makers = re.findall(r"\b(?:album|EP|LP|record|single|compilation|soundtrack|mixtape|box set)\s+by\s+(.{0,90})", text)
    if not makers:
        return False
    first = re.sub(r"^the", "", plain(re.split(r"\s*(?:,|&|/| and | feat\.? | with )\s*", artist)[0]))
    if any(first and first in plain(m) or "of the same name" in m for m in makers):
        return False
    untitled = re.sub(re.escape(re.sub(r"\s*[(\[].*$", "", title).strip()), " ", text, flags=re.I) if title.strip() else text
    return not (first and first in plain(untitled))  # named elsewhere in the opening (Revolver's starts on the remix)


def mai_langs():
    """The Wikipedias Music & Artist Information is asked in: the one chosen in its own settings, else English (the app's
    language, where the long pieces are) and then Lyrion's own. Left to itself it asks in Lyrion's language, so a Dutch
    house got Kid A's 3,000 Dutch characters over the 34,000 English ones."""
    if HAVE.get("mai_lang"):
        return [HAVE["mai_lang"]]
    own = str(HAVE.get("language") or "EN").lower()
    return ["en"] + ([own] if own != "en" else [])


MAI_FAILED = [0]  # write-ups and stories whose lookup didn't get through, since the start (for the diagnostics)


NOTHING_AGAIN = 14 * 86400  # a record or artist Music & Artist Information had nothing on is asked again after two weeks


def review_lookup(artist, title, album_id=None, fetch=True, again=False):
    """Wikipedia's piece on an album (through Music & Artist Information) and why there is none: (text, why), why ""
    when found, "none" (nothing written), "another" (the piece by that name is about another record), "failed" (the
    lookup itself didn't get through: noted, never kept) or "no-mai" (the plugin isn't there). A piece found is kept for
    good; none is asked again after NOTHING_AGAIN, or at once when again. (None, None) when not yet asked and fetch is
    off. Asked by Lyrion's album id first, so the plugin can use the record's own tags (its MusicBrainz id, a review
    file beside it), then by name."""
    if not (title or "").strip():  # no title to go by (the library still loading after a start): nothing asked, nothing kept
        return ("", "none") if fetch else (None, None)
    k = copies(artist, title)
    with db() as c:
        got = c.execute("select data, fetched from albums where k = ?", (k,)).fetchone()
    plain = re.sub(r"\s*[(\[].*?[)\]]", "", title)  # "(Remastered)" and the like: Wikipedia knows the album without them
    if got:
        data = json.loads(got[0])
        if data.get("review") and about_another(data["review"], artist, plain):  # kept before the check knew better
            data, got = {"review": "", "why": "another"}, (None, time.time())
            with db_lock, db() as c:
                c.execute("insert or replace into albums values (?,?,?)", (k, json.dumps(data), got[1]))
        if data.get("review"):
            return tidy(data["review"]), ""
        if not again and time.time() - got[1] < NOTHING_AGAIN:
            return "", data.get("why") or "none"
    if not fetch:
        return None, None
    if HAVE.get("mai") is False:
        return "", "no-mai"
    asks = [ask + [f"lang:{lang}"] for lang in mai_langs()
            for ask in ([[f"album_id:{int(album_id)}"]] if album_id and int(album_id) > 0 else []) + [[f"artist:{artist}", f"album:{plain}"]]]
    review = ""
    try:
        for ask in asks:
            review = (rpc("", "musicartistinfo", "albumreview", *ask, timeout=20).get("albumreview") or "").strip()
            if review:
                break
    except Exception as e:
        MAI_FAILED[0] += 1
        note_error(f"album piece, {artist} - {title}: {type(e).__name__}: {e}"[:200])
        return "", "failed"
    why = "" if review else "none"
    if review and about_another(review, artist, plain):
        review, why = "", "another"  # another record of that name: none rather than the wrong one
    with db_lock, db() as c:
        c.execute("insert or replace into albums values (?,?,?)", (k, json.dumps({"review": review, "why": why}), time.time()))
    return tidy(review), why


def review_of(artist, title, fetch=True, album_id=None):
    return review_lookup(artist, title, album_id, fetch)[0]


def album_row(album_id):
    """An album on the shelves by its id, or one of an album's other versions, as a row of its own."""
    with lib_lock:
        for a in library["albums"]:
            if a[0] == album_id:
                return a
            for v in a[10] if len(a) > 10 else []:
                if v[0] == album_id:
                    return [v[0], v[1], a[2], v[3], v[4], a[5], v[2], a[7], a[8], v[5], [], v[6] if len(v) > 6 else 0, a[0]]  # [12]: the album it is a pressing of
    return None


def without_versions(gone):
    """The shelves with these Lyrion albums taken off: a removed version leaves its album's versions; when the version
    shown goes, the best one left stands in its place; an album with none left goes."""
    out = []
    for x in library["albums"]:
        left = [v for v in x[10] if v[0] not in gone]
        if x[0] not in gone:
            out.append(x[:10] + [left] + x[11:12])
        elif left:
            v = left[0]
            out.append([v[0], v[1], x[2], v[3], v[4], x[5], v[2], x[7], x[8], v[5], left[1:], max([v[6] if len(v) > 6 else 0] + [w[6] for w in left[1:] if len(w) > 6])])
    return out


def album(album_id):
    """The tracks at once, and the review when it is already kept (else null: the app asks /api/review for it)."""
    tracks = album_tracks(album_id)
    row = album_row(album_id)
    artist, title = (row[2], row[1]) if row else ((tracks[0]["artist"] if tracks else ""), (tracks[0]["album"] if tracks else ""))
    if not get_profile(artist)[0]:
        want(artist, front=True)
    text, why = review_lookup(artist, title, fetch=False)
    return {"id": album_id, "album": title, "artist": artist, "review": text, "why": why, "tracks": tracks}


# ───────────────────────── a record not on the shelves: its own page, from Qobuz ─────────────────────────
AWAY = {}  # (artist, title) → (when asked, the page), a day
AWAY_DETAILS = {"Genre": "genre", "Qobuz Release Type": "type", "Duration": "length", "Released at": "released", "Music Label": "label"}


def away_album(artist, title, player, fresh=False):
    """A record off the shelves, as a page: on the shelves after all → its album id; else Qobuz's release of that name by
    that artist (the plugin's search, then the release's own menu): its songs, the facts its menu lists, whether it's a
    favourite, and the search and place that play, queue or keep it."""
    artist, title = (artist or "").strip()[:200], (title or "").strip()[:200]
    if not title:
        return {"error": "no record named"}
    want = lms_qobuz.plain(re.sub(r"\s*[(\[].*$", "", title)) or lms_qobuz.plain(title)
    for a in list(library["albums"]):
        if (not artist or key(a[2]) == key(artist)) and lms_qobuz.plain(re.sub(r"\s*[(\[].*$", "", a[1])) == want:
            return {"album_id": a[0]}
    k = (key(artist), want)
    hit = AWAY.get(k)
    if hit and not fresh and time.time() - hit[0] < 86400:
        return hit[1]
    out = {"artist": artist, "album": title, "tracks": [], "details": {}, "kept": False}
    player = player if lms_qobuz.PLAYER.match(player or "") else PLAYER  # the plugin answers for a player; any will do to look
    if not svc() or not lms_qobuz.PLAYER.match(player or ""):
        return dict(out, error="no Qobuz")
    out["service"] = svc().label
    try:
        page = svc().release(artist, title, want, player)
    except Exception as e:
        note_error(f"{svc().label} for {artist} - {title}: {type(e).__name__}: {e}")
        return dict(out, error="failed")
    if not page:
        AWAY[k] = (time.time(), dict(out, error="not on Qobuz"))
        return AWAY[k][1]
    page["service"] = svc().label
    AWAY[k] = (time.time(), page)
    return page


def album_ratings(album_id):
    """An album's track ratings in Lyrion (Ratings Light keeps them there, 0-100, 20 a star): each rated track's, and
    their average in stars to the half star (unrated tracks left out of it)."""
    got = rpc("", "titles", "0", "500", f"album_id:{int(album_id)}", "tags:R").get("titles_loop") or []
    rated = {t["id"]: int(t.get("rating") or 0) for t in got if int(t.get("rating") or 0) > 0}
    avg = round(sum(rated.values()) / len(rated) / 10) / 2 if rated else 0
    return {"tracks": len(got), "rated": len(rated), "stars": avg, "ratings": rated}


def rate_album(req):
    """Every track of the album rated the same, in Lyrion through Ratings Light (stars 0-5, halves allowed; 0 unrates)."""
    if not HAVE.get("ratings"):
        return {"error": "Ratings Light isn't installed"}
    stars = max(0.0, min(5.0, round(float(req.get("stars") or 0) * 2) / 2))
    got = rpc("", "ratingslight", "ratealbum", str(int(req.get("album_id") or 0)), str(int(stars * 20)))
    return dict(album_ratings(int(req.get("album_id") or 0)), count=int(got.get("count") or 0), scanning=bool(got.get("scanning")))


def ratings_ready():
    """Album stars are Lyrion's (Ratings Light's) once the house's own have gone over to it, or when there were none."""
    if kv_get("ratings-carried"):
        return True
    with db() as c:
        return not c.execute("select 1 from marks where kind = 'album' and rating > 0 limit 1").fetchone()


def carry_ratings():
    """Once, when Ratings Light is found: the album stars given in Soundsquatch before it go to those albums' tracks in
    Lyrion (only tracks not yet rated), so the stars the house gave aren't lost when the albums' stars become Lyrion's."""
    for _ in range(120):  # the library first (it loads after the start)
        if library["albums"]:
            break
        time.sleep(10)
    if not HAVE.get("ratings") or kv_get("ratings-carried"):
        return
    with db() as c:
        starred = dict(c.execute("select k, rating from marks where kind = 'album' and rating > 0").fetchall())
    done = 0
    with lib_lock:
        rows = [r for r in library["albums"] if copies(r[2], r[1]) in starred]
    for r in rows:
        for aid in [r[0]] + [v[0] for v in (r[10] if len(r) > 10 and r[10] else [])]:
            if not str(aid).isdigit():
                continue  # not one of Lyrion's albums
            try:
                done += int(rpc("", "ratingslight", "ratealbum", str(int(aid)), str(int(starred[copies(r[2], r[1])]) * 20), "1").get("count") or 0)
            except Exception as e:
                note_error(f"carrying ratings: {type(e).__name__}: {e}"[:200])
                return  # asked again at the next start
    kv_set("ratings-carried", {"at": time.time(), "albums": len(rows), "tracks": done})


def away_play(req):
    """One song of a record off the shelves, played from there on (its place in the release's menu)."""
    term, player = (req.get("term") or "")[:120], req.get("player") or PLAYER
    if not lms_qobuz.PLAYER.match(player) or not term:
        return {"error": "no such player or record"}
    if not svc():
        return {"error": "no streaming service"}
    return svc().play_release(term, int(req.get("index") or 0), int(req["track"]) if req.get("track") is not None else None,
                              req.get("how") if req.get("how") in ("play", "insert") else "play", player)


def review(album_id, again=False):
    row = album_row(album_id)
    if not row:
        tracks = album_tracks(album_id)
        row = [album_id, tracks[0]["album"], tracks[0]["artist"]] if tracks else None
    if not row:
        return {"review": "", "why": "none"}
    text, why = review_lookup(row[2], row[1], album_id, again=again)
    return {"review": text, "why": why}


def warmer():
    """Every album made ready before it is opened, newest first: first every cover (at each size) and track list, which
    are quick, then Wikipedia's reviews, which take a few seconds each. Then it waits for the next scan."""
    done_scan = None
    while True:
        try:
            scan = library["scan"]
            if not library["albums"] or scan == done_scan:
                time.sleep(60)
                continue
            albums = list(library["albums"])
            with db() as c:
                have = {r[0] for r in c.execute("select id from tracks where scan = ?", (str(scan),))}
            for a in albums:
                if library["scan"] != scan:
                    break
                try:
                    if a[4] and not os.path.exists(cover_path(a[4], 300)):
                        cover_file(a[4], 300)
                    if a[0] not in have:
                        album_tracks(a[0])
                except Exception:
                    pass
                crawl_state["warmed"] = crawl_state.get("warmed", 0) + 1
            for a in albums:
                if library["scan"] != scan:
                    break
                if review_of(a[2], a[1], fetch=False) is None:
                    try:
                        review_of(a[2], a[1], album_id=a[0])
                    except Exception:
                        pass
                    time.sleep(4)  # gently: Music & Artist Information's service and Wikipedia turned the first, faster pass away
            else:
                done_scan = scan
        except Exception as e:
            note_error(f"warmer: {type(e).__name__}: {e}"[:200])
            time.sleep(30)


def tidy(text):
    """Text as Music & Artist Information hands it over: lines broken at 80 characters, paragraphs by blank lines."""
    paras = re.split(r"\n\s*\n", (text or "").replace("\r", ""))
    out = []
    for p in paras:
        p = re.sub(r"\s*\n\s*", " ", p).strip()
        head = re.match(r"^(.*?)\s*[-=]{3,}$", p) or re.match(r"^=+\s*(.*?)\s*=+$", p)  # Wikipedia's section headings, underlined
        if head:
            p = "§ " + head.group(1).strip() if head.group(1).strip() else ""
        elif p and not p.startswith("§") and len(p) < 60 and len(p.split()) <= 6 and p[0].isupper() and not re.search(r"[.!?:;,\"'”’)\]]$", p):
            p = "§ " + p  # a sub-heading that came without its underline ("Critical reception"): a line no sentence ends
        if p:
            out.append(p)
    return "\n\n".join(out)


def story(name, again=False):
    """Wikipedia's whole story of an artist (through Music & Artist Information) and why there is none, as review_lookup:
    (text, why). Asked with their MusicBrainz id when the profile has it, so a namesake's story doesn't come instead."""
    with db() as c:
        got = c.execute("select story, fetched from stories where k = ?", (key(name),)).fetchone()
    if got and (got[0] and time.time() - got[1] < STALE or not again and not got[0] and time.time() - got[1] < NOTHING_AGAIN):
        return got[0], "" if got[0] else "none"
    if HAVE.get("mai") is False:
        return "", "no-mai"
    mbid = ((get_profile(name)[0] or {}).get("mb") or {}).get("mbid") or ""
    text = ""
    try:
        for lang in mai_langs():
            text = tidy(rpc("", "musicartistinfo", "biography", f"artist:{name}", *([f"mbid:{mbid}"] if mbid else []), f"lang:{lang}", timeout=25).get("biography") or "")
            if text:
                break
    except Exception as e:
        MAI_FAILED[0] += 1
        note_error(f"story, {name}: {type(e).__name__}: {e}"[:200])
        return "", "failed"
    text = re.sub(r"<[^>]+>", "", text)
    with db_lock, db() as c:
        c.execute("insert or replace into stories values (?,?,?)", (key(name), text, time.time()))
    return text, "" if text else "none"


cover_cache = {}


STAGE_PHOTOS = os.path.join(HERE, "stage-photos.json")


def venue_picture(venue, place, artist, rng):
    """A picture for a show's spread: a stage, any stage (small rooms, lights and gear, no recognisable faces), from
    stage-photos.json, chosen by hand from Wikimedia Commons. (url, credit)"""
    try:
        photos = json.load(open(STAGE_PHOTOS))["photos"]
        p = rng.choice(photos)
        return p["url"], p["credit"]
    except Exception:
        return "", ""


# ───────────────────────── the shelves' people: their birthdays, and the days they died ─────────────────────────
# ───────────────────────── artist radio: a station of one ─────────────────────────
ASIDE = re.compile(r"[(\[][^)\]]*\b(live|remix|mix|demo|edit|version|instrumental|acoustic|session|take)\b|^\s*(intro|outro|interlude|untitled|skit|reprise)\b|\b(interlude|reprise)\s*$", re.I)


def album_word(a):  # an album as one record, whoever it's filed under: "Mogwai Young Team (Remastered)" is "Young Team (Deluxe)"
    return copies("", re.sub(re.escape(a[2]), "", a[1], flags=re.I))


def best_tracks(artist, n, rng, not_from=()):
    """An artist's tracks from the shelves for a radio's start: whole songs (no interludes, live cuts, remixes or demos),
    the hearted, the starred and the often finished first, never two from one album; a little chance in the order."""
    with lib_lock:
        mine = [a for a in library["albums"] if key(a[2]) == key(artist)]
    with db() as c:
        marks = {k: (h, r) for k, h, r in c.execute("select k, heart, rating from marks where kind = 'track'")}
        bans = {(k, kk) for k, kk in c.execute("select kind, k from bans")}
    heard = Counter()
    try:
        lc = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        for title, outcome in lc.execute("select title, outcome from plays where artist like ?", (f"%{artist}%",)):
            heard[track_word(title)] += 1 if outcome == "finished" else -1 if outcome == "skipped" else 0
        lc.close()
    except Exception:
        pass
    mine = [a for a in mine if album_word(a) not in not_from]
    studio = [a for a in mine if not re.search(r"\blive\b|^\d{4}-\d\d-\d\d", a[1], re.I)] or mine  # live albums (and dated tapes) only when there is nothing else
    found = []
    for a in studio:
        for t in album_tracks(a[0]):
            if not (100 <= t["duration"] <= 900) or ASIDE.search(t["title"]) or banned(t, bans):
                continue
            h, r = marks.get(copies(t.get("artist") or a[2], a[1]) + "|" + track_word(t["title"]), (0, 0))
            album = album_word(a)
            found.append((6 * h + r + min(heard[track_word(t["title"])], 5) + rng.random() * 3, album, track_word(t["title"]), t["id"]))
    found.sort(reverse=True)
    out, albums, songs = [], set(), set()
    for _, album, song, tid in found:
        if album not in albums and song not in songs:  # never two from one album, nor one song twice
            out.append(tid)
            albums.add(album)
            songs.add(song)
        if len(out) == n:
            break
    return out


def artist_radio(req):
    """Artist radio, as a station of one: three or four of their best tracks from different albums, with one each from
    three or four artists like them on the shelves (Qobuz's similar artists, MusicBrainz's ties: members' other bands
    and the like) between, then the room's radio carries on from all of them."""
    artist, player = (req.get("artist") or "").strip(), req.get("player") or ""
    if not artist or not lms_qobuz.PLAYER.match(player):
        return {"error": "no artist or room"}
    rng = random.Random()
    theirs = best_tracks(artist, 4, rng)
    if not theirs:
        return {"error": f"none of {artist}'s songs on the shelves to start from"}
    with lib_lock:
        shelf = {k: a["name"] for k, a in library["artists"].items()}
    d = profiles.get(key(artist), ({},))[0] or {}
    kin = [x["name"] for x in (d.get("qobuz") or {}).get("similar", [])] + [r.get("name") or "" for r in (d.get("mb") or {}).get("rels") or []]
    kin = [shelf[key(x)] for x in dict.fromkeys(kin) if key(x) in shelf and key(x) != key(artist)]
    rng.shuffle(kin)
    others, names = [], []
    with lib_lock:
        theirs_albums = {album_word(a) for a in library["albums"] if key(a[2]) == key(artist)}
    for name in kin:
        got = best_tracks(name, 1, rng, theirs_albums)  # never one of their own albums filed under a member's name
        if got:
            others += got
            names.append(name)
        if len(others) == 4:
            break
    order = theirs[:2]  # two of theirs, then one like them and one of theirs in turn
    for i in range(max(len(theirs) - 2, len(others))):
        order += others[i:i + 1] + theirs[2 + i:3 + i]
    if req.get("dry"):  # what it would queue, played nowhere
        got = {}
        for t in order:
            x = (rpc("", "titles", "0", "1", f"track_id:{t}", "tags:al").get("titles_loop") or [{}])[0]
            got[t] = f"{x.get('artist')} – {x.get('title')} ({x.get('album')})"
        return {"ok": True, "would": [got[t] for t in order], "kin": names}
    rpc(player, "playlistcontrol", "cmd:load", "track_id:" + ",".join(str(t) for t in order))
    return {"ok": True, "tracks": len(order), "kin": names}


def focuses(req=None):
    """The house's kept focuses (the Albums page's combined filters, named): read, or replaced with {"list": […]}."""
    if req is not None:
        keep = [{"name": str(f.get("name") or "").strip()[:40], "f": {k: [str(v)[:40] for v in (vs or [])][:40] for k, vs in (f.get("f") or {}).items() if isinstance(vs, list)}}
                for f in req.get("list") or [] if isinstance(f, dict) and str(f.get("name") or "").strip()][:50]
        kv_set("focuses", keep)
    return {"list": kv_get("focuses", [])}


def heard_albums():
    """When each album was last played and how often, from the listening log: {copies key: [last, plays]} (Focus's Listening)."""
    out = {}
    try:
        lc = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        for artist, album, last, n in lc.execute("select artist, album, max(started), count(*) from plays where album != '' group by artist, album"):
            k = copies(artist or "", album or "")
            if k not in out or last > out[k][0]:
                out[k] = [round(last), n + (out[k][1] if k in out else 0)]
        lc.close()
    except Exception:
        pass
    return out


def play_albums(req):
    """A mix from a set of albums (a Focus): one whole song from each of up to twelve of them, drawn at random, then the
    room's radio carries on."""
    player, ids = req.get("player") or "", [int(i) for i in req.get("ids") or [] if str(i).lstrip("-").isdigit()]
    if not lms_qobuz.PLAYER.match(player) or not ids:
        return {"error": "nothing to play"}
    rng = random.Random()
    rng.shuffle(ids)
    with db() as c:
        bans = {(k, kk) for k, kk in c.execute("select kind, k from bans")}
    picks = []
    for i in ids[:30]:
        songs = [t for t in album_tracks(i) if 100 <= t["duration"] <= 900 and not ASIDE.search(t["title"]) and not banned(t, bans)]
        if songs:
            picks.append(rng.choice(songs)["id"])
        if len(picks) == 12:
            break
    if not picks:
        return {"error": "no songs to start from"}
    rpc(player, "playlistcontrol", "cmd:load", "track_id:" + ",".join(str(t) for t in picks))
    return {"ok": True, "tracks": len(picks)}


def people_on_shelves():
    """The individuals behind the shelves: each solo artist, and each member of each band (MusicBrainz's): {mbid: (name,
    the artist on the shelves whose records they are, whether as a member)}. Bands themselves are not born and do not die."""
    with lib_lock:
        shelf = dict(library["artists"])
    out = {}
    for k, a in shelf.items():
        mb = (profiles.get(k, ({},))[0] or {}).get("mb") or {}
        if mb.get("type") == "Person" and mb.get("mbid"):
            out[mb["mbid"]] = (a["name"], a["name"], False)
        elif mb.get("mbid"):
            for r in mb.get("rels") or []:
                if r.get("type") == "member of band" and r.get("dir") == "backward" and r.get("mbid"):
                    out.setdefault(r["mbid"], (r.get("name") or "", a["name"], True))
    return out


def lifedates_loop():
    """Each of the shelves' people's birth and death dates, from MusicBrainz at its pace (a few an hour once all are
    known): the living asked again every three months."""
    time.sleep(240)
    while True:
        try:
            people = people_on_shelves()
            with db() as c:
                have = {m: (died, fetched) for m, died, fetched in c.execute("select mbid, died, fetched from life_dates")}
            todo = [m for m in people if m not in have or (not have[m][0] and have[m][1] < time.time() - 90 * 86400)]
            crawl_state["people_left"] = len(todo)
            if not todo:
                time.sleep(6 * 3600)
                continue
            for m in todo[:100]:
                got = mb_get(f"artist/{m}", inc="url-rels")
                if not got.get("id"):
                    continue
                life = got.get("life-span") or {}
                wd = next(((r.get("url") or {}).get("resource") or "" for r in got.get("relations") or [] if r.get("type") == "wikidata"), "")
                with db_lock, db() as c:
                    c.execute("insert or replace into life_dates values (?,?,?,?,?,?)", (m, got.get("name") or people[m][0], life.get("begin") or "",
                              life.get("end") or "", wd if got.get("type") == "Person" else "", time.time()))
                crawl_state["people_left"] -= 1
        except Exception as e:
            note_error(f"people: {type(e).__name__}: {e}"[:200])
            time.sleep(300)


def people_story(md, today, rng):
    """One of the shelves' people born on this date (living) or who died on it: the artists most played and the round
    numbers first. With their Wikipedia portrait and opening, else their band's (or their own) picture."""
    people = people_on_shelves()
    with db() as c:
        rows = {m: (n, b, d, w) for m, n, b, d, w in c.execute("select mbid, name, born, died, wikidata from life_dates")}
    plays = Counter()
    try:
        lc = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        for artist, n in lc.execute("select artist, count(*) from plays where started > ? group by artist", (time.time() - 365 * 86400,)):
            for x in split_artists(artist or ""):
                plays[key(x)] += n
        lc.close()
    except Exception:
        pass
    found = []
    for m, (name, artist, member) in people.items():
        if m not in rows:
            continue
        n, born, died, wd = rows[m]
        for kind, date in (("born", born), ("died", died)):
            if len(date) == 10 and date[5:] == md and (kind == "died" or not died):
                years = int(today[:4]) - int(date[:4])
                if years > 0:
                    round_ = 25 if years % 10 == 0 else 10 if years % 5 == 0 else 0
                    found.append((1 + plays[key(artist)] + round_, kind, m, n or name, artist, member, date, years, born, died, wd))
    if not found:
        return None
    w, kind, m, name, artist, member, date, years, born, died, wd = rng.choices(found, weights=[f[0] for f in found])[0]
    wiki = {}
    try:
        wiki = part_wiki({"wikidata": wd}) if wd else {}
    except Exception:
        pass
    d = profiles.get(key(artist), ({},))[0] or {}
    pic = wiki.get("image") if wiki.get("w", 0) >= 400 else ""
    return {"kind": kind, "name": name, "artist": artist, "member": member, "date": date, "years": years,
            "born": born[:4], "died": died[:4], "pic": pic or pick_photo(dict(d, name=artist)) or wiki.get("image") or "",
            "text": (wiki.get("extract") or "")[:600], "others": len(found) - 1}


def cover_stories():
    """Discover's cover, a new one each day: an album on the shelves released on this date (MusicBrainz's dates, from the
    profiles), a show in the Archive collections recorded on this date, and a record not heard lately. Each is drawn so
    the same day gives the same stories."""
    today = time.strftime("%Y-%m-%d")
    if cover_cache.get("day") == today:
        return cover_cache["data"]
    saved = os.path.join(DATA, "cover-today.json")  # the day's cover, the same all day, restarts and all
    try:
        with open(saved) as f:
            got = json.load(f)
        if got.get("date") == today and got.get("stories"):
            cover_cache.update(day=today, data=got)
            return got
    except (OSError, ValueError):
        pass
    md, rng = today[5:], random.Random("cover" + today)
    with lib_lock:
        albums = list(library["albums"])
    stories = []
    # on this day: the shelves' albums whose release fell on this date
    dated = []
    for a in albums:
        d = profiles.get(key(a[2]), ({},))[0] or {}
        for g in d.get("rgs") or []:
            if len(g["date"]) == 10 and g["date"][5:] == md and lms_qobuz.plain(g["title"]) == lms_qobuz.plain(a[1]):
                dated.append((a, g["date"]))
                break
    if dated:
        dated.sort(key=lambda x: (not x[0][4], x[1]))  # with a cover first
        a, date = rng.choice([x for x in dated if x[0][4]] or dated)
        try:
            review = review_of(a[2], a[1], album_id=a[0]) or ""  # fetched now if the background pass has not reached it
        except Exception:
            review = ""
        stories.append({"kind": "day", "album_id": a[0], "title": a[1], "artist": a[2], "art": a[4], "date": date, "years": int(today[:4]) - int(date[:4]),
                        "text": review.split("\n\n")[0][:600] if review else "", "others": len(dated) - 1})
    # the shelves' people: a birthday, or the day one of them died
    try:
        st = people_story(md, today, rng)
        if st:
            stories.append(st)
    except Exception as e:
        note_error(f"cover people: {type(e).__name__}: {e}"[:200])
    # on this night: a show from the plugin's collections recorded on this date (its identifier carries the date)
    try:
        cols = rpc("", "pref", "plugin.archivelma:collections", "?").get("_p2") or []
        if cols:
            q = "collection:(" + " OR ".join(cols) + f") AND identifier:*-{md}*"
            got = get_json("https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
                [("q", q), ("fl[]", "identifier"), ("fl[]", "title"), ("fl[]", "creator"), ("fl[]", "date"), ("fl[]", "venue"), ("fl[]", "coverage"), ("rows", "200"), ("output", "json")]), timeout=30)
            shows = [x for x in got.get("response", {}).get("docs", []) if str(x.get("date", ""))[5:10] == md]
            mine = [x for x in shows if key(x.get("creator") if isinstance(x.get("creator"), str) else (x.get("creator") or [""])[0]) in library["artists"]]
            if shows:
                x = rng.choice(mine or shows)
                creator = x.get("creator") if isinstance(x.get("creator"), str) else (x.get("creator") or [""])[0]
                bg, credit = venue_picture(x.get("venue") or "", x.get("coverage") or "", creator, rng)
                stories.append({"kind": "night", "bg": bg, "credit": credit, "id": x["identifier"], "title": x.get("title") or "", "artist": creator, "venue": x.get("venue") or "",
                                "place": x.get("coverage") or "", "date": str(x.get("date"))[:10], "years": int(today[:4]) - int(str(x.get("date"))[:4]),
                                "image": f"https://archive.org/services/img/{x['identifier']}", "others": len(shows) - 1})
    except Exception as e:
        note_error(f"cover night: {type(e).__name__}: {e}"[:200])
    # record of the day: one not heard lately, with a cover and, where there is one, a review
    pool = [a for a in albums if a[4] and a[5] > 30]
    try:
        c = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        heard = {copies(r[0] or "", r[1] or "") for r in c.execute("select artist, album from plays where started > ?", (time.time() - 90 * 86400,))}
        c.close()
        pool = [a for a in pool if copies(a[2], a[1]) not in heard] or pool
    except Exception:
        pass
    for a in rng.sample(pool, min(25, len(pool))):
        review = review_of(a[2], a[1], fetch=False) or ""
        if review or a is pool[-1]:
            stories.append({"kind": "record", "album_id": a[0], "title": a[1], "artist": a[2], "art": a[4], "year": a[3], "text": review.split("\n\n")[0][:600]})
            break
    else:
        if pool:
            a = rng.choice(pool)
            stories.append({"kind": "record", "album_id": a[0], "title": a[1], "artist": a[2], "art": a[4], "year": a[3], "text": ""})
    out = {"date": today, "stories": stories}
    if stories:
        cover_cache.update(day=today, data=out)
        with open(saved + ".tmp", "w") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(saved + ".tmp", saved)
    return out


STUDIO = re.compile(r"producer|mixing|engineer|recording|remix|master|programming|edit", re.I)  # the studio's work, not the playing
NOT_MUSIC = re.compile(r"copyright|publish|legal|misc|booking|manage|label|liner|photo|design|art direction|illustrat|composer|lyricist|writer", re.I)
credit_index = [0, []]


def credit_people(albums, artists, profs):
    """The people the shelves' credits share, each with one song (or, for a producer, one record) for each of the
    shelves' artists they worked with, leaving out their own records and their band's. Three kinds, the most telling
    first: "guest", an artist on the shelves playing on another's record; "player", a session hand (who played, not who
    engineered or mixed); "producer", only one with a name of their own (on the shelves, or producing five or more of its
    artists). Kept an hour (it reads every album's credits)."""
    if time.time() - credit_index[0] < 3600:
        return credit_index[1]
    if not profs:  # who is in which band comes from the profiles: without them, a band's own would count as outside work
        return []
    by_key = {copies(a[2], a[1]): a for a in albums if key(a[2]) not in NOT_ARTISTS}
    members = {k: {key(r.get("name")) for r in (d.get("mb") or {}).get("rels", []) if r.get("type") in ("member of band", "is person")}
               for k, d in profs.items() if k in artists}
    plain = lambda s: re.sub(r"[^a-z0-9]", "", s)
    shelved = {plain(k) for k in artists}
    who, names = {}, {}
    with db() as c:
        rows = c.execute("select k, data from credits").fetchall()
    for k, data in rows:
        a = by_key.get(k)
        if not a:
            continue
        try:
            d = json.loads(data)
        except ValueError:
            continue
        ak = key(a[2])
        for t in d.get("tracks") or []:
            for p in t.get("people") or []:
                if not (isinstance(p, list) and len(p) > 2 and p[1]) or NOT_MUSIC.search(p[2] or ""):
                    continue
                pk = key(p[0])
                if plain(pk) == plain(ak) or pk in members.get(ak, ()) or ak in members.get(pk, ()):
                    continue
                names[p[1]] = p[0]
                on = who.setdefault(p[1], {}).setdefault(ak, {"artist": a[2], "played": {}, "studio": {}})
                side = on["studio" if STUDIO.search(p[2]) else "played"]
                side.setdefault((a[0], a[1], a[3], tuple(a[8] or ()), t.get("n"), t.get("title") or ""), []).append(p[2])
    out = []
    for mbid, on in who.items():
        guest = plain(key(names[mbid])) in shelved
        played = {ak: v for ak, v in on.items() if v["played"]}
        studio = {ak: v for ak, v in on.items() if v["studio"]}
        if guest and played or len(played) >= 2:  # an artist on the shelves on one other's record is a connection already
            kind, use = ("guest" if guest else "player"), played
        elif len(studio) >= 2 and (guest or len(studio) >= 5):
            kind, use = "producer", studio
        else:
            continue
        rows = []
        for ak, v in use.items():
            if kind == "producer":  # a record, not a song: the album they worked on most
                albums_ = Counter((x[0], x[1], x[2], x[3]) for x in v["studio"])
                (aid, title, year, genres), _ = albums_.most_common(1)[0]
                roles = sorted({r for x, rs in v["studio"].items() if x[0] == aid for r in rs})
                rows.append({"artist": v["artist"], "album_id": aid, "album": title, "year": year, "genres": list(genres), "song": "", "n": 0, "roles": roles})
            else:  # a song: the one they did most on
                x, roles = max(v["played"].items(), key=lambda kv: len(kv[1]))
                rows.append({"artist": v["artist"], "album_id": x[0], "album": x[1], "year": x[2], "genres": list(x[3]), "song": x[5], "n": x[4], "roles": sorted(set(roles))})
        out.append({"kind": kind, "name": names[mbid], "mbid": mbid, "on": rows})
    credit_index[:] = [time.time(), out]
    return out


def leap(rows):
    """How far a connection reaches: genres that don't overlap, and the years between its records (0 to 2)."""
    best = 0
    for i, x in enumerate(rows):
        for y in rows[i + 1:]:
            gx, gy = set(x["genres"]), set(y["genres"])
            apart = 1 - len(gx & gy) / len(gx | gy) if gx and gy else 0.5
            years = min(abs((x["year"] or 0) - (y["year"] or 0)), 30) / 30 if x["year"] and y["year"] else 0
            best = max(best, apart + years)
    return best


def credit_links(albums, artists, profs, links, rng, today):
    """Discover's connections, chosen once a day: four people the shelves' credits share (two of its own artists on
    each other's records, a session player, a producer with a name; nobody again for ninety days), each reaching as
    far as it can (genres and decades apart). Without credits, MusicBrainz's ties between artists on the shelves."""
    kept = kv_get("connections_day", {})
    if kept.get("date") == today and kept.get("picks"):
        return kept["picks"]
    seen = {m: d for m, d in (kv_get("connections_seen", {}) or {}).items() if d > time.strftime("%Y-%m-%d", time.localtime(time.time() - 90 * 86400))}
    people = credit_people(albums, artists, profs)
    fresh = [p for p in people if p["mbid"] not in seen] or people  # all shown lately: start round again
    # each with the three records that reach furthest apart; the people whose reach is widest first, in steps, so a
    # day's choice isn't always the same few
    cands = [dict(p, on=sorted(p["on"], key=lambda r: -leap([r] + [x for x in p["on"] if x is not r]))[:3], more=max(0, len(p["on"]) - 3)) for p in fresh]
    rng.shuffle(cands)
    cands.sort(key=lambda p: -round(leap(p["on"]) * 2) / 2)
    picks = []
    for kind, n in (("guest", 2), ("player", 1), ("producer", 1)):
        picks += [p for p in cands if p["kind"] == kind][:n]
    picks += [p for p in cands if p not in picks][:4 - len(picks)] if picks else []  # a kind missing: the next widest
    if not picks:  # no credits (switched off, or not gathered yet): the ties between artists, the unusual first
        ties = [l for l in links if l["type"] != "member of band"] + [l for l in links if l["type"] == "member of band"]
        picks = [dict(l, kind="band") for l in ties[:6]]
    for p in picks:
        if p.get("mbid"):
            seen[p["mbid"]] = today
    if picks:  # nothing to choose from yet (the shelves still loading): chosen again next time
        kv_set("connections_seen", seen)
        kv_set("connections_day", {"date": today, "picks": picks})
    return picks


beyond_asking = set()


def conn_beyond(pick, artists):
    """Where a connection leads off the shelves: two records the person worked on that the house doesn't have, by the
    artists they worked with most (a long collaboration says more than a one-off), one an artist. Their MusicBrainz
    credits are asked for in the background the first time; until then, nothing."""
    if not pick.get("mbid") or not artists:  # the shelves not loaded yet (a restart): what they hold can't be told apart
        return []
    p = person(pick["mbid"], pick["name"], local=True)
    if p.get("pending"):
        if pick["mbid"] not in beyond_asking:
            beyond_asking.add(pick["mbid"])
            threading.Thread(target=lambda: person(pick["mbid"], pick["name"]), name="connections", daemon=True).start()
        return []
    work = [w for w in p.get("work") or [] if not w["owned"] and w.get("artist") and key(w["artist"]) not in artists and key(w["artist"]) not in NOT_ARTISTS and key(w["artist"]) not in [key(pick["name"])] + key(pick["name"]).split()  # theirs as "Eno"
            and w.get("type") not in ("Single", "EP", "Broadcast") and not re.search(r"\b(live|demo|session|bootleg|single|remix|ep|tribute)\b", w["title"], re.I)]
    for w in work:
        w["roles"] = [r for r in w["roles"] if not NOT_MUSIC.search(r)]
    work = [w for w in work if w["roles"]]
    # their kind of work first: a producer's records produced, a player's played on
    fits = lambda w: any(bool(STUDIO.search(r)) == (pick["kind"] == "producer") and not re.search(r"additional|assistant", r, re.I) for r in w["roles"])
    often = Counter(key(w["artist"]) for w in work)
    out, had = [], set()
    for w in sorted(work, key=lambda w: (not fits(w), -often[key(w["artist"])], not w.get("group"), w.get("date") or "9999")):
        if key(w["artist"]) not in had:
            had.add(key(w["artist"]))
            out.append({k: w.get(k) for k in ("title", "artist", "date", "cover", "roles")})
        if len(out) == 2:
            break
    return out


def conn_photo(pick, profs):
    """A connection's picture: one of the shelves' own artists wears their profile's; anyone else, their Wikidata
    portrait, once their credits have been looked up (conn_beyond asks)."""
    d = profs.get(key(pick.get("name") or ""))
    if d and pick.get("kind") == "guest":
        return pick_photo(d, "thumb") or ""
    if not pick.get("mbid"):
        return ""
    return person(pick["mbid"], pick["name"], local=True).get("photo") or ""


def home():
    """The Discover page's makings. Rotation and rediscoveries come from the listening log; the rest from the profiles."""
    now = time.time()
    with lib_lock:
        albums, artists = library["albums"], library["artists"]
    today = time.strftime("%Y-%m-%d")
    rng = random.Random(today)
    plays = []
    try:
        c = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        plays = c.execute("select artist, album, started, outcome, played, library from plays where started > ?", (now - 60 * 86400,)).fetchall()
        c.close()
    except Exception:
        pass
    week = Counter(key(p[0]) for p in plays if p[2] > now - 14 * 86400 and (p[3] == "finished" or (p[4] or 0) > 60))
    rotation = [artists[k]["name"] for k, _ in week.most_common(30) if k in artists][:12]
    heard_albums = {copies(p[0], p[1]) for p in plays}
    back = []
    seen = set()
    for p in sorted(plays, key=lambda p: -p[2]):
        k = copies(p[0], p[1])
        if k in seen:
            continue
        seen.add(k)
        hit = next((a[0] for a in albums if copies(a[2], a[1]) == k), None)
        if hit:
            back.append(hit)
        if len(back) >= 16:
            break
    pool = [a for a in albums if a[4] and a[5] > 60 and copies(a[2], a[1]) not in heard_albums]
    rediscover = [a[0] for a in rng.sample(pool, min(18, len(pool)))]
    profs = {k: v[0] for k, v in list(profiles.items())}
    # the artist of the day: one on the shelves with a picture and a story, and more than one album
    candidates = sorted(k for k, d in profs.items() if k in artists and artists[k]["albums"] >= 2 and pick_photo(d) and ((d.get("wiki") or {}).get("extract") or (d.get("qobuz") or {}).get("bio")))
    kept = kv_get("spotlight", {})  # the artist of the day, chosen once and kept all day, however the shelves shift meanwhile
    if kept.get("date") == today and key(kept.get("name", "")) in artists:
        spotlight = kept["name"]
    else:
        spotlight = artists[rng.choice(candidates)]["name"] if candidates else ""
        kv_set("spotlight", {"date": today, "name": spotlight})
    # connections: two artists on the shelves that MusicBrainz ties together
    links, done = [], {}
    for k, d in profs.items():
        if k not in artists:
            continue
        for r in (d.get("mb") or {}).get("rels", []):
            other = key(r.get("name"))
            if other not in artists or other == k:
                continue
            pair = frozenset((k, other))  # each pair once, whichever way round and however many roles MusicBrainz lists (keyboard, piano)
            if pair in done:
                had = done[pair]
                had["attrs"] = had["attrs"] + [x for x in r.get("attrs", []) if x not in had["attrs"]]
                continue
            done[pair] = {"a": artists[k]["name"], "b": artists[other]["name"], "type": r.get("type"), "dir": r.get("dir"), "attrs": list(r.get("attrs", []))}
            links.append(done[pair])
    rng.shuffle(links)
    # beyond the shelves: the artists most often named as similar to the ones in rotation (or to any on the shelves), not on them
    shelved_profs = sorted(k for k in profs if k in artists)
    base = [key(n) for n in rotation] or rng.sample(shelved_profs, min(40, len(shelved_profs)))
    tally, faces = Counter(), {}
    loose = lambda n: re.sub(r"[^a-z0-9]", "", key(n).replace("&", "and"))
    shelved_loose = {loose(a["name"]) for a in artists.values()}  # "Godspeed You! Black Emperor" is on the shelves as Godspeed You Black Emperor
    for k in base:
        for s in ((profs.get(k) or {}).get("qobuz") or {}).get("similar", []):
            sk = key(s["name"])
            if sk not in artists and sk not in NOT_ARTISTS and loose(s["name"]) not in shelved_loose:
                tally[sk] += 1
                faces.setdefault(sk, s)
    beyond = []
    for sk, n in tally.most_common(24):
        s = faces[sk]
        why = [profs[k]["name"] if "name" in profs[k] else k for k in base if any(key(x["name"]) == sk for x in ((profs.get(k) or {}).get("qobuz") or {}).get("similar", []))][:3]
        beyond.append({"name": s["name"], "image": s.get("image", ""), "because": why})
    # round numbers: the shelves' albums turning 10, 20, 25, 30, 40, 50… this month (MusicBrainz's release months), oldest first
    month, rounds = today[:7], {}
    for a in albums:
        if not a[4]:
            continue
        d = profs.get(key(a[2])) or {}
        g = next((g for g in d.get("rgs") or [] if len(g["date"]) >= 7 and lms_qobuz.plain(g["title"]) == lms_qobuz.plain(a[1])), None)
        if g and g["date"][5:7] == month[5:7]:
            age = int(month[:4]) - int(g["date"][:4])
            if age >= 10 and (age % 10 == 0 or age in (25, 75)):
                rounds.setdefault(age, []).append(a[0])
    round_ = [{"age": age, "albums": ids[:18]} for age, ids in sorted(rounds.items(), reverse=True)]
    decades = sorted({a[3] // 10 * 10 for a in albums if a[3] >= 1950})
    decade = rng.choice(decades) if decades else 0
    genres = sorted({g for a in albums for g in a[8]})
    return {"date": today, "rotation": rotation, "back": back, "rediscover": rediscover, "spotlight": spotlight,
            "connections": [dict(c, beyond=conn_beyond(c, artists), photo=conn_photo(c, profs)) for c in credit_links(albums, artists, profs, links, rng, today)], "beyond": beyond, "round": round_, "decade": decade,
            "decade_albums": [a[0] for a in rng.sample([a for a in albums if a[3] // 10 * 10 == decade and a[4]], min(18, sum(1 for a in albums if a[3] // 10 * 10 == decade and a[4])))] if decade else [],
            "genre": rng.choice(genres) if genres else ""}


def qobuz(req):
    action, term, player = req.get("action"), (req.get("term") or "").strip()[:120], req.get("player") or PLAYER
    if not lms_qobuz.PLAYER.match(player) or not term:
        return {"error": "no such player or nothing to ask"}
    if not svc():
        return {"error": "Lyrion has no streaming plugin", "releases": [], "artists": []}
    if action not in ("search", "play", "queue", "keep", "aplay", "aqueue", "akeep"):
        return {"error": "unknown action"}
    return svc().act(dict(req, term=term), player)


# ───────────────────────── marks, lyrics, history, new releases, rooms ─────────────────────────
def marks():
    """Every heart, rating and tag, for the app to hold: {kind: {key: [heart, rating, [tags]]}}."""
    out = {}
    with db() as c:
        for kind, k, heart, rating, tags in c.execute("select kind, k, heart, rating, tags from marks"):
            out.setdefault(kind, {})[k] = [heart or 0, rating or 0, json.loads(tags or "[]")]
    return out


def mark(req):
    """Sets what is given of an album's, track's or artist's heart, rating and tags; a mark left empty is dropped."""
    kind, k = req.get("kind"), (req.get("key") or "")[:300]
    if kind not in ("album", "track", "artist") or not k:
        return {"error": "nothing to mark"}
    with db_lock, db() as c:
        row = c.execute("select heart, rating, tags from marks where kind = ? and k = ?", (kind, k)).fetchone() or (0, 0, "[]")
        heart = int(bool(req["heart"])) if "heart" in req else row[0]
        rating = max(0, min(5, int(req["rating"]))) if "rating" in req else row[1]
        tags = sorted({t.strip()[:40] for t in req["tags"] if t.strip()})[:20] if "tags" in req else json.loads(row[2] or "[]")
        if heart or rating or tags:
            c.execute("insert or replace into marks values (?,?,?,?,?,?)", (kind, k, heart, rating, json.dumps(tags), time.time()))
        else:
            c.execute("delete from marks where kind = ? and k = ?", (kind, k))
    return {"ok": True, "mark": [heart, rating, tags]}


def lyrics(artist, title, album, duration):
    """A song's lyrics from LRCLIB, synced when it has them: {"synced": "[mm:ss.xx] line…", "plain"}, kept a month (a miss a week)."""
    k = hashlib.sha1(f"{key(artist)}|{key(title)}".encode()).hexdigest()
    with db() as c:
        got = c.execute("select data, fetched from lyrics where k = ?", (k,)).fetchone()
    if got:
        data = json.loads(got[0])
        if time.time() - got[1] < (STALE if data.get("plain") or data.get("synced") else 7 * 86400):
            return data
    data = {}
    query = {"artist_name": artist, "track_name": re.sub(r"\s*[(\[].*?[)\]]", "", title).strip() or title}
    try:
        q = dict(query, album_name=album, duration=int(duration)) if album and duration else query
        hit = get_json(LRCLIB + "get?" + urllib.parse.urlencode(q), timeout=10)
    except Exception:
        try:  # nothing for that exact album and length: the best match by name
            found = get_json(LRCLIB + "search?" + urllib.parse.urlencode(query), timeout=10)
            hit = next((f for f in found if f.get("syncedLyrics")), found[0] if found else {})
        except Exception:
            hit = {}
    data = {"synced": hit.get("syncedLyrics") or "", "plain": hit.get("plainLyrics") or "", "instrumental": bool(hit.get("instrumental"))}
    with db_lock, db() as c:
        c.execute("insert or replace into lyrics values (?,?,?)", (k, json.dumps(data), time.time()))
    return data


def history(days):
    """What the listening log has heard in the last days, newest first, with the library's album where it has it."""
    with lib_lock:
        by_copy = {copies(a[2], a[1]): a for a in library["albums"]}
    try:
        c = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
        rows = c.execute("select started, room, title, artist, album, outcome, played, duration, who, library, url from plays where started > ? order by started desc limit 6000",
                         (time.time() - days * 86400,)).fetchall()
        c.close()
    except Exception:
        return {"plays": []}
    # one listen, however often the log saw it start: a track begun again in the same room before it could have run its
    # course (a restart, a re-queue, the radio refilling) joins the earlier start: its time added, the better ending kept.
    # A track played through and then played again is two listens.
    rank = {"finished": 4, "skipped": 3, "replaced": 2, "stopped": 1, "cut": 0}
    merged = []
    for r in reversed(rows):  # oldest first
        r = list(r)
        prev = merged[-1] if merged else None
        if (prev and prev[1] == r[1] and key(prev[2]) == key(r[2]) and key(prev[3]) == key(r[3])
                and r[0] - prev[0] < (prev[7] or 0) + 120 and not (prev[5] == "finished" and (prev[6] or 0) >= 0.9 * (prev[7] or 1))):
            prev[6] = min((prev[6] or 0) + (r[6] or 0), max(prev[7] or 0, r[7] or 0) or 1e9)
            if rank.get(r[5], 0) > rank.get(prev[5], 0):
                prev[5] = r[5]
            continue
        merged.append(r)
    rows = list(reversed(merged))
    out = []
    for started, room, title, artist, album, outcome, played, duration, who, lib, url in rows:
        a = by_copy.get(copies(artist or "", album or ""))
        out.append({"t": round(started), "room": room or "", "title": title or "", "artist": artist or "", "album": album or "", "outcome": outcome or "",
                    "played": round(played or 0), "duration": round(duration or 0), "who": who or "", "library": lib, "album_id": a[0] if a else None, "art": a[4] if a else "",
                    "url": url if streaming.by_url(url) and not a else ""})  # a Qobuz album not on the shelves: keepable
    return {"plays": out}


def afterwork(req):
    """The after-work record (Home Assistant's 4:20 mix): a record added to the shelves in the last two weeks that the
    listening log has never heard (nor judged before). "pick" chooses it (announced at 4:15), "another" chooses again
    from the rest, "play" plays the one chosen, whole and in order, in a room; it is then remembered for the verdict."""
    what, player = req.get("what") or "play", req.get("player") or ""
    if not lms_qobuz.PLAYER.match(player):
        return {"error": "no such room"}
    offer = kv_get("afterwork_offer") or {}
    if what == "play" and offer.get("id") and time.time() - offer.get("at", 0) < 3600:
        a = [offer["id"], offer["title"], offer["artist"]]
    else:
        with lib_lock:
            albums = list(library["albums"])
        judged = kv_get("afterwork_judged", {})
        passed = set(offer.get("passed", [])) | {offer.get("id")} if what == "another" else set()  # those already turned down today
        newest = []  # each record as the version that came in last (a new pressing of an old one is what's new): [id, title, artist, when]
        for e in albums:
            if e[11] > time.time() - 14 * 86400:
                v = next((x for x in e[10] if x[6] and x[6] == e[11]), None)
                newest.append([v[0], v[1], e[2], e[11]] if v else [e[0], e[1], e[2], e[11]])
        try:
            c = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True, timeout=5)
            heard = {copies(r[0] or "", r[1] or "") for r in c.execute("select artist, album from plays where started > ?", (time.time() - 30 * 86400,))}
            c.close()
        except Exception:
            return {"error": "the listening log can't be read"}
        newest = [v for v in newest if str(v[0]) not in judged and copies(v[2], v[1]) not in heard and v[0] not in passed]
        if not newest:
            return {"error": "nothing else new and unheard on the shelves" if passed else "nothing new and unheard on the shelves"}
        a = random.choice(newest)
        kv_set("afterwork_offer", {"id": a[0], "title": a[1], "artist": a[2], "at": time.time(), "passed": sorted(x for x in passed if x)})
    if what == "play":
        rpc(player, "playlist", "shuffle", "0")  # a record plays in its order
        rpc(player, "playlistcontrol", "cmd:load", f"album_id:{a[0]}")
        kv_set("afterwork", {"id": a[0], "title": a[1], "artist": a[2], "player": player, "at": time.time()})
        kv_set("afterwork_offer", None)
    return {"ok": True, "id": a[0], "title": a[1], "artist": a[2]}


def afterwork_verdict(req):
    """Stay or go for the after-work record: staying keeps it off the after-work list for good; going takes it off the
    shelves as Remove does (its files moved to music-removed, never deleted)."""
    cur, verdict = kv_get("afterwork"), req.get("verdict")
    if not cur or verdict not in ("stay", "go"):
        return {"error": "nothing to judge"}
    out = {"ok": True, "title": cur["title"], "artist": cur["artist"], "verdict": verdict}
    if verdict == "go":
        done = remove_album(int(cur["id"]), cur["player"])
        if done.get("error"):
            return dict(out, ok=False, error=done["error"])
    judged = kv_get("afterwork_judged", {})
    judged[str(cur["id"])] = verdict
    kv_set("afterwork_judged", judged)
    kv_set("afterwork", None)
    return out


def keep_from_log(req):
    """A Qobuz album the log heard, added to the library (a Qobuz favourite), by one of its tracks."""
    url, player = req.get("url") or "", req.get("player") or PLAYER
    service = streaming.by_url(url)
    if not service or not re.fullmatch(r"\w+://\d+\.\w+", url) or not lms_qobuz.PLAYER.match(player):
        return {"error": "not a streamed track"}
    out = service.keep_track(player, url)
    if out.get("result") == "added":
        for wait in (60, 150):
            threading.Timer(wait, lambda: load_library(force=True)).start()
    return out


def morning_loop():
    """The day's front page made at five in the morning, so the first look of the day doesn't wait for it."""
    while True:
        now = time.localtime()
        at = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 5, 0, 0, 0, 0, -1))
        if at <= time.time():
            at = time.mktime((now.tm_year, now.tm_mon, now.tm_mday + 1, 5, 0, 0, 0, 0, -1))  # tomorrow's five o'clock, summer time or not
        time.sleep(max(60, at - time.time()))
        try:
            warm_the_day()
        except Exception as e:
            note_error(f"morning: {type(e).__name__}: {e}"[:200])


def warm_the_day():
    """What the front page asks for, done ahead: the cover stories (their text looked up), Discover's makings, the new
    releases, and the pictures shown at the sizes the page asks for (the stories', the artist of the day's, the faces on
    rotation)."""
    t = time.time()
    st = cover_stories()
    h = home()
    new_releases()
    for x in st.get("stories") or []:
        for u, w in ((x.get("bg"), 1600), (x.get("image"), 640), (x.get("pic"), 1600), (x.get("pic"), 640)):
            if u:
                picture(u, w)
    for name in [h.get("spotlight")] + list(h.get("rotation") or [])[:8]:
        if not name:
            continue
        if get_profile(name)[0] is None:
            build(name)
        d = get_profile(name)[0] or {}
        for url, w in ((pick_photo(d), 1600), (pick_photo(d, "thumb"), 320)):
            if url:
                picture(url, w)
    crawl_state["morning"] = f"{time.strftime('%Y-%m-%d %H:%M')}, {round(time.time() - t)} s"


def new_releases(days=200):
    """Releases from artists on the shelves that came out lately (MusicBrainz's dates), with whether the shelves have them and
    where Qobuz has them (for playing from the artist's page)."""
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - days * 86400))
    with lib_lock:
        artists, albums = dict(library["artists"]), library["albums"]
    owned = {lms_qobuz.plain(a[1]) for a in albums}
    out = []
    for k, (d, _, _) in list(profiles.items()):
        if k not in artists:
            continue
        q = {lms_qobuz.plain(r["album"]): r for r in (d.get("qobuz") or {}).get("releases", [])}
        for g in d.get("rgs") or []:
            if g["date"] < since or g["date"] > time.strftime("%Y-%m-%d", time.localtime(time.time() + 14 * 86400)):
                continue
            if set(g["extra"]) & {"Compilation", "Live", "Remix", "DJ-mix", "Demo"}:
                continue
            hit = q.get(lms_qobuz.plain(g["title"]))
            out.append({"artist": artists[k]["name"], "title": g["title"], "date": g["date"], "type": g["type"], "owned": lms_qobuz.plain(g["title"]) in owned,
                        "cover": (hit or {}).get("cover") or f"https://coverartarchive.org/release-group/{g['id']}/front-500",
                        "qobuz": {"i": hit["i"], "album": hit["album"], "artist": hit["artist"]} if hit else None})
    return sorted(out, key=lambda r: r["date"], reverse=True)[:30]


def move_room(src, dst, play=True):
    """What src is playing, moved to dst: the queue from the current track on, copied across track by track (Lyrion
    cannot always save a playlist to hand it over: it has no folder of its own for them here), then the same place in
    the track. src stops only once dst holds the whole queue; if anything is short, src plays on and nothing is lost."""
    if not (lms_qobuz.PLAYER.match(src or "") and lms_qobuz.PLAYER.match(dst or "")) or src == dst:
        return {"error": "no such rooms"}
    st = rpc(src, "status", "-", "1")
    if not int(st.get("playlist_tracks") or 0):
        return {"error": "nothing to move"}
    index, at, playing = int(st.get("playlist_cur_index") or 0), float(st.get("time") or 0), st.get("mode") == "play"
    urls = [t.get("url") for t in rpc(src, "status", str(index), "500", "tags:u").get("playlist_loop") or [] if t.get("url")]
    if not urls:
        return {"error": "nothing to move"}
    rpc(dst, "playlist", "clear")
    for u in urls:
        rpc(dst, "playlist", "add", u)
    have = int(rpc(dst, "status", "-", "1").get("playlist_tracks") or 0)
    if have < len(urls):
        return {"error": f"only {have} of {len(urls)} tracks reached the other room; nothing was stopped"}
    if not play:
        return {"ok": True, "tracks": have, "dry": True}
    rpc(dst, "playlist", "index", "0")
    if at > 5:
        # the same place in the song, once the room is really playing: a Chromecast (through CastBridge) takes seconds to
        # wake, and a jump while it is still starting stops it ("Stop while still launching receiver")
        for _ in range(20):
            time.sleep(0.5)
            now = rpc(dst, "status", "-", "1")
            if now.get("mode") == "play" and float(now.get("time") or 0) > 0.5:
                rpc(dst, "time", str(int(at)))
                break
    if not playing:
        rpc(dst, "pause", "1")
    rpc(src, "stop")
    return {"ok": True, "tracks": have}


# ───────────────────────── credits: who made each album, from MusicBrainz ─────────────────────────
NOT_ROLES = {"additional", "assistant", "co", "guest", "solo", "executive", "lead", "background", "spoken vocals"}


def role_words(rel):
    """A MusicBrainz relationship as a credit reads: "guitar, bass", "lead vocals", "producer", "assistant engineer"."""
    t, attrs = rel.get("type") or "", rel.get("attributes") or []
    if t == "instrument":
        return ", ".join(a for a in attrs if a not in NOT_ROLES) or "instruments"
    if t == "vocal":
        return ", ".join(a for a in attrs if a not in ("additional", "guest", "solo")) or "vocals"
    words = {"mix": "mixing", "recording": "recording", "design/illustration": "design and illustration", "audio": "audio engineer",
             "sound": "sound engineer", "programming": "programming", "performer": "performer", "performing orchestra": "orchestra"}.get(t, t)
    for a in ("executive", "co", "assistant", "additional"):
        if a in attrs:
            words = ("co-" if a == "co" else a + " ") + words
    return words


def find_release(artist, title, ntracks, mbid):
    """The MusicBrainz release that is this album: of those its search finds by title (and the artist's id, when the
    profile has it), the surest match with the same number of tracks, an official one, the earliest."""
    plain = (re.sub(r"\s*[(\[].*?[)\]]", "", title).strip() or title).replace('"', "")
    q = f'release:"{plain}" AND ' + (f"arid:{mbid}" if mbid else f'artist:"{artist.replace(chr(34), "")}"')
    got = [r for r in mb_get("release", query=q, limit=15).get("releases", []) if int(r.get("score") or 0) >= 85]
    if not got:
        return None
    year = lambda r: int((r.get("date") or "9999")[:4]) if (r.get("date") or "")[:4].isdigit() else 9999
    return max(got, key=lambda r: (int(r.get("score") or 0) >= 95, -abs((r.get("track-count") or 0) - ntracks) if ntracks else 0, r.get("status") == "Official", -year(r)))


def fetch_credits(a):
    """Everyone MusicBrainz credits on an album (a library row): the release's own credits and each recording's, by person,
    with their roles and the tracks they played on (0 for the whole record)."""
    if key(a[2]) in NOT_ARTISTS:
        return {"release": None, "people": [], "tracks": []}
    mbid = ((get_profile(a[2])[0] or {}).get("mb") or {}).get("mbid")
    rel = find_release(a[2], a[1], len(album_tracks(a[0])), mbid)
    if not rel:
        return {"release": None, "people": [], "tracks": []}
    r = mb_get(f"release/{rel['id']}", inc="artist-credits+labels+recordings+artist-rels+recording-level-rels")
    people, tracks, n = {}, [], 0

    def add(x, track):
        if x.get("target-type") != "artist" or not x.get("artist"):
            return None
        p = x["artist"]
        e = people.setdefault(p["id"], {"name": p.get("name") or "", "mbid": p["id"], "roles": {}})
        role = role_words(x)
        e["roles"].setdefault(role, set()).add(track)
        return [e["name"], p["id"], role]
    for x in r.get("relations", []):
        add(x, 0)
    for m in r.get("media", []):
        for t in m.get("tracks", []):
            n += 1
            rec = t.get("recording") or {}
            row = [add(x, n) for x in rec.get("relations", [])]
            tracks.append({"n": n, "title": t.get("title") or rec.get("title") or "", "people": [x for x in row if x]})
    labels = sorted({(li.get("label") or {}).get("name") or "" for li in r.get("label-info", [])} - {""})
    return {"release": rel["id"], "title": r.get("title") or "", "date": r.get("date") or "", "label": ", ".join(labels), "tracks": tracks,
            "people": [{"name": e["name"], "mbid": e["mbid"], "roles": [[role, sorted(t for t in ts if t)] for role, ts in e["roles"].items()]} for e in people.values()]}


def credits_for(album_id, fetch=True):
    """An album's credits, kept a month; None when not yet fetched and fetch is off. Fetched for someone looking at the
    album, it goes ahead of the background passes."""
    a = album_row(album_id)
    if not a:
        return {"release": None, "people": [], "tracks": []}
    k = copies(a[2], a[1])
    with db() as c:
        got = c.execute("select data, fetched from credits where k = ?", (k,)).fetchone()
    if got and time.time() - got[1] < STALE:
        return json.loads(got[0])
    if not fetch:
        return None
    urgent[0] += threading.current_thread().name not in ("crawler", "credits")
    try:
        out = fetch_credits(a)
    finally:
        urgent[0] -= threading.current_thread().name not in ("crawler", "credits")
    with db_lock, db() as c:
        c.execute("insert or replace into credits values (?,?,?)", (k, json.dumps(out, ensure_ascii=False), time.time()))
    return out


def credits_loop():
    """Every album's credits, newest first, a little at a time behind the artists; then once a month again."""
    time.sleep(120)
    while True:
        try:
            todo = [a for a in list(library["albums"]) if credits_for(a[0], fetch=False) is None and key(a[2]) not in NOT_ARTISTS]
            crawl_state["credits_left"] = len(todo)
            if not todo:
                time.sleep(3600)
                continue
            for a in todo[:20]:
                try:
                    credits_for(a[0])
                except Exception as e:
                    note_error(f"credits {a[1]}: {type(e).__name__}: {e}"[:200])
                    with db_lock, db() as c:  # not asked again until the month is out
                        c.execute("insert or replace into credits values (?,?,?)", (copies(a[2], a[1]), json.dumps({"release": None, "people": [], "tracks": []}), time.time()))
                crawl_state["credits_left"] -= 1
        except Exception as e:
            note_error(f"credits: {type(e).__name__}: {e}"[:200])
            time.sleep(60)


def wikidata_photo(mb):
    """A person's portrait: Wikidata's image (its P18) for the MusicBrainz artist, as a 400px Wikimedia Commons
    thumbnail; else the first picture on their Discogs page (MusicBrainz's link to it, so theirs for certain), which
    most session players have when Wikipedia has no free one."""
    link = lambda t: next(((r.get("url") or {}).get("resource") or "" for r in mb.get("relations") or [] if r.get("type") == t), "")
    q = link("wikidata").rstrip("/").split("/")[-1]
    m = re.search(r"/artist/(\d+)", link("discogs"))
    token = m and discogs_token()
    if not re.fullmatch(r"Q\d+", q):
        return discogs_photo(m.group(1), token) if token else ""
    try:
        ent = get_json(f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={q}&props=claims&format=json")
        f = ent["entities"][q]["claims"]["P18"][0]["mainsnak"]["datavalue"]["value"].replace(" ", "_")
    except Exception:
        return discogs_photo(m.group(1), token) if token else ""
    h = hashlib.md5(f.encode()).hexdigest()
    name = urllib.parse.quote(f)
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{name}/400px-{name}" + (".png" if f.lower().endswith((".tif", ".tiff", ".svg")) else "")


def discogs_photo(artist_id, token):
    try:
        imgs = discogs_get(f"/artists/{int(artist_id)}", token).get("images") or []
    except Exception:
        return ""
    best = next((i for i in imgs if i.get("type") == "primary"), imgs[0] if imgs else {})
    return best.get("uri") or ""


def person(mbid, name, local=False):
    """A person's page: what they made that is on the shelves (with their roles there), and from MusicBrainz what else
    they are credited on, newest first, marked where the shelves have it."""
    if not re.fullmatch(r"[0-9a-f-]{36}", mbid or ""):
        return {"error": "no such person"}
    with lib_lock:
        by_copy = {copies(a[2], a[1]): a for a in library["albums"]}
        artists = library["artists"]
    shelves = []
    with db() as c:
        for k, data in c.execute("select k, data from credits where data like ?", (f"%{mbid}%",)):
            a = by_copy.get(k)
            e = next((p for p in json.loads(data)["people"] if p["mbid"] == mbid), None)
            if a and e:
                shelves.append({"album_id": a[0], "roles": [r for r, _ in e["roles"]]})
        got = c.execute("select data, fetched from persons where mbid = ?", (mbid,)).fetchone()
    if got and time.time() - got[1] < STALE and '"v": 2' in got[0]:  # kept from before portraits and records' kinds: asked again
        data = json.loads(got[0])
    elif local:  # what the shelves know, at once; the app asks again for the rest
        return {"name": name, "mbid": mbid, "shelves": shelves, "work": [], "pending": True, "type": "", "area": "", "begin": "", "end": "", "disambiguation": "",
                "artist": artists[key(name)]["name"] if key(name) in artists else ""}
    else:
        urgent[0] += 1
        try:
            p = mb_get(f"artist/{mbid}", inc="release-rels+release-group-rels+url-rels")
        finally:
            urgent[0] -= 1
        seen, work = {}, []
        for x in p.get("relations", []):
            t = x.get("release") or x.get("release_group") or x.get("release-group")
            if not t or x.get("target-type") not in ("release", "release_group", "release-group"):
                continue
            title, date = t.get("title") or "", t.get("date") or t.get("first-release-date") or ""
            k = lms_qobuz.plain(title)
            if k in seen:
                w = seen[k]
                if role_words(x) not in w["roles"]:
                    w["roles"].append(role_words(x))
                w["date"] = min(w["date"] or "9999", date or "9999").replace("9999", "")
                continue
            w = {"title": title, "date": date, "roles": [role_words(x)], "release": t.get("id") if x.get("target-type") == "release" else "",
                 "group": t.get("id") if x.get("target-type") != "release" else ""}
            seen[k] = w
            work.append(w)
        by_id = {}  # whose records they are: MusicBrainz's search takes forty ids at once
        for field, ids in (("reid", [w["release"] for w in work if w["release"]]), ("rgid", [w["group"] for w in work if w["group"]])):
            for i in range(0, min(len(ids), 240), 40):
                try:
                    kind = "release" if field == "reid" else "release-group"
                    found = mb_get(kind, query=" OR ".join(f"{field}:{x}" for x in ids[i:i + 40]), limit=100).get(kind + "s", [])
                    for f in found:
                        by_id[f["id"]] = ("".join(c.get("name", "") + c.get("joinphrase", "") for c in f.get("artist-credit") or []),
                                          (f.get("release-group") or {}).get("primary-type") or f.get("primary-type") or "")
                except Exception:
                    pass
        for w in work:
            w["artist"], w["type"] = by_id.get(w["release"] or w["group"], ("", ""))
        data = {"name": p.get("name") or name, "type": p.get("type") or "", "area": (p.get("area") or {}).get("name") or "",
                "begin": ((p.get("life-span") or {}).get("begin") or "")[:4], "end": ((p.get("life-span") or {}).get("end") or "")[:4],
                "disambiguation": p.get("disambiguation") or "", "photo": wikidata_photo(p), "v": 2, "work": sorted(work, key=lambda w: w["date"] or "0", reverse=True)[:240]}
        with db_lock, db() as c:
            c.execute("insert or replace into persons values (?,?,?)", (mbid, json.dumps(data, ensure_ascii=False), time.time()))
    owned = {lms_qobuz.plain(a[1]) for a in by_copy.values()}
    for w in data["work"]:
        w["owned"] = copies(w.get("artist", ""), w["title"]) in by_copy or (not w.get("artist") and lms_qobuz.plain(w["title"]) in owned)
        w["cover"] = f"https://coverartarchive.org/release/{w['release']}/front-250" if w["release"] else f"https://coverartarchive.org/release-group/{w['group']}/front-250" if w["group"] else ""
    return dict(data, mbid=mbid, shelves=shelves, artist=artists[key(data["name"])]["name"] if key(data["name"]) in artists else "")


# ───────────────────────── taking an album off the shelves ─────────────────────────
def copies_of(album_id):
    """Every copy Lyrion holds of an album (the shelves show one, its best): [(Lyrion's album id, [track urls])]."""
    a = album_row(album_id)
    if not a:
        return None, []
    k = copies(a[2], a[1])
    plain = re.sub(r"\s*[(\[].*?[)\]]", "", a[1]).strip() or a[1]
    found = rpc("", "albums", "0", "100", f"search:{plain}", "tags:la").get("albums_loop") or []
    ids = {int(x["id"]) for x in found if copies(x.get("artist") or "", x.get("album") or "") == k} | {a[0]}
    out = []
    for i in sorted(ids):
        urls = [t.get("url") or "" for t in rpc("", "titles", "0", "500", f"album_id:{i}", "tags:u").get("titles_loop") or []]
        out.append((i, [u for u in urls if u]))
    return a, out


def read_music_dirs():
    """Lyrion's own media folders (its mediadirs setting): where removing an album may move files from. Removed music goes
    beside the first of them (/share/music → /share/music-removed). And the player the Qobuz plugin is asked through: the
    one set before if it is still there, else any connected one."""
    global MUSIC_DIRS, REMOVED_DIR, PLAYER
    try:
        players = [p for p in rpc("", "players", "0", "50", timeout=5).get("players_loop") or [] if p.get("connected")]
        if players and PLAYER not in [p["playerid"] for p in players]:
            PLAYER = players[0]["playerid"]
    except Exception:
        pass
    try:
        got = rpc("", "pref", "mediadirs", "?", timeout=5).get("_p2")
        dirs = [d.rstrip("/") for d in (got if isinstance(got, list) else [got]) if d]
        if dirs:
            MUSIC_DIRS = dirs
    except Exception:
        pass
    REMOVED_DIR = os.environ.get("REMOVED_DIR") or MUSIC_DIRS[0] + "-removed"
    return MUSIC_DIRS


def placed(f):
    """A file's media folder and its place under removed music: as it sits in its folder when Lyrion has one folder, under
    that folder's own name when it has several. (root, rel) or (None, None) when it is in none of them."""
    for root in MUSIC_DIRS:
        if f.startswith(root + "/"):
            rel = os.path.relpath(f, root)
            return root, (rel if len(MUSIC_DIRS) == 1 else os.path.join(os.path.basename(root), rel))
    return None, None


def file_path(url):
    return urllib.parse.unquote(url[len("file://"):]) if url.startswith("file://") else None


def this_version(album_id):
    """The one album chosen, as Lyrion holds it: (row, [(its id, [track urls])]). Its other versions are albums of their
    own (each listed in the album's versions), removed one by one."""
    a = album_row(album_id)
    if not a:
        return None, []
    urls = [t.get("url") or "" for t in rpc("", "titles", "0", "500", f"album_id:{album_id}", "tags:u").get("titles_loop") or []]
    return a, [(album_id, [u for u in urls if u])]


def removal_plan(album_id):
    """What removing an album would do, for the app to say before it is done."""
    a, found = this_version(album_id)
    if not a:
        return {"error": "no such album"}
    qobuz = sum(1 for _, urls in found if any(streaming.by_url(u) for u in urls))
    read_music_dirs()
    files = [f for _, urls in found for f in map(file_path, urls) if f and placed(f)[0]]
    folders = sorted({os.path.dirname(placed(f)[1]) for f in files})
    gone = {i for i, _ in found}
    main = album_row(a[12]) if len(a) > 12 else a  # the album it is a pressing of
    others = [v for v in ([[main[0]]] + [[v[0]] for v in main[10]]) if v[0] not in gone] if main and len(main) > 10 else []
    return {"album": a[1], "artist": a[2], "copies": len(found), "qobuz": qobuz, "files": len(files), "folders": folders[:6], "to": REMOVED_DIR, "versions_left": len(others)}


def remove_album(album_id, player):
    """Takes an album off the shelves, the version chosen (its other versions stay): a Qobuz favourite is no longer one (the release's own menu, as keeping
    it used), and the files are moved, folder by folder as they were, to REMOVED_DIR, where Lyrion does not look and from
    where they can be put back. Then Lyrion looks again. What was done is written down (removals)."""
    a, found = this_version(album_id)
    if not a:
        return {"error": "no such album"}
    local = any(u.startswith("file:") for _, urls in found for u in urls)
    if not settings["features"]["write_files"] and local:
        return {"error": "Its files would be moved: changing music files is switched off (Settings, Features)"}
    read_music_dirs()
    try:  # removed music stays on the music's own disk (a move, never a copy): in Docker, the music's parent folder mounted
        if local and os.stat(os.path.dirname(REMOVED_DIR)).st_dev != os.stat(MUSIC_DIRS[0]).st_dev:
            raise OSError
    except OSError:
        return {"error": f"{REMOVED_DIR} isn't on the music's own disk: mount the folder above {MUSIC_DIRS[0]} (or set REMOVED_DIR)"}
    done = {"qobuz": [], "moved": [], "problems": [], "art": a[4], "album_id": a[0], "roots": {}}
    for _, urls in found:
        q = next((u for u in urls if streaming.by_url(u)), None)
        if q:
            try:
                if streaming.by_url(q).unkeep_track(player, q):
                    done["qobuz"].append(q)  # the streamed copies let go (kept under "qobuz", whichever service)
                else:
                    done["problems"].append(f"{streaming.by_url(q).label} offered no way to let it go (not a favourite?)")
            except Exception as e:
                done["problems"].append(f"Qobuz: {type(e).__name__}")
        emptied = set()
        for f in [file_path(u) for u in urls]:
            root, rel = placed(f) if f else (None, None)
            if not root or not os.path.exists(f):
                continue
            done["roots"][rel.split("/", 1)[0] if len(MUSIC_DIRS) > 1 else ""] = root  # for putting it back
            for src in (f, os.path.join(os.path.dirname(f), "._" + os.path.basename(f))):  # a Mac's sidecar goes with its track
                if os.path.exists(src):
                    dst = os.path.join(REMOVED_DIR, os.path.dirname(rel), os.path.basename(src))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    os.replace(src, dst)
                    done["moved"].append(os.path.relpath(dst, REMOVED_DIR))
            emptied.add(os.path.dirname(f))
        for d in emptied:  # a folder left with no music: its covers, cue sheets and the rest follow, and it goes
            try:
                left = os.listdir(d)
                if d not in MUSIC_DIRS and not any(n.lower().endswith(AUDIO) and not n.startswith("._") for n in left):
                    for n in left:
                        src = os.path.join(d, n)
                        if os.path.isfile(src):
                            dst = os.path.join(REMOVED_DIR, placed(src)[1])
                            os.makedirs(os.path.dirname(dst), exist_ok=True)
                            os.replace(src, dst)
                            done["moved"].append(os.path.relpath(dst, REMOVED_DIR))
                    if not os.listdir(d):
                        os.rmdir(d)
            except OSError as e:
                done["problems"].append(f"{os.path.basename(d)}: {e.strerror}")
    with db_lock, db() as c:
        c.execute("insert into removals values (?,?,?,?)", (time.time(), a[1], a[2], json.dumps(done, ensure_ascii=False)))
    if done["moved"]:
        rpc("", "rescan")  # looks for new, changed and missing files
    if done["qobuz"]:
        rpc("", "rescan", "onlinelibrary")
    for wait in (45, 120, 300):  # the shelves follow once Lyrion has looked
        threading.Timer(wait, lambda: load_library(force=True)).start()
    with lib_lock:  # and leave the app's list at once (its other versions stay)
        library["albums"] = without_versions({i for i, _ in found})
        library["etag"] = hashlib.sha1(json.dumps([library["albums"], library["scan"]]).encode()).hexdigest()[:16]
    return {"ok": True, "album": a[1], "qobuz": len(done["qobuz"]), "moved": len([m for m in done["moved"] if not os.path.basename(m).startswith("._")]), "problems": done["problems"]}


def removals():
    """What has been taken off the shelves, newest first, and whether it has been put back."""
    with db() as c:
        rows = c.execute("select rowid, at, album, artist, data from removals order by at desc limit 200").fetchall()
    out = []
    for rid, at, album, artist, data in rows:
        d = json.loads(data)
        out.append({"id": rid, "at": round(at), "album": album, "artist": artist, "art": d.get("art", ""), "qobuz": len(d.get("qobuz", [])),
                    "files": len([m for m in d.get("moved", []) if not os.path.basename(m).startswith("._")]), "restored": round(d.get("restored") or 0)})
    return {"removals": out}


def restore(rid, player):
    """A removal undone: the files moved back where they were (never over a file that has since appeared there), the Qobuz
    favourite added again, Lyrion rescanning. Nothing is deleted on either side."""
    read_music_dirs()
    with db() as c:
        row = c.execute("select album, data from removals where rowid = ?", (rid,)).fetchone()
    if not row:
        return {"error": "no such removal"}
    d = json.loads(row[1])
    back, kept, problems = 0, 0, []
    for rel in d.get("moved", []):
        # the folder each file came from: with one media folder its place is as it was; with several, under the folder's name
        roots = d.get("roots") or {"": MUSIC_DIRS[0]}
        if "" in roots:
            dst = os.path.join(roots[""], rel)
        else:
            head, _, rest = rel.partition("/")
            if head not in roots:
                continue
            dst = os.path.join(roots[head], rest)
        src = os.path.join(REMOVED_DIR, rel)
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            kept += 1  # something is there again: it stays, and so does the removed copy
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        back += not os.path.basename(rel).startswith("._")
    for rel in sorted({os.path.dirname(r) for r in d.get("moved", [])}, key=len, reverse=True):  # folders left empty in music-removed
        try:
            path = os.path.join(REMOVED_DIR, rel)
            while path != REMOVED_DIR and os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
                path = os.path.dirname(path)
        except OSError:
            pass
    added = 0
    for q in d.get("qobuz", []):
        try:
            out = (streaming.by_url(q) or streaming.ALL[0]).keep_track(player, q)
            added += out.get("result") in ("added", "already")
        except Exception as e:
            problems.append(f"Qobuz: {type(e).__name__}")
    d["restored"] = time.time()
    with db_lock, db() as c:
        c.execute("update removals set data = ? where rowid = ?", (json.dumps(d, ensure_ascii=False), rid))
    if back:
        rpc("", "rescan")
    for wait in (45, 120, 300):
        threading.Timer(wait, lambda: load_library(force=True)).start()
    return {"ok": True, "album": row[0], "files": back, "qobuz": added, "kept": kept, "problems": problems}


# ───────────────────────── what only lives here, exported for the backup ─────────────────────────
BACKUPS = os.path.join(DATA, "backups")  # its own nightly copies, two weeks of them
KEEP_BACKUPS = 14


def export():
    """Everything the house has made here that can't be fetched again: hearts, stars, tags, removals (to put things
    back), stations and their seeds, the never-play list, the settings, and the albums' genres (so none is asked again)."""
    with db() as c:
        out = {"soundsquatch": 2, "exported": time.time(),
               "marks": [list(m) for m in c.execute("select kind, k, heart, rating, tags, at from marks")],
               "removals": [list(r) for r in c.execute("select at, album, artist, data from removals")],
               "stations": [list(r) for r in c.execute("select key, name, blurb, seeds, pos from stations")],
               "bans": [list(r) for r in c.execute("select kind, k, label, at from bans")],
               "genres": [list(r) for r in c.execute("select k, genres, source, fetched from album_genres")],
               "tag_edits": [list(r) for r in c.execute("select path, field, original, at from tag_edits")],
               "kv": [list(r) for r in c.execute("select k, v from kv")]}
    out["settings"] = json.loads(json.dumps({g: settings[g] for g in DEFAULTS}))
    out["settings"]["connections"]["lms_password"] = ""  # a backup is a file anyone may download: no password, no PIN in it
    out["settings"]["house"]["pin"] = ""
    return out


def backup_now():
    os.makedirs(BACKUPS, exist_ok=True)
    path = os.path.join(BACKUPS, f"soundsquatch-{time.strftime('%Y-%m-%d')}.json")
    with open(path + ".tmp", "w") as f:
        json.dump(export(), f, ensure_ascii=False)
    os.replace(path + ".tmp", path)
    for old in sorted(f for f in os.listdir(BACKUPS) if f.startswith("soundsquatch-") and f.endswith(".json"))[:-KEEP_BACKUPS]:
        os.remove(os.path.join(BACKUPS, old))
    kv_set("last_backup", time.time())
    return path


def backups_loop():
    """A copy each night (at half past three), and one at start if the last is more than a day old."""
    time.sleep(120)
    while True:
        try:
            if time.time() - (kv_get("last_backup", 0) or 0) > 20 * 3600 and (time.localtime().tm_hour == 3 or time.time() - (kv_get("last_backup", 0) or 0) > 36 * 3600):
                backup_now()
        except Exception as e:
            note_error(f"backup: {type(e).__name__}: {e}"[:200])
        time.sleep(900)


def backup_list():
    try:
        files = sorted((f for f in os.listdir(BACKUPS) if f.endswith(".json")), reverse=True)
    except OSError:
        files = []
    return {"last": kv_get("last_backup", 0), "files": [{"name": f, "size": os.path.getsize(os.path.join(BACKUPS, f))} for f in files]}


def import_(req):
    """A backup put back: marks, stations, bans, genres and the like it holds replace those here; removals it has that are
    not here are added; its settings are taken (the connections only if this server has none of its own yet)."""
    if req.get("soundsquatch") not in (1, 2):
        return {"error": "not a Soundsquatch backup"}
    with db_lock, db() as c:
        for kind, k, heart, rating, tags, at in req.get("marks", []):
            c.execute("insert or replace into marks values (?,?,?,?,?,?)", (kind, k, heart, rating, tags, at))
        have = {(r[0], r[1]) for r in c.execute("select at, album from removals")}
        added = 0
        for at, album, artist, data in req.get("removals", []):
            if (at, album) not in have:
                c.execute("insert into removals values (?,?,?,?)", (at, album, artist, data))
                added += 1
        for row in req.get("stations", []):
            c.execute("insert or replace into stations values (?,?,?,?,?)", row)
        for row in req.get("bans", []):
            c.execute("insert or replace into bans values (?,?,?,?)", row)
        for row in req.get("genres", []):
            c.execute("insert or replace into album_genres values (?,?,?,?)", row)
        for row in req.get("tag_edits", []):
            c.execute("insert or ignore into tag_edits values (?,?,?,?)", row)  # the oldest original stands
        for k, v in req.get("kv", []):
            if k != "last_backup":
                c.execute("insert or replace into kv values (?,?)", (k, v))
    if req.get("settings"):
        save_settings({g: v for g, v in req["settings"].items() if g != "connections"})
    load_library(force=True)
    return {"ok": True, "marks": len(req.get("marks", [])), "removals": added, "stations": len(req.get("stations", [])), "bans": len(req.get("bans", []))}


# ───────────────────────── playlists (Lyrion's own) ─────────────────────────
def playlists():
    """Every playlist Lyrion keeps, with how many tracks and the covers of its first few."""
    out = []
    for pl in rpc("", "playlists", "0", "500").get("playlists_loop") or []:
        got = rpc("", "playlists", "tracks", "0", "12", f"playlist_id:{pl['id']}", "tags:JK")
        arts, seen = [], set()
        for t in got.get("playlisttracks_loop") or []:
            art = t.get("artwork_track_id") and f"/cover/{t['artwork_track_id']}/300.jpg" or t.get("artwork_url") or ""
            if art and art not in seen:
                seen.add(art)
                arts.append(art)
        out.append({"id": pl["id"], "name": pl.get("playlist") or "", "count": int(got.get("count") or 0), "arts": arts[:4]})
    return {"playlists": sorted(out, key=lambda p: p["name"].lower())}


def playlist(pid):
    got = rpc("", "playlists", "tracks", "0", "1000", f"playlist_id:{pid}", "tags:altdJKu")
    return {"id": pid, "tracks": [{"id": t.get("id"), "title": t.get("title") or "", "artist": t.get("artist") or "", "album": t.get("album") or "", "duration": float(t.get("duration") or 0),
                                   "art": t.get("artwork_track_id") or "", "remote_art": t.get("artwork_url") or "", "url": t.get("url") or ""} for t in got.get("playlisttracks_loop") or []]}


def playlist_add(req):
    """Adds an album's tracks, or one track, to a playlist (a new one when a name is given instead)."""
    pid = req.get("playlist_id")
    if not pid and (req.get("name") or "").strip():
        made = rpc("", "playlists", "new", f"name:{req['name'].strip()[:100]}")
        pid = made.get("playlist_id") or made.get("overwritten_playlist_id")
    if not pid:
        return {"error": "no playlist"}
    if req.get("album_id"):
        urls = [t.get("url") for t in rpc("", "titles", "0", "300", f"album_id:{int(req['album_id'])}", "sort:tracknum", "tags:u").get("titles_loop") or []]
    elif req.get("track_id"):
        urls = [t.get("url") for t in rpc("", "titles", "0", "1", f"track_id:{int(req['track_id'])}", "tags:u").get("titles_loop") or []]
    else:
        urls = [req.get("url")] if req.get("url") else []
    for u in [u for u in urls if u]:
        rpc("", "playlists", "edit", "cmd:add", f"playlist_id:{pid}", f"url:{u}")
    return {"ok": True, "playlist_id": pid, "added": len([u for u in urls if u])}


def playlist_do(req):
    """A playlist changed: a track moved or taken out, the list renamed or deleted, or the queue saved as a new one."""
    pid, what = req.get("playlist_id"), req.get("what")
    if what == "new":  # an empty playlist, to fill from albums' and tracks' playlist buttons
        name = (req.get("name") or "").strip()[:100]
        if not name:
            return {"error": "no name"}
        made = rpc("", "playlists", "new", f"name:{name}")
        if made.get("overwritten_playlist_id"):
            return {"error": "there is a playlist of that name already", "playlist_id": made["overwritten_playlist_id"]}
        return {"ok": True, "playlist_id": made.get("playlist_id")}
    if what == "save":
        rpc(req.get("player") or PLAYER, "playlist", "save", (req.get("name") or "Saved queue").strip()[:100], "silent:1")
    elif what == "move":
        rpc("", "playlists", "edit", "cmd:move", f"playlist_id:{pid}", f"index:{int(req['from'])}", f"toindex:{int(req['to'])}")
    elif what == "remove":
        rpc("", "playlists", "edit", "cmd:delete", f"playlist_id:{pid}", f"index:{int(req['index'])}")
    elif what == "rename":
        rpc("", "playlists", "rename", f"playlist_id:{pid}", f"newname:{(req.get('name') or '').strip()[:100]}")
    elif what == "delete":
        rpc("", "playlists", "delete", f"playlist_id:{pid}")
    else:
        return {"error": "unknown"}
    return {"ok": True}


# ───────────────────────── sharing: an album's public address ─────────────────────────
share_cache = {}


def qobuz_album_link(cover):
    """Qobuz's public page for an album, from its cover's address (…/covers/9b/jn/kk6wx5x06jn9b_600.jpg)."""
    m = re.search(r"/images/covers/[^/]+/[^/]+/([A-Za-z0-9]+)_\d+\.jpg", urllib.parse.unquote(cover or ""))
    return f"https://open.qobuz.com/album/{m.group(1)}" if m else ""


def share_link(album_id):
    """A library album's public address, when it came from Qobuz: one of its tracks' cover, as Lyrion's song info has it."""
    if album_id in share_cache:
        return share_cache[album_id]
    urls = [t.get("url") or "" for t in rpc("", "titles", "0", "50", f"album_id:{album_id}", "tags:u").get("titles_loop") or []]
    q = next((u for u in urls if u.startswith("qobuz:")), None)
    link = ""
    t = next((u for u in urls if u.startswith("tidal:")), None)
    if t and not q:  # TIDAL's public page for the album
        link = streaming.by_url(t).link(PLAYER, t)
    if q:
        for row in rpc(PLAYER, "songinfo", "0", "40", f"url:{q}", "tags:K").get("songinfo_loop") or []:
            if row.get("artwork_url"):
                link = qobuz_album_link(row["artwork_url"])
    share_cache[album_id] = {"url": link}
    return share_cache[album_id]


# ───────────────────────── stations: the chill mix's way, for every bin ─────────────────────────


def ha_call(path, data, timeout=30):
    """Home Assistant's REST API, with Soundsquatch's own token (HA_TOKEN); None when there is no token."""
    try:
        with open(HA_TOKEN) as f:
            token = f.read().strip()
    except OSError:
        return None
    req = urllib.request.Request(HA_URL + path, json.dumps(data).encode(), {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


DSTM = "plugin.dontstopthemusic:provider"
STATION_SEEDS, STATION_TRACKS = 3, 9


def kv_get(k, default=None):
    with db() as c:
        row = c.execute("select v from kv where k = ?", (k,)).fetchone()
    return json.loads(row[0]) if row else default


def kv_set(k, v):
    with db_lock, db() as c:
        c.execute("insert or replace into kv values (?,?)", (k, json.dumps(v, ensure_ascii=False)))


STARTER_STATIONS, STARTER_SEEDS = 8, 10


def starter_stations():
    """A new house's stations, made once from its own shelves when most of their genres are known: one for each of its
    biggest genres (four artists at least; the broad ones, rock and pop and the like, only to make up the number),
    seeded with the artists who have the most records in it, never-plays left out. None (and asked again later) while
    the genres are still being found. A house that has stations, or has had them and deleted them, keeps its own."""
    if kv_get("stations_started"):
        return
    with db() as c:
        if c.execute("select count(*) from stations").fetchone()[0]:
            kv_set("stations_started", True)  # a house with stations already (made before this, or by hand)
            return
    with lib_lock:
        albums = [a for a in library["albums"] if key(a[2]) not in NOT_ARTISTS]
    if not albums or sum(1 for a in albums if a[8]) < 0.6 * len(albums):
        return
    with db() as c:
        banned = {k for (k,) in c.execute("select k from bans where kind = 'artist'")}
    by_genre = {}
    for a in albums:
        if key(a[2]) in banned:
            continue
        for g in a[8]:
            by_genre.setdefault(g, Counter())[a[2]] += 1
    ranked = sorted(((g, n) for g, n in by_genre.items() if len(n) >= 4), key=lambda x: -len(x[1]))
    chosen = [x for x in ranked if x[0] not in house_genres.BROAD][:STARTER_STATIONS]
    chosen += [x for x in ranked if x[0] in house_genres.BROAD][:STARTER_STATIONS - len(chosen)]
    rows = []
    for n, (g, artists) in enumerate(chosen):
        seeds, seen = [], set()
        for name, _ in artists.most_common():  # one spelling of each ("Spiritualized®" is Spiritualized)
            loose = re.sub(r"[^a-z0-9]", "", name.lower())
            if loose not in seen and len(seeds) < STARTER_SEEDS:
                seen.add(loose)
                seeds.append(name)
        blurb = house_genres.BLURBS.get(g) or f"From your shelves: {', '.join(seeds[:2])} and {seeds[2]}."
        rows.append((re.sub(r"[^a-z0-9]+", "-", g.lower()).strip("-"), g, blurb, json.dumps(seeds, ensure_ascii=False), n))
    with db_lock, db() as c:
        c.executemany("insert or replace into stations values (?,?,?,?,?)", rows)
    kv_set("stations_started", True)
    if kv_get("exclude_albums") is None:
        kv_set("exclude_albums", [])


def import_stations():
    starter_stations()


def station_rows():
    with db() as c:
        return [{"key": k, "name": n, "blurb": b, "seeds": json.loads(sd)} for k, n, b, sd, _ in c.execute("select * from stations order by pos, name")]


def stations():
    """The stations, each with its seed artists and four covers from the shelves for its card."""
    if not feature("stations"):
        return {"stations": [], "token": True}
    import_stations()
    with lib_lock:
        albums = library["albums"]
    out = []
    for st in station_rows():
        keys, arts = {key(n) for n in st["seeds"]}, []
        for a in albums:
            if key(a[2]) in keys and a[4] and a[2] not in [x[1] for x in arts]:
                arts.append((a[4], a[2]))
            if len(arts) == 4:
                break
        out.append(dict(st, arts=[x[0] for x in arts]))
    return {"stations": out, "token": True}


def tracks_by(name, exclude, ban_keys=frozenset()):
    """Every track in the library by the artist named just so (any role), less excluded albums and banned tracks: [url]."""
    found = rpc("", "artists", "0", "20", f"search:{name}").get("artists_loop") or []
    ids = [a["id"] for a in found if (a.get("artist") or "").lower() == name.lower()] or [a["id"] for a in found[:1]]
    out = []
    for i in ids:
        for t in rpc("", "titles", "0", "2000", f"artist_id:{i}", "tags:ula").get("titles_loop") or []:
            album = (t.get("album") or "").lower()
            if t.get("url") and not any(x.lower() in album for x in exclude) and ("track", ban_key("track", t.get("artist") or name, t.get("title") or "")) not in ban_keys:
                out.append(t["url"])
    return out


def start_station(req):
    """A station on in a room, as the chill mix always was: three of its seed artists that the library has, nine of their
    tracks shuffled, then the radio (Don't Stop the Music, turned on if it is off) carries on with more like them."""
    k, player = req.get("key") or "", req.get("player") or PLAYER
    st = next((x for x in station_rows() if x["key"] == k), None)
    if not st or not lms_qobuz.PLAYER.match(player):
        return {"error": "no such station or room"}
    with db() as c:
        ban_keys = {(kd, kk) for kd, kk in c.execute("select kind, k from bans")}
    names = [n for n in st["seeds"] if ("artist", ban_key("artist", n)) not in ban_keys]  # a banned artist is never a seed
    random.shuffle(names)
    exclude, picked, urls = kv_get("exclude_albums", []), [], []
    for n in names:
        got = tracks_by(n, exclude, ban_keys)
        if got:
            picked.append(n)
            urls += got
        if len(picked) == STATION_SEEDS:
            break
    if not urls:
        return {"error": "none of its seed artists are on the shelves"}
    quiet_reset[player] = time.time() + 10
    rpc(player, "playlist", "clear")
    chosen = random.sample(urls, min(STATION_TRACKS, len(urls)))
    for u in chosen:
        rpc(player, "playlist", "add", u)
    radio_added[player] = set(chosen)
    if (rpc(player, "playerpref", DSTM, "?").get("_p2") or "0") in ("0", ""):
        rpc(player, "playerpref", DSTM, "PLUGIN_LASTMIX_DSTM_ITEM")
    rpc(player, "playlist", "shuffle", "1")
    rpc(player, "playlist", "index", "0")
    rpc(player, "mode", "play")
    return {"ok": True, "station": st["name"], "seeds": picked}


def station_edit(req):
    """A station changed: a seed artist added or taken off, renamed, a new one made, or one deleted."""
    what, k = req.get("what"), req.get("key") or ""
    rows = {x["key"]: x for x in station_rows()}
    if what == "new":
        name = (req.get("name") or "").strip()[:60]
        if not name:
            return {"error": "no name"}
        k = re.sub(r"[^a-z]", "", name.lower())[:20] or "station"
        while k in rows:
            k += "x"
        with db_lock, db() as c:
            c.execute("insert into stations values (?,?,?,?,?)", (k, name, (req.get("blurb") or "").strip()[:120], "[]", len(rows)))
        return {"ok": True, "key": k}
    if k not in rows:
        return {"error": "no such station"}
    st = rows[k]
    if what in ("add", "remove"):
        artist = (req.get("artist") or "").strip()[:120]
        if not artist and lms_qobuz.PLAYER.match(req.get("player") or ""):  # the artist the room is playing
            cur = (rpc(req["player"], "status", "-", "1", "tags:a").get("playlist_loop") or [{}])[0]
            artist = (split_artists(cur.get("artist") or "") or [""])[0]
        if not artist:
            return {"error": "no artist"}
        seeds = [x for x in st["seeds"] if key(x) != key(artist)] + ([artist] if what == "add" and artist else [])
        with db_lock, db() as c:
            c.execute("update stations set seeds = ? where key = ?", (json.dumps(seeds, ensure_ascii=False), k))
        return {"ok": True, "artist": artist, "already": what == "add" and any(key(x) == key(artist) for x in st["seeds"])}
    elif what == "rename":
        with db_lock, db() as c:
            c.execute("update stations set name = ?, blurb = ? where key = ?", ((req.get("name") or st["name"]).strip()[:60], (req.get("blurb") if req.get("blurb") is not None else st["blurb"]).strip()[:120], k))
    elif what == "delete":
        with db_lock, db() as c:
            c.execute("delete from stations where key = ?", (k,))
    else:
        return {"error": "unknown"}
    return {"ok": True}


# ───────────────────────── never play: banned artists and tracks, kept out of what the radio brings ─────────────────────────
def ban_key(kind, artist, title=""):
    return key(artist) if kind == "artist" else key(title) + "|" + key(artist)


def import_bans():
    """Once: the house's banned artists and tracks from the Home Assistant lists they were kept in (tracks there read
    "title - artist")."""
    if kv_get("bans_imported") or not settings["features"]["home_assistant"]:
        return
    rows = []
    for entity, kind in (("todo.banned_artists", "artist"), ("todo.banned_tracks", "track")):
        try:
            got = ha_call("/api/services/todo/get_items?return_response", {"entity_id": entity, "status": ["needs_action"]})
            for i in ((got or {}).get("service_response") or {}).get(entity, {}).get("items", []):
                name = (i.get("summary") or "").strip()
                if not name:
                    continue
                if kind == "artist":
                    rows.append(("artist", ban_key("artist", name), name, time.time()))
                else:
                    title, _, artist = name.rpartition(" - ")
                    if title and artist:
                        rows.append(("track", ban_key("track", artist, title), f"{title} — {artist}", time.time()))
        except Exception:
            return  # Home Assistant not answering: tried again next time
    with db_lock, db() as c:
        c.executemany("insert or replace into bans values (?,?,?,?)", rows)
    kv_set("bans_imported", True)


def bans():
    with db() as c:
        return [{"kind": k, "key": kk, "label": l, "at": round(a)} for k, kk, l, a in c.execute("select * from bans order by at desc")]


def ban(req):
    """Never play an artist, or one track; a ban lifted. What is playing now, if it is what was banned, is skipped."""
    kind, artist, title, player = req.get("kind"), (req.get("artist") or "").strip(), (req.get("title") or "").strip(), req.get("player") or ""
    if req.get("unban"):  # by name: an artist, or a track as "title - artist" or by its two names
        if kind == "track" and not title and " - " in artist:
            title, _, artist = artist.rpartition(" - ")
        req["lift"] = ban_key(kind, artist, title)
    if req.get("lift"):
        with db_lock, db() as c:
            c.execute("delete from bans where kind = ? and k = ?", (kind, req["lift"]))
        return {"ok": True, "bans": bans()}
    if not artist and lms_qobuz.PLAYER.match(player):  # what the room is playing (the wall's and the panels' buttons)
        cur = (rpc(player, "status", "-", "1", "tags:at").get("playlist_loop") or [{}])[0]
        artist, title = (split_artists(cur.get("artist") or "") or [""])[0] if kind == "artist" else (cur.get("artist") or ""), cur.get("title") or ""
    if kind not in ("artist", "track") or not artist or (kind == "track" and not title):
        return {"error": "nothing to ban"}
    k = ban_key(kind, artist, title)
    with db_lock, db() as c:
        c.execute("insert or replace into bans values (?,?,?,?)", (kind, k, artist if kind == "artist" else f"{title} — {artist}", time.time()))
    if lms_qobuz.PLAYER.match(player):
        cur = (rpc(player, "status", "-", "1", "tags:at").get("playlist_loop") or [{}])[0]
        if banned(cur, {(kind, k)}):
            rpc(player, "playlist", "index", "+1")  # banned while it plays: skipped, whoever put it on
        threading.Thread(target=sweep_room, args=(player,), daemon=True).start()
    return {"ok": True, "artist": artist, "title": title}


def banned(t, keys):
    a, ti = t.get("artist") or "", t.get("title") or ""
    return ("artist", ban_key("artist", a)) in keys or any(("artist", ban_key("artist", x)) in keys for x in split_artists(a)) or ("track", ban_key("track", a, ti)) in keys


# what the radio put in each room's queue (and the tracks a station started it with): the only music a sweep may take out.
# Lyrion's event stream tells: a batch of tracks added with no command from any app just before it is the radio's own
# (Don't Stop the Music works inside Lyrion); anything an app asked for comes after its command ("playlistcontrol …",
# "playlist add …"). A new queue (loaded, cleared) starts the room's record afresh.
radio_added = {}  # player → {track url}
recent_cmd = {}  # player → when an app last changed its queue
quiet_reset = {}  # player → until when its queue's being emptied is Soundsquatch's own doing (a station starting)
CMD = re.compile(r"^(playlistcontrol|playlist (add|insert|play|load|resume|append|inserttracks|playalbum|addalbum|loadalbum|insertalbum|move|delete)\b)")


def cli_port():
    """Lyrion's command line's port: LMS_CLI_PORT where a house maps it elsewhere (Docker), else Lyrion's own setting."""
    if os.environ.get("LMS_CLI_PORT"):
        return int(os.environ["LMS_CLI_PORT"])
    try:
        return int(rpc("", "pref", "plugin.cli:cliport", "?", timeout=5).get("_p2") or 9090)
    except Exception:
        return 9090


def radio_events():
    """Lyrion's event stream (its CLI), kept open, for what the radio adds to each queue."""
    while True:
        try:
            with socket.create_connection((urllib.parse.urlparse(LMS).hostname or "127.0.0.1", cli_port()), timeout=30) as sock:
                sock.sendall(cli_login() + b"listen 1\n")
                sock.settimeout(None)
                buf = b""
                while True:
                    data = sock.recv(65536)
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            text = urllib.parse.unquote(line.decode("utf-8", "replace")).strip()
                            if text.startswith("rescan done"):  # a scan finished (files, or the online library after a favourite): the shelves read again now
                                threading.Thread(target=load_library, kwargs={"force": True}, daemon=True).start()
                            radio_event(text)
                        except Exception:
                            pass
        except Exception:
            pass
        time.sleep(5)


def radio_event(line):
    player, _, rest = line.partition(" ")
    if not lms_qobuz.PLAYER.match(player):
        return
    now = time.time()
    if CMD.match(rest):
        recent_cmd[player] = now
    elif rest.startswith("playlist addtracks") and "listRef" in rest and now - recent_cmd.get(player, 0) > 3:
        m = re.search(r"index:(\d+)", rest)
        start = int(m.group(1)) if m else 0
        def note():  # the batch, read once Lyrion has it in place
            time.sleep(1)
            got = rpc(player, "status", str(start), "100", "tags:u").get("playlist_loop") or []
            radio_added.setdefault(player, set()).update(t.get("url") for t in got if t.get("url"))
        threading.Thread(target=note, daemon=True).start()
    elif (rest.startswith("playlist loadtracks") or rest.startswith("playlist clear")) and now > quiet_reset.get(player, 0):
        radio_added[player] = set()


def sweep_room(player):
    """Takes banned music, and excluded albums, out of a room's queue after what is playing: only what the radio brought
    (or a station started with). Music put on by hand plays whole."""
    with db() as c:
        keys = {(k, kk) for k, kk in c.execute("select kind, k from bans")}
    exclude = [x.lower() for x in kv_get("exclude_albums", [])]
    st = rpc(player, "status", "0", "1000", "tags:atlu")
    cur = int(st.get("playlist_cur_index") or 0)
    gone = 0
    for t in reversed(st.get("playlist_loop") or []):
        i = int(t.get("playlist index") or 0)
        if i <= cur:
            continue
        if t.get("url") not in radio_added.get(player, ()):
            continue
        if (keys and banned(t, keys)) or any(x in (t.get("album") or "").lower() for x in exclude):
            rpc(player, "playlist", "delete", str(i))
            gone += 1
    return gone


def sweeper():
    """Every half minute, the queues of the rooms playing: banned music the radio brought taken out."""
    time.sleep(60)
    while True:
        try:
            import_bans()
            for p in rpc("", "players", "0", "50").get("players_loop") or []:
                if p.get("connected") and p.get("isplaying") and radio_added.get(p["playerid"]):
                    n = sweep_room(p["playerid"])
                    if n:
                        crawl_state["swept"] = crawl_state.get("swept", 0) + n
        except Exception as e:
            note_error(f"sweeper: {type(e).__name__}: {e}"[:200])
        time.sleep(30)


# ───────────────────────── the Internet Archive, through Lyrion's ArchiveLMA plugin ─────────────────────────
archive_cache = {}


def archive_items(player, item, term=None, count=300):
    cmd = ["archivelma", "items", "0", str(count), f"item_id:{item}"] + ([f"search:{term}"] if term else [])
    return rpc(player, *cmd, timeout=60).get("loop_loop") or []


def show_parts(name):
    """ "★ Low Live at Miramar Theatre on 2001-10-27" → (artist, venue, date)."""
    name = name.lstrip("★ ").strip()
    m = re.match(r"^(.*?) Live at (.*?)(?: on)? (\d{4}-\d{2}-\d{2})$", name)
    return (m.group(1), m.group(2), m.group(3)) if m else (name, "", "")


def archive_show_row(it, ctx):
    artist, venue, date = show_parts(it.get("name") or "")
    image = it.get("image") or ""
    m = re.search(r"archive\.org/services/img/([^/?#]+)", urllib.parse.unquote(image))
    return {"ctx": ctx, "id": m.group(1) if m else "", "artist": artist, "venue": venue, "date": date, "title": (it.get("name") or "").lstrip("★ "), "image": image}


def archive_favorites():
    """The plugin's own favourites (its ★ Favorites menu): the Archive's shows on the house's shelves."""
    if not feature("archive"):
        return {"shows": []}
    hit = archive_cache.get("fav")
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    items = archive_items(PLAYER, "7")
    rows = [archive_show_row(it, {"item": it.get("id")}) for it in items if it.get("id")]
    # when each first appeared among the favourites (the plugin keeps no date): a new one leads Recently added
    with db_lock, db() as c:
        seen = dict(c.execute("select identifier, first_seen from archive_seen"))
        first_look = not seen
        for r in rows:
            r["id"] = r["id"] or r["title"]
            if r["id"] not in seen:
                seen[r["id"]] = 0 if first_look else time.time()  # the first look finds the old ones: undated
                c.execute("insert into archive_seen values (?,?)", (r["id"], seen[r["id"]]))
            r["added"] = seen[r["id"]]
    out = {"shows": rows}
    archive_cache["fav"] = (time.time(), out)
    return out


def archive_artist(name):
    """An artist's shows in the plugin's collections, newest first (its search, the shows named for them)."""
    if not feature("archive"):
        return {"shows": []}
    k = "artist:" + key(name)
    hit = archive_cache.get(k)
    if hit and time.time() - hit[0] < 6 * 3600:
        return hit[1]
    items = archive_items(PLAYER, "0", term=name)
    mine = [it for it in items if (it.get("name") or "").lower().startswith(name.lower() + " live")]
    rows = [archive_show_row(it, {"item": it.get("id"), "term": name}) for it in mine]
    out = {"shows": sorted(rows, key=lambda r: r["date"], reverse=True)}
    archive_cache[k] = (time.time(), out)
    return out


def archive_search(term):
    """The plugin's search of the house's Archive collections (artists and venues), for Search: shows by anyone, not
    only the shelves' artists. It finds nothing for "Spoon 2003", so a year at the end is kept out and matched here."""
    term = " ".join(term.split())[:120]
    if not feature("archive") or len(term) < 3:
        return {"shows": []}
    k = "search:" + term.lower()
    hit = archive_cache.get(k)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    m = re.fullmatch(r"(.+?)\s+((?:19|20)\d\d)", term)
    ask, year = (m.group(1), m.group(2)) if m else (term, "")
    items = [it for it in archive_items(PLAYER, "0", term=ask) if it.get("type") == "link"]
    rows = [archive_show_row(it, {"item": it.get("id"), "term": ask}) for it in items]
    out = {"shows": sorted([r for r in rows if r["date"].startswith(year)], key=lambda r: r["date"], reverse=True)}
    archive_cache[k] = (time.time(), out)
    return out


def archive_show(ctx, player):
    """A show's menu: its setlist and the plugin's own actions on it (kept ten minutes: archive.org is slow to answer)."""
    k = "show:" + json.dumps(ctx, sort_keys=True)
    hit = archive_cache.get(k)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    items = archive_items(player, ctx["item"], term=ctx.get("term"), count=200)
    tracks = [it.get("name") or "" for it in items if it.get("type") == "audio"]
    fav = any((it.get("name") or "").startswith("★ Remove") for it in items)
    title = next((it.get("name") for it in items if it.get("type") == "text"), "")
    out = {"title": title, "tracks": tracks, "favorite": fav}
    archive_cache[k] = (time.time(), out)
    return out


def archive_details(identifier):
    """What archive.org says of a show: where and when, the recording's source and lineage, its notes, and each track's
    length (the original audio files, in order); kept a month."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", identifier or ""):
        return {"error": "no such show"}
    with db() as c:
        got = c.execute("select data, fetched from archive_details where id = ?", (identifier,)).fetchone()
    if got and time.time() - got[1] < STALE:
        return json.loads(got[0])
    d = get_json("https://archive.org/metadata/" + identifier, timeout=30)
    m = d.get("metadata") or {}
    one = lambda k: (m.get(k)[0] if isinstance(m.get(k), list) else m.get(k)) or ""
    files = [f for f in d.get("files") or [] if f.get("source") == "original" and re.search(r"flac|mp3|ogg|wav|shorten|aiff", f.get("format") or "", re.I)
             and not re.search(r"fingerprint|ffp|md5|spectrogram", f.get("format") or "", re.I)]
    seen, tracks = set(), []
    def order(f):
        n = re.match(r"\d+", str(f.get("track") or ""))
        return (int(n.group()) if n else 9999, f.get("name") or "")
    for f in sorted(files, key=order):
        t = re.sub(r"\s+", " ", f.get("title") or os.path.splitext(f.get("name") or "")[0]).strip()  # a file with no title: its name
        if t.lower() in seen or not t:
            continue
        seen.add(t.lower())
        try:
            length = float(f.get("length") or 0) if ":" not in str(f.get("length")) else sum(float(x) * 60 ** i for i, x in enumerate(reversed(str(f["length"]).split(":"))))
        except ValueError:
            length = 0
        tracks.append({"title": t, "length": round(length)})
    # the notes' own lines, kept: a list's items one to a line, a paragraph ending with a blank line
    text = re.sub(r"<li[^>]*>|<br\s*/?>|</div>|</h\d>", "\n", one("description"), flags=re.I)
    text = re.sub(r"</p>|</?[ou]l[^>]*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text).replace("&amp;", "&").replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    text = "\n".join(l.strip() for l in text.split("\n")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    out = {"id": identifier, "title": one("title"), "creator": one("creator"), "date": one("date")[:10], "venue": one("venue"), "place": one("coverage"),
           "source": one("source"), "lineage": one("lineage"), "taper": one("taper"), "transferer": one("transferer"), "runtime": one("runtime"),
           "notes": text, "setlist": setlist_from(text), "tracks": tracks, "url": "https://archive.org/details/" + identifier}
    with db_lock, db() as c:
        c.execute("insert or replace into archive_details values (?,?,?)", (identifier, json.dumps(out, ensure_ascii=False), time.time()))
    return out


NUMBERED = re.compile(r"^(?:d\d+)?(?:t(?:rack)?)?\s*(\d{1,2})\s*[.):\-]?\s+(.+)$", re.I)
HEADER = re.compile(r"^(track\s*list(ing)?|set\s*list|setlist|songs|tracks)\s*:?\s*(.*)$", re.I)
SECTION = re.compile(r"^(encore|set\s*(\d|one|two|i+)|disc\s*\d|cd\s*\d|d\d)\b[^a-z]*:?$", re.I)


def setlist_from(notes):
    """The songs a show's notes list, in order: the lines under a "Track listing:" / "Setlist:" heading, or else its
    numbered lines ("01 White Horses", "d1t03. Sunflower"); headings like "Encore:" are passed over, and a footnote or a
    sentence ends the list. Lengths in brackets come off."""
    lines = [l.strip() for l in notes.split("\n")]
    clean = lambda l: re.sub(r"\s*[\(\[]?\d{1,2}:\d{2}[\)\]]?\s*$|\s+-\s*$", "", NUMBERED.sub(lambda m: m.group(2), l)).strip()
    out = []
    at = next((i for i, l in enumerate(lines) if HEADER.match(l)), None)
    if at is not None:
        rest = HEADER.match(lines[at]).group(3).strip()
        for l in ([rest] if rest else []) + lines[at + 1:]:
            if not l:
                if out:
                    break
                continue
            if SECTION.match(l):
                continue
            if ";" in l or len(l) > 80 or l.endswith("."):
                break
            out.append(clean(l))
    else:
        out = [clean(l) for l in lines if NUMBERED.match(l)]
    return [x for x in out if x]


def archive_do(req):
    """A show played, queued, or made (or unmade) a favourite, by opening the plugin's own entry for it; a track from
    the setlist plays the whole show from there."""
    ctx, what, player = req.get("ctx") or {}, req.get("what"), req.get("player") or PLAYER
    if not lms_qobuz.PLAYER.match(player) or not isinstance(ctx.get("item"), str):
        return {"error": "no such show"}
    items = archive_items(player, ctx["item"], term=ctx.get("term"), count=200)
    want = {"play": "Play Entire Show", "queue": "Add Entire Show to Queue", "fav": "★ Add to Favorites", "unfav": "★ Remove", "track": "Play Entire Show"}.get(what)
    entry = next((it for it in items if (it.get("name") or "").startswith(want or "\0")), None)
    if not entry:
        return {"error": "the plugin offers no such thing for this show"}
    archive_items(player, entry["id"], term=ctx.get("term"), count=5)  # opening it is what does it
    if what == "track":
        time.sleep(1.5)
        rpc(player, "playlist", "index", str(int(req.get("index") or 0)))
    if what in ("fav", "unfav"):  # the favourites, and this show's own menu, change
        for k in [k for k in archive_cache if k == "fav" or k.startswith("show:")]:
            archive_cache.pop(k, None)
    return {"ok": True}


# ───────────────────────── pictures ─────────────────────────
def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{threading.get_ident()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def shrink(data, width):
    """A picture no wider than width (nor taller than twice it), as a JPEG; as it was if it is smaller already."""
    im = Image.open(io.BytesIO(data))
    if im.width <= width and im.height <= width * 2 and im.format == "JPEG":
        return data
    im.draft("RGB", (width, width * 2))
    im = im.convert("RGB")
    im.thumbnail((width, width * 2), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=84, optimize=True, progressive=True)
    return out.getvalue()


def picture(url, width=None):
    """A picture from one of the sites the profiles name, from the cache or fetched into it, at width when asked:
    (bytes, type) or None."""
    host = urllib.parse.urlparse(url).hostname or ""
    if url.startswith("http://") and host in PICTURE_HOSTS:
        url = "https://" + url[len("http://"):]  # the same picture over https (TIDAL's plugin names its covers by http)
    if not url.startswith("https://") or host not in PICTURE_HOSTS:
        return None
    path = os.path.join(IMG_CACHE, hashlib.sha1(url.encode()).hexdigest())
    if width:
        try:
            with open(f"{path}_{width}", "rb") as f:
                return f.read(), "image/jpeg"
        except OSError:
            pass
    try:
        with open(path, "rb") as f:
            data = f.read()
        os.utime(path)
    except OSError:
        try:
            if time.time() - os.path.getmtime(path + ".none") < 7 * 86400:
                return None  # the site had no such picture lately: not asked again for a week
        except OSError:
            pass
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=20) as r:
                data = r.read(15 * 1024 * 1024)
        except urllib.error.HTTPError:  # none there, or the site failing over it (archive.org's thumbnails do): the page goes without
            save(path + ".none", b"")
            return None
        save(path, data)
    if width:
        try:
            data = shrink(data, width)
            save(f"{path}_{width}", data)
            return data, "image/jpeg"
        except Exception:
            pass
    kind = "image/png" if data[:4] == b"\x89PNG" else "image/webp" if data[8:12] == b"WEBP" else "image/jpeg"
    return data, kind


FACE_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "face_detection_yunet_2023mar.onnx")


def focus(url):
    """Where the faces are in an artist's photograph, as fractions of its width and height ({"x", "y"}), so a crop
    keeps their heads; {} when there's none to be seen (or no OpenCV), and the page crops from near the top instead.
    Found once for each picture (YuNet, a small face finder, on this machine) and kept."""
    k = "focus:" + hashlib.sha1(url.encode()).hexdigest()[:20]
    had = kv_get(k)
    if had is not None:
        return had
    try:
        import cv2, numpy
        if url.startswith("/artist-photo/"):
            n = url[len("/artist-photo/"):]
            if not re.fullmatch(r"[a-z0-9]+-\d+(-320)?\.jpg", n):
                return {}
            with open(os.path.join(ARTIST_PICS, n), "rb") as f:
                data = f.read()
        else:
            got = picture(url, 1600)
            if not got:
                return {}
            data = got[0]
        img = cv2.imdecode(numpy.frombuffer(data, numpy.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        scale = 640 / max(h, w)
        small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))))
        found = cv2.FaceDetectorYN.create(FACE_MODEL, "", (small.shape[1], small.shape[0]), 0.6).detect(small)[1]
        faces = [] if found is None else [(float(f[0] + f[2] / 2), float(f[1] + f[3] / 2), float(f[2] * f[3])) for f in found]
        out = {}
        if faces:
            big = max(f[2] for f in faces)
            near = [f for f in faces if f[2] >= big / 4]  # the band, not a face in the crowd
            wt = sum(f[2] for f in near)
            out = {"x": round(sum(f[0] * f[2] for f in near) / wt / small.shape[1], 3), "y": round(sum(f[1] * f[2] for f in near) / wt / small.shape[0], 3)}
    except ImportError:
        return {}
    except Exception as e:
        note_error(f"focus: {e}")
        return {}
    kv_set(k, out)
    return out


def cover_path(art, size):
    return os.path.join(COVERS, art[:2], f"{art}_{size}.jpg")


def cover_file(art, size):
    """An album's cover at size, from the cache; the first asking fetches Lyrion's at 800 and makes every size from it."""
    path = cover_path(art, size)
    if os.path.exists(path):
        return path
    if size > 800:  # as large as Lyrion has it, for a spread across the page
        with urllib.request.urlopen(f"{LMS}/music/{art}/cover_{size}x{size}_o.jpg", timeout=30) as r:
            save(path, shrink(r.read(), size))
        return path
    with urllib.request.urlopen(f"{LMS}/music/{art}/cover_800x800_o.jpg", timeout=30) as r:
        master = r.read()
    for s in COVER_SIZES:
        save(cover_path(art, s), master if s == 800 else shrink(master, s))
    return path


def trim_pictures():
    while True:
        try:
            files = [(e.stat().st_mtime, e.stat().st_size, e.path) for e in os.scandir(IMG_CACHE) if e.is_file()]
            total = sum(f[1] for f in files)
            for _, size, path in sorted(files):
                if total <= IMG_CAP:
                    break
                os.remove(path)
                total -= size
        except OSError:
            pass
        time.sleep(6 * 3600)


# ───────────────────────── serving ─────────────────────────
def stamped_index():
    with open(os.path.join(APP, "index.html")) as f:
        html = f.read()
    for name in ("app.js", "app.css"):
        with open(os.path.join(APP, name), "rb") as f:
            html = html.replace(f'"{name}"', f'"{name}?v={hashlib.sha1(f.read()).hexdigest()[:10]}"')
    return html.encode()


STATIC = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".png": "image/png", ".json": "application/manifest+json", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".woff2": "font/woff2"}


# ───────────────────────── the turntable: what the record player plays, heard ─────────────────────────
# A listener on a Pi sends the amplifier's record-out here (turntable.py's Ear). While the turntable's lid is open
# (Home Assistant's sensor, settings house.turntable_lid) what it hears is a record: each song is named (the house's own
# files first, then Shazam), the record found among the Discogs collection, and the spin kept: the songs heard, the
# sides. A record counts as played once two of its songs (or eight minutes of it) are heard: its plays go up, and on
# Discogs its "Plays" and "Last played" fields (when the collection has fields of those names). While it plays, and
# when a side ends, it suggests what to play next: the band's next record, and an artist that followed.
TT = {"state": "idle", "spin": None, "song": None, "side_over_at": 0, "lid": None, "lid_at": 0, "shazam_at": 0, "runs": {}, "error": ""}
tt_lock = threading.Lock()
SHAZAM_MAX, SHAZAM_WINDOW = 6, 1800  # at most six asks of Shazam in half an hour (two must agree; it throttled the house at hundreds an hour)
TT_INDEX = None
EAR = None


def tt_lid():
    """The lid: True (open: a record is on), False (closed), None (no sensor set), asked every ten seconds at most. When
    Home Assistant doesn't answer, the last answer stands for five minutes, then the lid counts as shut: a sensor that
    can't say it's open isn't a record playing (a missed answer once let the streamer be taken for one)."""
    entity = settings["house"].get("turntable_lid")
    if not entity or not HA_URL:
        return None
    if time.time() - TT["lid_at"] > 10:
        TT["lid_at"] = time.time()
        try:
            with open(HA_TOKEN) as f:
                token = f.read().strip()
            req = urllib.request.Request(f"{HA_URL}/api/states/{entity}", headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(req, timeout=5) as r:
                TT["lid"], TT["lid_known_at"] = json.load(r).get("state") == "on", time.time()
        except Exception:
            if time.time() - TT.get("lid_known_at", 0) > 300:
                TT["lid"] = False
    return TT["lid"]


def tt_room_busy():
    """The turntable's room playing something from Lyrion (other than the turntable itself): the amplifier is on the
    streamer, so the record-out carries that, not a record. Asked every ten seconds at most."""
    room = settings["house"].get("turntable_room")
    if not room:
        return False
    if time.time() - TT.get("room_at", 0) > 10:
        TT["room_at"] = time.time()
        try:
            st = rpc(room, "status", "-", "1", "tags:u", timeout=5)
            url = (st.get("playlist_loop") or [{}])[0].get("url") or ""
            TT["room_busy"] = st.get("mode") == "play" and not url.endswith("/turntable.flac")
        except Exception:
            TT["room_busy"] = False
    return TT["room_busy"]


def tt_not_record():
    """What the listener hears isn't a record: the lid is shut, or the turntable's room is playing from Lyrion."""
    return tt_lid() is False or tt_room_busy()


def discogs_release(rid):
    """A release as Discogs has it (its tracklist and sides, credits, notes, identifiers, videos, the community's
    numbers), kept a month."""
    k = f"dr:{rid}"
    got = kv_get(k)
    if got and time.time() - got.get("_at", 0) < 30 * 86400:
        return got
    token = discogs_token()
    if not token:
        return got or {}
    try:
        d = discogs_get(f"/releases/{int(rid)}", token)
    except Exception:
        return got or {}
    out = {"_at": time.time(), "title": d.get("title") or "", "year": d.get("year") or 0, "released": d.get("released_formatted") or d.get("released") or "",
           "country": d.get("country") or "", "notes": d.get("notes") or "", "master": d.get("master_id") or 0, "uri": d.get("uri") or "",
           "tracks": [{"pos": t.get("position") or "", "title": t.get("title") or "", "dur": t.get("duration") or "", "type": t.get("type_") or "track",
                       "artists": ", ".join(re.sub(r" \(\d+\)$", "", a.get("name") or "") for a in t.get("artists") or []),
                       "credits": [[re.sub(r" \(\d+\)$", "", a.get("name") or ""), a.get("role") or ""] for a in t.get("extraartists") or []]} for t in d.get("tracklist") or []],
           "credits": [[re.sub(r" \(\d+\)$", "", a.get("name") or ""), a.get("role") or "", a.get("tracks") or ""] for a in d.get("extraartists") or []],
           "ids": [[i.get("type") or "", i.get("value") or "", i.get("description") or ""] for i in d.get("identifiers") or []],
           "videos": [[v.get("uri") or "", v.get("title") or "", v.get("duration") or 0] for v in d.get("videos") or []][:12],
           "labels": [[l.get("name") or "", l.get("catno") or ""] for l in d.get("labels") or []],
           "companies": [[c.get("name") or "", c.get("entity_type_name") or ""] for c in d.get("companies") or []],
           "genres": d.get("genres") or [], "styles": d.get("styles") or [],
           "community": {"have": (d.get("community") or {}).get("have") or 0, "want": (d.get("community") or {}).get("want") or 0,
                         "rating": ((d.get("community") or {}).get("rating") or {}).get("average") or 0, "votes": ((d.get("community") or {}).get("rating") or {}).get("count") or 0},
           "images": [i.get("uri") or "" for i in d.get("images") or []][:8]}
    kv_set(k, out)
    return out


def record_side(rec_id, title, heard=()):
    """Where a song is on a record: (position such as "B2", its side "B"), by its title in Discogs's tracklist. When a
    title is on the record twice (a side of live takes, a reprise), the one not yet heard this spin; a live take to a
    title that says live."""
    want, best = lms_qobuz.plain(title), None
    live = "live" in (title or "").lower()
    for i, t in enumerate(discogs_release(rec_id).get("tracks") or []):
        have = lms_qobuz.plain(t["title"])
        if t["type"] != "track" or not want or not (have == want or want in have or have in want):
            continue
        score = (2 if have == want else 0) + (2 if ("live" in t["title"].lower()) == live else 0) + (1 if t["pos"] not in heard else 0)
        if not best or score > best[0]:
            best = (score, t["pos"])
    if not best:
        return "", ""
    m = re.match(r"^([A-Za-z]+)", best[1])
    return best[1], (m.group(1).upper() if m else "")


def physical_now():
    with lib_lock:
        albums = list(library["albums"])
    return albums, physical_records(albums)


def find_record(song):
    """The record in the collection a named song is from: by the album the house's files matched, else by the artist
    and the album's name, else by the song in each candidate's tracklist."""
    albums, phys = physical_now()
    if song.get("album_id"):
        a = album_row(song["album_id"])
        ids = {song["album_id"]} | ({a[12]} if a and len(a) > 12 else set())
        for e in albums:  # the album's other versions count too
            if e[0] in ids or any(v[0] in ids for v in e[10]):
                ids.add(e[0])
        got = [r for r in phys if r[8] in ids]
        if got:
            return got[0]
    by = [r for r in phys if key(r[2]) == key(song["artist"])] or [r for r in phys if song.get("album") and lms_qobuz.plain(r[1]) == lms_qobuz.plain(song["album"])]
    if len(by) > 1 and song.get("album"):
        same = [r for r in by if lms_qobuz.plain(r[1]) == lms_qobuz.plain(song["album"]) or lms_qobuz.plain(song["album"]).startswith(lms_qobuz.plain(r[1]))]
        by = same or by
    if len(by) > 1:
        by = [r for r in by if record_side(r[0], song["title"])[0]] or by
    return by[0] if by else discogs_lookup(song)


def discogs_lookup(song):
    """A record not in the collection: the vinyl pressing on Discogs most people own, by the artist and the album (else
    the song) Shazam named, shaped as a collection row and marked new, so it is added to the collection once played."""
    token, album = discogs_token(), re.sub(r"\s*(- (EP|Single)|\((Deluxe|Remaster|Expanded)[^)]*\))\s*$", "", song.get("album") or "", flags=re.I).strip()
    if not token or not song.get("artist"):
        return None
    k = "dl:" + key(song["artist"]) + "|" + lms_qobuz.plain(album or song["title"])
    hit = kv_get(k)
    if hit is None:
        hit = {}
        for q in ([("release_title", album)] if album else []) + [("track", song["title"])]:
            try:
                got = discogs_get("/database/search?" + urllib.parse.urlencode({"type": "release", "format": "Vinyl", "artist": song["artist"], q[0]: q[1], "per_page": 25}), token).get("results") or []
            except Exception as e:
                note_error(f"discogs search: {e}")
                return None
            if got:
                hit = max(got, key=lambda r: (r.get("community") or {}).get("have") or 0)
                break
        kv_set(k, hit)
    if not hit.get("id"):
        return None
    artist, _, title = (hit.get("title") or "").partition(" - ")
    fmts = hit.get("format") or []
    return [hit["id"], title or album, re.sub(r" \(\d+\)$", "", artist) or song["artist"], int(hit.get("year") or 0), hit.get("cover_image") or hit.get("thumb") or "",
            " ".join(f for f in fmts if f in ("Vinyl", "LP", "EP", '7"', '10"', '12"', "Album")), " ".join(x for x in ((hit.get("label") or [""])[0], hit.get("catno")) if x and x != "none"), "", 0,
            {"g": hit.get("genre") or [], "s": hit.get("style") or [], "d": fmts, "t": "", "box": False, "r": 0, "i": None, "f": None, "ln": (hit.get("label") or [""])[0], "n": {}, "new": True}]


def tt_lengths(rec):
    """Each song's length on a record, {position: seconds}: Discogs's, else the house's own copy's, else MusicBrainz's
    (by title); kept once found."""
    k = f"tl:{rec[0]}"
    out = kv_get(k)
    if out:
        return out
    tracks = [t for t in discogs_release(rec[0]).get("tracks") or [] if t["type"] == "track"]

    def secs(d):
        try:
            return float(sum(int(p) * 60 ** i for i, p in enumerate(reversed(d.split(":"))))) if d else 0.0
        except ValueError:
            return 0.0
    out = {t["pos"]: secs(t["dur"]) for t in tracks if secs(t["dur"])}
    if len(out) < len(tracks):
        others = {}
        if len(rec) > 8 and rec[8]:
            for x in rpc("", "titles", "0", "300", f"album_id:{rec[8]}", "tags:d", timeout=20).get("titles_loop") or []:
                others[lms_qobuz.plain(x.get("title") or "")] = float(x.get("duration") or 0)
        if sum(1 for t in tracks if others.get(lms_qobuz.plain(t["title"]))) < len(tracks):
            try:
                q = f'artist:"{rec[2].replace(chr(34), "")}" AND release:"{rec[1].strip().replace(chr(34), "")}"'
                rs = mb_get("release", query=q, limit=10).get("releases") or []
                rel = next((x for x in rs if x.get("track-count") == len(tracks)), None)
                if rel:
                    for m in mb_get("release/" + rel["id"], inc="recordings").get("media") or []:
                        for t in m.get("tracks") or []:
                            others.setdefault(lms_qobuz.plain(t.get("title") or ""), (t.get("length") or 0) / 1000)
            except Exception as e:
                note_error(f"song lengths: {e}")
        for t in tracks:
            if t["pos"] not in out and others.get(lms_qobuz.plain(t["title"])):
                out[t["pos"]] = others[lms_qobuz.plain(t["title"])]
    if out:
        kv_set(k, out)
    return out


def tt_schedule(spin):
    """The side playing, by the clock, from the song the house named and when it began: [(track, began)], the songs
    before it worked back from it, those after forward, each by its length and a two-second gap. It stops where a
    length isn't known."""
    tl = spin.get("timeline")
    if not tl or not EAR:
        return []
    tracks = [t for t in discogs_release(spin["id"]).get("tracks") or [] if t["type"] == "track"]
    side = [t for t in tracks if re.match(r"^([A-Za-z]+)", t["pos"]) and re.match(r"^([A-Za-z]+)", t["pos"]).group(1).upper() == tl["side"]]
    at = next((i for i, t in enumerate(side) if t["pos"] == tl["pos"]), None)
    if at is None:
        return []
    L, t0 = tt_lengths(spin["record"]), EAR.clock - (time.time() - tl["wall"])  # its start on the stream's clock
    out, b = [(side[at], t0)], t0
    for t in side[at + 1:]:  # forward
        prev = out[-1][0]
        if not L.get(prev["pos"]):
            break
        b += L[prev["pos"]] + 2
        out.append((t, b))
    b, back = t0, []
    for t in reversed(side[:at]):  # and back
        if not L.get(t["pos"]):
            break
        b -= L[t["pos"]] + 2
        back.insert(0, (t, b))
    return back + out


def tt_follow(spin, at):
    """A clip while the house's own naming holds: the song by the clock, no Shazam. A side over and sound again is the
    next side, from its first song."""
    tl = spin["timeline"]
    if TT["state"] in ("side over", "record over") or EAR.lifted_at > tl.get("since", 0):  # quiet, or the needle lifted
        tracks = [t for t in discogs_release(spin["id"]).get("tracks") or [] if t["type"] == "track"]
        on_side = [t for t in tracks if t["pos"].upper().startswith(tl["side"])]
        if on_side and (TT["song"] or {}).get("pos") != on_side[-1]["pos"]:
            # quiet before the side's last song: the needle lifted and set down again, not a flip. Which song it is
            # now isn't known: the clock lets go and the house is asked (the next in order as the guess)
            spin.pop("timeline", None)
            tt_save()
            return False
        sides = list(dict.fromkeys((re.match(r"^([A-Za-z]+)", t["pos"]) or re.match("", "")).group(0).upper() for t in tracks))
        nxt = sides[sides.index(tl["side"]) + 1] if tl["side"] in sides and sides.index(tl["side"]) + 1 < len(sides) else None
        if not nxt:  # the last side played: what plays now is another record
            with tt_lock:
                tt_end_spin()
            return False
        first = next(t for t in tracks if t["pos"].upper().startswith(nxt))
        start = EAR.run_start if EAR.run_start is not None else at
        spin["timeline"] = tl = {"side": nxt, "pos": first["pos"], "wall": time.time() - (EAR.clock - start), "since": time.time()}
    now = [x for x in tt_schedule(spin) if x[1] <= at]
    if not now:
        return False
    t, began = now[-1]
    if not TT["song"] or TT["song"].get("pos") != t["pos"]:
        rec = spin["record"]
        tt_heard({"title": t["title"], "artist": t["artists"] or rec[2], "album": rec[1].strip(), "how": "you", "at": time.time(), "run": EAR.run, "start": began})
    return True


def tt_clip(x8, wav, run_seconds, run, at=0):
    """A clip to name (from the Ear). Not while the lid is shut or the room streams: then it is the tuner, a tape or the streamer."""
    if tt_not_record() or TT_INDEX is None:
        return False
    spin = TT["spin"]
    if spin and spin.get("timeline") and spin.get("record"):  # the house named the record and a song: the rest by the clock
        return tt_follow(spin, at or EAR.clock)  # tt_heard takes the lock itself
    known = TT["runs"].get(run)
    song = None
    m = TT_INDEX.match(x8)
    if m:
        meta = (kv_get("tt_meta") or {}).get(str(m[0]))
        if meta:
            song = {"title": meta[0], "artist": meta[1], "album": meta[2], "album_id": meta[3], "duration": meta[4], "offset": m[1], "how": "house", "speed": m[3]}
    if not song:
        if known and known.get("how") == "shazam" and run_seconds < 60:
            return True  # named already this stretch; asked again only on the slow re-checks
        if time.time() - TT["shazam_at"] < TT.get("shazam_wait", 10):
            return False
        asks = [t for t in TT.get("shazam_asks", []) if time.time() - t < SHAZAM_WINDOW]
        if len(asks) >= SHAZAM_MAX:  # Shazam asked enough lately: the house is asked instead (tt_unnamed)
            TT["shazam_asks"] = asks
            return False
        TT["shazam_at"] = time.time()
        TT["shazam_asks"] = asks + [time.time()]
        got = turntable.shazam(wav)
        try:  # the last clip asked about, to hear (or ask again) when a song goes unnamed
            with open(os.path.join(DATA, "turntable", "last-clip.wav"), "wb") as f:
                f.write(wav)
        except OSError:
            pass
        if not got:
            TT["shazam_wait"] = min(60, TT.get("shazam_wait", 10) * 1.5)  # misses in a row: ask less often (Shazam throttles)
            print(f"turntable: nothing named {run_seconds:.0f}s into the stretch (next try in {TT['shazam_wait']:.0f}s at the soonest)", flush=True)
            return False
        TT["shazam_wait"] = 10
        spin = TT["spin"]
        same = spin and key(spin.get("artist") or "") == key(got["artist"])
        if spin and spin.get("chosen") and not same:
            print(f"turntable: Shazam's {got['artist']} - {got['title']} set aside: the house chose {spin.get('title')}", flush=True)
            return False
        maybe, TT["maybe"] = TT.get("maybe"), (key(got["artist"]), time.time())
        if not same and not (maybe and maybe[0] == key(got["artist"]) and time.time() - maybe[1] < 90):
            print(f"turntable: Shazam says {got['artist']} - {got['title']}; asking again to be sure", flush=True)
            return False
        song = dict(got, how="shazam")
    song["at"], song["run"] = time.time(), run
    if at:  # where the song began, by the stream's clock: the clip's start, less how far into the song it was
        song["start"] = at - len(x8) / turntable.RATE - float(song.get("offset") or 0)
    TT["runs"][run] = song
    for k in [k for k in TT["runs"] if k < run - 20]:
        TT["runs"].pop(k, None)
    tt_heard(song)
    spin = TT["spin"]
    m = re.match(r"^([A-Za-z]+)", song.get("pos") or "")
    if spin and spin.get("record") and m and song.get("start") and EAR and tt_lengths(spin["record"]):
        spin["timeline"] = {"side": m.group(1).upper(), "pos": song["pos"], "wall": time.time() - (EAR.clock - song["start"]), "since": time.time()}  # the rest by the clock
        tt_save()
    return True
    return True


def tt_heard(song):
    """A song named: into the spin (a new spin when it is another record)."""
    rec = find_record(song)
    with tt_lock:
        spin = TT["spin"]
        if spin and rec and spin["id"] and spin["id"] != rec[0]:
            tt_end_spin()
            spin = None
        if not spin:
            TT["done"] = None
            spin = TT["spin"] = {"id": rec[0] if rec else 0, "record": rec, "start": time.time(), "songs": [], "counted": False, "suggest": [],
                                 "artist": rec[2] if rec else song["artist"], "title": rec[1].strip() if rec else song.get("album") or ""}
            threading.Thread(target=tt_suggest, args=(spin,), daemon=True).start()
        last = spin["songs"][-1] if spin["songs"] else None
        if last and last["pos"] and lms_qobuz.plain(last["title"]) == lms_qobuz.plain(song["title"]):
            pos, side = last["pos"], last["side"]  # the same song named again
        else:
            pos, side = record_side(rec[0], song["title"], {x["pos"] for x in spin["songs"]}) if rec else ("", "")
        song.update(pos=pos, side=side, rec=[rec[0], rec[1].strip(), rec[2]] if rec else None)
        if song.get("start"):
            TT.setdefault("marks", []).append(dict(song))
            TT["marks"] = TT["marks"][-200:]
        last = spin["songs"][-1] if spin["songs"] else None
        if not last or lms_qobuz.plain(last["title"]) != lms_qobuz.plain(song["title"]):
            spin["songs"].append({k: song.get(k) for k in ("title", "artist", "pos", "side", "how", "at", "run")})
        TT.update(state="playing", song=song, side_over_at=0)
        tt_save()
        heard = len({lms_qobuz.plain(x["title"]) for x in spin["songs"]})
        if rec and not spin["counted"] and (heard >= 2 or time.time() - spin["start"] > 480):
            spin["counted"] = True
            threading.Thread(target=tt_count, args=(rec,), daemon=True).start()


def tt_quiet(seconds):
    """From the Ear while it is quiet. Half a minute after a song, a side is over; it's the record that's over (what to
    play next is wanted) when that side ended on the record's last song, or nothing follows for five minutes (it wasn't
    flipped), or the lid is shut. The spin ends with the lid shut or a quarter of an hour of quiet; "record over" is kept
    ten minutes, then the turntable is idle."""
    with tt_lock:
        spin = TT["spin"]
        if not spin:
            if TT["state"] == "record over" and time.time() - TT.get("over_at", 0) > 600:
                TT.update(state="idle", done=None)
            return
        if tt_not_record() or seconds > 900:
            tt_end_spin()
        elif seconds > 30 and TT["state"] == "playing":
            last = tt_last_song(spin)
            TT.update(state="record over" if last else "side over", side_over_at=time.time(), over_at=time.time())
        elif seconds > 300 and TT["state"] == "side over":
            TT.update(state="record over", over_at=time.time())


def tt_last_song(spin):
    """Whether the song heard last is the record's last (by Discogs's tracklist): the side just ended was the final one."""
    tracks = [t for t in discogs_release(spin["id"]).get("tracks") or [] if t["type"] == "track"] if spin["id"] else []
    return bool(tracks and spin["songs"] and spin["songs"][-1]["pos"] == tracks[-1]["pos"])


def tt_end_spin():
    """The spin over: kept in the turntable's history (the newest 500)."""
    spin, TT["spin"] = TT["spin"], None
    TT.update(state="idle", song=None, side_over_at=0)
    tt_save()
    if not spin or not spin["songs"]:
        return
    TT.update(state="record over", done=spin, over_at=time.time())  # what to play next, for ten minutes
    hist = kv_get("tt_spins", []) or []
    hist.append({"id": spin["id"], "title": spin["title"], "artist": spin["artist"], "start": int(spin["start"]), "end": int(time.time()),
                 "songs": [[x["title"], x["pos"], x["how"]] for x in spin["songs"]], "counted": spin["counted"]})
    kv_set("tt_spins", hist[-500:])
    if TT.pop("captured", False):
        try:
            rpc("", "rescan")  # the songs the spin left, into the library
        except Exception:
            pass


def tt_count(rec):
    """A record played: its count here, and on Discogs ("Plays", "Last played") when the collection has those fields."""
    plays = kv_get("tt_plays", {}) or {}
    d = kv_get("discogs", {}) or {}
    fields = {f["name"].strip().lower(): f["id"] for f in d.get("fields") or []}
    details = rec[9] if len(rec) > 9 else {}
    theirs = details.get("n") or {}
    p = plays.get(str(rec[0]), {"n": 0})
    try:
        on_discogs = int(re.sub(r"\D", "", str(theirs.get(str(fields.get("plays")), "")) or "0") or 0)
    except ValueError:
        on_discogs = 0
    p = {"n": max(p["n"], on_discogs) + 1, "last": time.strftime("%Y-%m-%d")}
    plays[str(rec[0])] = p
    kv_set("tt_plays", plays)
    token, user = discogs_token(), d.get("user")
    if token and user and details.get("new") and not details.get("i"):
        try:
            req = urllib.request.Request(f"{DISCOGS}/users/{urllib.parse.quote(user)}/collection/folders/1/releases/{rec[0]}", b"",
                                         dict(AGENT, Authorization="Discogs token=" + token), method="POST")
            got = json.load(urllib.request.urlopen(req, timeout=20))
            details.update(i=got.get("instance_id"), f=got.get("folder_id") or 1, new=False)
            threading.Timer(30, discogs_now.set).start()  # the collection read again, the record on the shelves
        except Exception as e:
            note_error(f"discogs add: {e}")
    if not (token and user and details.get("i")):
        return
    for name, value in (("plays", str(p["n"])), ("last played", p["last"])):
        if name not in fields:
            continue
        try:
            req = urllib.request.Request(f"{DISCOGS}/users/{urllib.parse.quote(user)}/collection/folders/{details.get('f') or 1}/releases/{rec[0]}/instances/{details['i']}/fields/{fields[name]}",
                                         json.dumps({"value": value}).encode(), dict(AGENT, Authorization="Discogs token=" + token, **{"Content-Type": "application/json"}), method="POST")
            urllib.request.urlopen(req, timeout=20).read()
            theirs[str(fields[name])] = value
        except Exception as e:
            note_error(f"discogs plays: {e}")
    with tt_lock:  # Discogs's own count as it now stands, so the next play counts on from it before the daily sync
        recs = (kv_get("discogs", {}) or {}).get("records", [])
        for r in recs:
            if r[0] == rec[0] and len(r) > 8:
                r[8]["n"] = theirs
        d["records"] = recs
        kv_set("discogs", d)


def tt_suggest(spin):
    """What to play next, for a spin: the band's next record (on the shelf, then among the digital albums, then one the
    house hasn't got), and an artist that followed (one of theirs on the shelf first)."""
    artist, rec = spin["artist"], spin["record"]
    albums, phys = physical_now()
    by_id = {a[0]: a for a in albums}
    year = (by_id[rec[8]][3] if rec and rec[8] in by_id else 0) or (rec[3] if rec else 0)
    here = lms_qobuz.plain(spin["title"])
    out = []
    theirs = [("vinyl", (by_id[r[8]][3] if r[8] in by_id else 0) or r[3], r) for r in phys if key(r[2]) == key(artist) and lms_qobuz.plain(r[1]) != here]
    theirs += [("digital", a[3], a) for a in albums if key(a[2]) == key(artist) and lms_qobuz.plain(a[1]) != here and not any(r[8] == a[0] for r in phys)]
    d = get_profile(artist)[0] or {}
    owned = {lms_qobuz.plain(x[2][1]) for x in theirs} | {here}
    theirs += [("new", int(g["date"][:4]), g) for g in d.get("rgs") or [] if g.get("type") == "Album" and not g.get("extra") and len(g.get("date") or "") >= 4
               and lms_qobuz.plain(g["title"]) not in owned]
    later = sorted((x for x in theirs if x[1] and year and x[1] > year), key=lambda x: (x[1], {"vinyl": 0, "digital": 1, "new": 2}[x[0]]))
    if later:
        out.append(suggestion(f"{artist}'s next record", *later[0]))
    # who came after them: the band's own people first (a member's own records are what followed the band most truly),
    # then only the closest of the artists like them (Qobuz's eight nearest), those who began later first
    members = [r.get("name") or "" for r in (d.get("mb") or {}).get("rels") or [] if "member" in (r.get("type") or "")]
    similar = [x["name"] for x in (d.get("qobuz") or {}).get("similar", [])][:8]
    begun = int(((d.get("mb") or {}).get("begin") or "0")[:4] or 0)

    def after(name):  # began later, as far as the house knows
        b = int((((get_profile(name)[0] or {}).get("mb") or {}).get("begin") or "0")[:4] or 0)
        return bool(begun and b and b > begun)

    def theirs_on(k, want):
        return [r for r in phys if key(r[2]) == key(k)] if want == "vinyl" else [a for a in albums if key(a[2]) == key(k)]
    picked = None
    solo = (d.get("mb") or {}).get("type") == "Person"  # a person's "members" are the bands they were in
    for group, why in ((members, lambda k: f"{artist}'s band {k}" if solo else f"{k}, of {artist}"), (sorted(similar, key=lambda k: not after(k)), lambda k: f"Came after {artist}" if after(k) else f"If you like {artist}")):
        for want in ("vinyl", "digital"):
            k = next((k for k in group if k and key(k) != key(artist) and theirs_on(k, want)), None)
            if k:
                pick = random.choice(theirs_on(k, "vinyl")) if want == "vinyl" else max(theirs_on(k, "digital"), key=lambda a: -a[5])
                year = ((by_id[pick[8]][3] if pick[8] in by_id else 0) or pick[3]) if want == "vinyl" else pick[3]  # the music's year, not a reissue's
                picked = suggestion(why(k), want, year, pick)
                break
        if picked:
            break
    if picked:
        out.append(picked)
    spin["suggest"] = out


def suggestion(why, where, year, x):
    """One suggestion, as the app, the phones and the wall show it."""
    if where == "vinyl":
        return {"why": why, "where": "On the shelf", "title": x[1].strip(), "artist": x[2], "year": year, "href": f"#/album/{x[8]}" if x[8] else f"#/record/{x[0]}", "image": x[4]}
    if where == "digital":
        return {"why": why, "where": "In the library", "title": x[1], "artist": x[2], "year": year, "href": f"#/album/{x[0]}", "image": f"/cover/{x[4]}/300.jpg" if x[4] else ""}
    return {"why": why, "where": "Not in the house yet", "title": x["title"], "artist": "", "year": year, "href": "", "image": ""}


def tt_side(path, s0, s1, gaps):
    """A side the Ear wrote whole (by the stream's clock, s0 to s1, with its quiet moments), cut into its songs: each
    song from where the naming says it began (the median of its matches, moved to the end of a quiet moment within a
    few seconds when there is one) to where the next began. Each is tagged and filed in its record's folder (CAPTURE_DIR,
    Artist - Record, "A2 Title.flac"). Sound before the first named song (the needle set down, a song nothing could
    name) is kept only when it's long enough to be one, as "Unnamed". The whole side, once cut, is not kept."""
    import shutil
    import subprocess
    try:
        if s1 - s0 < 20:
            return
        marks = [m for m in TT.get("marks", []) if s0 - 900 < m["start"] < s1 - 5]
        try:
            tt_signal(path, [m for m in marks if m["start"] > s0 - 30])
        except Exception as e:
            note_error(f"turntable signal: {type(e).__name__}: {e}"[:200])
        by = {}
        for m in marks:
            by.setdefault(lms_qobuz.plain(m["title"]), []).append(m)
        songs = []
        for ms in by.values():
            starts = sorted(m["start"] for m in ms)
            start = starts[len(starts) // 2]
            near = [g[1] for g in gaps if abs(g[1] - start) < 4]  # a quiet moment just before: the song starts as it ends
            start = min(near, key=lambda g: abs(g - start)) - 0.3 if near else start - 0.5
            songs.append((max(s0, start), ms[-1]))
        songs.sort(key=lambda x: x[0])
        if songs and songs[0][0] - s0 > 30:  # a stretch nothing named, long enough to be a song
            songs.insert(0, (s0, None))
        safe = lambda t: re.sub(r'[\\/:*?"<>|]+', "-", t).strip(" .")[:120] or "-"
        lengths = {}
        for n, (start, m) in enumerate(songs):
            end = songs[n + 1][0] if n + 1 < len(songs) else s1
            rec0 = (m or {}).get("rec")
            if rec0 and m.get("pos"):  # never past the song's own length: a locked run-out groove plays on until the arm lifts
                if rec0[0] not in lengths:
                    try:
                        lengths[rec0[0]] = tt_lengths(next((r for r in physical_now()[1] if r[0] == rec0[0]), None) or [rec0[0], rec0[1], rec0[2]])
                    except Exception:
                        lengths[rec0[0]] = {}
                if lengths[rec0[0]].get(m["pos"]):
                    end = min(end, start + lengths[rec0[0]][m["pos"]] + 6)
            if end - start < 20:
                continue
            rec = (m or {}).get("rec") or (songs[-1][1] or {}).get("rec")
            artist = rec[2] if rec else (m or {}).get("artist") or "Unknown"
            album = rec[1] if rec else (m or {}).get("album") or time.strftime("Heard %Y-%m-%d")
            title = m["title"] if m else time.strftime("Unnamed %H.%M")
            pos = (m or {}).get("pos") or ""
            folder = os.path.join(capture_dir(), safe(f"{artist} - {album}"))
            have = [f for f in os.listdir(folder) if f.endswith(".flac")] if os.path.isdir(folder) else []
            if rec and (any(f.startswith(pos + " ") for f in have) if pos else have):
                continue  # this record's song is captured already: the house keeps one take
            os.makedirs(folder, exist_ok=True)
            dest = os.path.join(folder, safe(f"{pos + ' ' if pos else ''}{title}") + ".flac")
            k = 2
            while os.path.exists(dest):  # the side played again: the next take beside the first
                dest = os.path.join(folder, safe(f"{pos + ' ' if pos else ''}{title} (take {k})") + ".flac")
                k += 1
            tmp = dest + ".part"
            subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", f"{start - s0:.3f}", "-to", f"{end - s0:.3f}", "-i", path, "-c:a", "flac", "-f", "flac", tmp], timeout=600)
            try:
                from mutagen.flac import FLAC
                f = FLAC(tmp)
                f.update({"title": title, "artist": (m or {}).get("artist") or artist, "albumartist": artist, "album": album,
                          "comment": "From the turntable, " + time.strftime("%Y-%m-%d")})
                if pos:  # "B3": side B as the second disc, the third song on it (Lyrion keeps only numbers); the position kept as it is
                    f.update(vinyl_numbers(pos))
                if rec:
                    f.update(record_tags(rec[0]))
                f.save()
            except Exception as e:
                note_error(f"turntable tags: {e}")
            shutil.move(tmp, dest)  # whole, and only then where Lyrion looks
            if rec:
                record_cover(rec[0], folder)
            TT["captured"] = True
    except Exception as e:
        note_error(f"turntable side: {type(e).__name__}: {e}"[:200])
    finally:
        if os.path.exists(path):
            os.remove(path)  # the side's own working copy: its songs are filed
    if TT.pop("captured", False):
        try:
            rpc("", "rescan")  # the side's songs into the library now, not when the spin ends (a restart before then would lose it)
        except Exception:
            pass


def tt_signal(path, marks):
    """A side's signal judged (turntable.analyse_side, with the turntable's speed from the songs matched on it) and kept
    (the newest 300 sides); then the chain judged across the sides, and anything worth looking into raised once."""
    got = turntable.analyse_side(path)
    speeds = [m["speed"] for m in marks if m.get("speed")]
    got["speed"] = round(float(sorted(speeds)[len(speeds) // 2]), 4) if speeds else None
    rec = next((m["rec"] for m in marks if m.get("rec")), None)
    side = next((m.get("side") for m in marks if m.get("side")), "")
    got.update(at=int(time.time()), id=rec[0] if rec else 0, title=rec[1] if rec else "", artist=rec[2] if rec else "", side=side)
    hist = (kv_get("tt_signal", []) or []) + [got]
    kv_set("tt_signal", hist[-300:])
    for a in tt_judge(hist, got):
        alerts = kv_get("tt_alerts", []) or []
        if any(x["key"] == a["key"] and time.time() - x["at"] < 14 * 86400 for x in alerts):
            continue  # said once a fortnight at most
        a.update(at=int(time.time()), id=f"{a['key']}-{int(time.time())}")
        kv_set("tt_alerts", (alerts + [a])[-50:])


def tt_judge(hist, now):
    """What the sides say, in plain words with what to try. The chain (balance, hum, speed) only from a pattern across
    many sides, so one odd pressing doesn't raise it; a record's own noise against the collection's usual."""
    out = []
    recent = hist[-10:]
    bal = [h["balance"] for h in recent if h.get("balance") is not None]
    for sign, quieter in ((1, "right"), (-1, "left")):
        off = [b for b in bal if b * sign > 1.0]
        if len(bal) >= 8 and len(off) >= 8:
            db = round(sum(off) / len(off) * sign, 1)
            out.append({"key": "balance", "title": f"The {quieter} channel is {db} dB quieter",
                        "text": f"On {len(off)} of the last {len(bal)} sides, every record, so it's the chain, not the pressings. Check the cartridge's tracking force and azimuth (its tilt) and the stylus; then swap the turntable's left and right leads at the amplifier: if the quiet side moves, it's before the swap (cartridge, tonearm wiring, leads); if it stays, it's the amplifier or the interface."})
    if now.get("corr") is not None and now["corr"] < -0.2:
        out.append({"key": "polarity", "title": "One channel looks wired backwards",
                    "text": "The two channels are moving in opposite directions. Check the cartridge's four pin connections (one channel's + and − swapped) and the leads."})
    if now.get("clipped", 0) > 50:
        out.append({"key": "clip", "title": "The recording is overloading",
                    "text": f"{now['clipped']} samples hit full scale on {now['title'] or 'the last side'}. The amplifier's record-out is too hot for the Behringer's input: turn down the interface's input, if it has one, or lower the source level."})
    hum = [h["hum"] for h in hist[-5:] if h.get("hum") is not None]
    if len(hum) >= 4 and sum(1 for x in hum if x > 15) >= 4:
        out.append({"key": "hum", "title": "There's hum in the quiet",
                    "text": "60 Hz hum and its multiples stand well above the surface noise between songs, side after side. Check the turntable's ground wire to the amplifier's GND post, and keep the turntable's leads away from power cables."})
    sp = [h["speed"] for h in recent if h.get("speed")]
    if len(sp) >= 6:
        m = sorted(sp)[len(sp) // 2]
        if abs(m - 1) > 0.005:
            out.append({"key": "speed", "title": f"The turntable runs {abs(m - 1) * 100:.1f}% {'fast' if m > 1 else 'slow'}",
                        "text": "Measured against the house's own copies of the songs, across the last sides. Check the speed setting and pitch control, and the belt (stretched or slipping) if it has one."})
    noise = sorted(h["noise"] for h in hist if h.get("noise") is not None)
    if len(noise) >= 10 and now.get("noise") is not None and now["noise"] > noise[len(noise) // 2] + 8:
        out.append({"key": f"noise-{now['id']}", "title": f"{now['title'] or 'That side'} is noisy",
                    "text": f"Its surface noise is {round(now['noise'] - noise[len(noise) // 2])} dB above the collection's usual. The record wants a clean (and if it stays noisy once clean, it may be worn)."})
    return out


def record_tags(rid):
    """What a captured record's songs say of it beside their names: the year the music came out (its album's among the
    digital ones, else the pressing's), Discogs's genres, and the release."""
    rec = next((r for r in physical_now()[1] if r[0] == rid), None)
    out = {"discogs_release_id": str(rid)}
    if rec:
        if tt_year(rec):
            out["date"] = str(tt_year(rec))
        if (rec[9] or {}).get("g"):
            out["genre"] = rec[9]["g"]
    return out


def record_cover(rid, folder):
    """The record's cover from Discogs as folder.jpg in its folder, for Lyrion and any other player (once)."""
    path = os.path.join(folder, "folder.jpg")
    rec = next((r for r in physical_now()[1] if r[0] == rid), None)
    if os.path.exists(path) or not rec or not rec[4]:
        return
    try:
        got = picture(rec[4])
        if got:
            with open(path + ".part", "wb") as f:
                f.write(got[0])
            os.replace(path + ".part", path)
    except Exception as e:
        note_error(f"turntable cover: {e}")


def vinyl_numbers(pos):
    """A record's position ("B3", "A", "C12", "4") as the tags Lyrion orders by: the side as the disc (A 1, B 2…), the
    song's number on it, and the position itself."""
    m = re.match(r"^([A-Za-z]*)(\d*)", pos or "")
    side, n = m.group(1).upper(), m.group(2)
    out = {"tracknumber": n or "1", "vinyl_position": pos}
    if side:
        out["discnumber"] = str(ord(side[0]) - 64)
    return out


def capture_dir():
    read_music_dirs()
    return CAPTURE_DIR or os.path.join(MUSIC_DIRS[0], "From vinyl")


def tt_index_loop():
    """The house's own files for the records on the shelf, fingerprinted (new ones each night)."""
    global TT_INDEX
    TT_INDEX = turntable.Index(os.path.join(DATA, "turntable"))
    while True:
        try:
            albums, phys = physical_now()
            want = {r[8] for r in phys if r[8]}
            if not want:  # the shelves not read yet (just started), or no collection: look again in a minute
                time.sleep(60)
                continue
            ids = set()
            for a in albums:
                if a[0] in want:
                    ids |= {a[0]} | {v[0] for v in a[10] if v[5] == "local"}
            tracks, meta = {}, {}
            for i in ids:
                for t in rpc("", "titles", "0", "300", f"album_id:{i}", "tags:uadle", timeout=20).get("titles_loop") or []:
                    f = file_path(t.get("url") or "")
                    if f and os.path.exists(f):
                        tracks[int(t["id"])] = f
                        meta[str(t["id"])] = [t.get("title") or "", t.get("artist") or "", t.get("album") or "", int(t.get("album_id") or i), float(t.get("duration") or 0)]
            kv_set("tt_meta", meta)
            TT["indexing"] = [0, len(tracks)]
            TT_INDEX.build(tracks, progress=lambda n, of: TT.__setitem__("indexing", [n, of]))
            TT.pop("indexing", None)
        except Exception as e:
            note_error(f"turntable index: {e}")
        time.sleep(86400)


def tt_save():
    """The record on the turntable now, kept, so a restart (a deploy, a crash) doesn't forget it or the house's choice."""
    try:
        kv_set("tt_spin", {"spin": TT["spin"], "song": TT["song"], "state": TT["state"], "at": time.time()})
    except Exception as e:
        note_error(f"turntable save: {e}")


def start_turntable():
    global EAR
    import glob
    for f in glob.glob(os.path.join(DATA, "turntable", "songs", ".side-*.flac")):
        try:  # a side cut off by a restart or a crash: never whole, never filed, so not kept
            os.remove(f)
        except OSError:
            pass
    kept = kv_get("tt_spin") or {}
    if kept.get("spin") and time.time() - kept.get("at", 0) < 1200:  # back as it was, if it was playing in the last twenty minutes
        TT.update(spin=kept["spin"], song=kept.get("song"), state=kept.get("state") or "playing")
    EAR = turntable.Ear(TURNTABLE_PORT, tt_clip, tt_quiet, os.path.join(DATA, "turntable", "songs"), tt_side, lambda: settings["features"].get("turntable_capture") and not tt_not_record())
    EAR.start()
    threading.Thread(target=tt_index_loop, name="turntable-index", daemon=True).start()


def turntable_state():
    """What the turntable is doing, for the app, Home Assistant's sensor and the wall: idle, playing, "side over" (a
    flip likely) or "record over" (what to play next wanted); the record, the song, the songs heard, the suggestions,
    and its plays."""
    spin, song = TT["spin"] or (TT.get("done") if TT["state"] == "record over" else None), TT["song"]
    tt_lid()
    rec = spin and spin["record"]
    un = tt_unnamed()
    plays = (kv_get("tt_plays", {}) or {}).get(str(rec[0]), {}) if rec else {}
    # a record nothing has named yet is still playing: said so, with the question of what it is (it read "idle")
    return {"state": "playing" if un and TT["state"] == "idle" else TT["state"], "listener": bool(EAR and EAR.connected), "lid": TT["lid"], "level": round(EAR.level, 1) if EAR else None,
            "record": {"id": rec[0], "title": rec[1].strip(), "artist": rec[2], "year": tt_year(rec), "image": rec[4], "album_id": rec[8],
                       "href": f"#/album/{rec[8]}" if rec[8] else f"#/record/{rec[0]}", "plays": plays.get("n", 0), "last": plays.get("last", ""),
                       "new": bool(len(rec) > 9 and (rec[9] or {}).get("new"))} if rec else
                      ({"id": 0, "title": spin["title"], "artist": spin["artist"]} if spin else None),
            "song": {k: song.get(k) for k in ("title", "artist", "pos", "side", "how")} if song and spin else None,
            "songs": [[x["title"], x["pos"]] for x in spin["songs"]] if spin else [],
            "side": song.get("side", "") if song and spin else "", "suggest": spin["suggest"] if spin else [], "side_over_at": TT["side_over_at"],
            "unnamed": {"guess": un[1] and {"pos": un[1]["pos"], "title": un[1]["title"]}} if un else None,
            "room": settings["house"].get("turntable_room", ""), "alert": tt_active_alert()}


def tt_active_alert():
    """The newest thing the signal check raised that no one has dismissed yet, for a month at most (then it's let go)."""
    done = set(kv_get("tt_alerts_done", []) or [])
    live = [a for a in kv_get("tt_alerts", []) or [] if a.get("id") not in done and time.time() - a.get("at", 0) < 30 * 86400]
    return live[-1] if live else None


def turntable_dismiss(req):
    """An alert seen to ("Got it"): not raised on the Vinyl page again."""
    done = kv_get("tt_alerts_done", []) or []
    if req.get("id") and req["id"] not in done:
        kv_set("tt_alerts_done", (done + [str(req["id"])[:80]])[-100:])
    return {"ok": True, "alert": tt_active_alert()}


def tt_next_in_order(spin):
    """The record's next song after the last one heard, by its tracklist: what an unnamed song most likely is."""
    tracks = [t for t in discogs_release(spin["id"]).get("tracks") or [] if t["type"] == "track"] if spin and spin["id"] else []
    if not tracks:
        return None
    last = spin["songs"][-1]["pos"] if spin["songs"] else ""
    at = next((i for i, t in enumerate(tracks) if t["pos"] == last), -1)
    return tracks[at + 1] if at + 1 < len(tracks) else None


def tt_unnamed():
    """The stretch of sound playing now when nothing has named it for 25 s: (run, the likely song by the tracklist)."""
    if not EAR or EAR.run_start is None or EAR.run in TT["runs"] or EAR.clock - EAR.run_start < 25 or tt_not_record():
        return None
    if TT["spin"] and TT["spin"].get("timeline") and TT["spin"]["songs"]:
        return None  # the record is known and followed by the clock; a quiet bar on it isn't a new question
    return EAR.run, tt_next_in_order(TT["spin"])


def turntable_name(req):
    """The house naming what the turntable plays when nothing else could: the record (from the collection) and, if
    given, the song by its position; else the next in its tracklist."""
    albums, phys = physical_now()
    rec = next((r for r in phys if r[0] == int(req.get("record") or 0)), None)
    if not rec and TT["spin"] and TT["spin"]["id"] == int(req.get("record") or 0):
        rec = TT["spin"]["record"]  # a record found on Discogs, not yet in the collection
    if not rec:
        return {"error": "no such record"}
    run = EAR.run if EAR else 0
    with tt_lock:
        if TT["spin"] and TT["spin"]["id"] != rec[0]:
            tt_end_spin()
        if not TT["spin"]:
            TT["spin"] = {"id": rec[0], "record": rec, "start": time.time(), "songs": [], "counted": False, "suggest": [], "artist": rec[2], "title": rec[1].strip()}
            threading.Thread(target=tt_suggest, args=(TT["spin"],), daemon=True).start()
        else:
            TT["spin"].update(id=rec[0], record=rec, artist=rec[2], title=rec[1].strip())
        TT["spin"]["chosen"] = True  # Shazam no longer overrules it this spin
        tracks = [t for t in discogs_release(rec[0]).get("tracks") or [] if t["type"] == "track"]
        t = next((t for t in tracks if t["pos"] == req.get("pos")), None) or tt_next_in_order(TT["spin"])
    if t:
        # from here the rest of the record follows by the clock: this song began when this stretch of sound did (at most
        # its length ago), and the songs before it on the side are worked back from it
        m = re.match(r"^([A-Za-z]+)", t["pos"])
        if EAR and m:
            began = EAR.run_start if EAR.run_start is not None else EAR.clock
            L = tt_lengths(rec)
            if L.get(t["pos"]):
                began = max(began, EAR.clock - L[t["pos"]] + 5)
            TT["spin"]["timeline"] = {"side": m.group(1).upper(), "pos": t["pos"], "wall": time.time() - (EAR.clock - began), "since": time.time()}
            side_from = EAR.side[2] if EAR.side else began
            for x, b in tt_schedule(TT["spin"]):  # tt_heard takes the lock itself
                if x["pos"] == t["pos"]:
                    break
                if b >= side_from - 5:
                    tt_heard({"title": x["title"], "artist": x["artists"] or rec[2], "album": rec[1].strip(), "how": "you", "at": time.time(), "run": run, "start": b})
        song = {"title": t["title"], "artist": t["artists"] or rec[2], "album": rec[1].strip(), "how": "you", "at": time.time(), "run": run}
        if EAR and TT["spin"].get("timeline"):
            song["start"] = EAR.clock - (time.time() - TT["spin"]["timeline"]["wall"])
        TT["runs"][run] = song
        tt_heard(song)
    return {"ok": True}


def turntable_new(req):
    """A new record on: the spin closed (kept as far as it got), the clock let go, the next sound named afresh."""
    with tt_lock:
        tt_end_spin()
        TT["runs"].clear()
        TT.update(state="idle", done=None)  # not "record over": nothing to suggest, nothing to announce
        tt_save()
    return {"ok": True}


def turntable_play(req):
    """The turntable, live, in a room (any Lyrion player), as a stream from here."""
    player = req.get("player") or ""
    if not lms_qobuz.PLAYER.match(player):
        return {"error": "no such room"}
    host = BIND if BIND not in ("0.0.0.0", "") else socket.gethostbyname(socket.gethostname())
    rpc(player, "playlist", "play", f"http://{host}:{PORT}/turntable.flac", "The turntable")
    return {"ok": True}


def tt_year(rec):
    """The year a record's music came out: its album's among the digital ones when it's there (a reissue's pressing year
    says less), else the pressing's."""
    a = rec[8] and album_row(rec[8])
    return (a[3] if a else 0) or rec[3]


def turntable_for_settings():
    return {"lid": settings["house"].get("turntable_lid", ""), "room": settings["house"].get("turntable_room", ""), "listener": bool(EAR and EAR.connected), "heard_at": int(EAR.heard_at) if EAR else 0,
            "indexing": TT.get("indexing"), "indexed": len(TT_INDEX.tracks) if TT_INDEX else 0, "port": TURNTABLE_PORT, "capture": capture_dir(),
            "fields": [f["name"] for f in (kv_get("discogs", {}) or {}).get("fields") or [] if f["name"].strip().lower() in ("plays", "last played")]}


# ───────────────────────── screens: a small square screen in a room, showing the nearest music ─────────────────────────
SCREEN_ART = {}  # a cover's key → where it comes from (a cover id or a picture's address), for /api/screen/art
PAUSED_SINCE = {}  # a room → when a screen first saw it paused
SCREEN_PAUSE_HOLD = 180  # how long a paused room stays on a screen before the nearest one still playing takes over


def screen_text(s):
    """Text the wall screens' font can draw: Latin, Greek, Cyrillic and common punctuation.
    NFKC first (the micro sign becomes Greek mu, full-width letters plain ones), then
    anything still out of reach loses its accents, or failing that is dropped."""
    out = []
    for ch in unicodedata.normalize("NFKC", s or ""):
        if ord(ch) < 0x530 or 0x2010 <= ord(ch) <= 0x206F or ch in "\u20ac\u2122":
            out.append(ch)
        else:
            out.append("".join(c for c in unicodedata.normalize("NFKD", ch) if ord(c) < 0x530 and not unicodedata.combining(c)))
    return re.sub(r"\s+", " ", "".join(out)).strip()


def screen(rooms):
    """What a room's screen shows: the first of its rooms (its own first, then the nearest) that's playing, or paused
    for less than SCREEN_PAUSE_HOLD; {"on": False} when none is. Flat, for a screen that parses it in a few lines."""
    rooms = [p for p in rooms.split(",") if lms_qobuz.PLAYER.match(p)][:8]
    for i, pid in enumerate(rooms):
        try:
            st = rpc(pid, "status", "-", 1, "tags:aAlcKNdj", timeout=4)
        except Exception:
            continue
        if st.get("mode") == "pause":
            paused = time.time() - PAUSED_SINCE.setdefault(pid, time.time())
        else:
            PAUSED_SINCE.pop(pid, None)
        if st.get("mode") != "play" and not (st.get("mode") == "pause" and paused < SCREEN_PAUSE_HOLD):
            continue
        t = (st.get("playlist_loop") or [st.get("remoteMeta") or {}])[0]
        title, artist, album, art = t.get("title") or t.get("remote_title") or "", t.get("artist") or "", t.get("album") or "", ""
        if "/turntable." in (t.get("url") or "") or title == "The turntable":  # the record on the turntable, as the app shows it
            tt = turntable_state()
            r, song = tt.get("record") or {}, tt.get("song") or {}
            title, artist, album, art = song.get("title") or (r.get("title") and "On the turntable") or "The turntable", r.get("artist") or song.get("artist") or "", r.get("title") or "", r.get("image") or ""
        elif str(t.get("coverid") or "-")[0] != "-":
            art = str(t["coverid"])
        elif t.get("artwork_url"):
            art = t["artwork_url"]
        k = hashlib.sha1(art.encode()).hexdigest()[:12] if art else ""
        if k:
            SCREEN_ART[k] = art
        room = settings["house"]["rooms"].get(pid, {})
        return {"on": True, "player": pid, "room": room.get("name") or st.get("player_name") or "", "here": i == 0, "playing": st.get("mode") == "play",
                "title": screen_text(title), "artist": screen_text(artist), "album": screen_text(album), "art": f"/api/screen/art?k={k}" if k else "",
                "pos": int(float(st.get("time") or 0)), "dur": int(float(t.get("duration") or 0)), "vol": int(st.get("mixer volume") or 0), "fixed": bool(room.get("fixed"))}
    return {"on": False}


def screen_art(k):
    """A cover at 480 square, as a plain (baseline) JPEG: what a screen's decoder can read."""
    from PIL import ImageOps
    src = SCREEN_ART.get(k) or ""
    m = re.match(r"^/cover/([0-9a-f-]{1,40})/\d+\.jpg$", src)
    if re.match(r"^[0-9a-f-]{1,40}$", src) or m:
        with open(cover_file(m.group(1) if m else src, 600), "rb") as f:
            data = f.read()
    elif src.startswith("https://"):
        got = picture(src)
        if not got:
            return None
        data = got[0]
    elif src:
        with urllib.request.urlopen(LMS + "/" + src.lstrip("/"), timeout=15) as r:
            data = r.read()
    else:
        return None
    im = ImageOps.fit(Image.open(io.BytesIO(data)).convert("RGB"), (480, 480), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=85)
    return out.getvalue()


def screen_do(req):
    """A screen's tap: play/pause, next, back, or the volume up or down a step (not in a room whose volume is set on the device)."""
    pid, do = req.get("player") or "", req.get("do") or ""
    if not lms_qobuz.PLAYER.match(pid):
        return {"error": "not a player"}
    if do == "toggle":
        rpc(pid, "pause")
    elif do in ("next", "prev"):
        rpc(pid, "playlist", "index", "+1" if do == "next" else "-1")
    elif do in ("up", "down") and not settings["house"]["rooms"].get(pid, {}).get("fixed"):
        rpc(pid, "mixer", "volume", "+5" if do == "up" else "-5")
    else:
        return {"error": "not something a screen does"}
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def reply(self, body, kind="application/json; charset=utf-8", cache="no-cache", status=200, etag=None, extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        if etag and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        zipped = len(body) > 1024 and "gzip" in (self.headers.get("Accept-Encoding") or "") and not kind.startswith("image/")
        if zipped:
            body = gzip.compress(body, 5)
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        for h, v in (extra or {}).items():
            self.send_header(h, v)
        if etag:
            self.send_header("ETag", etag)
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def reply_zipped(self, body, etag):
        """A body gzipped already (the library): sent as it is, or plain to a client that won't take gzip."""
        if self.headers.get("If-None-Match") == etag:
            return self.reply(b"", etag=etag)
        if "gzip" not in (self.headers.get("Accept-Encoding") or ""):
            return self.reply(gzip.decompress(body), etag=etag)
        self.send_response(200)
        for h, v in (("Content-Type", "application/json; charset=utf-8"), ("Content-Encoding", "gzip"), ("Content-Length", str(len(body))), ("Cache-Control", "no-cache"), ("ETag", etag)):
            self.send_header(h, v)
        self.end_headers()
        self.wfile.write(body)

    def pass_to_lms(self, method, body=None):
        headers = {"Content-Type": self.headers.get("Content-Type") or "application/json"} if body is not None else {}
        req = urllib.request.Request(LMS + self.path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data, kind = r.read(), r.headers.get("Content-Type") or "application/octet-stream"
            cache = "max-age=2592000" if method == "GET" else "no-store"
            # the shelves' own tag on every reply the app's player bar already asks for: it reads the shelves again when it changes
            self.reply(data, kind, cache, extra={"X-Shelves": library.get("etag") or ""} if method == "POST" else None)
        except urllib.error.HTTPError as e:
            self.reply(b"", "text/plain", "no-store", e.code)
        except Exception:
            self.reply(b"", "text/plain", "no-store", 502)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                return self.reply(stamped_index(), "text/html; charset=utf-8")
            if url.path.startswith("/music/") or url.path.startswith("/imageproxy/"):
                return self.pass_to_lms("GET")
            if url.path == "/api/turntable":
                return self.reply(turntable_state())
            if url.path == "/api/screen":
                return self.reply(screen(qs.get("rooms", "")))
            if url.path == "/api/screen/art":
                art = screen_art(qs.get("k", ""))
                return self.reply(art, "image/jpeg", "max-age=86400") if art else self.reply(b"", "text/plain", "no-store", 404)
            if url.path == "/api/turntable/live":
                return self.turntable_live()
            if url.path in ("/turntable.flac", "/turntable.mp3"):
                return self.turntable_stream(url.path.endswith(".mp3"))
            if url.path == "/api/turntable/signal":
                return self.reply({"sides": (kv_get("tt_signal", []) or [])[-60:], "alerts": kv_get("tt_alerts", []) or []})
            if url.path == "/api/record":
                rid = int(qs.get("id") or 0)
                rec = next((r for r in (kv_get("discogs", {}) or {}).get("records", []) if r[0] == rid), None)
                return self.reply(dict(discogs_release(rid), plays=(kv_get("tt_plays", {}) or {}).get(str(rid), {}), review=review_of(rec[2], rec[1].strip()) if rec else "",
                                       spins=[x for x in kv_get("tt_spins", []) or [] if x["id"] == rid][-10:]))
            name = url.path.lstrip("/")
            if "/" not in name and os.path.splitext(name)[1] in STATIC and os.path.exists(os.path.join(APP, name)):
                with open(os.path.join(APP, name), "rb") as f:
                    return self.reply(f.read(), STATIC[os.path.splitext(name)[1]], "max-age=31536000, immutable" if "v" in qs else "no-cache")
            m = re.match(r"^/cover/([0-9a-f-]{1,40})/(\d+)\.jpg$", url.path)
            if m and int(m.group(2)) in COVER_SIZES:
                try:
                    with open(cover_file(m.group(1), int(m.group(2))), "rb") as f:
                        return self.reply(f.read(), "image/jpeg", "max-age=31536000, immutable")
                except Exception:
                    return self.reply(b"", "text/plain", "no-store", 404)
            if url.path.startswith("/artist-photo/"):
                n = url.path[len("/artist-photo/"):]
                try:
                    if not re.fullmatch(r"[a-z0-9]+-\d+(-320)?\.jpg", n):
                        raise OSError
                    with open(os.path.join(ARTIST_PICS, n), "rb") as f:
                        return self.reply(f.read(), "image/jpeg", "max-age=31536000, immutable")
                except OSError:
                    return self.reply(b"", "text/plain", "no-store", 404)
            if url.path == "/api/focus":
                return self.reply(focus(qs.get("u", "")[:2000]), cache="max-age=86400")
            if url.path == "/api/artist-photos":
                return self.reply(artist_photo_choices(qs.get("name", "")))
            if url.path == "/img":
                w = int(qs.get("w") or 0)
                got = picture(qs.get("u", ""), w if w in PICTURE_WIDTHS else None)
                return self.reply(*got, "max-age=31536000, immutable") if got else self.reply(b"", "text/plain", "no-store", 404)
            if url.path == "/api/library":
                if not library["albums"]:
                    load_library()
                body, etag = library_payload()
                return self.reply_zipped(body, etag)
            if url.path == "/api/artist" and qs.get("name", "").strip():
                return self.reply(profile_for_app(qs["name"].strip()[:200]))
            if url.path == "/api/album":
                return self.reply(album(int(qs.get("id", "0"))))
            if url.path == "/api/vinyl-qobuz":  # the shelf's records with nothing digital: whether Qobuz has each
                return self.reply({k: v[0] for k, v in (kv_get("vinyl-qobuz", {}) or {}).items()})
            if url.path == "/api/ratings":
                return self.reply(album_ratings(int(qs.get("album_id", "0"))) if HAVE.get("ratings") else {"error": "no Ratings Light"})
            if url.path == "/api/away":
                return self.reply(away_album(qs.get("artist", ""), qs.get("album", ""), qs.get("player", ""), fresh=qs.get("again") == "1"))
            if url.path == "/api/review" and qs.get("album"):  # a record off the shelves, by its names
                text, why = review_lookup(qs.get("artist", "")[:200], qs["album"][:200], again=qs.get("again") == "1")
                return self.reply({"review": text or "", "why": why or "none"}, cache="max-age=86400" if text else "no-store")
            if url.path == "/api/review":
                got = review(int(qs.get("id", "0")), again=qs.get("again") == "1")
                return self.reply(got, cache="max-age=86400" if got["review"] else "no-store")  # none: asked again soon
            if url.path == "/api/story":
                text, why = story(qs.get("name", "")[:200], again=qs.get("again") == "1")
                return self.reply({"story": text, "why": why})
            if url.path == "/api/cover":
                return self.reply(cover_stories())
            if url.path == "/api/home":
                return self.reply(dict(home(), new=new_releases()))
            if url.path == "/api/marks":
                return self.reply(marks())
            if url.path == "/api/lyrics":
                return self.reply(lyrics(qs.get("artist", "")[:200], qs.get("title", "")[:200], qs.get("album", "")[:200], float(qs.get("duration") or 0)))
            if url.path == "/api/credits":
                return self.reply(credits_for(int(qs.get("id", "0"))))
            if url.path == "/api/person":
                return self.reply(person(qs.get("mbid", ""), qs.get("name", "")[:200], local=qs.get("local") == "1"))
            if url.path == "/api/export":
                return self.reply(export())
            if url.path == "/api/backups":
                return self.reply(backup_list())
            if url.path == "/api/backup":  # the latest backup (made now), as a file to keep
                body = json.dumps(export(), ensure_ascii=False).encode()
                self.send_response(200)
                for h, v in (("Content-Type", "application/json"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"),
                             ("Content-Disposition", f'attachment; filename="soundsquatch-{time.strftime("%Y-%m-%d")}.json"')):
                    self.send_header(h, v)
                self.end_headers()
                return self.wfile.write(body)
            if url.path == "/api/removals":
                return self.reply(removals())
            if url.path == "/api/removal":
                return self.reply(removal_plan(int(qs.get("id", "0"))))
            if url.path == "/api/playlists":
                return self.reply(playlists())
            if url.path == "/api/playlist":
                return self.reply(playlist(int(qs.get("id", "0"))))
            if url.path == "/api/share":
                return self.reply(share_link(int(qs.get("album_id", "0"))))
            if url.path == "/api/focuses":
                return self.reply(focuses())
            if url.path == "/api/heard-albums":
                return self.reply(heard_albums())
            if url.path == "/api/art-choices":
                return self.reply(art_choices(int(qs.get("id") or 0)))
            if url.path == "/api/track-title":
                return self.reply(track_title_info(int(qs.get("id") or 0)))
            if url.path == "/api/album-genres":
                return self.reply(album_genres_info(int(qs.get("id") or 0)))
            if url.path in ("/api/genres", "/music-genres.json"):
                return self.reply(genres_file())
            if url.path == "/api/bans":
                return self.reply({"bans": bans()})
            if url.path == "/api/settings":
                return self.reply(settings_for_app())
            if url.path == "/api/stations":
                return self.reply(stations())
            if url.path == "/api/archive/favorites":
                return self.reply(archive_favorites())
            if url.path == "/api/archive/details":
                return self.reply(archive_details(qs.get("id", "")))
            if url.path == "/api/archive/artist":
                return self.reply(archive_artist(qs.get("name", "")[:200]))
            if url.path == "/api/archive/search":
                return self.reply(archive_search(qs.get("q", "")))
            if url.path == "/api/history":
                return self.reply(history(min(90, int(qs.get("days") or 14))))
            if url.path == "/api/diagnostics":
                return self.reply({"text": diagnostics()})
            if url.path == "/api/settling":
                return self.reply(settling())
            if url.path == "/api/crawl":
                return self.reply(dict(crawl_state, wanted=len(wanted)))
        except Exception as e:
            return self.reply({"error": f"{type(e).__name__}: {e}"[:200]}, status=500)
        self.reply(b"", "text/plain", "no-store", 404)

    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        if size > 25 * 1024 ** 2:  # a picture sent from a device is the largest thing asked for
            self.close_connection = True
            return self.reply({"error": "too large: 25 MB at most"}, status=413)
        body = self.rfile.read(size)
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlparse(origin).netloc not in (self.headers.get("Host"), self.headers.get("X-Forwarded-Host")):
            return self.reply({"error": "another site"}, status=403)  # a page elsewhere on the web posting to the house's Soundsquatch
        if self.path == "/jsonrpc.js":
            return self.pass_to_lms("POST", body)
        guarded = {"/api/settings", "/api/import", "/api/album-genres", "/api/track-title", "/api/art", "/api/remove", "/api/restore", "/api/artist-photo",
                   "/api/ban", "/api/station-edit", "/api/artist-tags"}  # what changes the house for everyone: settings, files, never-play, stations
        if self.path in guarded and not pin_ok(self.headers.get("X-Soundsquatch-PIN")):
            return self.reply({"error": "pin", "pin": True}, status=403)
        routes = {"/api/ban": ban, "/api/station-edit": station_edit, "/api/settings": save_settings, "/api/keep": keep_from_log, "/api/station": start_station, "/api/archive/do": archive_do,
                  "/api/archive/show": lambda r: archive_show(r.get("ctx") or {}, r.get("player") if lms_qobuz.PLAYER.match(r.get("player") or "") else PLAYER),
                  "/api/import": import_, "/api/qobuz": qobuz, "/api/away-play": away_play, "/api/rate-album": rate_album, "/api/mark": mark, "/api/move": lambda r: move_room(r.get("from", ""), r.get("to", "")),
                  "/api/playlist-add": playlist_add, "/api/playlist-do": playlist_do, "/api/album-genres": album_genres_edit, "/api/track-title": track_title_edit, "/api/art": album_art_edit, "/api/artist-photo": artist_photo_edit, "/api/artist-tags": artist_tags_edit, "/api/artist-radio": artist_radio, "/api/play-albums": play_albums, "/api/turntable/play": turntable_play, "/api/turntable/name": turntable_name, "/api/turntable/new": turntable_new, "/api/turntable/dismiss": turntable_dismiss, "/api/afterwork": afterwork, "/api/afterwork/verdict": afterwork_verdict, "/api/focuses": focuses, "/api/screen": screen_do,
                  "/api/restore": lambda r: restore(int(r.get("id") or 0), r.get("player") if lms_qobuz.PLAYER.match(r.get("player") or "") else PLAYER),
                  "/api/remove": lambda r: remove_album(int(r.get("id") or 0), r.get("player") if lms_qobuz.PLAYER.match(r.get("player") or "") else PLAYER)}
        if self.path in routes:
            try:
                out = routes[self.path](json.loads(body or b"{}"))
            except Exception as e:
                out = {"error": f"{type(e).__name__}: {e}"[:200]}
            return self.reply(out)
        self.reply(b"", "text/plain", "no-store", 404)

    def turntable_live(self):
        """The turntable's levels for visualisers, about thirty frames a second, as server-sent events (a band's level
        0-1, low to high, and the loudness in dB), until the page goes away."""
        self.send_response(200)
        for h, v in (("Content-Type", "text/event-stream"), ("Cache-Control", "no-store"), ("Connection", "close")):
            self.send_header(h, v)
        self.end_headers()
        self.close_connection = True
        q = []
        EAR.watchers.append(q)
        try:
            while True:
                if q:
                    frame, q[:] = q[-1], []
                    self.wfile.write(b"data: " + json.dumps(frame, separators=(",", ":")).encode() + b"\n\n")
                    self.wfile.flush()
                time.sleep(1 / 60)
        except Exception:
            pass
        finally:
            EAR.watchers.remove(q)

    def turntable_stream(self, mp3=False):
        """The turntable, live, for any player in the house: lossless FLAC (or MP3 for a player that wants it), from
        the moment it's asked for until the player hangs up."""
        import subprocess
        self.send_response(200)
        for h, v in (("Content-Type", "audio/mpeg" if mp3 else "audio/flac"), ("Cache-Control", "no-store"), ("Connection", "close"), ("icy-name", "The turntable")):
            self.send_header(h, v)
        self.end_headers()
        self.close_connection = True
        enc = subprocess.Popen(["ffmpeg", "-v", "quiet", "-f", "s16le", "-ar", str(turntable.SR), "-ac", str(turntable.CH), "-i", "-"]
                               + (["-c:a", "libmp3lame", "-b:a", "320k", "-f", "mp3"] if mp3 else ["-c:a", "flac", "-f", "flac"]) + ["-"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        q, stop = [], threading.Event()
        EAR.streams.append(q)

        def feed():
            silence = bytes(turntable.BLOCK * turntable.CH * 2)
            while not stop.is_set():
                blocks, q[:] = q[:], []
                try:
                    enc.stdin.write(b"".join(blocks) if blocks else (silence if not EAR.connected else b""))
                    enc.stdin.flush()
                except Exception:
                    break
                time.sleep(1 / 30)
        threading.Thread(target=feed, daemon=True).start()
        try:
            while True:
                got = enc.stdout.read1(16384) if hasattr(enc.stdout, "read1") else enc.stdout.read(4096)
                if not got:
                    break
                self.wfile.write(got)
        except Exception:
            pass
        finally:
            stop.set()
            EAR.streams.remove(q)
            enc.kill()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    # asked to stop (docker stop, systemctl stop): stop now. As a container's first process it would otherwise ignore
    # the request and be killed ten seconds later
    __import__("signal").signal(15, lambda *a: sys.exit(0))
    load_settings()
    setup()
    reach_lms()
    detect()
    chosen_photos.update(kv_get("artist-photos", {}))
    start_recorder()
    start_turntable()
    for job in (carry_ratings, library_loop, crawler, watcher, warmer, trim_pictures, sweeper, backups_loop, radio_events, update_loop, discogs_loop, morning_loop, scrobble_loop, vinyl_qobuz_loop):
        threading.Thread(target=job, name=job.__name__, daemon=True).start()
    threading.Thread(target=credits_loop, name="credits", daemon=True).start()
    threading.Thread(target=lifedates_loop, name="credits", daemon=True).start()  # stands aside at MusicBrainz as the credits pass does
    threading.Thread(target=genres_loop, name="credits", daemon=True).start()  # stands aside at MusicBrainz as the credits pass does  # the name mb_get knows: it stands aside for someone waiting
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
