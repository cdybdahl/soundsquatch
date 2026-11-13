#!/usr/bin/env python3
"""The library's shared rules: how good a copy of a track is, and when two albums are copies of one another (the
shelves show one album a title, its best copy). Used by soundsquatch.py."""
import re


LOSSLESS = {"flc", "wav", "aif", "alc", "wvp", "ape"}


def quality(track):
    """A track's quality, as a key that sorts better copies higher, and in words."""
    kind, bits, rate = track.get("type") or "", int(track.get("samplesize") or 0), int(track.get("samplerate") or 0)
    if kind in LOSSLESS:
        bits = bits or 16
        words = "CD" if (bits, rate) == (16, 44100) else f"{bits}/{rate / 1000:g}"
        return (1, bits, rate), words
    kbps = int(re.sub(r"\D.*", "", track.get("bitrate") or "") or 0)
    return (0, kbps, rate), f"{'AAC' if kind in ('mp4', 'aac') else kind.upper()} {kbps}".strip()


def copies(artist, album):
    """An album as copies of it are matched: no case, "&" as "and", no (Deluxe Edition) or [Remastered] asides."""
    return re.sub(r"[^a-z0-9|]", "", re.sub(r"[(\[].*?[)\]]", "", f"{artist}|{album}".lower().replace("&", "and")))
