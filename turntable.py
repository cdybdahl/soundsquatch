#!/usr/bin/env python3
"""The turntable's ear: naming what the record player is playing, from what a small listener (turntable/listener.py, on a
Raspberry Pi with a USB audio interface on the amplifier's record-out) hears.

Songs are named two ways. First by the house's own files: each track of the records also on the digital shelves as files
is fingerprinted once (the peaks of its spectrogram, paired into hashes, as Shazam's own paper describes) and a clip is
matched against them here, with nothing leaving the house. Only when that finds nothing is the clip sent to Shazam
(shazamio), which knows nearly everything.

Uses numpy (already here for the face finder) and ffmpeg (to read the music files)."""
import asyncio
import collections
import io
import os
import subprocess
import threading
import wave

import numpy as np

RATE = 8000  # the fingerprints' sample rate: the clip and the files are both brought down to it
NFFT, HOP = 1024, 256  # 128 ms windows, 32 ms apart
FAN, DT_MAX = 4, 63  # each peak paired with the next four within two seconds
NEIGH_F, NEIGH_T = 20, 12  # a peak is the loudest in its 20 bins by 12 frames
SPEEDS = (1, 1.004, 0.996, 1.008, 0.992, 1.012, 0.988)  # a clip's speeds tried, nearest first


def spectrum(x):
    """Log magnitudes, [frames, bins] (512 bins: 0–4 kHz)."""
    if len(x) < NFFT:
        return np.zeros((0, NFFT // 2), np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(x, NFFT)[::HOP] * np.hanning(NFFT)
    return np.log1p(np.abs(np.fft.rfft(frames, axis=1))[:, :NFFT // 2]).astype(np.float32)


def peaks(S):
    """The spectrogram's landmarks: (frame, bin) of each local maximum well above the frame's average."""
    if not len(S):
        return np.zeros((0, 2), int)
    pad = np.pad(S, ((NEIGH_T, NEIGH_T), (NEIGH_F, NEIGH_F)), constant_values=-1)
    m = np.lib.stride_tricks.sliding_window_view(pad, 2 * NEIGH_F + 1, axis=1).max(axis=2)
    m = np.lib.stride_tricks.sliding_window_view(m, 2 * NEIGH_T + 1, axis=0).max(axis=2)
    keep = (S == m) & (S > S.mean(axis=1, keepdims=True) + 1.0) & (S > 0.5)
    keep[:, :4] = False  # the hum and the rumble at the bottom
    return np.argwhere(keep)


def hashes(x):
    """(hash, frame) for each pair of landmarks: the two bins and the frames between them, in 24 bits."""
    p = peaks(spectrum(x))
    out_h, out_t = [], []
    for i in range(len(p)):
        t1, f1 = p[i]
        n = 0
        for j in range(i + 1, len(p)):
            dt = p[j][0] - t1
            if dt <= 0:
                continue
            if dt > DT_MAX or n == FAN:
                break
            out_h.append((int(f1) << 15) | (int(p[j][1]) << 6) | int(dt))
            out_t.append(int(t1))
            n += 1
    return np.array(out_h, np.uint32), np.array(out_t, np.int32)


def read_file(path, seconds=None):
    """A music file as mono samples at RATE, through ffmpeg."""
    cmd = ["ffmpeg", "-v", "quiet", "-i", path, "-ac", "1", "-ar", str(RATE)] + (["-t", str(seconds)] if seconds else []) + ["-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=300).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def read_wav(data):
    """A clip from the listener (16-bit PCM WAV, any rate, mono or stereo) as mono samples at RATE."""
    with wave.open(io.BytesIO(data)) as w:
        rate, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != RATE:  # a plain resampling is enough for landmarks
        n = int(len(x) * RATE / rate)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


class Index:
    """The house's own tracks as fingerprints, kept as one sorted array (index.npz in the folder given): a clip's hashes
    are looked up by binary search, and the track whose matches line up at one offset is the song."""

    def __init__(self, folder):
        self.folder, self.lock = folder, threading.Lock()
        os.makedirs(folder, exist_ok=True)
        self.h = self.track = self.t = None
        self.tracks = {}  # track id → path, as it was indexed
        try:
            z = np.load(os.path.join(folder, "index.npz"), allow_pickle=True)
            self.h, self.track, self.t = z["h"], z["track"], z["t"]
            self.tracks = dict(z["tracks"].item())
        except Exception:
            pass

    def build(self, tracks, progress=None):
        """tracks: {lms track id: file path}. Only the ones not indexed yet are read; those gone are dropped."""
        keep = {i: p for i, p in self.tracks.items() if i in tracks and tracks[i] == p}
        hs, ts, ks = [], [], []
        if self.h is not None and keep:
            sel = np.isin(self.track, list(keep))
            hs, ts, ks = [self.h[sel]], [self.t[sel]], [self.track[sel]]
        todo = [(i, p) for i, p in tracks.items() if i not in keep]
        for n, (i, p) in enumerate(todo):
            try:
                h, t = hashes(read_file(p))
            except Exception:
                continue
            hs.append(h), ts.append(t), ks.append(np.full(len(h), i, np.int32))
            keep[i] = p
            if progress:
                progress(n + 1, len(todo))
        if not hs:
            return
        h, t, k = np.concatenate(hs), np.concatenate(ts), np.concatenate(ks)
        order = np.argsort(h, kind="stable")
        with self.lock:
            self.h, self.t, self.track, self.tracks = h[order], t[order], k[order], keep
        np.savez(os.path.join(self.folder, "index.tmp.npz"), h=self.h, t=self.t, track=self.track, tracks=np.array(keep, dtype=object))
        os.replace(os.path.join(self.folder, "index.tmp.npz"), os.path.join(self.folder, "index.npz"))

    def match(self, x):
        """(track id, seconds into it where the clip starts, votes, the turntable's speed) for the best match, or None. A turntable runs a little
        fast or slow (half a percent moves the peaks enough to lose them), so the clip is tried at speeds around its own."""
        best = None
        for speed in SPEEDS:
            y = x if speed == 1 else np.interp(np.arange(0, len(x) - 1, speed), np.arange(len(x)), x).astype(np.float32)
            m = self.match_one(y)
            if m and (not best or m[2] > best[2]):
                best = (m[0], m[1] * speed, m[2], 1 / speed)  # the last: how fast the turntable ran (the clip matched sped up by speed)
                if m[2] >= 40:
                    break  # certain enough
        return best

    def match_one(self, x):
        with self.lock:
            if self.h is None or not len(self.h):
                return None
            qh, qt = hashes(x)
            lo, hi = np.searchsorted(self.h, qh, "left"), np.searchsorted(self.h, qh, "right")
            tr, off = [], []
            for a, b, t in zip(lo, hi, qt):
                if b > a and b - a < 200:  # a hash found everywhere says nothing
                    tr.append(self.track[a:b])
                    off.append(self.t[a:b] - t)
        if not tr:
            return None
        tr, off = np.concatenate(tr), np.concatenate(off)
        pairs, counts = np.unique(tr.astype(np.int64) * 100000 + (off + 50000), return_counts=True)
        best = np.argsort(counts)[::-1][:2]
        top = counts[best[0]]
        second = counts[best[1]] if len(best) > 1 else 0
        if top < 10 or top < 2 * second:
            return None
        track, offset = divmod(int(pairs[best[0]]), 100000)
        return track, max(0, (offset - 50000) * HOP / RATE), int(top)


def shazam(data):
    """Shazam's name for a clip (WAV bytes): {title, artist, album, offset}, or None. The clip leaves the house."""
    try:
        from shazamio import Shazam
    except ImportError:
        return None

    async def ask():
        return await asyncio.wait_for(Shazam().recognize(data), 20)  # a slow Shazam must not hold up the next try

    try:
        got = asyncio.run(ask())
    except Exception as e:
        print(f"turntable: Shazam failed: {type(e).__name__}: {e}", flush=True)
        return None
    t = got.get("track") or {}
    if not t.get("title"):
        return None
    album = ""
    for s in t.get("sections") or []:
        for m in s.get("metadata") or []:
            if m.get("title") == "Album":
                album = m.get("text") or ""
    offset = ((got.get("matches") or [{}])[0]).get("offset") or 0
    return {"title": t["title"], "artist": t.get("subtitle") or "", "album": album, "offset": float(offset)}


# ───────────────────────── the stream from the listener ─────────────────────────
# The listener on the Pi sends the amplifier's record-out as it is (arecord, 44.1 kHz, 16-bit stereo, raw) over one TCP
# connection; everything else is done here: the levels for visualisers, the gaps between songs, the clips to name, and
# each song written to a file of its own.
SR, CH = 44100, 2
BLOCK = 1470  # 1/30 s: one visualiser frame
QUIET_DB = -48  # below this a block is the run-out groove, the gap between songs, or nothing at all
GAP = 1.2  # this long below it is a gap between songs
SIDE_GAP = 20  # this long, the side is over (the run-out groove, the arm lifted)
BANDS = np.unique(np.geomspace(2, 1024, 33).astype(int))  # the visualiser's bands over a 2048-point spectrum, 40 Hz up


class Ear:
    """The listener's stream, heard. on_clip(x8k, wav16k, run_seconds, run) is called from a thread of its own whenever
    a clip should be named: 6 s into a stretch of sound (a quick guess), at 11 s (to be sure), then now and then while it
    lasts. on_quiet(seconds) while it is quiet. Frames for visualisers go to each queue in self.watchers.

    With capture_dir set (and capturing() true), each side is written whole, from a moment before the needle's first
    sound to the run-out (twenty seconds of quiet, or the listener gone); on_side(path, start, end, gaps) then cuts it
    into its songs. Silences can't be trusted to part the songs (a record's gaps are short, and some songs run into the
    next), so the cuts come from the naming: each match says how far into its song the clip was, so where every song
    began; the quiet moments (gaps, by the stream's clock) only steady the cut."""

    def __init__(self, port, on_clip, on_quiet, capture_dir=None, on_side=None, capturing=lambda: True):
        self.port, self.on_clip, self.on_quiet = port, on_clip, on_quiet
        self.capture_dir, self.on_side, self.capturing = capture_dir, on_side, capturing
        self.run = 0  # which stretch of sound this is (between gaps: usually a song)
        self.side = None  # (ffmpeg, path, started) while a side is being written
        self.gaps = []  # (quiet began, quiet ended) by the stream's clock, while a side is written
        self.preroll = []  # the last second and a half of raw blocks, so the side's first notes are kept
        self.ring = np.zeros(SR * 30, np.float32)  # the last 30 s, mono
        self.filled = 0
        self.lock = threading.Lock()
        self.watchers = []  # visualiser queues (each a list the HTTP side drains)
        self.streams = []  # the live stream's listeners: each a list of raw blocks the HTTP side drains
        self.connected = False
        self.heard_at = 0.0
        self.smooth, self.n_blocks, self.quiet_db = None, 0, QUIET_DB
        self.levels = collections.deque(maxlen=9000)  # the smoothed level every tenth of a second, a quarter hour of it
        self.run_start = None  # when the current stretch of sound began (after a gap), by the stream's clock
        self.quiet_for = 0.0
        self.clock = 0.0  # seconds of stream received
        self.asked = []  # the run times already named in this stretch
        self.level = -90.0

    def start(self):
        threading.Thread(target=self.serve, name="turntable", daemon=True).start()
        threading.Thread(target=self.namer_kept, name="turntable-namer", daemon=True).start()

    def serve(self):
        import socket
        import time
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", self.port))
        s.listen(1)
        while True:
            conn, _ = s.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(10)
            self.connected, buf = True, b""
            try:
                while True:
                    got = conn.recv(65536)
                    if not got:
                        break
                    self.heard_at = time.time()
                    buf += got
                    n = len(buf) // (BLOCK * CH * 2) * BLOCK * CH * 2
                    for i in range(0, n, BLOCK * CH * 2):
                        self.block(buf[i:i + BLOCK * CH * 2])
                    buf = buf[n:]
            except Exception:
                pass
            finally:
                self.connected = False
                self.end_side()
                conn.close()

    def block(self, raw):
        """One 1/30 s: into the ring, its level, the gap watch, the song being written, a visualiser frame."""
        pcm = np.frombuffer(raw, np.int16)
        x = pcm.astype(np.float32).reshape(-1, CH).mean(axis=1) / 32768
        with self.lock:
            self.ring = np.roll(self.ring, -len(x))
            self.ring[-len(x):] = x
            self.filled = min(len(self.ring), self.filled + len(x))
        self.clock += len(x) / SR
        rms = float(np.sqrt(np.mean(x * x)) + 1e-9)
        db = 20 * np.log10(rms)
        self.level = db
        # silence by this turntable's own surface noise: a few dB above the quietest of the last quarter hour (never
        # above QUIET_DB), on the level smoothed over a few blocks, so a quiet record's soft bars aren't taken for gaps
        self.smooth = db if self.smooth is None else self.smooth * 0.8 + db * 0.2
        self.n_blocks += 1
        if self.n_blocks % 3 == 0 and self.smooth > -85:
            self.levels.append(self.smooth)
        if self.n_blocks % 300 == 0 and len(self.levels) > 600:
            self.quiet_db = float(min(QUIET_DB, max(-62.0, np.percentile(self.levels, 3) + 5)))
        db = self.smooth
        if db < self.quiet_db:
            self.quiet_for += len(x) / SR
            if self.quiet_for >= GAP and self.run_start is not None:
                self.run_start, self.asked = None, []
            if self.quiet_for >= SIDE_GAP:
                self.end_side()
        else:
            if self.quiet_for >= 0.4 and self.side:
                self.gaps.append((self.clock - self.quiet_for, self.clock))
            if self.run_start is None:
                self.run_start, self.run = self.clock, self.run + 1
            if not self.side:
                self.begin_side()
            self.quiet_for = 0.0
        for q in list(self.streams):
            q.append(raw)
            del q[:-300]  # ten seconds behind at most
        if self.side:
            try:
                self.side[0].stdin.write(raw)
            except Exception:
                self.side = None
        self.preroll = (self.preroll + [raw])[-45:]
        if self.watchers:
            with self.lock:
                tail = self.ring[-2048:] * np.hanning(2048)
            mag = np.abs(np.fft.rfft(tail))
            bands = [float(mag[a:b].mean()) for a, b in zip(BANDS[:-1], BANDS[1:])]
            frame = {"db": round(db, 1), "b": [round(min(1.0, max(0.0, (20 * np.log10(v + 1e-9) + 10) / 60)), 3) for v in bands]}
            for q in list(self.watchers):
                q.append(frame)
                del q[:-8]  # a slow watcher gets the newest

    def clip(self, seconds):
        """The last seconds heard: mono at 8 kHz (for the house's fingerprints) and a 16 kHz WAV (for Shazam)."""
        with self.lock:
            x = self.ring[-int(seconds * SR):].copy()
        lo = np.convolve(x, np.ones(5) / 5, "same")  # a gentle low-pass before bringing it down
        x8 = np.interp(np.arange(0, len(lo) - 1, SR / RATE), np.arange(len(lo)), lo).astype(np.float32)
        # Shazam's clip: brought up to a full level (a quiet record is still a record) and resampled by ffmpeg, which
        # Shazam takes where a plain interpolation was turned away
        peak = float(np.abs(x).max()) or 1.0
        loud = (np.clip(x * (0.7 / peak), -1, 1) * 32767).astype(np.int16).tobytes()
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:  # a file, not a pipe: a piped WAV has no length in its header
            subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-", "-ar", "16000", f.name],
                           input=loud, capture_output=True, timeout=20)
            return x8, open(f.name, "rb").read()

    def namer_kept(self):
        """The namer, started again after anything unforeseen (said in the log), so naming never quietly stops."""
        import time, traceback
        while True:
            try:
                self.namer()
            except Exception:
                traceback.print_exc()
                time.sleep(1)

    def namer(self):
        """When to name what's playing: at 6 s and 11 s into a stretch of sound, every 12 s after while it has no name,
        then every 90 s (a record segues without a gap often enough); the quiet reported every second (a listener gone
        is quiet too). on_clip answers whether it named the song."""
        import time
        last_quiet, named = 0, set()
        while True:
            time.sleep(0.25)
            if not self.connected or self.run_start is None:
                quiet = self.quiet_for if self.connected else time.time() - (self.heard_at or time.time())
                if time.time() - last_quiet >= 1:
                    last_quiet = time.time()
                    try:
                        self.on_quiet(quiet)
                    except Exception:
                        pass
                continue
            start = self.run_start  # read once: the stream's thread clears it at each gap
            if start is None:
                continue
            run = self.clock - start
            due = next((t for t in (6, 11) if run >= t and t not in self.asked), None)
            if due is None and run >= 11 and run - max(self.asked or [0]) >= (90 if self.run in named else 12):
                due = run
            if due is None:
                continue
            self.asked.append(due)
            try:
                x8, wav = self.clip(min(run, 10))
                if self.on_clip(x8, wav, run, self.run, self.clock):
                    named.add(self.run)
            except Exception:
                import traceback
                traceback.print_exc()  # a song unnamed for a reason should say so in the log

    def begin_side(self):
        if not self.capture_dir or not self.capturing():
            return
        import time
        os.makedirs(self.capture_dir, exist_ok=True)
        path = os.path.join(self.capture_dir, f".side-{int(time.time())}.flac")
        p = subprocess.Popen(["ffmpeg", "-v", "quiet", "-y", "-f", "s16le", "-ar", str(SR), "-ac", str(CH), "-i", "-", "-c:a", "flac", path], stdin=subprocess.PIPE)
        for raw in self.preroll:
            p.stdin.write(raw)
        self.side, self.gaps = (p, path, self.clock - len(self.preroll) * BLOCK / SR), []

    def end_side(self):
        """The side written to its end; handed on to be cut into songs."""
        side, self.side = self.side, None
        if not side:
            return
        p, path, started = side
        try:
            p.stdin.close()
            p.wait(timeout=60)
        except Exception:
            p.kill()
        if self.on_side:
            threading.Thread(target=self.on_side, args=(path, started, self.clock - self.quiet_for, list(self.gaps)), daemon=True).start()


# ───────────────────────── the signal chain, judged from a side ─────────────────────────
def analyse_side(path):
    """What a side's recording says of the chain that made it (the cartridge and stylus, the tonearm, the amplifier, the
    interface), second by second, read through ffmpeg so a whole side never sits in memory:

      balance   left over right in dB while music plays (the median); persistently off on every record: the chain
      corr      how alike the channels are while music plays (1 same, 0 unrelated, below 0 one channel's wires reversed)
      noise     the floor in the quiet (the lead-in, the gaps): surface noise, in dBFS
      hum       60, 120 and 180 Hz above their neighbours in the quiet, in dB: a ground loop
      rumble    energy below 20 Hz against the music's, in dB: the motor or the bearing
      clicks    sharp spikes a minute of the quiet (the lead-in, the gaps, the run-out): dust, static, damage
      clipped   samples at full scale: the interface's input driven too hard
      peak      the loudest moment, in dBFS
    """
    cmd = ["ffmpeg", "-v", "quiet", "-i", path, "-f", "s16le", "-ac", "2", "-ar", str(SR), "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    bal, corr, quiet_db, hum, rumble = [], [], [], [], []
    clicks = clipped = 0
    peak, seconds = 0.0, 0
    freqs = np.fft.rfftfreq(SR, 1 / SR)
    lowband, humbins = freqs < 20, [int(f) for f in (60, 120, 180)]
    while True:
        raw = p.stdout.read(SR * 4)
        if len(raw) < SR * 4:
            break
        seconds += 1
        x = np.frombuffer(raw, np.int16).reshape(-1, 2).astype(np.float32) / 32768
        L, R = x[:, 0], x[:, 1]
        clipped += int(np.sum(np.abs(x) > 0.999))
        peak = max(peak, float(np.abs(x).max()))
        m = (L + R) / 2
        rl, rr, rm = float(np.sqrt(np.mean(L * L))) + 1e-9, float(np.sqrt(np.mean(R * R))) + 1e-9, float(np.sqrt(np.mean(m * m))) + 1e-9
        db = 20 * np.log10(rm)
        if db > -35:
            bal.append(20 * np.log10(rl / rr))
            corr.append(float(np.mean(L * R) / (rl * rr)))
            spec = np.abs(np.fft.rfft(m))
            rumble.append(20 * np.log10((spec[lowband].mean() + 1e-9) / (spec[20:2000].mean() + 1e-9)))
        elif -80 < db < -47:  # true quiet: the lead-in, the gaps, the run-out (not a song fading out)
            quiet_db.append(db)
            # clicks, where they stand out and are heard: in the quiet (under music a cymbal looks like one). A sample far
            # from the median of its neighbours, counted once however many samples it spans
            r = np.abs(m[4:-4] - np.median(np.lib.stride_tricks.sliding_window_view(m, 9), axis=1))
            hit = np.flatnonzero(r > max(0.004, 20 * float(np.median(r))))
            clicks += int(np.sum(np.diff(hit) > 88)) + (1 if len(hit) else 0)
            spec = np.abs(np.fft.rfft(m * np.hanning(len(m))))
            near = lambda f: np.median(np.r_[spec[f - 12:f - 3], spec[f + 4:f + 13]]) + 1e-12
            hum.append(max(20 * np.log10(spec[f - 1:f + 2].max() / near(f)) for f in humbins))
    p.wait()
    med = lambda v: round(float(np.median(v)), 2) if len(v) else None
    return {"seconds": seconds, "balance": med(bal), "corr": med(corr), "noise": med(quiet_db) if len(quiet_db) >= 5 else None,
            "hum": med(hum) if len(hum) >= 5 else None, "rumble": med(rumble), "clicks": round(clicks / (len(quiet_db) / 60), 1) if len(quiet_db) >= 5 else None,
            "clipped": clipped, "peak": round(float(20 * np.log10(peak + 1e-9)), 1), "music": len(bal), "quiet": len(quiet_db)}
