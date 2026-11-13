"""The ``transcriptfix`` command line."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from . import __version__
from .core import chapters, clean, clock, keywords, load, render_markdown


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="transcriptfix",
        description="Turn SRT, VTT or Whisper transcripts into clean, readable notes.",
    )
    parser.add_argument("input", help="transcript file, or - for stdin")
    parser.add_argument("-o", "--output", help="write markdown here (default: stdout)")
    parser.add_argument("--format", choices=["auto", "srt", "vtt", "json", "txt"], default="auto")
    parser.add_argument("--title", help="override the title")
    parser.add_argument("--chapter-every", type=float, default=300.0, help="seconds per chapter (default: 300)")
    parser.add_argument("--keep-timestamps", action="store_true", help="keep inline timestamps")
    parser.add_argument("--keep-fillers", action="store_true", help="keep um/uh/hmm")
    parser.add_argument("--keep-annotations", action="store_true", help="keep [music] and (laughs)")
    parser.add_argument("--no-dedupe", action="store_true", help="do not merge rolling duplicate captions")
    parser.add_argument("--json", action="store_true", help="print structured output instead of markdown")
    parser.add_argument("--version", action="version", version="transcriptfix {}".format(__version__))
    args = parser.parse_args(argv)

    if args.input == "-":
        text = sys.stdin.read()
        from .core import Transcript, detect_format, parse_plain, parse_srt, parse_vtt, parse_whisper

        fmt = args.format if args.format != "auto" else detect_format(text)
        parsers = {"srt": parse_srt, "vtt": parse_vtt, "json": parse_whisper, "txt": parse_plain}
        transcript = Transcript(parsers[fmt](text), source="stdin", title=args.title or "Transcript")
    else:
        try:
            transcript = load(args.input, fmt=None if args.format == "auto" else args.format)
        except (OSError, ValueError) as exc:
            print("transcriptfix: {}".format(exc), file=sys.stderr)
            return 2
        if args.title:
            transcript.title = args.title

    cues, paragraphs = clean(
        transcript.cues,
        remove_fillers=not args.keep_fillers,
        keep_annotations=args.keep_annotations,
        dedupe=not args.no_dedupe,
    )
    if not paragraphs:
        print("transcriptfix: no speech found in that file", file=sys.stderr)
        return 2

    if args.json:
        payload = transcript.to_dict()
        payload["paragraphs"] = [paragraph.to_dict() for paragraph in paragraphs]
        payload["keywords"] = keywords(paragraphs)
        payload["chapters"] = [
            {"start": round(start, 2), "time": clock(start), "title": title}
            for start, title, _items in chapters(paragraphs, every=args.chapter_every)
        ]
        print(json.dumps(payload, indent=2))
        return 0

    markdown = render_markdown(
        transcript,
        paragraphs,
        title=args.title,
        chapter_every=args.chapter_every,
        timestamps=args.keep_timestamps,
    )
    if args.output:
        pathlib.Path(args.output).write_text(markdown, encoding="utf-8")
        print(
            "wrote {}: {} paragraph(s), {} words".format(args.output, len(paragraphs), transcript.words),
            file=sys.stderr,
        )
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
