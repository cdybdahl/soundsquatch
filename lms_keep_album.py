#!/usr/bin/env python3
"""Keep the album a room is playing: makes it a Qobuz favourite, which brings it into the Lyrion library.

  lms_keep_album.py PLAYER         the album PLAYER (a Lyrion player's MAC; the living room when left out) is playing
  lms_keep_album.py PLAYER URL     the album of the track at URL (qobuz://...), as the Log lists it: played before, maybe
                                   in another room. PLAYER is the room Lyrion asks the menu for

Lyrion's Qobuz plugin has no command of its own for a favourite, but it offers one in the track's information menu
(On Qobuz > Manage Favorites > "Add Release '...' to Qobuz favorites"), so this walks that menu as an app would, by
the entries' names, and only ever adds: "Remove Release" there means the album is a favourite already. Then it asks
Lyrion to look at the online library again (rescan onlinelibrary, the same scan it runs itself each hour when Qobuz has
changed), which brings the album onto the shelves within a minute or two.

Prints JSON for the dashboard: {"album", "artist", "result"} where result is "added", "already" (a favourite, or a
file of the house's own), "not qobuz" (radio and the like) or "nothing" (nothing playing); or {"error"}.
Uses only the standard library, so it runs inside the Home Assistant container.
"""
import json
import re
import sys
import urllib.request

LMS = "http://127.0.0.1:9000/jsonrpc.js"  # Soundsquatch points it at its own Lyrion
PLAYER = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
QOBUZ = re.compile(r"^qobuz://\d+\.\w+$")


def rpc(player, *cmd):
    body = json.dumps({"id": 1, "method": "slim.request", "params": [player, list(cmd)]}).encode()
    req = urllib.request.Request(LMS, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("result") or {}


def menu(player, url, item=None):
    """The track information menu, or one of its submenus: [(text, item_id)]."""
    cmd = ["trackinfo", "items", "0", "100", f"url:{url}", "menu:1"] + ([f"item_id:{item}"] if item else [])
    out = []
    for i, it in enumerate(rpc(player, *cmd).get("item_loop") or []):
        go = ((it.get("actions") or {}).get("go") or {}).get("params") or {}
        out.append((it.get("text") or "", go.get("item_id") or (f"{item}.{i}" if item else str(i))))
    return out


def find(items, pattern):
    return next((i for t, i in items if re.search(pattern, t, re.I)), None)


def keep(player, url=None):
    if url:  # a track from the Log: its album and artist are in its menu
        items = menu(player, url)
        named = lambda k: next((t[len(k):] for t, _ in items if t.startswith(k)), "")
        out = {"album": named("Album: "), "artist": named("Artist: ")}
    else:
        st = rpc(player, "status", "-", "1", "tags:alu")
        track = (st.get("playlist_loop") or [{}])[0]
        url = track.get("url") or ""
        out = {"album": track.get("album") or "", "artist": track.get("artist") or ""}
        if not url or st.get("mode") not in ("play", "pause"):
            return dict(out, result="nothing")
    if url.startswith("file:"):
        return dict(out, result="already")
    if not url.startswith("qobuz:"):
        return dict(out, result="not qobuz")
    on_qobuz = find(menu(player, url), r"^On Qobuz$")
    manage = on_qobuz and find(menu(player, url, on_qobuz), r"^Manage Favorites$")
    if not manage:
        return {"error": "Lyrion's Qobuz menu has changed: no Manage Favorites for this track"}
    choices = menu(player, url, manage)
    if find(choices, r"^Remove Release "):
        return dict(out, result="already")
    add = find(choices, r"^Add Release ")
    if not add:
        return {"error": "Lyrion's Qobuz menu offers no Add Release for this track"}
    menu(player, url, add)  # opening the entry is what adds it
    rpc("", "rescan", "onlinelibrary")
    return dict(out, result="added")


if __name__ == "__main__":
    player = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "c0:f5:35:04:67:32"
    url = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    if not PLAYER.match(player):
        sys.exit("not a player id")
    if url and not QOBUZ.match(url):
        sys.exit("not a Qobuz track")
    try:
        print(json.dumps(keep(player, url)))
    except Exception as e:  # Lyrion away, or an answer not as expected
        print(json.dumps({"error": str(e)}))
