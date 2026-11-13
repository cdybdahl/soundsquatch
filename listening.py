#!/usr/bin/env python3
"""The listening log: what every Lyrion player plays, and how each track ends (Soundsquatch's History, rotation and plays).

Soundsquatch runs this itself (listen() and settling() on threads of its own, no HTTP of its own, no steward) when no
recorder of the house's own is already keeping a log; the text below is the recorder's as it runs on its own.

Runs on sasquatch-server beside Lyrion (deepvalley-listening.service). It listens to Lyrion's own event stream (the CLI on
port 9090, "listen 1"), so it hears every track start, pause, skip and queue change as it happens, from any app. It
changes nothing: it only records.

Each track played is a row in log.db: the room, the track (title, artist, album, genre, Lyrion's id and address), when it
started, how long it really played, and how it ended:

  finished   played to (near) the end
  skipped    moved on early by a skip (next, a jump to another track in the queue)
  replaced   something else was put on (a new playlist, an album, a chill mix)
  stopped    playback stopped, or the player went off
  cut        ended early for no reason heard (taken out of the queue, a stream that failed)

and, for a skip, where it came from and who it was. "From": the wall panel when the dashboard sent a note saying so
(/note, through shell_command.listening_note, within a few seconds of the skip), a phone when the player is someone's own
(OWNERS), otherwise an app. "Who": the player's owner, else the one person home when only one is, else the household.
Who is home comes in with each call for the summary (/summary?home=chad,tonya), which Home Assistant makes every half
minute. "library" says whether the track is in Lyrion's library (a positive id) or came from beyond it (Qobuz's catalogue,
by way of Don't Stop the Music), and "first" whether this is the first time the log has heard it.

Every line of the event stream is kept too (events, for 90 days), so later questions can be asked of the raw record.

The steward (STEWARD_PLAYERS, the living room for now) is the one part that acts. When Don't Stop the Music tops up a
steward player's queue ("playlist addtracks listRef ... index:N", the tracks from N on are its new batch; an album or a
chill mix put on by hand never comes that way), it takes out of that batch, and only that batch:

  track_hold   a track skipped early twice in 60 days, for 60 days from the last
  artist_hold  an artist skipped early 3 times in 30 days, for 30 days from the last
  rest         a track played through in the last 14 days
  spacing      an artist heard within the last 8 tracks
  day_cap      an artist's 4th track of the day already

One more acts on what stays: upgrade, a lossy file (an MP3) the library also holds in better quality (the same artist,
album and title, a Qobuz favourite or a lossless file) is swapped for that copy, in the same place in the queue.

A skip is "early" inside 45 seconds, and a burst (3 or more within a minute, someone running through the queue) is not
counted at all. Taking tracks out makes Don't Stop the Music top the queue up again when it runs short, so it never runs
dry; a player is pruned at most ROUNDS times in two minutes, then left alone. One more rule only writes down what it
would do: course, after an early skip of a track from beyond the library, the next two from beyond it in the queue.
Every removal, done or only written down, is a row in steward, and in the summary for the Log tab.

  GET  /summary?home=chad,tonya   the JSON for sensor.deepvalley_listening (today, the week, recent plays, a timeline, by player MAC)
  GET  /note?player=MAC&from=wall&what=skip   the dashboard saying a skip (or a ban) came from the wall panel
  GET  /artist?name=Karate                    what the log has heard of an artist (the Music page's artist sheet)

Standard library only (Python 3.10 on the server).
"""
import json
import os
import re
import socket
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LMS_HOST = os.environ.get("LMS_HOST", "127.0.0.1")
CLI_PORT = int(os.environ.get("LMS_CLI_PORT", "9090"))
JSONRPC = f"http://{LMS_HOST}:{os.environ.get('LMS_WEB_PORT', '9000')}/jsonrpc.js"
DB = os.environ.get("LISTENING_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "log.db"))
BIND = os.environ.get("LISTENING_BIND", "192.168.1.6")
PORT = int(os.environ.get("LISTENING_PORT", "8099"))
# A player that belongs to one person (their phone's own Lyrion player): MAC -> "chad" or "tonya"
OWNERS = json.loads(os.environ.get("LISTENING_OWNERS", "{}"))
NOTE_WINDOW = 15  # seconds either side of a skip in which a note from the wall panel claims it
CMD_WINDOW = 8  # seconds before a track change in which a skip or a new playlist explains it
SETTLE = 4  # seconds an ended track waits for late word on why it ended
KEEP_EVENTS = 90 * 86400
CODES = {"finished": "f", "skipped": "k", "replaced": "r", "stopped": "x", "cut": "c"}  # in the timeline
# The steward: the players it looks after (MACs, separated by commas), and its rules
STEWARD = {m.strip() for m in os.environ.get("STEWARD_PLAYERS", "").split(",") if m.strip().count(":") == 5}
EARLY = 45  # seconds: a skip inside this is a judgement on the track
BURST = 3  # this many skips on one player within a minute are someone running through the queue, not judgements
SPACING = 8  # tracks between one artist and the same artist again
DAY_CAP = 4  # tracks by one artist in a day, on one player
REST = 14 * 86400  # a track played through rests this long
TRACK_HOLD = (2, 60 * 86400)  # early skips of a track, and how long it rests after the last
ARTIST_HOLD = (3, 30 * 86400)  # early skips of an artist within ARTIST_HOLD[1], and how long it rests after the last
ROUNDS = 3  # prunings of one player within two minutes, before it is left alone
COURSE = 2  # tracks from beyond the library the course rule would take after an early skip of one

lock = threading.Lock()  # the database
state = threading.Lock()  # players and pending, between the event stream and the settling
db = sqlite3.connect(DB, check_same_thread=False)
db.executescript("""
create table if not exists plays (id integer primary key, player text, room text, started real, ended real, played real,
  duration real, track_id integer, url text, title text, artist text, album text, genre text, library integer,
  outcome text, source text, who text, home text, first integer);
create index if not exists plays_started on plays(started);
create index if not exists plays_url on plays(url);
create table if not exists events (t real, player text, line text);
create index if not exists events_t on events(t);
create table if not exists notes (t real, player text, src text, what text);
create table if not exists steward (t real, player text, title text, artist text, url text, rule text, detail text, acted integer);
create index if not exists steward_t on steward(t);
""")
home_now = ""  # who is home, as Home Assistant last said: "chad,tonya", "tonya", ""
rooms = {}  # player MAC -> name
players = {}  # player MAC -> what it is playing: {"track": {...}, "started", "played", "resumed" (None while paused), "skip", "replace"}
pending = []  # tracks just ended, as in players with "player", "ended" and "why", until settle writes them
rounds = {}  # player MAC -> times the steward pruned it lately
quiet = {}  # player MAC -> when the steward last added a track itself (not a batch to look at)
shelf = {"t": 0, "best": {}}  # the library's best copy of each track (upgrade): {key: (quality, url, words)}, an hour old at most
LOSSLESS = {"flc", "wav", "aif", "alc", "wvp", "ape"}


def rpc(player, cmd):
    body = json.dumps({"id": 1, "method": "slim.request", "params": [player, cmd]}).encode()
    req = urllib.request.Request(JSONRPC, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r).get("result", {})


def refresh_rooms():
    try:
        for p in rpc("", ["players", 0, 100]).get("players_loop", []):
            rooms[p["playerid"]] = p.get("name", p["playerid"])
    except Exception:
        pass


def current_track(player):
    """The track the player has just started, from Lyrion."""
    st = rpc(player, ["status", "-", 1, "tags:aldgeuK"])
    t = (st.get("playlist_loop") or [{}])[0]
    tid = t.get("id")
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        tid = None
    return {"track_id": tid, "url": t.get("url", ""), "title": t.get("title", ""), "artist": t.get("artist", ""),
            "album": t.get("album", ""), "genre": t.get("genre", ""), "duration": float(t.get("duration") or 0),
            "library": 1 if tid and tid > 0 else 0}


def finish(player, now, why=None):
    """The track the player was playing has ended: set it aside for a few seconds (Lyrion can announce the next track
    before the skip or the new playlist that caused it), then write it (settle)."""
    cur = players.pop(player, None)
    if not cur or not cur.get("track"):
        return
    cur["played"] += (now - cur["resumed"]) if cur["resumed"] else 0
    cur.update(ended=now, why=why, player=player)
    pending.append(cur)


def settle(now):
    """Write the tracks set aside long enough for any late word on why they ended."""
    for cur in [c for c in pending if now - c["ended"] > SETTLE]:
        pending.remove(cur)
        write(cur)


def write(cur):
    player, end, played, why = cur["player"], cur["ended"], cur["played"], cur["why"]
    tr, dur = cur["track"], cur["track"]["duration"]
    done = dur and played >= max(dur * .9, dur - 15)
    if done:
        outcome = "finished"
    elif cur.get("replace") and abs(end - cur["replace"]) <= CMD_WINDOW:  # before skips: a new playlist also jumps
        outcome = "replaced"
    elif cur.get("skip") and abs(end - cur["skip"]) <= CMD_WINDOW:
        outcome = "skipped"
    else:
        outcome = why or "cut"
    source = who = None
    if outcome == "skipped":
        with lock:
            note = db.execute("select src from notes where player = ? and t between ? and ? order by t desc limit 1",
                              (player, cur["skip"] - NOTE_WINDOW, cur["skip"] + NOTE_WINDOW)).fetchone()
        source = note[0] if note else ("phone" if player in OWNERS else "app")
        here = [p for p in cur["home"].split(",") if p]
        who = OWNERS.get(player) or (here[0] if len(here) == 1 else "household")
    with lock:
        first = 0 if db.execute("select 1 from plays where url = ? limit 1", (tr["url"],)).fetchone() else 1
        db.execute("insert into plays (player, room, started, ended, played, duration, track_id, url, title, artist, album, genre,"
                   " library, outcome, source, who, home, first) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (player, rooms.get(player, player), cur["started"], end, round(played, 1), dur, tr["track_id"], tr["url"],
                    tr["title"], tr["artist"], tr["album"], tr["genre"], tr["library"], outcome, source, who, cur["home"], first))
        db.commit()
    if outcome == "skipped" and played < EARLY and not tr["library"] and player in STEWARD:
        threading.Thread(target=steward_course, args=(player,), daemon=True).start()


def handle(line):
    """One line of Lyrion's event stream."""
    parts = [urllib.parse.unquote(p) for p in line.split(" ")]
    if len(parts) < 2 or parts[0].count(":") != 5:
        return
    player, cmd, now = parts[0], parts[1:], time.time()
    with lock:
        db.execute("insert into events values (?,?,?)", (now, player, " ".join(cmd)[:300]))
        db.commit()
    cur = players.get(player)
    head = cmd[0], (cmd[1] if len(cmd) > 1 else "")
    # the tracks this player just ended, still waiting for word on why
    just = [c for c in pending if c["player"] == player and now - c["ended"] <= SETTLE]
    if head == ("playlist", "newsong"):
        if cur:
            finish(player, now)
        if player not in rooms:
            refresh_rooms()
        try:
            track = current_track(player)
        except Exception:
            track = None
        players[player] = {"track": track, "started": now, "played": 0.0, "resumed": now, "home": home_now}
        return
    skip = head in (("playlist", "index"), ("playlist", "jump"), ("button", "jump_fwd"), ("button", "jump_rew")) \
        or (cmd[0] == "button" and cmd[1:2] and cmd[1].startswith("jump"))
    replace = head[0] in ("playlist", "playlistcontrol") and (head[1] in ("load", "loadtracks", "play", "clear", "loadalbum", "resume")
                                                              or "cmd:load" in cmd)
    if head == ("playlist", "addtracks") and cmd[2:3] == ["listRef"] and player in STEWARD and now - quiet.get(player, 0) > 5:  # Don't Stop the Music's batch
        at = [c[6:] for c in cmd if c.startswith("index:")]
        if at and at[0].isdigit() and int(at[0]) > 0:
            threading.Timer(1.5, steward_prune, args=(player, int(at[0]))).start()
    if skip or replace:  # heard just after the track changed: it is why the last one ended
        for c in just:
            c["skip" if skip else "replace"] = now
    if not cur:
        return
    elif head in (("playlist", "pause"), ("pause", "")) or cmd[0] == "pause":
        paused = cmd[-1] == "1" if cmd[-1] in ("0", "1") else cur["resumed"] is not None
        if paused and cur["resumed"]:
            cur["played"] += now - cur["resumed"]
            cur["resumed"] = None
        elif not paused and not cur["resumed"]:
            cur["resumed"] = now
    elif skip:
        cur["skip"] = now
    elif replace:
        cur["replace"] = now
    elif head == ("playlist", "stop") or head == ("stop", "") or (head[0] == "power" and cmd[-1] == "0") \
            or head == ("client", "disconnect"):
        finish(player, now, "stopped")


def pick_up():
    """What each player is already playing (at start, or after Lyrion comes back), from as far in as it has got."""
    now = time.time()
    for player in list(rooms):
        try:
            st = rpc(player, ["status", "-", 1])
            if st.get("mode") not in ("play", "pause") or player in players:
                continue
            elapsed = float(st.get("time") or 0)
            players[player] = {"track": current_track(player), "started": now - elapsed, "played": elapsed,
                               "resumed": now if st["mode"] == "play" else None, "home": home_now}
        except Exception:
            pass


def norm(s):
    """An artist or title as the steward compares them: no case, no leading "the", "&" as "and", no (remastered) or [live] asides."""
    s = re.sub(r"[(\[].*?[)\]]", "", (s or "").lower()).replace("&", " and ")
    return re.sub(r"\s+", " ", re.sub(r"^the ", "", s.strip())).strip()


def quality(t):
    """A track's quality, as a key that sorts better copies higher, and in words ("MP3 128", "CD", "24/96")."""
    kind, bits, rate = t.get("type") or "", int(t.get("samplesize") or 0), int(t.get("samplerate") or 0)
    if kind in LOSSLESS:
        bits = bits or 16
        return (1, bits, rate), "CD" if (bits, rate) == (16, 44100) else f"{bits}/{rate / 1000:g}"
    kbps = int(re.sub(r"\D.*", "", t.get("bitrate") or "") or 0)
    return (0, kbps, rate), f"{kind.upper()} {kbps}"


def copy_key(t):
    """A track as its copies are matched for upgrade: artist, album and title, only remaster notes set aside (a live
    take is not the studio one)."""
    plain = lambda x: re.sub(r"[^a-z0-9]", "", re.sub(r"[(\[][^)\]]*remaster[^)\]]*[)\]]|\s-\s.*remaster.*$", "", (x or "").lower()).replace("&", "and"))
    return plain(t.get("artist")) + "|" + plain(t.get("album")) + "|" + plain(t.get("title"))


def best_copies():
    """The library's best copy of each track, kept an hour."""
    if time.time() - shelf["t"] > 3600:
        best = {}
        for t in rpc("", ["titles", 0, 200000, "tags:aloIrTu"]).get("titles_loop", []):
            q, words = quality(t)
            k = copy_key(t)
            if k not in best or q > best[k][0]:
                best[k] = (q, t.get("url"), words)
        shelf.update(t=time.time(), best=best)
    return shelf["best"]


def early_skips(since):
    """Skips inside EARLY seconds since a time, as (started, ended, title, artist, player), bursts left out."""
    with lock:
        rows = db.execute("select started, ended, title, artist, player, played from plays where outcome = 'skipped' and ended >= ?",
                          (since - 60,)).fetchall()
    burst = lambda r: sum(1 for x in rows if x[4] == r[4] and abs(x[1] - r[1]) <= 60) >= BURST
    return [r[:5] for r in rows if r[0] >= since and r[5] < EARLY and not burst(r)]


def holds(now):
    """What rests after early skips: {track key: until}, {artist: until}."""
    tracks, artists = {}, {}
    for started, ended, title, artist, player in early_skips(now - max(TRACK_HOLD[1], ARTIST_HOLD[1])):
        tracks.setdefault(norm(artist) + "|" + norm(title), []).append(ended)
        if ended >= now - ARTIST_HOLD[1]:
            artists.setdefault(norm(artist), []).append(ended)
    return ({k: max(v) + TRACK_HOLD[1] for k, v in tracks.items() if len(v) >= TRACK_HOLD[0] and max(v) + TRACK_HOLD[1] > now},
            {k: max(v) + ARTIST_HOLD[1] for k, v in artists.items() if len(v) >= ARTIST_HOLD[0] and max(v) + ARTIST_HOLD[1] > now})


def steward_note(player, t, rule, detail, acted):
    with lock:
        db.execute("insert into steward values (?,?,?,?,?,?,?,?)", (time.time(), player, t.get("title", ""), t.get("artist", ""),
                                                                    t.get("url", ""), rule, detail, acted))
        db.commit()


def steward_prune(player, start):
    """Don't Stop the Music has added tracks start onward to a steward player's queue: take out the ones the rules say."""
    try:
        now = time.time()
        recent = [t for t in rounds.get(player, []) if now - t < 120]
        if len(recent) >= ROUNDS:
            return
        rounds[player] = recent + [now]
        st = rpc(player, ["status", 0, 500, "tags:aloIrTu"])
        cur = int(st.get("playlist_cur_index") or 0)
        queue = [t for t in st.get("playlist_loop", []) if int(t["playlist index"]) >= cur]
        lt = time.localtime(now)
        midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        with lock:
            heard = [a for (a,) in db.execute("select artist from plays where player = ? order by started desc limit ?", (player, SPACING))][::-1]
            today = [a for (a,) in db.execute("select artist from plays where player = ? and started >= ?", (player, midnight))]
            rested = {norm(a) + "|" + norm(t): e for a, t, e in db.execute(
                "select artist, title, max(ended) from plays where outcome = 'finished' and ended >= ? group by artist, title", (now - REST,))}
        track_hold, artist_hold = holds(now)
        seq = [norm(a) for a in heard]  # the artists heard and to come, oldest first
        count = {}
        for a in today:
            count[norm(a)] = count.get(norm(a), 0) + 1
        for t in queue:  # what is playing and what was queued before the batch counts as heard
            if int(t["playlist index"]) < start:
                a = norm(t.get("artist"))
                seq.append(a)
                count[a] = count.get(a, 0) + 1  # the one playing has no row in plays yet
        drop = []
        for t in queue:
            i = int(t["playlist index"])
            if i < start:
                continue
            a, key = norm(t.get("artist")), norm(t.get("artist")) + "|" + norm(t.get("title"))
            window = seq[-SPACING:]
            ago = len(window) - max(n for n, x in enumerate(window) if x == a) if a and a in window else 0  # 1: the track before
            why = (("track_hold", time.strftime("%b %d", time.localtime(track_hold[key]))) if key in track_hold
                   else ("artist_hold", time.strftime("%b %d", time.localtime(artist_hold[a]))) if a in artist_hold
                   else ("rest", time.strftime("%b %d", time.localtime(rested[key]))) if key in rested
                   else ("spacing", str(ago)) if ago
                   else ("day_cap", str(count[a])) if a and count.get(a, 0) >= DAY_CAP
                   else None)
            if why:
                drop.append((i, t, why, None))
            else:
                seq.append(a)
                count[a] = count.get(a, 0) + 1
                q, words = quality(t)
                better = best_copies().get(copy_key(t)) if not q[0] else None
                if better and better[0] > q and better[1] != t.get("url"):
                    drop.append((i, t, ("upgrade", f"{words} → {better[2]}"), better[1]))
        for i, t, (rule, detail), url in sorted(drop, key=lambda d: -d[0]):  # from the end, so the places before stay put
            if rpc(player, ["playlist", "path", i, "?"]).get("_path") != t.get("url"):
                continue  # the queue moved under us: leave it
            if url:  # the better copy in its place: added at the end, then moved up
                quiet[player] = time.time()
                rpc(player, ["playlist", "add", url])
                last = int(rpc(player, ["status", "-", 1]).get("playlist_tracks") or 0) - 1
                if last > i and rpc(player, ["playlist", "path", last, "?"]).get("_path") == url:
                    rpc(player, ["playlist", "move", last, i])
                    rpc(player, ["playlist", "delete", i + 1])
                    steward_note(player, t, rule, detail, 1)
                continue
            rpc(player, ["playlist", "delete", i])
            steward_note(player, t, rule, detail, 1)
    except Exception as e:
        print("steward:", type(e).__name__, e, flush=True)


def steward_course(player):
    """After an early skip of a track from beyond the library: what the course rule would take (written down only)."""
    try:
        time.sleep(2)
        st = rpc(player, ["status", 0, 500, "tags:alu"])
        cur = int(st.get("playlist_cur_index") or 0)
        beyond = [t for t in st.get("playlist_loop", []) if int(t["playlist index"]) > cur and int(t.get("id") or 0) <= 0]
        for t in beyond[:COURSE]:
            steward_note(player, t, "course", "", 0)
    except Exception as e:
        print("course:", type(e).__name__, e, flush=True)


def listen():
    """Lyrion's event stream, kept open; reconnects if Lyrion restarts."""
    while True:
        try:
            refresh_rooms()
            with state:
                pick_up()
            with socket.create_connection((LMS_HOST, CLI_PORT), timeout=30) as s:
                s.sendall(os.environ.get("LMS_LOGIN", "").encode() + b"listen 1\n")  # a Lyrion with a password: logged in first
                s.settimeout(None)
                buf = b""
                while True:
                    data = s.recv(65536)
                    if not data:
                        break
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            with state:
                                handle(line.decode("utf-8", "replace").strip())
                        except Exception as e:
                            print("event:", type(e).__name__, e, flush=True)
        except Exception as e:
            print("cli:", type(e).__name__, e, flush=True)
        time.sleep(5)


def settling():
    while True:
        time.sleep(2)
        try:
            with state:
                settle(time.time())
        except Exception as e:
            print("settle:", type(e).__name__, e, flush=True)


def summary():
    now = time.time()
    lt = time.localtime(now)
    midnight = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    week = now - 7 * 86400
    q = lambda sql, *a: db.execute(sql, a).fetchall()
    with lock:
        db.execute("delete from events where t < ?", (now - KEEP_EVENTS,))
        today = q("select player, started, played, duration, outcome, library, first from plays where started >= ? order by started", midnight)
        wk = q("select outcome, count(*) from plays where started >= ? group by outcome", week)
        top = q("select artist, count(*) n from plays where started >= ? and outcome = 'finished' and artist != '' group by artist order by n desc limit 8", week)
        steward = q("select t, player, title, artist, rule, detail, acted from steward order by t desc limit 25")
        steward_today = q("select sum(acted), sum(1 - acted) from steward where t >= ?", midnight)[0]
        recent = q("select started, player, title, artist, outcome, played, duration, who, source, library, first, album, url from plays order by started desc limit 30")
        since = q("select min(started) from plays")[0][0]
        beyond_wk = q("select count(*), sum(outcome = 'finished'), sum(outcome = 'skipped') from plays where started >= ? and library = 0", week)[0]
    skipped = {}  # the early skips this month by track, bursts left out: [title, artist, n, last, who]
    with lock:
        early = db.execute("select started, ended, title, artist, player, played, url, who from plays where outcome = 'skipped' and started >= ?",
                           (now - 30 * 86400 - 60,)).fetchall()
    for r in early:
        if r[5] < EARLY and r[0] >= now - 30 * 86400 and sum(1 for x in early if x[4] == r[4] and abs(x[1] - r[1]) <= 60) < BURST:
            k = skipped.setdefault(r[6], [r[2], r[3], 0, 0, set()])
            k[2] += 1
            k[3] = max(k[3], r[0])
            k[4].add(r[7] or "")
    skipped = sorted(skipped.values(), key=lambda k: (-k[2], -k[3]))[:8]
    count = lambda o: sum(1 for r in today if r[4] == o)
    wkd = dict(wk)
    wk_all = sum(wkd.values())
    timeline = {}
    for player, started, played, dur, outcome, lib, first in today:
        timeline.setdefault(player, []).append([round((started - midnight) / 60, 1), round(max(played, 1) / 60, 1), CODES.get(outcome, "c"), lib])
    return {
        "state": len(today),
        "updated": now,
        "since": since,
        "home": home_now,
        "rooms": {p: rooms[p] for p in rooms},
        "playing": {p: (c["track"] or {}).get("title", "") for p, c in players.items() if c.get("track")},
        "today": {"plays": len(today), "finished": count("finished"), "skipped": count("skipped"),
                  "minutes": round(sum(r[2] for r in today) / 60), "beyond": sum(1 for r in today if not r[5]),
                  "new": sum(1 for r in today if r[6])},
        "week": {"plays": wk_all, "finished": wkd.get("finished", 0), "skipped": wkd.get("skipped", 0),
                 "beyond": beyond_wk[0] or 0, "beyond_finished": beyond_wk[1] or 0, "beyond_skipped": beyond_wk[2] or 0,
                 "top": [list(r) for r in top]},
        "skipped": [[t, a, n, round(last), ",".join(sorted(w - {""}))] for t, a, n, last, w in skipped],
        # the steward: the players it looks after, today's removals (done, only written down), and the latest
        "steward": {"players": sorted(STEWARD), "today": [steward_today[0] or 0, steward_today[1] or 0],
                    "recent": [[round(t), pl, ti, a, r, d, ac] for t, pl, ti, a, r, d, ac in steward]},
        # each play's album and Lyrion address on the end, for the Log's "Keep album" (a Qobuz address only: a file's is the house's own)
        "recent": [[round(s), pl, t, a, o, round(p), round(d or 0), w, src, lib, f, al or "", u if (u or "").startswith("qobuz://") else ""]
                   for s, pl, t, a, o, p, d, w, src, lib, f, al, u in recent],
        "timeline": timeline,
    }


def artist_heard(name):
    """What the log has heard of one artist, for the Music page's artist sheet: plays, played through, early skips (bursts
    left out) and when last, over the whole log."""
    a = norm(name)
    with lock:
        rows = db.execute("select artist, outcome, started from plays where artist like ?", (f"%{name[:40]}%",)).fetchall()
    rows = [r for r in rows if norm(r[0]) == a]
    early = sum(1 for r in early_skips(0) if norm(r[3]) == a)
    return {"plays": len(rows), "finished": sum(1 for r in rows if r[1] == "finished"), "skipped": early,
            "last": round(max((r[2] for r in rows), default=0))}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        global home_now
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if url.path == "/summary":
            if "home" in qs:
                home_now = ",".join(sorted(p for p in qs["home"][0].lower().split(",") if p in ("chad", "tonya")))
            with state:
                body = json.dumps(summary(), ensure_ascii=False).encode()
        elif url.path == "/artist":
            body = json.dumps(artist_heard(qs.get("name", [""])[0])).encode()
        elif url.path == "/note":
            player = qs.get("player", [""])[0]
            if player.count(":") != 5:
                return self.send_error(400)
            with lock:
                db.execute("insert into notes values (?,?,?,?)", (time.time(), player, qs.get("from", ["wall"])[0][:20], qs.get("what", ["skip"])[0][:20]))
                db.execute("delete from notes where t < ?", (time.time() - 86400,))
                db.commit()
            body = b'{"ok": true}'
        else:
            return self.send_error(404)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    threading.Thread(target=listen, daemon=True).start()
    threading.Thread(target=settling, daemon=True).start()
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
