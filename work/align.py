"""
Forced-alignment template.

HOW TO USE:
1. Copy this file into your video's working directory (next to audio/vo.mp3) as align.py.
2. Fill in LINES below with the exact script that was sent to ElevenLabs — one
   string per scene/chunk. This must match the audio word-for-word, punctuation
   included (periods matter: they're where the narrator naturally pauses).
3. Run it: `python3 align.py`. Read the "missing from dictionary" list it prints.
4. For each missing word, add a pronunciation to EXTRA (see the comment there
   for how to find one) and/or a token split to SPLIT if it's a hyphenated
   word or an acronym read letter-by-letter. Rerun until it aligns cleanly.

Output: words.json, containing every word with its exact spoken start/end time
(in seconds), grouped by chunk. Everything in render_template.py reads from
this file via the T() and boundary() helpers — this script only needs to be
run once per video, before scene design starts.

Requires: pip install pocketsphinx --break-system-packages
(pocketsphinx bundles its own acoustic model + dictionary, so this works
fully offline — no model download needed, unlike most other STT options.)
"""
import re, json, os, subprocess
from pocketsphinx import Decoder

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# --- FILL IN: the exact script, one string per scene -----------------------
LINES = ["Grey hair isn't grey.",
 "It's see-through.",
 'Every hair starts out clear, like fishing line.',
 'The color gets injected from the root.',
 'Deep in each follicle, pigment cells pump melanin into the hair while it grows.',
 'When those cells quit, the hair grows in empty.',
 'Tiny air pockets scatter light, and clear looks white.',
 'Pull one out and hold it up to a lamp.',
 "But here's the insane part.",
 "Stress really can turn you grey, and it isn't stress hormones.",
 'In 2020, Harvard scientists stressed out mice with pain, confinement and chaos.',
 'Within weeks, their black fur grew in white.',
 'The culprit?',
 'The fight or flight nerves wrapped around every single follicle.',
 'Under stress, they flood it with noradrenaline.',
 'The pigment stem cells all panic, wake up at once, and burn through the entire reserve.',
 'In those mice, the cells never came back.',
 'And it gets weirder.',
 "The hair on your head is already dead, so it can't go white overnight.",
 "But in 2021, Columbia researchers mapped single human hairs and found grey strands that went dark again, lining up with calmer stretches in people's lives.",
 'Not everyone, not every hair.',
 'But your grey might be negotiable.',
 'So next time you find one in the mirror, remember.']

def norm(w):
    w = w.lower().replace("\u2019", "'")
    return re.sub(r"[^a-z0-9'\-]", "", w)

orig = []
for ci, line in enumerate(LINES):
    for wi, w in enumerate(line.split()):
        orig.append({"chunk": ci, "i": wi, "text": w, "n": norm(w)})

# --- FILL IN: hyphenated/compound words or acronyms that need splitting
# into separate alignment tokens. Key = the normalized word (norm() applied:
# lowercase, punctuation stripped, hyphens kept). Value = the tokens to align
# against instead. Timing is automatically merged back onto the ONE original
# word afterward (first token's start, last token's end) — you don't need to
# do anything else with these.
#   "potassium-forty": ["potassium", "forty"]
#   "gps": ["g", "p", "s"]                 # acronym read letter-by-letter
#   "x-ray": ["x", "ray"]
SPLIT = {"2020":["twenty","twenty"],"2021":["twenty","twenty","one"]}
tokens = []  # (index into `orig`, token)
for oi, o in enumerate(orig):
    parts = SPLIT.get(o["n"], [p for p in o["n"].split("-") if p])
    for p in parts:
        tokens.append((oi, p))

# --- FILL IN: pronunciations for words the first run reports as missing.
# Format: space-separated ARPAbet phonemes, NO stress digits. To find the
# right phonemes for a new word, look up a similar-sounding real word first —
# e.g. dec.lookup_word("seconds") returns "S EH K AH N D Z"; copy that pattern
# for a new word like "nanosieverts" -> "N AE N OW S IY V ER T S". A handful
# of technical words that have come up before: nanosieverts, isotope,
# potassium, radioactive, excretes, uncorrected, microseconds, nanosecond.
EXTRA = {"noradrenaline": "N AO R AH D R EH N AH L IH N",
    # "nanosieverts": "N AE N OW S IY V ER T S",
}

subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "audio/vo.mp3", "-ar", "16000", "-ac", "1",
                "-f", "s16le", "audio/vo16k.raw"], check=True)
raw = open("audio/vo16k.raw", "rb").read()

dec = Decoder(samprate=16000, loglevel="FATAL")
missing = sorted({tok for _, tok in tokens if dec.lookup_word(tok) is None})
print("missing from dictionary:", missing)
for w in missing:
    if w in EXTRA:
        dec.add_word(w, EXTRA[w], True)
    else:
        raise SystemExit(f"No pronunciation for {w!r} yet -- add it to EXTRA and rerun.")

dec.set_align_text(" ".join(tok for _, tok in tokens))
dec.start_utt()
dec.process_raw(raw, full_utt=True)
dec.end_utt()

segs = []
for s in dec.seg():
    w = re.sub(r"\(\d+\)$", "", s.word)
    if w in ("<s>", "</s>", "<sil>", "[NOISE]", "(NULL)") or w.startswith("+"):
        continue
    segs.append((w, s.start_frame / 100.0, (s.end_frame + 1) / 100.0))

print("aligned tokens:", len(segs), "expected:", len(tokens))
assert len(segs) == len(tokens), "alignment token count mismatch -- check SPLIT/EXTRA above"

words = [dict(o) for o in orig]
for (oi, tok), (w, s, e) in zip(tokens, segs):
    assert w == tok, (w, tok)
    words[oi].setdefault("s", s)   # first token's start
    words[oi]["e"] = e             # last token's end (overwritten each time, ends up correct)

json.dump({"words": words, "lines": LINES}, open("words.json", "w"), indent=1)

# Sanity printout: one line per chunk so you can eyeball that durations look
# plausible (roughly proportional to word count) before moving on to scene design.
for ci in range(len(LINES)):
    cw = [w for w in words if w["chunk"] == ci]
    print(f"chunk {ci:2d}: {cw[0]['s']:6.2f} -> {cw[-1]['e']:6.2f}   {LINES[ci][:60]}")
