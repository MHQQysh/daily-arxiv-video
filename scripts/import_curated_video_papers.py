import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List


SUMMARY_PLACEHOLDER = "<details><summary>展开</summary>待生成</details>"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Import a reviewed arXiv ID list into papers.md."
	)
	parser.add_argument("--source", required=True, help="Collector JSON path")
	parser.add_argument("--ids", required=True, help="Reviewed arXiv ID list")
	parser.add_argument("--papers", default="papers.md")
	return parser.parse_args()


def normalize_id(value: str) -> str:
	match = re.match(r"^(\d{4}\.\d{4,5})", value.strip())
	return match.group(1) if match else ""


def load_selected_ids(path: Path) -> List[str]:
	selected: List[str] = []
	for line in path.read_text(encoding="utf-8").splitlines():
		value = line.strip()
		if not value or value.startswith("#"):
			continue
		arxiv_id = normalize_id(value)
		if not arxiv_id:
			raise ValueError(f"Invalid arXiv ID in {path}: {value}")
		if arxiv_id not in selected:
			selected.append(arxiv_id)
	return selected


def load_source(path: Path) -> Dict[str, Dict[str, object]]:
	payload = json.loads(path.read_text(encoding="utf-8"))
	by_id: Dict[str, Dict[str, object]] = {}
	for paper in payload.get("papers", []):
		arxiv_id = normalize_id(str(paper.get("arxiv_id", "")))
		if arxiv_id:
			by_id[arxiv_id] = paper
	return by_id


def existing_ids(lines: List[str]) -> set[str]:
	return set(re.findall(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", "".join(lines)))


def format_row(arxiv_id: str, paper: Dict[str, object]) -> str:
	published = datetime.fromisoformat(
		str(paper["published"]).replace("Z", "+00:00")
	).strftime("%Y-%m-%d")
	title = str(paper["title"]).replace("|", "\\|").strip()
	return (
		f"| {published} | {title} | http://arxiv.org/abs/{arxiv_id} | "
		f"{SUMMARY_PLACEHOLDER} |\n"
	)


def main() -> None:
	args = parse_args()
	source = load_source(Path(args.source))
	selected = load_selected_ids(Path(args.ids))
	missing = [arxiv_id for arxiv_id in selected if arxiv_id not in source]
	if missing:
		raise ValueError(f"Selected IDs missing from source JSON: {', '.join(missing)}")

	papers_path = Path(args.papers)
	lines = papers_path.read_text(encoding="utf-8").splitlines(keepends=True)
	if len(lines) < 2:
		raise ValueError(f"{papers_path} does not contain the expected table header")
	existing = existing_ids(lines)
	new_ids = [arxiv_id for arxiv_id in selected if arxiv_id not in existing]
	new_ids.sort(
		key=lambda arxiv_id: (
			str(source[arxiv_id]["published"]),
			arxiv_id,
		),
		reverse=True,
	)
	rows = [format_row(arxiv_id, source[arxiv_id]) for arxiv_id in new_ids]
	if rows:
		papers_path.write_text("".join(lines[:2] + rows + lines[2:]), encoding="utf-8")
	print(
		f"selected={len(selected)} inserted={len(rows)} "
		f"already_present={len(selected) - len(rows)}"
	)


if __name__ == "__main__":
	main()
