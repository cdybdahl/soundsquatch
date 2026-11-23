# Soundsquatch

A music app in the browser, for a tablet, a phone, a computer or a screen on the wall: magazine-like and discovery-first, with
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
  members, bands and per-track credits (every name a link; each track's own behind a button on its row), Wikipedia's
  album reviews, similar artists, and one discography per artist: your records and your streaming service's together,
  in the order they first came out, with All / Mine / On Qobuz (or TIDAL). Every album opens its page, owned or not.
- **Listening**: History by day, an album you played through as one row; each album page says how often and when you
  played it, and each track how often.
- **The Internet Archive**, through the ArchiveLMA Lyrion plugin: favourites on
  the shelves, each artist's shows, a show page with its setlist and recording notes.
- **Playing**: rooms (join, leave, move the music), Now Playing with synced lyrics
  (LRCLIB) and credits, queue reordering, playlists, radio (Don't Stop the Music),
  stations seeded like a chill mix.
- **Marks**: hearts, stars and tags, kept on the server for the household.
- **Remove from library**: Qobuz or TIDAL favourites un-favourited, files *moved* to
  `music-removed` (never deleted), with a Recently removed page to put them back.
- **Your records**, from your Discogs collection: the albums you also have on vinyl (or CD) say so, the records you
  have only on vinyl are kept beside the digital ones, with filters (format, pressing, genre, decade, and *To capture*:
  the records with nothing digital, those your streaming service lacks first) and a page for each record (its tracklist by side, credits, the pressing's barcodes and run-out, videos, plays).
- **The turntable**, with a small listener on your amplifier's record-out: Soundsquatch names what the record player
  plays (from your own files first, then Shazam), shows it as Now Playing, suggests what to play next, keeps count of
  plays (on Discogs too), records each side as tagged songs into your library, streams it live to any room, and
  watches the signal for trouble in the chain (balance, hum, speed, overload).

## The beta

Soundsquatch is in beta: it runs every day in one house (about 1,500 albums), and it's now being tried in a
few more. Expect rough edges, and please say what you find.

### What you need

- **Lyrion Music Server** 9.x, on your network, with the music in it already. Soundsquatch is a way of browsing and
  playing it; Lyrion stays the player, the library and the queue.
- **Docker** on a machine on the same network (the Lyrion machine itself is fine).
- Optional Lyrion plugins, each found by itself and left out when it isn't there:
  - **Qobuz**: Qobuz releases, artists' stories and similar artists, search beyond your shelves
  - **TIDAL**: the same from TIDAL (no artist stories: those come from Wikipedia). With both signed in, Qobuz is used
  - **Ratings Light** (3.2 or later): album stars become the average of your track ratings in Lyrion, and rating an
    album rates its tracks
  - **Music & Artist Information**: album reviews, longer stories, more artist photographs
  - **ArchiveLMA**: Internet Archive shows
  - **Don't Stop the Music** with **LastMix**: radio and stations
  - **Listen Later**: a Listen Later button on albums, and your saved list on Discover
  - **ListenBrainz Fresh Releases**: fresh releases picked for you, on Discover
  - **Pitchfork Reviews**: Best New Music, on Discover
- A library up to about **10,000 albums**. Bigger ones aren't supported.
- Lyrion set to **English** if you want to keep or remove Qobuz albums from Soundsquatch (TIDAL doesn't need it). Everything else works in
  any language.

### Install

```sh
mkdir soundsquatch && cd soundsquatch
curl -fsSLO https://raw.githubusercontent.com/cdybdahl/soundsquatch/main/compose.yaml
docker compose up -d
```

That fetches the ready-built image (for 64-bit Intel/AMD and ARM machines). Set your time zone in `compose.yaml`
first.

**The first start takes a while.** The shelves and covers are there in minutes, but Soundsquatch then gathers what it
knows about every artist and album: stories, photographs, genres and credits, mostly from MusicBrainz, which answers
one question a second. Expect three or four hours for about 1,500 albums, and the best part of a day near 10,000.
Everything works meanwhile, and pages fill in as it goes (Discover says how far it has got); it only happens once,
and after that only new albums are looked up.

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

Put a record on, and Soundsquatch knows. A few seconds after the needle drops, Now Playing shows the record and the
song: its cover, its place on the side, the tracklist with what's been heard ticked off, and a visualiser moving with
the music. Turn the record over and it carries on. Lift the arm at the end and it suggests what to play next. Every
side is quietly recorded, cut into its songs and filed in your library, so a record you own only on vinyl is
there to play anywhere in the house the next day. And it keeps an ear on the turntable itself: a stylus wearing, a
channel going quiet, a hum creeping in, a belt slowing down.

All it takes is a small listener (a Raspberry Pi and a USB audio interface, about the price of a record) on the
amplifier's record-out. The turntable, the cartridge and the amplifier stay exactly as they are.

#### A record, from the needle to the run-out

This is *Pink Moon*, side A to side B, as Soundsquatch had it, with nothing done by hand:

1. **The needle drops.** Six seconds in, "Pink Moon" (A1) is named: not by sending it anywhere, but by matching it
   against fingerprints of the house's own copy of the album. Eleven seconds in, it's sure. Now Playing switches to
   the turntable (the room's own streaming paused when the lid went up), with the record's tracklist from Discogs.
2. **Each song as it comes.** "Place to Be" (A2), "Road" (A3)… each named as it starts, even where one runs straight
   into the next. Elsewhere in the house, **Hear it in…** plays the turntable live in any room.
3. **The side ends.** Half a minute of quiet: the side is over, and it's probably being flipped, so nothing is said.
   Meanwhile the side, recorded whole, is cut into its six songs where the naming says each one began, tagged and
   filed, and Lyrion is asked to look:

   ```
   From vinyl/Nick Drake - Pink Moon/
     A1 Pink Moon.flac          A6 Things Behind the Sun.flac     B4 Harvest Breed.flac
     A2 Place to Be.flac        B1 Know.flac                      B5 From the Morning.flac
     A3 Road.flac               B2 Parasite.flac                  folder.jpg
     A4 Which Will.flac         B3 Free Ride.flac
     A5 Horn.flac
   ```

   Each song carries the artist, the record, its side (as the disc) and number, its position as printed (B3), the
   year the music came out, Discogs's genres and the release, beside the record's cover. In the library it's a
   pressing of its own, **Vinyl, captured by Soundsquatch**, next to the digital copies and never in their place.
4. **Side B, the last song.** "From the Morning" is the record's last track, so this time it's over: Home Assistant
   can tell the phones "That's the record", with what to play next: the band's next record (on the shelf, in the
   library, or not in the house yet) and an artist who followed (a member's own records first).
5. **Counted.** The record's plays go up, on Discogs too (*Plays 1, Last played 2026-11-16*).
6. **Judged.** Each side's signal goes into the turntable's history:

   | | Side A | Side B |
   |---|---|---|
   | Left and right | −0.1 dB | −0.4 dB |
   | The channels in step | 0.95 | 0.95 |
   | Surface noise, between songs | −55 dB | −54 dB |
   | Hum, over that noise | 12 dB | 13 dB |
   | Loudest moment | −0.5 dB | −1.1 dB |
   | Speed, against the house's own copy | 0.4% slow | 0.4% slow |

   One side says little; the same thing side after side, record after record, is the turntable rather than the
   pressing, and then it's said plainly, with what to try. For example: *"The right channel is 1.4 dB quieter, on 9 of the last
   10 sides… swap the turntable's left and right leads at the amplifier: if the quiet side moves, it's before the
   swap."* The same goes for hum (the ground wire), speed (the belt), overload (the interface's input) and a channel
   wired backwards; and a record much noisier than the rest of the collection is told it wants a clean.

When a song can't be named from the house's files, ten seconds of it go to Shazam. When Shazam doesn't know it either
(it doesn't know everything on vinyl), the app asks: *Is it B3, "Free Ride"?*, or which record is on and which
song, and carries on from there.

#### What you need

- **A Raspberry Pi**: a Pi 3 or newer is plenty (it only records and sends), with **Raspberry Pi OS Lite (64-bit)**.
  A network cable is steadier than Wi-Fi for a constant stream; on Wi-Fi a Pi 3 only joins 2.4 GHz networks.
- **A USB audio interface with line inputs**, such as the Behringer UCA202 or UCA222 (any USB sound card with a
  line-level input works). The signal comes from the amplifier's **record-out** (or tape-out) because it needs the
  phono stage first: a turntable straight into the interface won't do.
- **A good power supply for the Pi**: 5.1 V, 2.5 A, on a short cable. The interface draws its power through the Pi,
  and a weak supply shows up as clicks in the recordings (`vcgencmd get_throttled` on the Pi should say `0x0`).
- **Your records on Discogs** (see *Your records*, above): it's how Soundsquatch knows which record a song is from,
  its tracklist and sides, and which of your files to fingerprint.
- Optionally, **a contact sensor on the lid** in Home Assistant, so that what the amplifier plays from the tuner or
  the streamer isn't taken for a record.

Wire the amplifier's **REC OUT** to the interface's **inputs**, plug the interface into the Pi, and on the Pi run:

```sh
curl -fsSL https://raw.githubusercontent.com/cdybdahl/soundsquatch/main/turntable/install.sh | sudo sh -s <the Soundsquatch machine>
```

**Settings → Your records → The turntable** says when it's listening. On **Change** there: the lid's sensor, and the
room the turntable is in. To keep the recordings, switch on **Settings → Features → Keep the turntable's songs** (the
music has to be mounted read-write, as for *Changing music files*).

#### How it works

```
amplifier REC OUT ─► USB interface ─► Pi ── one raw stream ──► Soundsquatch
                                                                 ├─ naming: your files' fingerprints, then Shazam
                                                                 ├─ each side recorded, cut into tagged songs
                                                                 ├─ the signal check
                                                                 ├─ levels for the visualiser
                                                                 └─ a live stream any room can play
```

The Pi does nothing but send: `arecord` (ALSA's recorder) reads the interface at CD quality, and `netcat` passes it,
raw, over one connection to Soundsquatch's port **8095**, with about a tenth of a second's delay. Everything else
happens on the Soundsquatch machine. The fingerprints are the spectrogram's peaks paired into hashes, made overnight
from your files of the records in your collection, and a clip is tried at a few speeds either side of its own, since
no turntable runs exactly true; the speed that matches is how the speed check knows. Each match says how far into
its song the clip was, which is where the song began: that's where the sides are cut, not at the silences (a
record's gaps are short, and some songs run straight on).

**With Home Assistant** (optional): `http://<the Soundsquatch machine>:8097/api/turntable` is the turntable's state as
JSON, for a REST sensor: `state` is `idle`, `playing`, `side over` (likely a flip) or `record over`, with the record,
the song, the songs heard, the suggestions, and the signal check's newest `alert`. Three automations make the most of
it: pause the room's streaming when the lid opens; tell the phones what to play next on `record over`; pass on a new
`alert`. The live stream is `http://<the Soundsquatch machine>:8097/turntable.flac` (or `.mp3`), for any player.

### A PIN

Anyone on your network can open Soundsquatch. A PIN (**Settings → PIN**) is asked for, once on each device, before the
things that change the house for everyone: settings, music files, the never-play list, stations and artists' tags.
Playing music, hearts and playlists never ask. It keeps a housemate or a guest from changing things by accident; it is
not security. Soundsquatch passes Lyrion's own controls through, logged in when Lyrion has a password, so anyone who
can open Soundsquatch can work Lyrion too. Keep it inside the house: to reach it from outside, put a login in front of it
(a VPN, or a reverse proxy that asks for one), never a bare port forward. Backups and exports leave out Lyrion's
password and the PIN.

### What leaves the house

Artist names and album titles, sent to MusicBrainz, Wikidata and Wikipedia, LRCLIB (for lyrics), the Cover Art
Archive, Apple and Deezer (for covers you choose), and to Qobuz, TIDAL and Discogs through Lyrion's own plugins. Nothing about who listens
or when: the listening log stays in `./data`, unless you connect a scrobble server (Settings, Your records), which
then gets each play: artist, track, album and when. Once a day it asks GitHub for the newest release number, which sends
nothing but the question. If you connect Discogs (Settings, Your records), it reads your collection there once a day
with your token, and, with a turntable listener, writes each record's plays to its Plays and Last played fields. A
record you play that isn't in your collection yet is looked up on Discogs and, once it has played, added to the collection. The
turntable's sound stays in the house, except a ten-second clip sent to Shazam when your own files can't name a song.

### Telling us

Post problems and ideas in the [Soundsquatch thread](https://forums.lyrion.org/forum/user-forums/3rd-party-software/1842759-announce-soundsquatch-beta-a-magazine-style-interface-for-all-your-music) on the Lyrion forums. Say what you did and what you expected, and
paste the report from **Settings → Diagnostics** (versions, what was found, the last errors; no names, addresses or
listening). `docker logs soundsquatch` has the rest.

Soundsquatch is for 64-bit machines (x86, or ARM such as a Raspberry Pi on 64-bit Raspberry Pi OS); a 32-bit Pi isn't supported.

## Layout

| Path | What |
|---|---|
| `soundsquatch.py` | the service: app, Lyrion pass-through, crawler, caches (standard library + Pillow) |
| `app/` | the app itself: plain HTML, CSS and script, no build step, older-Safari safe |
| `streaming.py` | the streaming services, each through its Lyrion plugin: Qobuz and TIDAL behind the same few doings |
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

## Buy the sasquatch a beer

Soundsquatch is made in spare evenings. If it earns a place in your house, you can
[buy the sasquatch a beer](https://www.buymeacoffee.com/mryeti).

## Licence

Soundsquatch is free for personal and other noncommercial use under the
[PolyForm Noncommercial License 1.0.0](LICENSE): run it, change it, share it. Selling it, or using it in a business,
needs a separate licence from the author. The fonts, stage photos, the face finder's model and the libraries in the
container (ffmpeg, shazamio and the rest) keep their own licences, named in LICENSE.
