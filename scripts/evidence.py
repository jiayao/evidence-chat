#!/usr/bin/env python3
"""Index transcripts and large documents, then compile cited evidence packets with Jev."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


TYPESAFE_ENDPOINT = os.getenv(
    "TYPESAFE_ENDPOINT", "https://api.typesafe.ai/v1/systemone"
)
DEFAULT_TYPESAFE_MODEL = "jev-latest"
LIBRARY_VERSION = 1

SPEAKER_TIME_RE = re.compile(
    r"^(?P<speaker>.*?)\s*\((?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\):\s*(?P<text>.*)$"
)
BRACKET_TIME_RE = re.compile(
    r"^\[(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\]\s*(?P<text>.*)$"
)
LEADING_TIME_RE = re.compile(
    r"^(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s+(?P<text>\S.*)$"
)
RANGE_TIME_RE = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?)"
)
TOKEN_RE = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown"}


class EvidenceChatError(RuntimeError):
    pass


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def require_typesafe_key() -> str:
    value = os.getenv("TYPESAFE_API_KEY", "").strip()
    if not value:
        raise EvidenceChatError("TYPESAFE_API_KEY is not set")
    return value


def post_typesafe(payload: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    retryable = {408, 409, 429, 500, 502, 503, 504, 529}
    delay = 0.75
    for attempt in range(4):
        request = Request(
            TYPESAFE_ENDPOINT,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {require_typesafe_key()}",
                "Content-Type": "application/json",
                "User-Agent": "evidence-chat-skill/0.1",
            },
        )
        try:
            with urlopen(request, timeout=120) as response:
                parsed = json.loads(response.read().decode("utf-8"))
                answers = parsed.get("answers")
                if not isinstance(answers, dict):
                    raise EvidenceChatError("TypeSafe response is missing answers")
                usage = parsed.get("usage", {})
                return answers, {
                    "input_tokens": int(usage.get("input_tokens", 0) or 0),
                    "output_tokens": int(usage.get("output_tokens", 0) or 0),
                }
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            if exc.code not in retryable or attempt == 3:
                raise EvidenceChatError(f"TypeSafe HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 3:
                raise EvidenceChatError(f"TypeSafe request failed: {exc}") from exc
        time.sleep(delay)
        delay *= 2
    raise AssertionError("retry loop exited unexpectedly")


def timestamp_seconds(value: str) -> float:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"Unsupported timestamp: {value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def format_timestamp(seconds: Optional[float]) -> str:
    if seconds is None:
        return "no timestamp"
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def normalize_space(text: str) -> str:
    return " ".join(text.split())


def split_speaker(text: str) -> Tuple[str, str]:
    head, separator, tail = text.partition(":")
    if separator and 0 < len(head.split()) <= 8 and len(head) <= 80:
        return head.strip(), tail.strip()
    return "", text.strip()


def parse_timestamped_source(text: str) -> List[Dict[str, Any]]:
    cues: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            body = normalize_space(" ".join(current.pop("lines", [])))
            if body:
                current["text"] = body
                cues.append(current)
        current = None

    for raw_line in text.replace("\ufeff", "").splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or line.isdigit():
            continue
        match = RANGE_TIME_RE.match(line)
        if match:
            flush()
            current = {
                "start": timestamp_seconds(match.group("start")),
                "end": timestamp_seconds(match.group("end")),
                "speaker": "",
                "lines": [],
            }
            continue
        match = SPEAKER_TIME_RE.match(line)
        if match:
            flush()
            current = {
                "start": timestamp_seconds(match.group("time")),
                "end": None,
                "speaker": match.group("speaker").strip(),
                "lines": [match.group("text")],
            }
            continue
        match = BRACKET_TIME_RE.match(line) or LEADING_TIME_RE.match(line)
        if match:
            flush()
            speaker, body = split_speaker(match.group("text"))
            current = {
                "start": timestamp_seconds(match.group("time")),
                "end": None,
                "speaker": speaker,
                "lines": [body],
            }
            continue
        if current is not None:
            current["lines"].append(line)
    flush()
    for index, cue in enumerate(cues[:-1]):
        if cue.get("end") is None:
            cue["end"] = cues[index + 1]["start"]
    return cues


def parse_markdown_document(text: str) -> List[Dict[str, Any]]:
    """Split a markdown/text document into section-aware blocks with line numbers."""
    section_stack: List[Tuple[int, str]] = []
    cues: List[Dict[str, Any]] = []
    block_lines: List[str] = []
    block_start = 0

    def current_section() -> str:
        return " / ".join(title for _, title in section_stack)

    def flush(end_line: int) -> None:
        nonlocal block_lines, block_start
        body = normalize_space(" ".join(block_lines))
        if body:
            cues.append(
                {
                    "start": None,
                    "end": None,
                    "speaker": "",
                    "section": current_section(),
                    "line_start": block_start,
                    "line_end": end_line,
                    "text": body,
                }
            )
        block_lines = []

    lines = text.replace("\ufeff", "").splitlines()
    for lineno, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        heading = HEADING_RE.match(stripped)
        if heading:
            flush(lineno - 1)
            level = len(heading.group(1))
            title = normalize_space(heading.group(2))
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, title))
            block_start = lineno + 1
            continue
        if not stripped:
            flush(lineno - 1)
            block_start = lineno + 1
            continue
        if not block_lines:
            block_start = lineno
        block_lines.append(stripped)
    flush(len(lines))
    return [cue for cue in cues if cue["text"]]


def untimestamped_cues(text: str) -> List[Dict[str, Any]]:
    paragraphs = [normalize_space(part) for part in re.split(r"\n\s*\n", text) if part.strip()]
    cues: List[Dict[str, Any]] = []
    cursor = 1
    for paragraph in paragraphs:
        # Best-effort line span so plain-text sources still get locators.
        cues.append(
            {
                "start": None,
                "end": None,
                "speaker": "",
                "section": "",
                "line_start": cursor,
                "line_end": cursor,
                "text": paragraph,
            }
        )
        cursor += paragraph.count("\n") + 2
    return cues


def parse_source(path: Path) -> Tuple[List[Dict[str, Any]], bool]:
    text = path.read_text(encoding="utf-8", errors="replace")
    cues = parse_timestamped_source(text)
    if cues:
        for cue in cues:
            cue.setdefault("section", "")
            cue.setdefault("line_start", None)
            cue.setdefault("line_end", None)
        return cues, True
    if path.suffix.lower() in MARKDOWN_EXTENSIONS or HEADING_RE.search(text):
        return parse_markdown_document(text), False
    return untimestamped_cues(text), False


def cue_text(cue: Mapping[str, Any]) -> str:
    speaker = str(cue.get("speaker", "")).strip()
    text = str(cue.get("text", "")).strip()
    return f"{speaker}: {text}" if speaker else text


def chunk_cues(cues: Sequence[Mapping[str, Any]], target_words: int = 160) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    current: List[Mapping[str, Any]] = []
    words = 0

    def emit(items: Sequence[Mapping[str, Any]]) -> None:
        if items:
            section_label = ""
            for item in items:
                section = str(item.get("section", "") or "").strip()
                body_len = len(str(item.get("text", "")))
                if section and body_len > 40:
                    section_label = section
                    break
            if not section_label:
                for item in items:
                    section = str(item.get("section", "") or "").strip()
                    if section:
                        section_label = section
                        break
            line_starts = [
                item.get("line_start")
                for item in items
                if isinstance(item.get("line_start"), int)
            ]
            line_ends = [
                item.get("line_end")
                for item in items
                if isinstance(item.get("line_end"), int)
            ]
            body = "\n".join(cue_text(item) for item in items)
            if section_label:
                body = f"[{section_label}] {body}"
            chunks.append(
                {
                    "start": items[0].get("start"),
                    "end": items[-1].get("end"),
                    "section": section_label,
                    "line_start": min(line_starts) if line_starts else None,
                    "line_end": max(line_ends) if line_ends else None,
                    "text": body,
                }
            )

    for cue in cues:
        count = len(cue_text(cue).split())
        if current and words + count > target_words:
            emit(current)
            current = current[-1:] if len(current) > 1 else []
            words = sum(len(cue_text(item).split()) for item in current)
        current.append(cue)
        words += count
    emit(current)
    return chunks


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def tokenize(text: str) -> List[str]:
    return TOKEN_RE.findall(text.lower())


def load_manifest(path: Path) -> List[Dict[str, Any]]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    entries: List[Any] = []
    if isinstance(parsed, dict):
        for key in ("episodes", "documents", "sources"):
            value = parsed.get(key)
            if isinstance(value, list):
                entries.extend(value)
    if not entries:
        raise EvidenceChatError(
            "Manifest must contain a non-empty episodes, documents, or sources array"
        )
    base = path.resolve().parent
    result: List[Dict[str, Any]] = []
    seen = set()
    for raw in entries:
        if not isinstance(raw, dict) or not raw.get("title"):
            raise EvidenceChatError("Every entry needs a title field")
        source_file = raw.get("transcript", raw.get("file", raw.get("path")))
        if not source_file:
            raise EvidenceChatError(
                "Every entry needs a transcript/file/path field pointing to "
                ".txt, .srt, .vtt, or .md"
            )
        episode = dict(raw)
        episode["id"] = str(episode.get("id") or slug(str(episode["title"])))
        if episode["id"] in seen:
            raise EvidenceChatError(f"Duplicate entry id: {episode['id']}")
        seen.add(episode["id"])
        transcript = Path(str(source_file))
        episode["transcript_path"] = transcript if transcript.is_absolute() else base / transcript
        if not episode["transcript_path"].is_file():
            raise EvidenceChatError(f"Source file not found: {episode['transcript_path']}")
        result.append(episode)
    return result


def load_library(path: Path) -> Dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if parsed.get("version") != LIBRARY_VERSION:
        raise EvidenceChatError("Unsupported library version; rebuild the index")
    if not parsed.get("segments"):
        raise EvidenceChatError("Library has no source segments")
    return parsed


def bm25_rank(segments: Sequence[Mapping[str, Any]], query: str) -> List[Tuple[float, Mapping[str, Any]]]:
    query_terms = list(dict.fromkeys(tokenize(query)))
    if not query_terms:
        return []
    document_tokens = [tokenize(str(segment["text"])) for segment in segments]
    document_frequency = Counter()
    for tokens in document_tokens:
        document_frequency.update(set(tokens))
    average_length = sum(map(len, document_tokens)) / max(1, len(document_tokens))
    count = len(document_tokens)
    k1, b = 1.5, 0.75
    ranked: List[Tuple[float, Mapping[str, Any]]] = []
    for segment, tokens in zip(segments, document_tokens):
        frequencies = Counter(tokens)
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            df = document_frequency.get(term, 0)
            inverse_document_frequency = math.log(1.0 + (count - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1.0 - b + b * len(tokens) / max(1.0, average_length))
            score += inverse_document_frequency * frequency * (k1 + 1.0) / denominator
        if score > 0:
            ranked.append((score, segment))
    return sorted(ranked, key=lambda row: row[0], reverse=True)


def retrieve_candidates(
    library: Mapping[str, Any], queries: Sequence[str], candidate_limit: int
) -> List[Dict[str, Any]]:
    segments = list(library["segments"])
    best: Dict[str, Dict[str, Any]] = {}
    per_query = max(5, min(12, candidate_limit // max(1, len(queries)) + 5))
    for query_index, query in enumerate(queries):
        ranked = bm25_rank(segments, query)[:per_query]
        peak = ranked[0][0] if ranked else 1.0
        for score, segment in ranked:
            normalized = score / peak if peak else 0.0
            row = best.setdefault(
                str(segment["id"]),
                {**segment, "retrieval_score": normalized, "retrieved_for": []},
            )
            row["retrieval_score"] = max(float(row["retrieval_score"]), normalized)
            row["retrieved_for"].append(query_index)
    return sorted(
        best.values(),
        key=lambda row: (float(row["retrieval_score"]), len(row["retrieved_for"])),
        reverse=True,
    )[:candidate_limit]


def evidence_questions(candidate_count: int, obligation_count: int) -> Dict[str, Any]:
    questions: Dict[str, Any] = {}
    for candidate_index in range(candidate_count):
        ref = f"`candidates[{candidate_index}]`"
        for obligation_index in range(obligation_count):
            questions[f"support_{candidate_index}_{obligation_index}"] = {
                "type": "noul",
                "instructions": (
                    f"Does {ref} contain concrete source evidence that materially establishes "
                    f"`obligations[{obligation_index}]`, rather than merely sharing its topic?"
                ),
                "criteria": {
                    "true": "The source's words directly establish or substantially explain the obligation.",
                    "false": "The passage is irrelevant, topical-only, or too weak to establish the obligation.",
                },
            }
        questions[f"role_{candidate_index}"] = {
            "type": "choice",
            "instructions": f"What is the most useful evidence role of {ref} for `question`?",
            "criteria": {
                "direct": "Directly states a fact or causal explanation needed by the answer.",
                "corroborating": "Independently reinforces direct evidence or supplies an important detail.",
                "contextual": "Provides a useful conceptual frame but does not prove the central claim.",
                "counterevidence": "Disagrees with, limits, or contradicts a premise or likely answer.",
                "irrelevant": "Does not materially help answer the actual question.",
            },
        }
        questions[f"premise_conflict_{candidate_index}"] = {
            "type": "noul",
            "instructions": f"Does {ref} directly contradict a factual assumption in `premises`?",
            "criteria": {
                "true": "The source provides affirmative evidence that a premise is false or materially qualified.",
                "false": "No direct contradiction; missing information alone is not a contradiction.",
            },
        }
    return questions


def answer_probability(answer: Mapping[str, Any], option: str) -> float:
    probabilities = answer.get("probabilities", {})
    try:
        return float(probabilities.get(option, 0.0))
    except (TypeError, ValueError, AttributeError):
        return 0.0


def judge_candidates(
    question: str,
    obligations: Sequence[str],
    premises: Sequence[str],
    candidates: Sequence[Mapping[str, Any]],
    model: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    answers, usage = post_typesafe(
        {
            "model": model,
            "state": {
                "question": question,
                "obligations": list(obligations),
                "premises": list(premises),
                "candidates": [
                    {
                        "id": candidate["id"],
                        "source": candidate["episode_title"],
                        "locator": locator(candidate),
                        "section": str(candidate.get("section", "") or ""),
                        "passage": candidate["text"],
                    }
                    for candidate in candidates
                ],
            },
            "questions": evidence_questions(len(candidates), len(obligations)),
        }
    )
    judged: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        supports = [
            float(answers.get(f"support_{index}_{obligation_index}", {}).get("noul", 0.0))
            for obligation_index in range(len(obligations))
        ]
        role_answer = answers.get(f"role_{index}", {})
        role = str(role_answer.get("choice", "irrelevant"))
        role_strength = answer_probability(role_answer, role)
        conflict = float(answers.get(f"premise_conflict_{index}", {}).get("noul", 0.0))
        role_value = {
            "direct": 1.0,
            "corroborating": 0.85,
            "counterevidence": 0.9,
            "contextual": 0.55,
            "irrelevant": 0.0,
        }.get(role, 0.0)
        score = (
            0.57 * max(supports or [0.0])
            + 0.24 * role_value * role_strength
            + 0.09 * float(candidate["retrieval_score"])
            + 0.10 * conflict
        )
        judged.append(
            {
                **candidate,
                "supports": supports,
                "role": role,
                "role_probability": role_strength,
                "premise_conflict": conflict,
                "evidence_score": score,
            }
        )
    return judged, usage


def compile_packet(
    judged: Sequence[Mapping[str, Any]], obligation_count: int, max_items: int
) -> Tuple[List[Dict[str, Any]], List[bool]]:
    selected: List[Dict[str, Any]] = []
    selected_ids = set()
    coverage = [False] * obligation_count
    for obligation_index in range(obligation_count):
        ranked = sorted(
            judged,
            key=lambda row: (
                float(row["supports"][obligation_index]),
                float(row["evidence_score"]),
            ),
            reverse=True,
        )
        if ranked and float(ranked[0]["supports"][obligation_index]) >= 0.50:
            candidate = dict(ranked[0])
            if candidate["id"] not in selected_ids:
                selected.append(candidate)
                selected_ids.add(candidate["id"])
            coverage[obligation_index] = True
    for row in sorted(judged, key=lambda item: float(item["evidence_score"]), reverse=True):
        if len(selected) >= max_items:
            break
        if row["id"] in selected_ids:
            continue
        important_counter = (
            str(row["role"]) == "counterevidence"
            or float(row["premise_conflict"]) >= 0.58
        )
        if str(row["role"]) != "irrelevant" and (
            float(row["evidence_score"]) >= 0.47 or important_counter
        ):
            selected.append(dict(row))
            selected_ids.add(row["id"])
    return selected, coverage


def packet_status(
    question: str,
    obligations: Sequence[str],
    premises: Sequence[str],
    selected: Sequence[Mapping[str, Any]],
    coverage: Sequence[bool],
    model: str,
) -> Tuple[str, float, Dict[str, int]]:
    answers, usage = post_typesafe(
        {
            "model": model,
            "state": {
                "question": question,
                "obligations": list(obligations),
                "premises": list(premises),
                "coverage": list(coverage),
                "evidence": [
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "source": row["episode_title"],
                        "locator": locator(row),
                        "section": str(row.get("section", "") or ""),
                        "passage": row["text"],
                    }
                    for row in selected
                ],
            },
            "questions": {
                "status": {
                    "type": "choice",
                    "instructions": "What does this complete evidence packet warrant for answering `question`?",
                    "criteria": {
                        "supported": "Direct evidence covers the required obligations without material unresolved conflict.",
                        "partial": "Some useful evidence exists, but a required obligation remains unsupported.",
                        "contradicted": "The packet affirmatively contradicts the question's central premise.",
                        "conflicted": "Material sources disagree and the conflict cannot be resolved from the packet.",
                        "no_evidence": "The packet contains no evidence that warrants an answer.",
                    },
                }
            },
        }
    )
    answer = answers.get("status", {})
    return str(answer.get("choice", "partial")), float(answer.get("confidence", 0.0)), usage


def timestamp_url(source_url: str, seconds: Optional[float]) -> str:
    if not source_url or seconds is None:
        return source_url
    parsed = urlparse(source_url)
    host = parsed.netloc.lower()
    if "youtube.com" not in host and "youtu.be" not in host:
        return source_url
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["t"] = str(max(0, int(seconds)))
    return urlunparse(parsed._replace(query=urlencode(query)))


def locator(row: Mapping[str, Any]) -> str:
    """Human-readable position: timestamp for audio, section+lines for documents."""
    start = row.get("start")
    if isinstance(start, (int, float)):
        return format_timestamp(start)
    section = str(row.get("section", "") or "").strip()
    line_start = row.get("line_start")
    line_end = row.get("line_end")
    if isinstance(line_start, int) and isinstance(line_end, int):
        span = f"L{line_start}-{line_end}" if line_end != line_start else f"L{line_start}"
        return f"{section} ({span})" if section else span
    if section:
        return section
    return "no locator"


def citation(row: Mapping[str, Any]) -> str:
    title = str(row.get("episode_title", "source"))
    start = row.get("start")
    if isinstance(start, (int, float)):
        label = f"{title} @{format_timestamp(start)}"
        link = timestamp_url(str(row.get("source_url", "")), start)
        return f"[{label}]({link})" if link else f"[{label}]"
    section = str(row.get("section", "") or "").strip()
    line_start = row.get("line_start")
    line_end = row.get("line_end")
    if isinstance(line_start, int) and isinstance(line_end, int):
        span = f"L{line_start}-{line_end}" if line_end != line_start else f"L{line_start}"
        label = f"{title} § {section} ({span})" if section else f"{title} ({span})"
    elif section:
        label = f"{title} § {section}"
    else:
        label = title
    link = str(row.get("source_url", "") or "")
    return f"[{label}]({link})" if link else f"[{label}]"


def packet_markdown(
    question: str,
    obligations: Sequence[str],
    selected: Sequence[Mapping[str, Any]],
    coverage: Sequence[bool],
    status: str,
    confidence: float,
) -> str:
    lines = [
        f"# Evidence packet: {question}",
        "",
        f"Packet status: **{status}** ({confidence:.2f})",
        "",
        "## Obligations",
        "",
    ]
    for index, obligation in enumerate(obligations):
        marker = "covered" if coverage[index] else "not covered"
        lines.append(f"- [{marker}] {obligation}")
    lines.extend(["", "## Evidence", ""])
    for row in selected:
        support_text = ", ".join(
            f"O{index + 1}={value:.2f}" for index, value in enumerate(row["supports"])
        )
        lines.extend(
            [
                f"### {row['id']} — {citation(row)}",
                "",
                f"Role: **{row['role']}** ({row['role_probability']:.2f}); {support_text}",
                "",
                str(row["text"]),
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def command_inspect(args: argparse.Namespace) -> int:
    source = getattr(args, "transcript", None) or getattr(args, "file", None)
    if not source:
        raise EvidenceChatError("Provide --transcript <path> (or --file <path>)")
    path = Path(source)
    cues, timestamped = parse_source(path)
    chunks = chunk_cues(cues)
    sections = sorted({str(cue.get("section", "")) for cue in cues if cue.get("section")})
    print(f"Source: {path}")
    print(f"Timestamped: {'yes' if timestamped else 'no'}")
    print(f"Sections: {len(sections)}")
    print(f"Cues: {len(cues)}")
    print(f"Chunks: {len(chunks)}")
    if chunks:
        print(f"First chunk: {locator(chunks[0])} — {chunks[0]['text'][:240]}")
    return 0


def command_index(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    episodes = load_manifest(manifest_path)
    segments: List[Dict[str, Any]] = []
    untimestamped: List[str] = []
    for episode in episodes:
        cues, timestamped = parse_source(Path(episode["transcript_path"]))
        if not timestamped:
            has_sections = any(cue.get("section") for cue in cues)
            if not has_sections:
                untimestamped.append(str(episode["title"]))
        for index, chunk in enumerate(chunk_cues(cues)):
            segments.append(
                {
                    "id": f"{episode['id']}:{index:04d}",
                    "episode_id": episode["id"],
                    "episode_title": str(episode["title"]),
                    "source_url": str(episode.get("source_url", "")),
                    **chunk,
                }
            )
    if not segments:
        raise EvidenceChatError("No source content was found")
    output = {
        "version": LIBRARY_VERSION,
        "created_at": int(time.time()),
        "manifest": str(manifest_path.resolve()),
        "episodes": [
            {
                "id": episode["id"],
                "title": episode["title"],
                "source_url": episode.get("source_url", ""),
                "transcript": str(Path(episode["transcript_path"]).resolve()),
            }
            for episode in episodes
        ],
        "segments": segments,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    print(
        f"Indexed {len(episodes)} sources and {len(segments)} chunks locally → {out_path}"
    )
    if untimestamped:
        print("Warning: no timestamps or sections found for: " + ", ".join(untimestamped))
    return 0


def command_compile(args: argparse.Namespace) -> int:
    library = load_library(Path(args.library))
    obligations = args.obligation or [args.question]
    queries = args.query or [args.question, *obligations]
    candidates = retrieve_candidates(library, queries, args.candidate_limit)
    if not candidates:
        raise EvidenceChatError(
            "Local search found no candidates; add queries using likely source wording"
        )
    eprint(f"Local search found {len(candidates)} candidates; judging with Jev...")
    judged, judge_usage = judge_candidates(
        args.question,
        obligations,
        args.premise or [],
        candidates,
        args.typesafe_model,
    )
    selected, coverage = compile_packet(judged, len(obligations), args.max_evidence)
    if selected:
        status, confidence, status_usage = packet_status(
            args.question,
            obligations,
            args.premise or [],
            selected,
            coverage,
            args.typesafe_model,
        )
    else:
        status, confidence = "no_evidence", 1.0
        status_usage = {"input_tokens": 0, "output_tokens": 0}
    usage = {
        "input_tokens": judge_usage["input_tokens"] + status_usage["input_tokens"],
        "output_tokens": judge_usage["output_tokens"] + status_usage["output_tokens"],
    }
    if args.json:
        print(
            json.dumps(
                {
                    "question": args.question,
                    "status": status,
                    "status_confidence": confidence,
                    "obligations": obligations,
                    "coverage": coverage,
                    "evidence": [
                        {
                            "id": row["id"],
                            "citation": citation(row),
                            "locator": locator(row),
                            "section": str(row.get("section", "") or ""),
                            "role": row["role"],
                            "role_probability": row["role_probability"],
                            "supports": row["supports"],
                            "text": row["text"],
                        }
                        for row in selected
                    ],
                    "typesafe_usage": usage,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    print(
        packet_markdown(
            args.question, obligations, selected, coverage, status, confidence
        )
    )
    eprint(
        f"TypeSafe usage: {usage['input_tokens']} input / "
        f"{usage['output_tokens']} output tokens"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile cited evidence packets from transcripts and large documents with local search and Jev."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Check source parsing without API calls"
    )
    inspect_parser.add_argument(
        "--transcript",
        required=False,
        default=None,
        help="Transcript or document path (.txt, .srt, .vtt, .md)",
    )
    inspect_parser.add_argument(
        "--file",
        required=False,
        default=None,
        help="Alias for --transcript",
    )
    inspect_parser.set_defaults(func=command_inspect)

    index_parser = subparsers.add_parser(
        "index", help="Build a local reusable source index"
    )
    index_parser.add_argument("--manifest", required=True)
    index_parser.add_argument("--out", required=True)
    index_parser.set_defaults(func=command_index)

    compile_parser = subparsers.add_parser(
        "compile", help="Compile a Jev-selected evidence packet"
    )
    compile_parser.add_argument("--library", required=True)
    compile_parser.add_argument("--question", required=True)
    compile_parser.add_argument("--obligation", action="append")
    compile_parser.add_argument("--query", action="append")
    compile_parser.add_argument("--premise", action="append")
    compile_parser.add_argument("--candidate-limit", type=int, default=16)
    compile_parser.add_argument("--max-evidence", type=int, default=6)
    compile_parser.add_argument("--typesafe-model", default=DEFAULT_TYPESAFE_MODEL)
    compile_parser.add_argument("--json", action="store_true")
    compile_parser.set_defaults(func=command_compile)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "candidate_limit", 1) < 1:
        parser.error("--candidate-limit must be positive")
    if getattr(args, "max_evidence", 1) < 1:
        parser.error("--max-evidence must be positive")
    try:
        return int(args.func(args))
    except (EvidenceChatError, OSError, ValueError, json.JSONDecodeError) as exc:
        eprint(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
