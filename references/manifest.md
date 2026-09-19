# Podcast library manifest

The manifest is a JSON object with one `episodes` array. Every episode has:

| Field | Required | Meaning |
| --- | --- | --- |
| `title` | yes | Human-readable title used in citations |
| `transcript` | yes | `.txt`, `.srt`, or `.vtt` path, relative to the manifest |
| `id` | no | Stable unique ID; generated from the title when omitted |
| `source_url` | no | Publisher, player, RSS item, or video URL |

Example:

```json
{
  "episodes": [
    {
      "id": "anish-acharya-2",
      "title": "Anish Acharya 2.0",
      "transcript": "transcripts/Anish Acharya 2.0.txt",
      "source_url": "https://www.youtube.com/watch?v=example"
    },
    {
      "id": "roman-ugarte",
      "title": "Roman Ugarte",
      "transcript": "transcripts/Roman Ugarte.vtt",
      "source_url": "https://publisher.example/roman-ugarte"
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

YouTube citations get a `t=<seconds>` query parameter. Other source URLs link to the
episode page while retaining the timestamp in the citation label.

