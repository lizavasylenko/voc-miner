#!/usr/bin/env python3
"""Voice-of-Customer miner.

Turns a CSV of customer reviews into a report of pains, desires, objections and
reusable customer phrases. Every item must be backed by a verbatim quote, and the
script checks each quote against the source reviews. Quotes it cannot find are
dropped and listed at the end of the report.

Three ways to run it:
  1. API mode:         python voc_miner.py reviews.csv            (needs ANTHROPIC_API_KEY)
  2. Copy-paste mode:  python voc_miner.py reviews.csv --print-prompt
                       paste the output into any AI chat, save the JSON answer, then
                       python voc_miner.py reviews.csv --analysis answer.json
  3. Demo mode:        python voc_miner.py sample_reviews_synthetic.csv \
                           --analysis sample_analysis.json
"""
import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = os.environ.get("VOC_MODEL", "claude-sonnet-5-5")
MIN_QUOTE_WORDS = 3
SECTIONS = [
    ("pains", "Pains"),
    ("desires", "Desires"),
    ("objections", "Objections"),
]


def load_reviews(path, column="review"):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            sys.exit(f"Column '{column}' not found. Columns in file: {reader.fieldnames}")
        rows = list(reader)
    broken = sum(1 for row in rows if None in row)
    if broken:
        print(
            f"Warning: {broken} rows have extra columns. Reviews that contain commas must be wrapped "
            "in double quotes, otherwise the text is cut off and quotes cannot be verified.",
            file=sys.stderr,
        )
    return [row[column].strip() for row in rows if row.get(column) and row[column].strip()]


def numbered(reviews):
    return "\n".join(f"[{i}] {text}" for i, text in enumerate(reviews, start=1))


def load_prompt():
    return (HERE / "voc_prompt.md").read_text(encoding="utf-8")


def normalize(text):
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def extract_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in the model answer.")
    return json.loads(text[start : end + 1])


def call_llm(system_prompt, reviews, model):
    try:
        import anthropic
    except ImportError:
        sys.exit("Install the SDK first: pip install -r requirements.txt")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set the ANTHROPIC_API_KEY environment variable first (see README).")
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": "Reviews:\n" + numbered(reviews)}],
    )
    return extract_json("".join(b.text for b in message.content if b.type == "text"))


def quote_is_valid(item, norm_reviews):
    """A quote is valid if it has enough words and appears verbatim in the review it cites."""
    quote = str(item.get("quote", ""))
    rid = item.get("review_id")
    if not isinstance(rid, int) or not 1 <= rid <= len(norm_reviews):
        return False, "review_id does not exist"
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return False, "quote too short"
    if normalize(quote) not in norm_reviews[rid - 1]:
        return False, "quote not found in the cited review"
    return True, ""


def verify(analysis, reviews):
    """Keep only verified quotes. Drop themes without any verified quote."""
    norm_reviews = [normalize(r) for r in reviews]
    dropped, total, kept = [], 0, 0
    cleaned = {"summary": analysis.get("summary", "")}

    for key, _ in SECTIONS:
        themes_out = []
        for theme in analysis.get(key, []):
            good = []
            for q in theme.get("quotes", []):
                total += 1
                ok, reason = quote_is_valid(q, norm_reviews)
                if ok:
                    kept += 1
                    good.append(q)
                else:
                    dropped.append((key, theme.get("theme", "?"), q.get("quote", ""), reason))
            if good:
                themes_out.append({"theme": theme.get("theme", "?"), "quotes": good})
            else:
                dropped.append((key, theme.get("theme", "?"), "(whole theme)", "no verified quote"))
        cleaned[key] = themes_out

    phrases = []
    for item in analysis.get("reusable_phrases", []):
        total += 1
        ok, reason = quote_is_valid(item, norm_reviews)
        if ok:
            kept += 1
            phrases.append(item)
        else:
            dropped.append(("reusable_phrases", item.get("use_in", "?"), item.get("quote", ""), reason))
    cleaned["reusable_phrases"] = phrases
    return cleaned, {"total": total, "kept": kept, "dropped": dropped}


def render(cleaned, stats, n_reviews, source):
    lines = ["# Voice-of-Customer report", "", f"Source: `{source}`, {n_reviews} reviews.", ""]
    if cleaned.get("summary"):
        lines += ["## Summary", "", cleaned["summary"], ""]
    for key, title in SECTIONS:
        themes = cleaned.get(key, [])
        if not themes:
            continue
        lines += [f"## {title}", ""]
        def mentions(t):
            return len({q["review_id"] for q in t["quotes"]})
        for theme in sorted(themes, key=mentions, reverse=True):
            lines += [f"### {theme['theme']} (verified in {mentions(theme)} of {n_reviews} reviews)", ""]
            for q in theme["quotes"]:
                lines.append(f"> {q['quote']} (review #{q['review_id']})")
                lines.append("")
    if cleaned.get("reusable_phrases"):
        lines += ["## Customer phrases worth reusing", ""]
        for p in cleaned["reusable_phrases"]:
            lines.append(f"- \"{p['quote']}\" (review #{p['review_id']}). Use in: {p.get('use_in', '')}")
        lines.append("")
    lines += [
        "## Verification",
        "",
        f"{stats['kept']} of {stats['total']} quotes matched the source reviews word for word. "
        f"{len(stats['dropped'])} items were dropped.",
        "",
        "Counts are lower bounds: they only include reviews with a verified quote.",
        "",
    ]
    if stats["dropped"]:
        lines += ["Dropped items:", ""]
        for section, theme, quote, reason in stats["dropped"]:
            lines.append(f"- [{section}] {theme}: \"{quote}\" ({reason})")
        lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Voice-of-Customer miner with verified quotes.")
    p.add_argument("csv_path", help="CSV file with one review per row")
    p.add_argument("--column", default="review", help="Name of the column with the review text")
    p.add_argument("--out", default="report.md", help="Where to save the report")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--max-reviews", type=int, default=200, help="Use only the first N reviews")
    p.add_argument("--print-prompt", action="store_true", help="Print a prompt to paste into any AI chat")
    p.add_argument("--analysis", help="Use an existing analysis JSON instead of calling the API")
    args = p.parse_args()

    reviews = load_reviews(args.csv_path, args.column)
    if len(reviews) > args.max_reviews:
        print(f"Warning: using the first {args.max_reviews} of {len(reviews)} reviews.", file=sys.stderr)
        reviews = reviews[: args.max_reviews]
    if not reviews:
        sys.exit("No reviews found.")

    if args.print_prompt:
        print(load_prompt() + "\n\nReviews:\n" + numbered(reviews))
        return

    if args.analysis:
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    else:
        analysis = call_llm(load_prompt(), reviews, args.model)

    cleaned, stats = verify(analysis, reviews)
    Path(args.out).write_text(render(cleaned, stats, len(reviews), args.csv_path), encoding="utf-8")
    print(f"Saved {args.out}. Verified {stats['kept']} of {stats['total']} quotes.")


if __name__ == "__main__":
    main()
