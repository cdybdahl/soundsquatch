#!/usr/bin/env python3
"""The house's genres: up to two for each album from one short list of real subgenres, made from MusicBrainz's community
tags (the release group's, else the artist's). Qobuz files half a library under "Alternative/Indie"; this says what it is.
Used by soundsquatch.py, which looks albums up in the background and keeps the answers."""
import collections

# The list, in the order the page offers it, and the MusicBrainz tags that mean each. Broad genres come last and only
# win when nothing more particular is known.
GENRES = [
    ("Post-Rock", ["post-rock", "post rock", "post-metal"]),
    ("Math Rock", ["math rock", "math-rock", "midwest emo"]),
    ("Slowcore", ["slowcore", "sadcore"]),
    ("Shoegaze", ["shoegaze", "shoegazing", "nu gaze"]),
    ("Dream Pop", ["dream pop", "dreampop", "ethereal wave"]),
    ("Art Rock & Prog", ["art rock", "progressive rock", "symphonic rock", "progressive pop", "canterbury scene"]),
    ("Noise & Experimental", ["noise rock", "experimental rock", "experimental", "avant-garde", "no wave", "noise", "avant-rock", "krautrock"]),
    ("Psychedelic", ["psychedelic rock", "neo-psychedelia", "psychedelic pop", "psychedelic", "space rock", "stoner rock"]),
    ("Post-Punk & New Wave", ["post-punk", "post-punk revival", "new wave", "gothic rock", "coldwave", "dance-punk"]),
    ("Punk", ["punk rock", "punk", "hardcore punk", "pop punk", "garage punk", "riot grrrl"]),
    ("Emo & Post-Hardcore", ["emo", "post-hardcore", "emocore", "screamo"]),
    ("Lo-Fi", ["lo-fi", "lo-fi indie", "slacker rock", "noise pop", "bedroom pop"]),
    ("Grunge & Garage", ["grunge", "garage rock", "garage rock revival"]),
    ("Indie Rock", ["indie rock", "indie", "jangle pop", "power pop"]),
    ("Indie Pop", ["indie pop", "twee pop", "art pop", "sophisti-pop"]),
    ("Chamber Pop", ["chamber pop", "baroque pop", "orchestral pop", "chamber folk"]),
    ("Indie Folk", ["indie folk", "freak folk", "anti-folk", "folktronica", "new weird america"]),
    ("Folk", ["folk", "contemporary folk", "folk rock", "british folk", "american folk"]),
    ("Singer-Songwriter", ["singer-songwriter", "singer/songwriter"]),
    ("Alt-Country & Americana", ["alt-country", "alternative country", "americana", "country rock", "country", "outlaw country", "bluegrass", "country folk"]),
    ("Blues", ["blues", "blues rock", "delta blues", "electric blues"]),
    ("Soul & R&B", ["soul", "r&b", "rhythm and blues", "neo soul", "neo-soul", "contemporary r&b", "motown", "northern soul"]),
    ("Funk & Disco", ["funk", "disco", "p-funk", "funk rock", "boogie"]),
    ("Jazz", ["jazz", "jazz fusion", "spiritual jazz", "free jazz", "cool jazz", "bebop", "hard bop", "modal jazz", "soul jazz", "vocal jazz", "jazz rock"]),
    ("Hip-Hop", ["hip hop", "hip-hop", "rap", "conscious hip hop", "alternative hip hop", "abstract hip hop", "boom bap"]),
    ("Trip-Hop & Downtempo", ["trip hop", "trip-hop", "downtempo", "chillout", "chill-out", "acid jazz"]),
    ("Electronic", ["electronic", "electronica", "idm", "techno", "house", "synth-pop", "synthpop", "edm", "electro", "glitch", "drum and bass", "breakbeat", "dubstep", "dance"]),
    ("Ambient", ["ambient", "drone", "dark ambient", "ambient pop", "new age"]),
    ("Modern Classical", ["modern classical", "contemporary classical", "minimalism", "neoclassical", "neo-classical", "post-minimalism"]),
    ("Classical", ["classical", "baroque", "romantic", "orchestral", "opera", "chamber music"]),
    ("Metal", ["metal", "heavy metal", "doom metal", "sludge metal", "black metal", "stoner metal"]),
    ("Reggae & Dub", ["reggae", "dub", "ska", "rocksteady", "dancehall"]),
    ("World", ["world", "afrobeat", "afrobeats", "latin", "bossa nova", "mpb", "highlife", "desert blues", "cumbia", "tropicália"]),
    ("Soundtrack", ["soundtrack", "film score", "score", "film soundtrack", "video game music"]),
    ("Pop", ["pop", "pop rock", "soft rock", "adult contemporary"]),
    ("Rock", ["rock", "alternative rock", "classic rock", "hard rock", "progressive rock", "southern rock", "art rock"]),
]
BROAD = {"Pop", "Rock", "Electronic", "Folk", "Indie Rock"}  # used only when nothing more particular is known, and never second
TAGS = {}
for name, tags in GENRES:
    for t in tags:
        TAGS.setdefault(t, name)  # the first (more particular) genre to claim a tag keeps it

# Lyrion's own genres that may stand in when MusicBrainz knows nothing (never "Alternative/Indie" and its kind).
LYRION = {"classical": "Classical", "jazz": "Jazz", "blues": "Blues", "soundtrack": "Soundtrack", "country": "Alt-Country & Americana",
          "folk": "Folk", "ambient": "Ambient", "post-rock": "Post-Rock", "funk": "Funk & Disco", "r&b": "Soul & R&B", "soul": "Soul & R&B",
          "world": "World", "metal": "Metal", "techno": "Electronic", "singer/songwriter": "Singer-Songwriter", "slowcore": "Slowcore",
          "hip hop": "Hip-Hop", "hip-hop/rap": "Hip-Hop", "reggae": "Reggae & Dub", "folk/americana": "Alt-Country & Americana", "alt-country": "Alt-Country & Americana"}


def pick(tags):
    """Up to two genres from a list of [tag, votes]: the particular before the broad, the second only with real support."""
    score = collections.Counter()
    for t, votes in tags:
        g = TAGS.get(t.lower().strip())
        if g:
            score[g] += votes + 1
    if not score:
        return []
    tier = lambda g: 0 if g not in BROAD else 1 if g == "Indie Rock" else 2  # among the broad, indie rock still says more than rock
    ranked = sorted(score.items(), key=lambda kv: (tier(kv[0]), -kv[1]))
    out = [ranked[0][0]]
    for g, s in ranked[1:]:
        if g not in BROAD and s >= max(2, ranked[0][1] * 0.4):
            out.append(g)
            break
    return out


# A station's line for each genre, for the starter stations a new house gets (soundsquatch.py starter_stations)
BLURBS = {
    "Post-Rock": "Long builds, big swells, few words.", "Math Rock": "Odd time signatures and clean, tangled guitars.",
    "Slowcore": "Slow, quiet and close.", "Shoegaze": "Haze, reverb and walls of guitar.", "Dream Pop": "Soft focus and shimmer.",
    "Art Rock & Prog": "Ambitious, odd and built in movements.", "Noise & Experimental": "Out past the edges.",
    "Psychedelic": "Colours, loops and long trips.", "Post-Punk & New Wave": "Angles, bass lines and nervous energy.",
    "Punk": "Fast, loud and short.", "Emo & Post-Hardcore": "Basement shows and big feelings.", "Lo-Fi": "Tape hiss and bedroom songs.",
    "Grunge & Garage": "Fuzz, feedback and three chords.", "Indie Rock": "Guitars, mostly.", "Indie Pop": "Bright, small and catchy.",
    "Chamber Pop": "Strings, horns and careful arrangements.", "Indie Folk": "Acoustic, odd and close to home.",
    "Folk": "Plain voices and plain-spoken songs.", "Singer-Songwriter": "One voice and the songs it wrote.",
    "Alt-Country & Americana": "Porches, pedal steel and plain-spoken songs.", "Blues": "Twelve bars and a long way from home.",
    "Soul & R&B": "Voices first.", "Funk & Disco": "Grooves, horns and heavy pockets.", "Jazz": "From the standards outward.",
    "Hip-Hop": "Beats and words.", "Trip-Hop & Downtempo": "Slow beats and late nights.", "Electronic": "Machines with feelings.",
    "Ambient": "Space to think.", "Modern Classical": "Piano, strings and patience.", "Classical": "The long tradition.",
    "Metal": "Heavy.", "Reggae & Dub": "Bass, space and echo.", "World": "From everywhere else.", "Soundtrack": "Music for pictures.",
    "Pop": "Hooks.", "Rock": "Turned up.",
}
