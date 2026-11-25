# Soundsquatch

A magazine-style app for your music: Discover, albums and artists with their stories and credits, rooms, stations, your
records and the turntable. It works with **Lyrion Music Server** or **Music Assistant**.

## Getting started

1. Install the add-on, start it, and choose **Open Web UI** (or open `http://<your Home Assistant's address>:8098` on any
   screen in the house: an iPad on the wall, a phone, a computer).
2. Soundsquatch looks for Lyrion on your network, and for Music Assistant on this Home Assistant.
   - If it finds one of them, it uses that one, and you're done.
   - If it finds both, the first screen asks which one to use. Music Assistant also needs a long-lived token from its
     **Settings → Profile**.
   - If it finds neither, the first screen asks where Lyrion is, or offers *Use Music Assistant instead*.

You can switch between them later in Soundsquatch's **Settings**.

Everything else is set in Soundsquatch's own **Settings**. The add-on itself has no options.

## Good to know

- Your music folders: the add-on can see Home Assistant's `share` and `media` folders. Soundsquatch only changes music
  files when you switch that on in its Settings.
- The connection to Home Assistant is made for you.
- Soundsquatch is on port **8098** here and the turntable's listener sends to **8093** (Music Assistant uses 8095 and 8097).
- Everything Soundsquatch keeps (settings, ratings, stations, the listening log, pictures, nightly backups) lives in the
  add-on's own data, which Home Assistant's backups include.
