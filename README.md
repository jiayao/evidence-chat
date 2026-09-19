# evidence-chat

Chat with one or many sources — podcast episodes as well as other large files such
as earnings releases, filings, or manuals — from timestamped transcripts or
markdown documents.

Compiles a focused evidence packet with episode-and-timestamp or
section-and-line citations before answering. Use when you want to ask questions about a podcast, compare episodes or guests, synthesize themes across a show, find where something was said, interrogate a large report, or create a cited listening/reading guide.

## Layout

- `SKILL.md` – skill instructions (frontmatter `name: evidence-chat`)
- `scripts/evidence.py` – `inspect`, `index`, `compile` evidence pipeline
- `references/manifest.md` – library manifest format (`episodes`, `documents`, `sources`)
- `agents/openai.yaml` – agent interface metadata

## Requirements

- Python 3.9+
- `TYPESAFE_API_KEY` for Jev evidence judgments
- Local `.txt`, `.srt`, `.vtt`, or `.md` sources (prefer timestamped transcripts;
  markdown uses section-and-line locators)

## Quick start

```bash
python scripts/evidence.py inspect --transcript episode.txt
python scripts/evidence.py inspect --file nvda-latest-earnings.md

python scripts/evidence.py index \
  --manifest evidence-library.json \
  --out .evidence-chat/library.json

python scripts/evidence.py compile \
  --library .evidence-chat/library.json \
  --question "Why did this product break through?" \
  --obligation "What made the product experience different?" \
  --query "underlying model harness UX product breakthrough"
```

See `SKILL.md` for full usage and `references/manifest.md` for manifest format.

## License

MIT – see `LICENSE`.
