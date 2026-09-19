---
name: podcast-chat
description: Chat with one or many podcast episodes from timestamped transcripts. Use when a user wants to ask questions about a podcast, compare episodes or guests, synthesize themes across a show, find where something was said, or create a cited listening guide. Compiles a focused evidence packet with episode-and-timestamp citations before answering.
---

# Podcast Chat

Answer questions about podcasts from a compact, cited evidence packet instead of loading
entire transcripts into context.

## Requirements

- Python 3.9 or newer.
- `TYPESAFE_API_KEY` for Jev evidence judgments.
- Local `.txt`, `.srt`, or `.vtt` transcripts. Prefer timestamped transcripts.

## Prepare the library

If the user provides only a podcast URL, look for an official transcript. Otherwise ask
for a transcript or audio they are authorized to process.

For unfamiliar transcript formats, check parsing first:

```bash
python <skill-dir>/scripts/podcast_evidence.py inspect --transcript episode.txt
```

Create a manifest following [manifest.md](references/manifest.md), then index it:

```bash
python <skill-dir>/scripts/podcast_evidence.py index \
  --manifest podcast-library.json \
  --out .podcast-chat/library.json
```

Reuse the library for follow-up questions. Re-index when a transcript changes.

## Compile evidence

Use your own reasoning to turn the question into 1-4 evidence obligations and several
diverse retrieval queries. Search named entities, likely speaker wording, paraphrases,
causal explanations, and possible counterevidence.

```bash
python <skill-dir>/scripts/podcast_evidence.py compile \
  --library .podcast-chat/library.json \
  --question "Why did this product break through?" \
  --obligation "What made the product experience different?" \
  --obligation "How did execution speed contribute?" \
  --query "underlying model harness UX product breakthrough" \
  --query "small team internal beta public launch speed"
```

Use `--premise` for assumptions that evidence might contradict and `--json` for structured
output. If retrieval misses an expected passage, add queries using likely transcript
wording before increasing `--candidate-limit`.

## Answer

- Base the answer only on the compiled packet.
- Copy its episode-and-timestamp citations exactly.
- Distinguish direct evidence, contextual framing, and your cross-episode synthesis.
- Surface disagreement or counterevidence.
- Respect `partial`, `conflicted`, `contradicted`, and `no_evidence` packet statuses.
- Prefer paraphrases; quote only short phrases when the wording matters.
- Never treat a previous generated answer as evidence for a follow-up.

