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
- **Your records**, from your Discogs collection: the albums you also have on vinyl (or CD) say so, the records you
  have only on vinyl are kept beside the digital ones, with filters (format, pressing, genre, decade) and a page for
  each record (its tracklist by side, credits, the pressing's barcodes and run-out, videos, plays).
- **The turntable**, with a small listener on your amplifier's record-out: Soundsquatch names what the record player
  plays (from your own files first, then Shazam), shows it as Now Playing, suggests what to play next, keeps count of
  plays (on Discogs too), records each side as tagged songs into your library, streams it live to any room, and
  watches the signal for trouble in the chain (balance, hum, speed, overload).

## The beta

Soundsquatch 0.10 is a soft beta: it runs every day in one house (about 1,500 albums), and it's now being tried in a
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
mkdir soundsquatch && cd soundsquatch
curl -fsSLO https://raw.githubusercontent.com/cdybdahl/soundsquatch/main/compose.yaml
docker compose up -d
```

That fetches the ready-built image (for 64-bit Intel/AMD and ARM machines). Set your time zone in `compose.yaml`
first.

On **Docker Desktop** (a Mac or Windows PC), follow the note in `compose.yaml` first: Docker Desktop doesn't share the
host's network by default, so Soundsquatch publishes its port and is told Lyrion's address instead of finding it.

Open `http://<that machine>:8097` on an iPad, a phone or a browser. Soundsquatch finds Lyrion by itself, the way
players do. If it can't, it asks for Lyrion's address on the first screen, and for a username and password if Lyrion has password
protection on (Lyrion's Settings, Security). It builds a profile for every artist on
your shelves in the background, so the first day is sparser than the second.

When a new version is out, Soundsquatch says so (once on each screen, and at the top of Settings). To update, in
that folder: `docker compose pull && docker compose up -d`. Everything Soundsquatch keeps (settings, hearts and stars,
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

### Your records (Discogs)

If you keep your records on [Discogs](https://www.discogs.com), Soundsquatch can show them beside the digital shelves.
On discogs.com go to **Settings → Developers → Generate new token**, and paste it in **Settings → Your records** (or on
the **Vinyl** page). Soundsquatch reads the collection once a day.

To have the turntable's plays counted on Discogs too, add two custom fields to your collection there (your
Collection's settings → **Custom fields** → Add): **Plays** and **Last played**, both of the **Text area** kind.
Soundsquatch adds to the first and writes the date into the second each time a record is played.

### The turntable

A small listener on your amplifier's record-out (or tape-out) sends what the record player plays to Soundsquatch,
which does everything else. You need:

- **A Raspberry Pi**, a Pi 3 or newer is plenty (it only records and sends), with **Raspberry Pi OS Lite**. A network
  cable is steadier than Wi-Fi for a constant stream; on Wi-Fi a Pi 3 only joins 2.4 GHz networks.
- **A USB audio interface with line inputs**, such as the Behringer UCA202 or UCA222 (any USB sound card with a
  line-level input works). A turntable straight into the interface won't do: the signal needs its phono stage first,
  which is why it comes from the amplifier's record-out.
- **A good power supply for the Pi**: 5.1 V, 2.5 A. The interface takes its power from the Pi, and a weak supply
  shows up as clicks in the recordings (`vcgencmd get_throttled` on the Pi should say `0x0`).

Wire the amplifier's **REC OUT** to the interface's **inputs**, plug the interface into the Pi, and on the Pi run:

```sh
curl -fsSL https://raw.githubusercontent.com/cdybdahl/soundsquatch/main/turntable/install.sh | sudo sh -s <the Soundsquatch machine>
```

It installs ALSA's recorder and netcat and a service that starts at boot: the record-out, CD quality, sent raw over
one connection to Soundsquatch's port **8095**. **Settings → Your records → The turntable** says when it's listening.

What Soundsquatch does with it:

- **Names each song** six seconds in (sure by eleven): first against fingerprints of your own files of the records in
  your Discogs collection (made once, overnight, on the Soundsquatch machine), then, only when those can't, by
  sending ten seconds of it to Shazam. When neither can, the app asks which record and which song.
- **Shows it** as Now Playing whenever the room's own player is quiet: the record, the song, its side and place in
  the tracklist, the songs heard, a visualiser, and **Hear it in…** to play it in another room (a live stream from
  Soundsquatch, a few seconds behind; any player can also open `http://<the Soundsquatch machine>:8097/turntable.flac`).
- **Suggests what's next**: the band's next record (on the shelf, in the library, or not in the house yet), and an
  artist who followed (a member's own records first).
- **Counts plays**: a record counts once two of its songs (or eight minutes) are heard; on Discogs too (above).
- **Keeps each side**, if you switch on **Settings → Features → Keep the turntable's songs**: recorded whole, then cut
  into its songs where the naming says each began, tagged (artist, record, side as the disc, its position, the Discogs
  release) and filed in a `From vinyl` folder in your music, so Lyrion adds them to the library. They show as their
  own pressing, **Vinyl, captured by Soundsquatch**, and never displace the digital one. Needs the music mounted
  read-write, as for *Changing music files*.
- **Checks the signal**: each side's balance, how alike the channels are, surface noise, clicks and hum in the quiet,
  overload, and the turntable's speed against your own copies. One odd side is the pressing; the same thing side
  after side is the chain, and the **Vinyl** page says so plainly, with what to try.

Two more settings, on **Change** in that row: Home Assistant's **sensor for the lid** (a contact sensor, on while
it's open; with none, whatever the amplifier plays is taken for a record, the tuner included), and **the room** the
turntable is in.

**With Home Assistant** (optional): `http://<the Soundsquatch machine>:8097/api/turntable` is the turntable's state as
JSON, for a REST sensor: `state` is `idle`, `playing`, `side over` (likely a flip) or `record over`, with the record,
the song, the songs heard, the suggestions, and the signal check's newest `alert`. Useful automations: pause the
room's streaming when the lid opens; tell the phones what to play next on `record over`; pass on a new `alert`.

### A PIN

Anyone on your network can open Soundsquatch. A PIN (**Settings → PIN**) is asked for, once on each device, before the
things that change the house for everyone: settings, music files, the never-play list, stations and artists' tags.
Playing music, hearts and playlists never ask. It keeps a housemate or a guest from changing things by accident; it is
not security. Soundsquatch passes Lyrion's own controls through, and Lyrion itself is open to the network unless you
give it a password.

### What leaves the house

Artist names and album titles, sent to MusicBrainz, Wikidata and Wikipedia, LRCLIB (for lyrics), the Cover Art
Archive, Apple and Deezer (for covers you choose), and to Qobuz and Discogs through Lyrion's own plugins. Nothing about who listens
or when: the listening log stays in `./data`. Once a day it asks GitHub for the newest release number, which sends
nothing but the question. If you connect Discogs (Settings, Your records), it reads your collection there once a day
with your token, and, with a turntable listener, writes each record's plays to its Plays and Last played fields. The
turntable's sound stays in the house, except a ten-second clip sent to Shazam when your own files can't name a song.

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
| `turntable.py` | the turntable: the stream from the listener, the fingerprints, Shazam, the sides and the signal check |
| `turntable/` | the listener for the Pi (`listener.sh`) and its installer |
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
needs a separate licence from the author. The fonts, stage photos, the face finder's model and the libraries in the
container (ffmpeg, shazamio and the rest) keep their own licences, named in LICENSE.
