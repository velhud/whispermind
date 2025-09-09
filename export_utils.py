from pathlib import Path
from typing import List, Tuple


def export_markdown(records: List[Tuple[str, str, str]], output_file: str) -> None:
    """Export transcription records to a markdown file."""
    lines = []
    for timestamp, original, translated in records:
        lines.append(f"### {timestamp}\n")
        lines.append(f"- Original: {original}\n")
        lines.append(f"- Translated: {translated}\n\n")
    Path(output_file).write_text(''.join(lines), encoding='utf-8')
