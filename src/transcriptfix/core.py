"""Transcript parsing and cleanup.

Handles SRT, WebVTT, Whisper JSON and plain text, then removes the artefacts
that make raw captions unreadable: rolling duplicates, HTML tags, sound
annotations, filler words and one-line-per-cue breaks. Everything is offline.
"""

from __future__ import annotations

import html
import json
import pathlib
import re

TIMESTAMP = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})"
)
TAG = re.compile(r"<[^>]+>")
ANNOTATION = re.compile(
    r"[\[(](?:[^\])]*?(?:music|laughs?|applause|inaudible|crosstalk|silence)[^\])]*?[\])]", re.IGNORECASE
)
FILLERS = re.compile(r"\b(?:um+|uh+|erm+|hmm+|mm+|mhm+)\b[,.]?", re.IGNORECASE)
SPEAKER_PREFIX = re.compile(
    r"^\s*(?:>>\s*)*(?P<name>(?:SPEAKER|Speaker|speaker)\s*\d+|[A-Z][A-Za-z0-9 .'-]{1,24}|\[[^\]]{1,24}\])\s*:\s*"
)
SENTENCE_END = re.compile(r"[.!?]\s*$")
STOPWORDS = set(
    "a about above after again against all am an and any are aren't as at be because been before being below "
    "between both but by can cannot could did do does doing down during each few for from further had has have "
    "having he her here hers herself him himself his how i if in into is it its itself just me more most my "
    "myself no nor not now of off on once only or other ought our ours ourselves out over own same she should "
    "so some such than that the their theirs them themselves then there these they this those through to too "
    "under until up very was we were what when where which while who whom why will with would you your yours "
    "yourself yourselves going get got also really thing things think know like okay yeah right want lot actually".split()
)


class Transcript:
    def __init__(self, cues, source="", title=""):
        self.cues = list(cues)
        self.source = source
        self.title = title

    @property
    def duration(self):
        return self.cues[-1].end if self.cues else 0.0

    @property
    def speakers(self):
        return sorted({cue.speaker for cue in self.cues if cue.speaker})

    @property
    def words(self):
        return sum(len(cue.text.split()) for cue in self.cues)

    def to_dict(self):
        return {
            "source": self.source,
            "title": self.title,
            "duration": round(self.duration, 2),
            "speakers": self.speakers,
            "cues": [
                {"start": round(cue.start, 2), "end": round(cue.end, 2), "text": cue.text, "speaker": cue.speaker}
                for cue in self.cues
            ],
        }


class Cue:
    __slots__ = ("start", "end", "text", "speaker")

    def __init__(self, start, end, text, speaker=""):
        self.start = float(start)
        self.end = float(end)
        self.text = text
        self.speaker = speaker

    def __repr__(self):
        return "Cue({:.2f}, {:.2f}, {!r}, {!r})".format(self.start, self.end, self.text[:30], self.speaker)


class Paragraph:
    __slots__ = ("start", "end", "speaker", "text")

    def __init__(self, start, end, speaker, text):
        self.start = start
        self.end = end
        self.speaker = speaker
        self.text = text

    def to_dict(self):
        return {"start": round(self.start, 2), "speaker": self.speaker, "text": self.text}


def parse_timestamp(text):
    parts = text.replace(",", ".").split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        hours, (minutes, seconds) = "0", parts
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_srt(text):
    cues = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        stamp_at = None
        match = None
        for index, line in enumerate(lines[:2]):
            match = TIMESTAMP.search(line)
            if match:
                stamp_at = index
                break
        if not match or stamp_at is None:
            continue
        body = " ".join(lines[stamp_at + 1 :])
        cues.append(Cue(parse_timestamp(match.group("start")), parse_timestamp(match.group("end")), body.strip()))
    return cues


def parse_vtt(text):
    cues = []
    current = None

    def flush():
        nonlocal current
        if current is not None and current[2]:
            cues.append(Cue(current[0], current[1], " ".join(current[2]).strip()))
        current = None

    for line in text.replace("\r\n", "\n").splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("WEBVTT") or stripped.upper().startswith("NOTE"):
            flush()
            continue
        if not stripped:
            flush()
            continue
        match = TIMESTAMP.search(line)
        if match:
            flush()
            current = [parse_timestamp(match.group("start")), parse_timestamp(match.group("end")), []]
            continue
        if current is None or stripped.isdigit():
            continue
        current[2].append(stripped)
    flush()
    return cues


def parse_whisper(text):
    data = json.loads(text)
    cues = []
    for segment in data.get("segments") or []:
        cues.append(
            Cue(
                segment.get("start", 0.0),
                segment.get("end", 0.0),
                str(segment.get("text", "")).strip(),
                str(segment.get("speaker", "") or "").strip(),
            )
        )
    if not cues and data.get("text"):
        cues.append(Cue(0.0, 0.0, str(data["text"]).strip()))
    return cues


def parse_plain(text):
    return [Cue(0.0, 0.0, line.strip()) for line in text.splitlines() if line.strip()]


def detect_format(text, name=""):
    suffix = pathlib.Path(name).suffix.lower()
    stripped = text.lstrip()
    if suffix == ".vtt" or stripped.upper().startswith("WEBVTT"):
        return "vtt"
    if suffix == ".json" or stripped.startswith("{"):
        return "json"
    if suffix == ".srt" or "-->" in stripped[:2000]:
        return "srt"
    return "txt"


PARSERS = {"srt": parse_srt, "vtt": parse_vtt, "json": parse_whisper, "txt": parse_plain}


def load(path, fmt=None):
    path = pathlib.Path(path)
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    fmt = fmt or detect_format(text, path.name)
    if fmt not in PARSERS:
        raise ValueError("unknown format {!r}; use srt, vtt, json or txt".format(fmt))
    return Transcript(PARSERS[fmt](text), source=path.name, title=path.stem.replace("_", " ").replace("-", " "))


def _strip_speaker(text):
    match = SPEAKER_PREFIX.match(text)
    if not match:
        return "", text
    name = match.group("name").strip("[]").strip()
    return name, text[match.end() :].strip()


def clean(cues, remove_fillers=True, keep_annotations=False, merge_gap=2.5, dedupe=True):
    """Normalise cue text, drop rolling duplicates, then group cues into paragraphs."""
    prepared = []
    for cue in cues:
        text = html.unescape(TAG.sub(" ", cue.text or "")).replace("\u200b", " ")
        text = re.sub(r"\s+", " ", text).strip()
        speaker, text = _strip_speaker(text)
        speaker = cue.speaker or speaker
        if not keep_annotations:
            text = ANNOTATION.sub(" ", text)
        if remove_fillers:
            text = FILLERS.sub("", text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        prepared.append(Cue(cue.start, cue.end, text, speaker))

    if dedupe:
        merged = []
        for cue in prepared:
            if merged:
                previous = merged[-1]
                if cue.text == previous.text:
                    previous.end = max(previous.end, cue.end)
                    previous.speaker = previous.speaker or cue.speaker
                    continue
                if previous.text.endswith(cue.text) and len(cue.text) > 12:
                    previous.end = max(previous.end, cue.end)
                    continue
                if cue.text.startswith(previous.text) and len(previous.text) > 12:
                    previous.text = cue.text
                    previous.end = max(previous.end, cue.end)
                    continue
            merged.append(cue)
        prepared = merged

    paragraphs = []
    for cue in prepared:
        if paragraphs:
            current = paragraphs[-1]
            # An unlabelled cue never inherits or steals a speaker: only identical
            # speaker labels may continue a paragraph.
            same_speaker = current.speaker == cue.speaker
            close_enough = cue.start - current.end <= merge_gap
            if same_speaker and close_enough and not SENTENCE_END.search(current.text + " "):
                current.text = (current.text + " " + cue.text).strip()
                current.end = cue.end
                continue
            if same_speaker and close_enough and len(current.text.split()) < 12:
                current.text = (current.text + " " + cue.text).strip()
                current.end = cue.end
                continue
        paragraphs.append(Paragraph(cue.start, cue.end, cue.speaker, cue.text))
    return prepared, paragraphs


def keywords(paragraphs, limit=12):
    counts = {}
    for paragraph in paragraphs:
        for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", paragraph.text.lower()):
            if word in STOPWORDS or len(word) < 4:
                continue
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [word for word, count in ranked[:limit] if count > 1]


def chapters(paragraphs, every=300.0):
    """Group paragraphs into sections by elapsed time, titled from their first words."""
    groups = []
    current = []
    start = None
    for paragraph in paragraphs:
        if start is None:
            start = paragraph.start
            current = [paragraph]
            continue
        if paragraph.start - start >= every:
            groups.append((start, current))
            start = paragraph.start
            current = [paragraph]
        else:
            current.append(paragraph)
    if current:
        groups.append((start or 0.0, current))
    result = []
    for start, items in groups:
        title = " ".join(items[0].text.split()[:7]).rstrip(",.;:!?") or "Section"
        if len(title) > 58:
            title = title[:55].rstrip() + "..."
        result.append((start, title, items))
    return result


def clock(seconds):
    seconds = int(round(seconds))
    return "{:02d}:{:02d}:{:02d}".format(seconds // 3600, (seconds % 3600) // 60, seconds % 60)


def render_markdown(transcript, paragraphs, title=None, chapter_every=300.0, timestamps=True, keyword_limit=12):
    lines = ["# {}".format(title or transcript.title or "Transcript"), ""]
    meta = ["source `{}`".format(transcript.source or "stdin")]
    if transcript.duration:
        meta.append(clock(transcript.duration))
    meta.append("{} words".format(transcript.words))
    meta.append("~{:.0f} min read".format(transcript.words / 200.0))
    if transcript.speakers:
        meta.append("{} speaker(s)".format(len(transcript.speakers)))
    lines.append("> {}".format(" | ".join(meta)))
    lines.append("")

    terms = keywords(paragraphs, limit=keyword_limit)
    if terms:
        lines.append("**Keywords:** {}".format(", ".join(terms)))
        lines.append("")

    for start, heading, items in chapters(paragraphs, every=chapter_every):
        lines.append("## {}".format("[{}] {}".format(clock(start), heading) if timestamps else heading))
        lines.append("")
        for paragraph in items:
            if paragraph.speaker:
                prefix = "**{}:** ".format(paragraph.speaker)
            elif timestamps:
                prefix = "`[{}]` ".format(clock(paragraph.start))
            else:
                prefix = ""
            lines.append("{}{}".format(prefix, paragraph.text))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
