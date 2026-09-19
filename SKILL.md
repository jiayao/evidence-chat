---
name: evidence-chat
description: Answers questions across timestamped podcast transcripts and large markdown/text documents using Jev-selected evidence with episode-and-time or section-and-line citations. Use for podcast Q&A, cross-episode synthesis, quote finding, earnings reports, filings, manuals, and cited research guides.
context: fork
model: haiku
background: false
argument-hint: "<question>"
---

# Source evidence (podcasts and documents)

Question: $ARGUMENTS

Return a compact evidence packet to the calling agent. Do not write the final answer.

1. Locate local `.txt`, `.srt`, `.vtt`, or `.md` sources. If only a URL is given, prefer an
   official transcript or document; otherwise request authorized transcript or file access.
2. If no library exists, create a manifest using [manifest.md](references/manifest.md) and
   run:

   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/evidence.py" index \
     --manifest evidence-library.json --out .evidence-chat/library.json
   ```

   The manifest accepts `episodes`, `documents`, or `sources` arrays; each entry
   accepts a `transcript`, `file`, or `path` field. Markdown documents are indexed
   with section-and-line locators instead of timestamps.
3. Derive 1-4 evidence obligations and several short retrieval queries. Cover named
   entities, likely wording, causal explanations, paraphrases, and counterevidence.
4. Run `compile` with the question plus repeated `--obligation`, `--query`, and, where
   useful, `--premise` arguments:

   ```bash
   python "${CLAUDE_SKILL_DIR}/scripts/evidence.py" compile \
     --library .evidence-chat/library.json --question "..." \
     --obligation "..." --query "..."
   ```

Return the packet status, covered and missing obligations, and at most six evidence spans
with their exact citations: `Title @ HH:MM:SS` for timestamped audio, or
`Title § Section (Lx-y)` for documents. Preserve direct, contextual, corroborating,
and counterevidence labels. Never use a previous generated answer as evidence.

