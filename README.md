# transcriptfix

**Turn a raw transcript into something you would actually read.**

Auto-generated captions are exhausting: every cue starts a new line, filler words everywhere, the same sentence repeated three times because the captions roll, `[Music]` in the middle of a paragraph, and no paragraphs at all. `transcriptfix` reads SRT, WebVTT, Whisper JSON or plain text and gives you clean Markdown with paragraphs, speakers, chapters, keywords and timestamps.

```bash
pip install -e .
transcriptfix lecture.vtt -o lecture.md
```

## Before and after

Input (`lecture.srt`):

```
1
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
```

Output (`transcriptfix lecture.srt`):

```markdown
# lecture

> source `lecture.srt` | 00:00:10 | 11 words | ~0 min read | 1 speaker(s)

## [00:00:01] welcome to the show. Today we talk

`[00:00:01]` welcome to the show. Today we talk about, tokenizers.

**Speaker 1:** Sounds good.
```

Fillers are gone, the rolling duplicate is merged, the speaker label became a speaker, cues became paragraphs, and the section has a heading you can skim.

## What it handles

| Noise | What happens |
| --- | --- |
| One line per cue | Merged into paragraphs by speaker and time gap |
| Rolling captions (`Sounds good.` twice) | Duplicate and overlapping cues are collapsed |
| `um`, `uh`, `hmm`, `erm` | Removed, `--keep-fillers` to keep them |
| `<v Ada>`, `<i>`, `&amp;` | Tags stripped, entities decoded |
| `[Music]`, `(laughs)`, `[inaudible]` | Removed, `--keep-annotations` to keep them |
| `Speaker 1:` / `Ada:` prefixes | Promoted to a speaker, new paragraph for each change |

## Formats

The format is detected from the file name and contents; `--format` forces one.

- **SRT**: the usual `.srt` from YouTube, Zoom or a captioning service.
- **WebVTT**: `.vtt`, including `WEBVTT` headers, `NOTE` comments and `<v Ada>` voice tags.
- **Whisper JSON**: `{"segments": [{"start", "end", "text", "speaker"}]}` or a plain `{"text": ...}`.
- **Plain text**: one cue per line, no timing.

Anything unrecognised is treated as plain text, so a pasted transcript still works. Use `-` to read from stdin.

## Options

```
transcriptfix INPUT [-o OUT.md] [--format auto|srt|vtt|json|txt]
                    [--title TITLE] [--chapter-every SECONDS]
                    [--keep-timestamps] [--keep-fillers]
                    [--keep-annotations] [--no-dedupe] [--json]
```

- `--chapter-every` (default `300`) sets how often a new section heading appears. Each heading takes its title from the first words spoken after it.
- `--keep-timestamps` puts a `[hh:mm:ss]` marker on every paragraph instead of only on headings.
- `--json` prints cues, paragraphs, keywords and chapters as structured data, which is what you want if a script is going to consume it.

## Using it from Python

```python
from transcriptfix.core import clean, chapters, keywords, load, render_markdown

transcript = load("meeting.vtt")
cues, paragraphs = clean(transcript.cues)
print(len(paragraphs), "paragraphs for", transcript.speakers)
print(keywords(paragraphs))
print(render_markdown(transcript, paragraphs))
```

`clean()` returns both the cleaned cues (for JSON) and the merged paragraphs (for reading).

## Limits

- No speaker diarisation: it only reads speaker labels that already exist.
- Chapter boundaries follow the clock, not the content, so a long tangent can own a heading.
- No translation and no audio handling; this is a text tool.

## Tests

```bash
python -m pytest
```

Covered: SRT/VTT/Whisper/plain parsing, voice tags and `NOTE` blocks, filler and annotation removal, rolling-duplicate collapsing, speaker changes starting new paragraphs, chapter splitting, keyword filtering, Markdown rendering and format detection.

MIT licensed.
