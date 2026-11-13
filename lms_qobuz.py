#!/usr/bin/env python3
"""Qobuz from the Music page: its releases searched, played in a room, or added to the library, through Lyrion's Qobuz
plugin (which already holds the house's Qobuz sign-in), so the dashboard needs no Qobuz account of its own.

  lms_qobuz.py search TERM PLAYER             the first releases Qobuz finds for TERM (base64 of UTF-8); the plugin will
                                              only answer on behalf of a player, so a room is named
  lms_qobuz.py play TERM PLAYER INDEX         play the INDEXth of those releases in PLAYER (a Lyrion player's MAC)
  lms_qobuz.py queue TERM PLAYER INDEX        the same, queued after what is playing
  lms_qobuz.py keep TERM PLAYER INDEX         add it to the library: a Qobuz favourite, from the release's own menu ("Add
                                              Release '...' to Qobuz favorites"; a track's menu, as lms_keep_album.py uses,
                                              needs a track Lyrion has met, and a release found here has none)
  lms_qobuz.py artist NAME PLAYER             an artist's page: Qobuz's short biography, every release (grouped as its
                                              artist page groups them), similar artists, Qobuz's picture and what the
                                              listening log has heard of them
  lms_qobuz.py wiki NAME PLAYER               the artist's longer story (Wikipedia, through Music & Artist Information)
  lms_qobuz.py aplay|aqueue|akeep NAME PLAYER INDEX   play, queue or add the INDEXth release of the artist's page

The plugin's menus are walked as an app walks them: its Search, a new search for TERM, then Releases. Each command
searches again, since the plugin's item ids belong to the search that made them, and the order of the results is stable
from one search to the next. Prints JSON for the dashboard: search {"releases": [{"i", "artist", "album", "cover"}]};
play and queue {"result": "playing"|"queued", "album"}; keep as lms_keep_album.py does; or {"error"}.

Qobuz files same-named artists under one (Karate the Boston band, a Russian rapper, a Korean act), so an artist's page
keeps only the releases MusicBrainz credits to the right one: of MusicBrainz's artists named just so, the one whose
releases best match the albums on the shelves, then Qobuz's list. A release stays when its title, or a side of a split
title ("Cherry Coke b/w The Schwinn"), matches one of theirs (or one holds the other: "Frigid Stars" in "Frigid Stars LP"),
or it is on the shelves. An artist MusicBrainz cannot place
keeps everything. MusicBrainz's answers are kept a month (MB_CACHE); it asks for a second between requests.
Uses only the standard library, so it runs inside the Home Assistant container.
"""
import base64
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lms_keep_album import PLAYER, rpc  # noqa: E402

LIMIT = 24  # releases a search shows
LOG = os.environ.get("LISTENING_URL", "")  # a listening log's own server, when the house runs one (standalone use only)
MB = "https://musicbrainz.org/ws/2/"
MB_CACHE = os.environ.get("MB_CACHE", "/tmp/lms_qobuz_mb")  # outside /config: nothing for the repo to see
MB_AGENT = {"User-Agent": "Soundsquatch/1.0 (a home music app)", "Accept": "application/json"}


def releases(term, player):
    """The releases a search for term finds: [(the plugin's item id, name, cover, path)]. Releases are the first of the
    search's sections (0.0 is a new search, its .0 the releases); asked for in one step, the ids it hands back open the
    release when asked again with the same search, where a step at a time nests the search into the ids and they open
    nothing. The path is the release's place from the top (0.0.0.N), for a step into its own menu (favourite)."""
    got = rpc(player, "qobuz", "items", "0", str(LIMIT), "item_id:0.0.0", f"search:{term}").get("loop_loop") or []
    return None, [(x.get("id"), x.get("name") or "", x.get("image") or "", f"0.0.0.{n}") for n, x in enumerate(got)]


def same_name(a, b):
    """Two spellings of one artist's name: no case, accents, punctuation or leading "The", "&" as "and", the words in any
    order ("Wilco & Billy Bragg"), and a slip of a letter or two in a longer name ("Amiee Mann")."""
    import difflib
    import unicodedata
    def words(s):
        s = s.lower().replace("&", " and ").translate(str.maketrans({"ø": "o", "æ": "ae", "ß": "ss", "ł": "l", "đ": "d"}))
        s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
        return [w for w in re.findall(r"[a-z0-9]+", re.sub(r"^\s*the\s+", "", s)) if w != "and"]
    x, y = words(a), words(b)
    if not x or not y:
        return False
    if sorted(x) == sorted(y):
        return True
    j, k = "".join(x), "".join(y)
    return len(x) == len(y) and len(j) == len(k) >= 8 and difflib.SequenceMatcher(None, j, k).ratio() >= 0.88  # letters swapped or changed, none added


def artist_page(name, player):
    """The artist's page on Qobuz: (its place among the search's artists, its name, its picture, {section name: item id}),
    the artist being the one named just so (else none). As with releases, each part is asked for in one step from
    the top of a new search (0.0.1 its artists, 0.0.1.A the artist, 0.0.1.A.K a section), which keeps the ids usable."""
    found = rpc(player, "qobuz", "items", "0", "10", "item_id:0.0.1", f"search:{name}").get("loop_loop") or []
    if not found:
        return None
    at = next((n for n, x in enumerate(found) if same_name(x.get("name") or "", name)), None)
    if at is None:  # nobody of that name: none (better no story than someone else's)
        return None
    parts = rpc(player, "qobuz", "items", "0", "10", f"item_id:0.0.1.{at}", f"search:{name}").get("loop_loop") or []
    sections = {x.get("name"): f"0.0.1.{at}.{k}" for k, x in enumerate(parts)}
    if len(parts) >= 4 and "Releases" not in sections:  # a Lyrion in another language: the page's sections by their places
        sections.update({s: f"0.0.1.{at}.{k}" for k, s in enumerate(("Releases", "Songs", "Biography", "Similar Artists"))})
    return at, found[at].get("name") or name, found[at].get("image") or "", sections


def artist_releases(name, player, page):
    """Every release on the artist's page, [(item id, group, name, cover, path)]: the page's headers ("Albums (14)") are
    groups; the path, its place from the top, as releases' (headers count in it)."""
    if not page[3].get("Releases"):
        return []
    got = rpc(player, "qobuz", "items", "0", "300", f"item_id:{page[3]['Releases']}", f"search:{name}").get("loop_loop") or []
    out, group = [], "Releases"
    for n, x in enumerate(got):
        if x.get("type") == "header":
            group = re.sub(r"\s*\(\d+\)$", "", x.get("name") or "")
        else:
            out.append((x.get("id"), group, x.get("name") or "", x.get("image") or "", f"{page[3]['Releases']}.{n}"))
    return out


def plain(title):
    """A title as releases are matched: no case, no (Deluxe Edition) or [Remastered] asides, "&" as "and", letters only."""
    return re.sub(r"[^a-z0-9]", "", re.sub(r"[(\[].*?[)\]]", "", (title or "").lower()).replace("&", "and"))


def sides(title):
    """A title and, for a split one ("A b/w B", "A / B"), each side of it."""
    parts = re.split(r"\s+b/w\s+|\s*/\s*|\s+-\s+", title or "", flags=re.I)
    return {plain(t) for t in [title] + parts if len(plain(t)) >= 3}


def mb_get(path, **query):
    with urllib.request.urlopen(urllib.request.Request(MB + path + "?" + urllib.parse.urlencode(dict(query, fmt="json")), headers=MB_AGENT), timeout=15) as r:
        time.sleep(1.05)  # MusicBrainz's one request a second
        return json.load(r)


def mb_releases(name):
    """Every MusicBrainz artist named just so, with the titles of their releases: [(id, what they are, {titles})]; a month."""
    path = os.path.join(MB_CACHE, hashlib.sha1(name.lower().encode()).hexdigest() + ".json")
    try:
        if time.time() - os.path.getmtime(path) < 30 * 86400:
            with open(path) as f:
                return [(i, d, set(t)) for i, d, t in json.load(f)]
    except OSError:
        pass
    found = [a for a in mb_get("artist", query=f'artist:"{name}"', limit=10).get("artists", []) if a.get("name", "").lower() == name.lower()][:4]
    out = []
    for a in found:
        titles, offset = set(), 0
        while offset < 400:
            got = mb_get("release-group", artist=a["id"], limit=100, offset=offset)
            for g in got.get("release-groups", []):
                titles |= sides(g.get("title"))
            offset += 100
            if offset >= got.get("release-group-count", 0):
                break
        out.append((a["id"], a.get("disambiguation", ""), titles))
    os.makedirs(MB_CACHE, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump([(i, d, sorted(t)) for i, d, t in out], f)
    os.replace(path + ".tmp", path)
    return out


def shelved(name):
    """The titles of the artist's albums on the shelves (Lyrion's library)."""
    got = rpc("", "artists", "0", "20", f"search:{name}").get("artists_loop") or []
    titles = set()
    for a in got:
        if (a.get("artist") or "").lower() == name.lower():
            for al in rpc("", "albums", "0", "500", f"artist_id:{a['id']}", "tags:l").get("albums_loop") or []:
                titles |= sides(al.get("album"))
    return titles


def theirs(name, releases):
    """The releases that are the artist's own (see the top): the same list, less what belongs to their namesakes."""
    try:
        candidates = mb_releases(name)
    except Exception:
        return releases  # MusicBrainz not answering: everything, as Qobuz has it
    own = shelved(name)
    first = releases[0][1] if releases else ""  # the page's first group is its albums, whatever the language calls them
    albums = set().union(*[sides(r[2]) for r in releases if r[1] == "Albums" or r[1] == first]) if releases else set()
    score = lambda c: (len(c[2] & own), len(c[2] & albums))
    best = max(candidates, key=score, default=None)
    if not best or sum(score(best)) < 2:
        return releases  # MusicBrainz can't place them: everything
    keep = best[2] | own
    same = lambda a, b: a == b or (min(len(a), len(b)) >= 6 and (a in b or b in a))  # "Frigid Stars" is "Frigid Stars LP"
    return [r for r in releases if any(same(a, b) for a in sides(split(r[2])[1]) for b in keep)]


def heard(name):
    """What the listening log has heard of an artist, or {} if it is not answering."""
    if not LOG:
        return {}
    try:
        with urllib.request.urlopen(f"{LOG}/artist?name={urllib.parse.quote(name)}", timeout=5) as r:
            return json.load(r)
    except Exception:
        return {}


def artist_sheet(name, player):
    page = artist_page(name, player)
    if not page:
        return {"error": "Qobuz knows no such artist"}
    _, title, img, parts = page
    every = artist_releases(name, player, page)  # its numbering is the one aplay, aqueue and akeep go by
    own = {r[0] for r in theirs(title, every)}
    bio = ""
    if parts.get("Biography"):
        got = rpc(player, "qobuz", "items", "0", "1", f"item_id:{parts['Biography']}", f"search:{name}").get("loop_loop") or []
        bio = (got[0].get("name") if got else "") or ""
    similar = (rpc(player, "qobuz", "items", "0", "24", f"item_id:{parts['Similar Artists']}", f"search:{name}").get("loop_loop") or []) if parts.get("Similar Artists") else []
    photo = cover(img).replace("/covers/small/", "/covers/medium/")  # Qobuz's own; Music & Artist Information's photo lookup hangs as often as not
    return {"name": title, "bio": bio.strip(), "photo": photo, "heard": heard(title),
            "releases": [{"i": i, "group": g, "artist": split(n)[0], "album": split(n)[1], "cover": cover(c)} for i, (item, g, n, c, _) in enumerate(every) if item in own],
            "similar": [{"name": x.get("name") or "", "image": cover(x.get("image") or "")} for x in similar if x.get("name")]}


def cover(img):
    """The cover's own address on Qobuz, out of Lyrion's image proxy, so it loads wherever the page is read."""
    m = re.match(r"^/imageproxy/([^/]+)/", img)
    return urllib.parse.unquote(m.group(1)) if m else ""


def split(name):  # "Mogwai - The Bad Fire" → ("Mogwai", "The Bad Fire")
    artist, _, album = name.partition(" - ")
    return (artist, album) if album else ("", name)


def main(args):
    if len(args) < 2:
        return {"error": "usage: search|play|queue|keep TERM PLAYER [INDEX]"}
    try:
        term = base64.b64decode(args[1], validate=True).decode("utf-8").strip()[:120]
    except ValueError:
        return {"error": "the search is not base64"}
    if not term:
        return {"error": "nothing to search for"}
    if len(args) < 3 or not PLAYER.match(args[2]):
        return {"error": "no such player"}
    if args[0] == "artist":
        return artist_sheet(term, args[2])
    if args[0] == "wiki":
        return {"wiki": (rpc("", "musicartistinfo", "biography", f"artist:{term}").get("biography") or "").strip()}
    if args[0] in ("aplay", "aqueue", "akeep"):  # a release from the artist's page: as a search's, from there on
        page = artist_page(term, args[2])
        found = [(i, n, c, p) for i, g, n, c, p in artist_releases(term, args[2], page)] if page else []
        args = [args[0][1:]] + args[1:]
    else:
        rel, found = releases(term, args[2])
    if args[0] == "search":  # the releases, and the artists (the search's second section, 0.0.1)
        people = rpc(args[2], "qobuz", "items", "0", "12", "item_id:0.0.1", f"search:{term}").get("loop_loop") or []
        return {"releases": [{"i": i, "artist": split(n)[0], "album": split(n)[1], "cover": cover(img)} for i, (_, n, img, _p) in enumerate(found)],
                "artists": [{"name": x.get("name") or "", "image": cover(x.get("image") or "")} for x in people if x.get("name")]}
    if len(args) < 4 or not args[3].isdigit() or int(args[3]) >= len(found):
        return {"error": "no such release"}
    item, name, _, path = found[int(args[3])]
    artist, album = split(name)
    if args[0] in ("play", "queue"):
        rpc(args[2], "qobuz", "playlist", "play" if args[0] == "play" else "add", f"item_id:{item}", f"search:{term}")
        return {"result": "playing" if args[0] == "play" else "queued", "album": album, "artist": artist}
    if args[0] == "keep":  # the release's own menu: "Remove Release" there means a favourite already
        entries = rpc(args[2], "qobuz", "items", "0", "60", f"item_id:{path}", f"search:{term}").get("loop_loop") or []
        names = [x.get("name") or "" for x in entries]
        if any(n.startswith("Remove Release ") for n in names):
            return {"result": "already", "album": album, "artist": artist}
        add = next((k for k, n in enumerate(names) if n.startswith("Add Release ")), None)
        if add is None:
            return {"error": "Lyrion's Qobuz menu offers no Add Release for this release"}
        rpc(args[2], "qobuz", "items", "0", "10", f"item_id:{path}.{add}", f"search:{term}")  # opening the entry is what adds it
        rpc("", "rescan", "onlinelibrary")
        return {"result": "added", "album": album, "artist": artist}
    return {"error": "unknown command"}


if __name__ == "__main__":
    try:
        out = main(sys.argv[1:])
    except Exception as e:  # the dashboard is told, whatever went wrong
        out = {"error": f"{type(e).__name__}: {e}"[:200]}
    print(json.dumps(out, ensure_ascii=False))
