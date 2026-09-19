# Source library manifest

The manifest is a JSON object with one source array. Use `episodes` for podcasts,
or `documents` (or `sources`) for large files such as earnings releases, filings,
manuals, or reports. Every entry has:

| Field | Required | Meaning |
| --- | --- | --- |
| `title` | yes | Human-readable title used in citations |
| `transcript` / `file` / `path` | yes | `.txt`, `.srt`, `.vtt`, or `.md` path, relative to the manifest |
| `id` | no | Stable unique ID; generated from the title when omitted |
| `source_url` | no | Publisher, player, RSS item, video, or canonical document URL |

Example mixing podcasts and a document:

```json
{
  "episodes": [
    {
      "id": "anish-acharya-2",
      "title": "Anish Acharya 2.0",
      "transcript": "transcripts/Anish Acharya 2.0.txt",
      "source_url": "https://www.youtube.com/watch?v=example"
    }
  ],
  "documents": [
    {
      "id": "nvda-q2fy27",
      "title": "NVIDIA Q2 FY27 Earnings",
      "file": "nvda-latest-earnings.md",
      "source_url": "https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2027"
    }
  ]
}
```

Supported timestamp forms include SRT/VTT cue ranges and speaker-turn transcripts such as:

```text
Guest Name (00:12:34):
The transcript text starts here.
```

```text
[00:12:34] Guest Name: The transcript text starts here.
```

Markdown documents (`.md`) are split into section-aware blocks. ATX headings
(`#`–`######`) become the section breadcrumb, and every chunk records its
`section`, `line_start`, and `line_end`.

Citations:

- Timestamped audio: `[Anish Acharya 2.0 @00:12:34]`
- Document section: `[NVIDIA Q2 FY27 Earnings § Outlook (L60-66)]`
- Document lines only: `[Notes (L10-14)]`

YouTube citations get a `t=<seconds>` query parameter. Other source URLs link to the
episode or document page while retaining the locator in the citation label.

