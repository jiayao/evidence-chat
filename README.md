# podcast-chat

Chat with one or many podcast episodes from timestamped transcripts.

Compiles a focused evidence packet with episode-and-timestamp citations before answering. Use when you want to ask questions about a podcast, compare episodes or guests, synthesize themes across a show, find where something was said, or create a cited listening guide.

## Layout

- `SKILL.md` – skill instructions (frontmatter `name: podcast-chat`)
- `scripts/podcast_evidence.py` – `inspect`, `index`, `compile` evidence pipeline
- `references/manifest.md` – library manifest format
- `agents/openai.yaml` – agent interface metadata

## Requirements

- Python 3.9+
- `TYPESAFE_API_KEY` for Jev evidence judgments
- Local `.txt`, `.srt`, or `.vtt` transcripts (prefer timestamped)

## Quick start

```bash
python scripts/podcast_evidence.py inspect --transcript episode.txt

python scripts/podcast_evidence.py index \
  --manifest podcast-library.json \
  --out .podcast-chat/library.json

python scripts/podcast_evidence.py compile \
  --library .podcast-chat/library.json \
  --question "Why did this product break through?" \
  --obligation "What made the product experience different?" \
  --query "underlying model harness UX product breakthrough"
```

See `SKILL.md` for full usage and `references/manifest.md` for manifest format.

## License

MIT – see `LICENSE`.
