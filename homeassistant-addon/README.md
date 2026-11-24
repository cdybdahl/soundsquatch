# Soundsquatch

A magazine-style app for your music: Discover, albums and artists with their stories and credits, rooms, stations, your
records and the turntable. It works with **Lyrion Music Server** or **Music Assistant**.

## Getting started

1. Install the add-on, start it, and choose **Open Web UI** (or open `http://<your Home Assistant's address>:8098` on any
   screen in the house: an iPad on the wall, a phone, a computer).
2. Soundsquatch looks for Lyrion on your network. If it finds it, you're done.
3. To use **Music Assistant** instead, choose *Use Music Assistant instead* on the first screen. When Music Assistant runs
   as an add-on on the same machine, its address is filled in already; you only add a long-lived token from Music
   Assistant's **Settings → Profile**.

Everything else is set in Soundsquatch's own **Settings**. The add-on itself has no options.

## Good to know

- Your music folders: the add-on can see Home Assistant's `share` and `media` folders. Soundsquatch only changes music
  files when you switch that on in its Settings.
- The connection to Home Assistant is made for you.
- Soundsquatch is on port **8098** here and the turntable's listener sends to **8093** (Music Assistant uses 8095 and 8097).
- Everything Soundsquatch keeps (settings, ratings, stations, the listening log, pictures, nightly backups) lives in the
  add-on's own data, which Home Assistant's backups include.
