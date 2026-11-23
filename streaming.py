"""The streaming services Soundsquatch leans on, each through its own Lyrion plugin (which holds the house's sign-in, so
Soundsquatch needs no account of its own): Qobuz, and TIDAL. Each is a class with the same few doings, so the rest of
Soundsquatch asks "the service" and never a service by name:

  available(can)                    whether Lyrion has the plugin (can: Lyrion's "can" query)
  sheet(name, player)               an artist's page there: {name, bio, photo, releases [{i, group, artist, album, cover}], similar}
  search(term, player)              the releases a search finds: [(artist, album, cover)], in the plugin's order
  act(req, player)                  the app's asks (search, play, queue, keep; aplay, aqueue, akeep from an artist's page),
                                    each finding its release again by the search term and its place in the results
  release(artist, title, want, player)   a record's own page: {artist, album, cover, term, i, tracks [{n, title, k}],
                                    details, year, kept}, or None when the service hasn't got it
  play_release(term, i, track, how, player)   a release (or one of its songs, and on from there) played or put next
  keep_track(player, url), unkeep_track(player, url)   the album of a track the service streamed, kept (it joins the
                                    library) or let go, by the track's address
  scheme                            its tracks' addresses begin so ("qobuz", "tidal")

A search's place numbers (i) are the plugin's order of results, stable from one search to the next; Qobuz's plugin also
hands out item ids that only work inside the search that made them, which is why each ask searches again.

TIDAL's side is written from its plugin's source (michaelherger/lms-plugin-tidal) and not yet tried against an account:
where it guesses at the plugin's answers it says so (TRIAL).
"""
import re
import urllib.parse

import lms_keep_album
import lms_qobuz
from lms_qobuz import plain, same_name, split

DETAILS = {"Genre": "genre", "Qobuz Release Type": "type", "Duration": "length", "Released at": "released", "Music Label": "label"}


def rpc(player, *cmd):
    return lms_keep_album.rpc(player, *[str(x) for x in cmd])


class Qobuz:
    key, label, scheme = "qobuz", "Qobuz", "qobuz"

    def available(self, can):
        return can("qobuz", "items")

    def sheet(self, name, player):
        return lms_qobuz.artist_sheet(name, player)

    def search(self, term, player):
        return [split(n) + (lms_qobuz.cover(img),) for _, n, img, _ in lms_qobuz.releases(term, player)[1]]

    def act(self, req, player):
        term = (req.get("term") or "").strip()[:120]
        b64 = __import__("base64").b64encode(term.encode()).decode()
        args = [req.get("action"), b64, player] + ([str(int(req["index"]))] if req.get("index") is not None else [])
        if args[0] in ("aplay", "aqueue", "akeep") and req.get("album"):
            # the profile's numbering may be a month old: the release found by its title on the page as it is now
            page = lms_qobuz.artist_page(term, player)
            now = lms_qobuz.artist_releases(term, player, page) if page else []
            at = next((n for n, r in enumerate(now) if split(r[2])[1] == req["album"]), None)
            if at is None:
                return {"error": "Qobuz no longer lists that release"}
            args[3:] = [str(at)]
        return lms_qobuz.main(args)

    def release(self, artist, title, want, player):
        term = f"{artist} {title}".strip()[:120]
        _, found = lms_qobuz.releases(term, player)

        def fit(r):
            a, t = split(r[1])
            same_t = plain(re.sub(r"\s*[(\[].*$", "", t)) == want
            return (same_t and (not artist or same_name(a, artist) or a.lower() == artist.lower())) * 2 + same_t
        best = max(range(len(found)), key=lambda n: fit(found[n]), default=None)
        if best is None or not fit(found[best]):
            return None
        item, name, img, path = found[best]
        a, t = split(name)
        entries = rpc(player, "qobuz", "items", "0", "100", f"item_id:{path}", f"search:{term}").get("loop_loop") or []
        tracks, details = [], {}
        for n, x in enumerate(entries):
            nm = x.get("name") or ""
            if x.get("isaudio") and " by " in nm:
                song = nm[:-len(" from " + t)] if nm.endswith(" from " + t) else nm.rsplit(" from ", 1)[0]
                tracks.append({"n": len(tracks) + 1, "title": song.rsplit(" by ", 1)[0], "k": n})
            elif ": " in nm and nm.split(": ", 1)[0] in DETAILS:
                details[DETAILS[nm.split(": ", 1)[0]]] = nm.split(": ", 1)[1]
        m = re.match(r"(\d+)/(\d+)/(\d{4})$", details.get("released", ""))
        return {"artist": a or artist, "album": t, "cover": lms_qobuz.cover(img), "term": term, "i": best, "tracks": tracks, "details": details,
                "year": m.group(3) if m else "", "kept": any((x.get("name") or "").startswith("Remove Release ") for x in entries)}

    def play_release(self, term, i, track, how, player):
        _, found = lms_qobuz.releases(term, player)
        if i >= len(found):
            return {"error": "Qobuz no longer lists that release"}
        rpc(player, "qobuz", "playlist", how, f"item_id:{found[i][3]}.{track}" if track is not None else f"item_id:{found[i][0]}", f"search:{term}")
        return {"result": "playing"}

    def keep_track(self, player, url):
        return lms_keep_album.keep(player, url)

    def unkeep_track(self, player, url):
        """The album's Remove Release, through the track's menu (On Qobuz > Manage Favorites): True when it was there."""
        k = lms_keep_album
        on = k.find(k.menu(player, url), r"^On Qobuz$")
        manage = on and k.find(k.menu(player, url, on), r"^Manage Favorites$")
        drop = manage and k.find(k.menu(player, url, manage), r"^Remove Release ")
        if drop:
            k.menu(player, url, drop)  # opening the entry is what removes it
        return bool(drop)


class Tidal:
    """TIDAL through its Lyrion plugin: its menus under "tidal items" (the top level: Home, Featured, My Mix, Playlists,
    Albums, Songs, Artists, Search, …; Search: Everything, Playlists, Artists, Albums, Songs) and its own commands, which
    take a release's TIDAL id: tidal_browse playlist load|insert|add type:album id:N, tidal_browse items type:album id:N
    (its songs), tidal_action add|remove type:album id:N (a favourite, which the plugin's library import brings onto
    the shelves). Tracks it streams are tidal://ID.flc (or .mp4)."""
    key, label, scheme = "tidal", "TIDAL", "tidal"
    SEARCH, S_ARTISTS, S_ALBUMS = 7, 2, 3  # the places of Search and its Artists and Albums (plugin 1.10)

    def available(self, can):
        return can("tidal_browse", "items")

    def _items(self, player, path, term=None, n=100):
        cmd = ["tidal", "items", "0", str(n), f"item_id:{path}", "menu:1"] + ([f"search:{term}"] if term else [])
        return rpc(player, *cmd).get("item_loop") or []

    @staticmethod
    def _album_id(x):
        """A release's TIDAL id, from its menu item (TRIAL: where the plugin puts it: its actions' fixed params, else its
        favourites address tidal://album:N)."""
        for act in ((x.get("actions") or {}).get(a) or {} for a in ("play", "add", "more", "go")):
            p = act.get("params") or {}
            if p.get("type") == "album" and p.get("id"):
                return str(p["id"])
        m = re.search(r"tidal://album:(\d+)", str((x.get("presetParams") or {}).get("favorites_url") or x.get("favorites_url") or ""))
        return m.group(1) if m else None

    @staticmethod
    def _name(x):  # TRIAL: a search's albums carry the title as text and the artist on a second line
        lines = (x.get("text") or x.get("name") or "").split("\n")
        title = re.sub(r"\s*\[E\]$", "", lines[0])
        return ((lines[1] if len(lines) > 1 else ""), title)

    @staticmethod
    def _cover(x):
        img = x.get("image") or x.get("icon") or ""
        m = re.match(r"^/imageproxy/([^/]+)/", img)
        url = urllib.parse.unquote(m.group(1)) if m else img if img.startswith("http") else ""
        return re.sub(r"^http://resources\.tidal\.com/", "https://resources.tidal.com/", url)

    def _albums(self, term, player):
        return [x for x in self._items(player, f"{self.SEARCH}.{self.S_ALBUMS}", term, 60) if self._album_id(x)]

    def search(self, term, player):
        return [self._name(x) + (self._cover(x),) for x in self._albums(term, player)]

    def _artist(self, name, player):
        found = self._items(player, f"{self.SEARCH}.{self.S_ARTISTS}", name, 10)
        at = next((n for n, x in enumerate(found) if same_name(self._name(x)[1], name)), None)
        if at is None:
            return None, {}
        parts = self._items(player, f"{self.SEARCH}.{self.S_ARTISTS}.{at}", name, 20)
        return found[at], {(x.get("text") or "").split("\n")[0]: f"{self.SEARCH}.{self.S_ARTISTS}.{at}.{k}" for k, x in enumerate(parts)}

    def _artist_releases(self, name, player):
        art, sections = self._artist(name, player)
        out = []
        for group in ("Albums", "Singles & EPs", "Compilations"):  # TRIAL: the artist menu's names, from the plugin's strings
            if sections.get(group):
                for x in self._items(player, sections[group], name, 300):
                    if self._album_id(x):
                        a, t = self._name(x)
                        out.append({"id": self._album_id(x), "group": group, "artist": a or name, "album": re.sub(r"\s+-\s+" + re.escape(a or name) + r"$", "", t), "cover": self._cover(x)})
        return art, sections, out

    def sheet(self, name, player):
        art, sections, rels = self._artist_releases(name, player)
        if not art:
            return {"error": "TIDAL knows no such artist"}
        similar = self._items(player, sections["Similar Artists"], name, 24) if sections.get("Similar Artists") else []
        return {"name": self._name(art)[1], "bio": "", "photo": self._cover(art), "heard": {},  # the plugin has no biographies
                "releases": [dict({k: v for k, v in r.items() if k != "id"}, i=i) for i, r in enumerate(rels)],
                "similar": [{"name": self._name(x)[1], "image": self._cover(x)} for x in similar if self._name(x)[1]]}

    def _pick(self, req, player):
        """The release an ask means: the index-th of the search's albums, or of the artist page's (found by its title)."""
        term, i = (req.get("term") or "").strip()[:120], int(req.get("index") or 0)
        if req.get("action", "").startswith("a"):
            rels = self._artist_releases(term, player)[2]
            r = next((r for r in rels if r["album"] == req.get("album")), None) or (rels[i] if i < len(rels) else None)
            return (r["id"], r["album"], r["artist"]) if r else None
        found = self._albums(term, player)
        return (self._album_id(found[i]),) + self._name(found[i])[::-1] if i < len(found) else None

    def act(self, req, player):
        action = req.get("action")
        if action == "search":
            people = self._items(player, f"{self.SEARCH}.{self.S_ARTISTS}", req.get("term"), 12)
            return {"releases": [{"i": i, "artist": a, "album": t, "cover": c} for i, (a, t, c) in enumerate(self.search(req.get("term"), player))],
                    "artists": [{"name": self._name(x)[1], "image": self._cover(x)} for x in people if self._name(x)[1]]}
        got = self._pick(req, player)
        if not got:
            return {"error": "TIDAL no longer lists that release"}
        rid, album, artist = got
        verb = action[1:] if action in ("aplay", "aqueue", "akeep") else action
        if verb in ("play", "queue"):
            rpc(player, "tidal_browse", "playlist", "play" if verb == "play" else "add", "type:album", f"id:{rid}")
            return {"result": "playing" if verb == "play" else "queued", "album": album, "artist": artist}
        if verb == "keep":
            rpc(player, "tidal_action", "add", "type:album", f"id:{rid}")
            rpc("", "rescan", "onlinelibrary")
            return {"result": "added", "album": album, "artist": artist}
        return {"error": "unknown command"}

    def release(self, artist, title, want, player):
        term = f"{artist} {title}".strip()[:120]
        found = self._albums(term, player)
        fit = lambda x: (plain(re.sub(r"\s*[(\[].*$", "", self._name(x)[1])) == want) * (2 if not artist or same_name(self._name(x)[0], artist) else 1)
        best = max(range(len(found)), key=lambda n: fit(found[n]), default=None)
        if best is None or not fit(found[best]):
            return None
        x, rid = found[best], self._album_id(found[best])
        a, t = self._name(x)
        songs = rpc(player, "tidal_browse", "items", "0", "200", "type:album", f"id:{rid}").get("loop_loop") or []  # TRIAL
        info = rpc(player, "tidal_info", "items", "0", "50", "type:album", f"id:{rid}", "menu:1").get("item_loop") or []
        facts = dict((y.get("text") or "").split(": ", 1) for y in info if y.get("type") == "text" and ": " in (y.get("text") or ""))
        return {"artist": a or artist, "album": t, "cover": self._cover(x), "term": term, "i": best,
                "details": {k2: facts[k1] for k1, k2 in (("Duration", "length"), ("Year", "released")) if facts.get(k1)},
                "tracks": [{"n": n + 1, "title": (s.get("name") or "").split("\n")[0], "k": n} for n, s in enumerate(y for y in songs if y.get("isaudio") or y.get("type") == "audio")],
                "year": facts.get("Year", ""), "kept": any("Remove from TIDAL favorites" in (y.get("text") or "") for y in info)}

    def play_release(self, term, i, track, how, player):
        found = self._albums(term, player)
        if i >= len(found):
            return {"error": "TIDAL no longer lists that release"}
        rid = self._album_id(found[i])
        if track is None:
            rpc(player, "tidal_browse", "playlist", how, "type:album", f"id:{rid}")
        else:  # one song and on from there: the album played, then that song
            rpc(player, "tidal_browse", "playlist", "play", "type:album", f"id:{rid}")
            rpc(player, "playlist", "index", str(track))
        return {"result": "playing"}

    def album_of(self, player, url):
        """The TIDAL album a track is from: (its id, its title), from the track's information menu ("Album: …")."""
        tid = (re.match(r"tidal://(\d+)", url or "") or [None, None])[1]
        if not tid:
            return None, ""
        for y in rpc(player, "tidal_info", "items", "0", "30", "type:track", f"id:{tid}", "menu:1").get("item_loop") or []:
            go = ((y.get("actions") or {}).get("go") or {}).get("params") or {}
            if go.get("type") == "album" and go.get("id"):
                return str(go["id"]), (y.get("text") or "").split(": ", 1)[-1]
        return None, ""

    def keep_track(self, player, url):
        """The album of a streamed track, kept (a TIDAL favourite, which the plugin's import brings onto the shelves)."""
        rid, album = self.album_of(player, url)
        if not rid:
            return {"error": "TIDAL didn't say which album that track is from"}
        info = rpc(player, "tidal_info", "items", "0", "3", "type:album", f"id:{rid}", "menu:1").get("item_loop") or []
        if any("Remove from TIDAL favorites" in (y.get("text") or "") for y in info):
            return {"album": album, "result": "already"}
        rpc(player, "tidal_action", "add", "type:album", f"id:{rid}")
        rpc("", "rescan", "onlinelibrary")
        return {"album": album, "result": "added"}

    def unkeep_track(self, player, url):
        rid, _ = self.album_of(player, url)
        if rid:
            rpc(player, "tidal_action", "remove", "type:album", f"id:{rid}")
        return bool(rid)

    def link(self, player, url):
        """The album's public page on TIDAL."""
        rid, _ = self.album_of(player, url)
        return f"https://tidal.com/browse/album/{rid}" if rid else ""


ALL = [Qobuz(), Tidal()]


def by_url(url):
    """The service a track's address belongs to, or None (the house's files, radio, the Archive)."""
    return next((s for s in ALL if (url or "").startswith(s.scheme + ":")), None)
