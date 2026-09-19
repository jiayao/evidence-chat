---
name: podcast-chat
description: Answers questions across timestamped podcast transcripts using Jev-selected evidence with episode-and-time citations. Use for podcast Q&A, cross-episode synthesis, quote finding, and cited listening guides.
context: fork
model: haiku
background: false
argument-hint: "<question>"
---

# Podcast evidence

Question: $ARGUMENTS

Return a compact evidence packet to the calling agent. Do not write the final answer.

1. Locate local `.txt`, `.srt`, or `.vtt` transcripts. If only a URL is given, prefer an
   official transcript; otherwise request authorized transcript or audio access.
2. If no library exists, create a manifest using [manifest.md](references/manifest.md) and
   run:

   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/podcast_evidence.py" index \
     --manifest podcast-library.json --out .podcast-chat/library.json
   ```

3. Derive 1-4 evidence obligations and several short retrieval queries. Cover named
   entities, likely wording, causal explanations, paraphrases, and counterevidence.
4. Run `compile` with the question plus repeated `--obligation`, `--query`, and, where
   useful, `--premise` arguments:

   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/podcast_evidence.py" compile \
     --library .podcast-chat/library.json --question "..." \
     --obligation "..." --query "..."
   ```

Return the packet status, covered and missing obligations, and at most six evidence spans
with their exact episode-and-time citations. Preserve direct, contextual, corroborating,
and counterevidence labels. Never use a previous generated answer as evidence.

