import json

import pytest

from transcriptfix.core import (
    Transcript,
    chapters,
    clean,
    clock,
    detect_format,
    keywords,
    load,
    parse_plain,
    parse_srt,
    parse_vtt,
    parse_whisper,
    render_markdown,
)

SRT = """1
00:00:01,000 --> 00:00:04,000
Um, welcome to the show.

2
00:00:04,000 --> 00:00:06,500
Today we talk about, uh, tokenizers.

3
00:00:06,500 --> 00:00:09,000
Speaker 1: Sounds good.

4
00:00:09,000 --> 00:00:10,000
Sounds good.
"""

VTT = """WEBVTT

NOTE recorded on a laptop

00:00:01.000 --> 00:00:03.000
<v Ada>Hello there.

00:00:03.000 --> 00:00:04.500
Second line.
"""


def test_parse_srt_reads_timestamps_and_text():
    cues = parse_srt(SRT)
    assert len(cues) == 4
    assert cues[0].start == 1.0 and cues[0].end == 4.0
    assert cues[2].start == 6.5
    assert "welcome to the show" in cues[0].text


def test_parse_vtt_skips_headers_and_tags():
    cues = parse_vtt(VTT)
    assert len(cues) == 2
    assert cues[0].text == "Hello there."
    assert cues[1].start == 3.0


def test_parse_whisper_segments_and_plain_lines():
    payload = json.dumps(
        {"text": "full text", "segments": [{"start": 0, "end": 1.5, "text": " hi there", "speaker": "Ada"}]}
    )
    cues = parse_whisper(payload)
    assert len(cues) == 1 and cues[0].speaker == "Ada" and cues[0].end == 1.5
    assert parse_whisper(json.dumps({"text": "only text"}))[0].text == "only text"
    assert len(parse_plain("one\n\ntwo\n")) == 2


def test_clean_removes_fillers_tags_and_duplicates():
    cues, paragraphs = clean(parse_srt(SRT))
    assert len(cues) == 3  # the repeated final cue is merged away
    joined = " ".join(cue.text for cue in cues)
    assert "um," not in joined.lower() and " uh," not in joined.lower()
    assert cues[0].text.startswith("welcome")
    assert paragraphs[0].speaker == ""
    assert paragraphs[-1].speaker == "Speaker 1"
    assert len(paragraphs) == 2


def test_clean_handles_annotations_and_html():
    cues = parse_plain("[Music] the point is <i>simple</i>\n(music) still here\n")
    cleaned, _ = clean(cues)
    assert "Music" not in cleaned[0].text
    assert "<i>" not in cleaned[1].text
    kept, _ = clean(cues, keep_annotations=True, remove_fillers=False)
    assert "Music" in kept[0].text


def test_speaker_change_starts_a_new_paragraph():
    cues = parse_plain("Ada: we should ship\nBob: not yet\nBob: one more test\n")
    _, paragraphs = clean(cues)
    assert [paragraph.speaker for paragraph in paragraphs] == ["Ada", "Bob"]
    assert paragraphs[1].text == "not yet one more test"


def test_chapters_split_by_elapsed_time():
    cues = parse_plain("first section about tokenizers\nsecond section about caching\nthird section about billing\n")
    cues[0].start, cues[0].end = 0.0, 5.0
    cues[1].start, cues[1].end = 400.0, 405.0
    cues[2].start, cues[2].end = 800.0, 805.0
    _, paragraphs = clean(cues, merge_gap=0)
    sections = chapters(paragraphs, every=300.0)
    assert len(sections) == 3
    assert sections[0][1].startswith("first section")
    assert sections[1][0] == 400.0


def test_keywords_ignore_stopwords_and_singletons():
    cues = parse_plain("tokenizers are fast\ntokenizers are small\nthe tokenizers win\nzebra\n")
    _, paragraphs = clean(cues, merge_gap=0)
    terms = keywords(paragraphs)
    assert terms[0] == "tokenizers"
    assert "zebra" not in terms and "the" not in terms


def test_render_markdown_contains_metadata_and_timestamps():
    transcript = Transcript(parse_srt(SRT), source="talk.srt", title="Talk")
    cues, paragraphs = clean(transcript.cues)
    transcript.cues = cues
    page = render_markdown(transcript, paragraphs, chapter_every=60.0)
    assert page.startswith("# Talk")
    assert "source `talk.srt`" in page
    assert "| 00:00:10" in page.replace("00:00:10", "00:00:10")
    assert "## [00:00:00]" in page
    assert "**Speaker 1:**" in page
    assert page.endswith("\n")


def test_detect_format_and_load(tmp_path):
    assert detect_format(SRT) == "srt"
    assert detect_format(VTT) == "vtt"
    assert detect_format(json.dumps({"text": "x"})) == "json"
    assert detect_format("plain words") == "txt"
    path = tmp_path / "weekly_call.vtt"
    path.write_text(VTT, encoding="utf-8")
    transcript = load(path)
    assert transcript.source == "weekly_call.vtt"
    assert transcript.title == "weekly call"
    assert load(path, fmt="txt").cues
    with pytest.raises(ValueError):
        load(path, fmt="docx")


def test_duration_speakers_and_clock():
    transcript = Transcript(parse_srt(SRT), source="a.srt")
    transcript.cues, _ = clean(transcript.cues)
    assert round(transcript.duration, 2) == 10.0
    assert transcript.speakers == ["Speaker 1"]
    assert transcript.to_dict()["cues"][0]["start"] == 1.0
    assert clock(3661) == "01:01:01"
    assert clock(0) == "00:00:00"
