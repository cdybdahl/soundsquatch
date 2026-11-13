# Soundsquatch

A music app for the iPad (and phone), magazine-like and discovery-first, with
[Lyrion Music Server](https://lyrion.org) as its player and library. It runs as one
small Python service beside Lyrion and serves the app, passes Lyrion's JSON-RPC
through, and keeps a profile of every artist on the shelves.

## What it does

- **Discover**: a cover that turns through the day's stories (*On this day*, an
  album released on this date; *On this night*, an Internet Archive show recorded
  on it; *Record of the day*), stations, rotation from the listening log, new
  releases from your artists, rediscoveries, connections, artists beyond the
  shelves, a decade, a genre.
- **Artists, albums, credits**: Qobuz's and Wikipedia's stories, MusicBrainz's
  members, bands and per-track credits (every name a link), Wikipedia's album
  reviews, Qobuz releases not on the shelves, similar artists.
- **The Internet Archive**, through the ArchiveLMA Lyrion plugin: favourites on
  the shelves, each artist's shows, a show page with its setlist and recording notes.
- **Playing**: rooms (join, leave, move the music), Now Playing with synced lyrics
  (LRCLIB) and credits, queue reordering, playlists, radio (Don't Stop the Music),
  stations seeded like a chill mix.
- **Marks**: hearts, stars and tags, kept on the server for the household.
- **Remove from library**: Qobuz favourites un-favourited, files *moved* to
  `music-removed` (never deleted), with a Recently removed page to put them back.

## The beta

Soundsquatch 0.9 is a soft beta: it runs every day in one house (about 1,500 albums), and it's now being tried in a
few more. Expect rough edges, and please say what you find.

### What you need

- **Lyrion Music Server** 9.x, on your network, with the music in it already. Soundsquatch is a way of browsing and
  playing it; Lyrion stays the player, the library and the queue.
- **Docker** on a machine on the same network (the Lyrion machine itself is fine).
- Optional Lyrion plugins, each found by itself and left out when it isn't there:
  - **Qobuz**: Qobuz releases, artists' stories and similar artists, search beyond your shelves
  - **Music & Artist Information**: album reviews, longer stories, more artist photographs
  - **ArchiveLMA**: Internet Archive shows
  - **Don't Stop the Music** with **LastMix**: radio and stations
- A library up to about **10,000 albums**. Bigger ones aren't supported.
- Lyrion set to **English** if you want to keep or remove Qobuz albums from Soundsquatch. Everything else works in
  any language.

### Install

```sh
git clone https://github.com/cdybdahl/soundsquatch.git
cd soundsquatch
docker compose up -d
```

On **Docker Desktop** (a Mac or Windows PC), follow the note in `compose.yaml` first: Docker Desktop doesn't share the
host's network by default, so Soundsquatch publishes its port and is told Lyrion's address instead of finding it.

Open `http://<that machine>:8097` on an iPad, a phone or a browser. Soundsquatch finds Lyrion by itself, the way
players do. If it can't, it asks for Lyrion's address on the first screen, and for a username and password if Lyrion has password
protection on (Lyrion's Settings, Security). It builds a profile for every artist on
your shelves in the background, so the first day is sparser than the second.

To update: `git pull && docker compose up -d --build`. Everything Soundsquatch keeps (settings, hearts and stars,
stations, the listening log, pictures, nightly backups) lives in `./data`.

### Changing music files

Soundsquatch can write genres, track titles and covers into your files, and **Remove from the library** moves an
album's files to a `music-removed` folder beside your music. Nothing is ever deleted. This is **off** until you switch
on **Settings → Features → Change music files**. Before you do:

1. In `compose.yaml`, mount the folder *above* your music, at the very path Lyrion uses for it. For example, if
   Lyrion's media folder is `/srv/media/music`, mount `/srv/media:/srv/media`. Soundsquatch refuses to remove an album
   when `music-removed` would land anywhere but the music's own disk.
2. Set `PUID` and `PGID` to the owner of the music files (both 1000 unless you change them).

Soundsquatch has to reach the files at the paths Lyrion has for them. A Lyrion on Windows (`C:\Music\…`), or one reading
its music from a network share Soundsquatch can't mount at the same path, works for everything else, but its files
can't be changed from Soundsquatch: it says so and leaves them alone.

While it's off, genre edits stay in Soundsquatch and the files are never touched. The tags each file had before
Soundsquatch first changed it are kept, so **Put back** restores them.

### A PIN

Anyone on your network can open Soundsquatch. A PIN (**Settings → PIN**) is asked for, once on each device, before the
things that change the house for everyone: settings, music files, the never-play list, stations and artists' tags.
Playing music, hearts and playlists never ask. It keeps a housemate or a guest from changing things by accident; it is
not security. Soundsquatch passes Lyrion's own controls through, and Lyrion itself is open to the network unless you
give it a password.

### What leaves the house

Artist names and album titles, sent to MusicBrainz, Wikidata and Wikipedia, LRCLIB (for lyrics), the Cover Art
Archive, Apple and Deezer (for covers you choose), and to Qobuz and Discogs through Lyrion's own plugins. Nothing about who listens
or when: the listening log stays in `./data`.

### Telling us

Post problems and ideas in the Soundsquatch thread on the Lyrion forums. Say what you did and what you expected, and
paste the report from **Settings → Diagnostics** (versions, what was found, the last errors; no names, addresses or
listening). `docker logs soundsquatch` has the rest.

Soundsquatch is for 64-bit machines (x86, or ARM such as a Raspberry Pi on 64-bit Raspberry Pi OS); a 32-bit Pi isn't supported.

## Layout

| Path | What |
|---|---|
| `soundsquatch.py` | the service: app, Lyrion pass-through, crawler, caches (standard library + Pillow) |
| `app/` | the app itself: plain HTML, CSS and script, no build step, older-Safari safe |
| `lms_qobuz.py`, `lms_keep_album.py`, `library.py` | helpers for Qobuz (through Lyrion's plugin) and the library's rules |
| `stage-photos.json` | stage photos for *On this night*, from Wikimedia Commons, credited |
| `Dockerfile`, `compose.yaml` | the container |
| `install.sh`, `compose.sasquatch.yaml`, `check.py` | the author's own deploy; the script checked first |

## The author's own install

`./install.sh` deploys to the author's server the same container testers run: the source to `~/soundsquatch-src`
over SSH (`HOST`, default `sasquatch`), built and started with `compose.sasquatch.yaml`, whose volumes are that
house's own (its data in `~/soundsquatch`, its music in `/share`).

### What it needs, and what it finds

Only Lyrion. Everything else is Soundsquatch's own, kept in its database beside it: stations and their seed artists, the
never-play list, the house genres (found on MusicBrainz for every album), hearts, stars and tags, and nightly backups
(two weeks kept; download and restore in Settings). The listening log is kept by Soundsquatch itself
(`listening.py`) unless the house already runs a recorder of its own, whose database it then reads. Music folders come
from Lyrion's own settings. The Internet Archive features need the ArchiveLMA plugin and hide themselves without it.

On first start in a house that kept these in Home Assistant (stations' seed lists, banned artists and tracks, genres),
Soundsquatch copies them over once, with a token in `.ha_token`; nothing after that depends on Home Assistant.

Its connections are set on the app's **Settings** page
(saved in `settings.json` beside the script; today's values are the defaults), with
a check beside each connection. Features (stations, the Archive, history, credits,
lyrics) and Discover's sections can be switched off for the house; text size,
lighter drawing, reduced motion and the starting room are set per device.

## Licence

Soundsquatch is free for personal and other noncommercial use under the
[PolyForm Noncommercial License 1.0.0](LICENSE): run it, change it, share it. Selling it, or using it in a business,
needs a separate licence from the author. The fonts and stage photos keep their own licences, named in LICENSE.
