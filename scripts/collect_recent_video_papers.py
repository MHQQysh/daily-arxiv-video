import argparse
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import requests


ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"

DEFAULT_VIDEO_QUERY = "ti:video"

ALLOWED_PRIMARY_CATEGORIES = {
	"cs.AI",
	"cs.CL",
	"cs.CV",
	"cs.LG",
	"cs.MM",
	"cs.RO",
}

TOPIC_PATTERNS: Sequence[Tuple[str, Sequence[str]]] = (
	(
		"视频生成",
		(
			"text-to-video",
			"image-to-video",
			"video generation",
			"video diffusion",
			"video synthesis",
			"generative video",
			"video world model",
		),
	),
	(
		"视频理解与推理",
		(
			"video understanding",
			"video reasoning",
			"video question answering",
			"video-language",
			"video language",
			"video llm",
			"video-language model",
			"multimodal video",
		),
	),
	(
		"视频编辑与控制",
		("video editing", "video manipulation", "video inpainting", "video control"),
	),
	(
		"视频分析与感知",
		(
			"video anomaly detection",
			"video segmentation",
			"video tracking",
			"action recognition",
			"temporal grounding",
			"video retrieval",
			"video captioning",
			"streaming video",
		),
	),
	(
		"视频数据与表征",
		(
			"video dataset",
			"video representation",
			"video pretraining",
			"video pre-training",
			"video encoder",
		),
	),
)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Collect and rank recent video-related arXiv papers."
	)
	parser.add_argument("--start-date", required=True, help="Inclusive YYYY-MM-DD")
	parser.add_argument("--end-date", required=True, help="Inclusive YYYY-MM-DD")
	parser.add_argument("--output", required=True, help="JSON output path")
	parser.add_argument("--query", default=DEFAULT_VIDEO_QUERY)
	parser.add_argument("--slice-days", type=int, default=7)
	parser.add_argument("--page-size", type=int, default=100)
	parser.add_argument("--request-delay", type=float, default=4.0)
	parser.add_argument("--max-retries", type=int, default=5)
	parser.add_argument(
		"--server-date-filter",
		action="store_true",
		help="Use arXiv submittedDate queries instead of client-side date filtering.",
	)
	return parser.parse_args()


def parse_date(value: str) -> date:
	return datetime.strptime(value, "%Y-%m-%d").date()


def iter_date_slices(start: date, end: date, days: int) -> Iterable[Tuple[date, date]]:
	cursor = start
	while cursor <= end:
		slice_end = min(end, cursor + timedelta(days=days - 1))
		yield cursor, slice_end
		cursor = slice_end + timedelta(days=1)


def clean_text(value: str) -> str:
	return re.sub(r"\s+", " ", value or "").strip()


def normalize_arxiv_url(value: str) -> str:
	return re.sub(r"v\d+$", "", value.strip())


def classify_topics(title: str, abstract: str) -> List[str]:
	text = f"{title} {abstract}".lower()
	return [
		name
		for name, patterns in TOPIC_PATTERNS
		if any(pattern in text for pattern in patterns)
	]


def relevance_score(title: str, abstract: str, topics: Sequence[str]) -> int:
	title_lower = title.lower()
	abstract_lower = abstract.lower()
	score = 0
	if re.search(r"\bvideos?\b", title_lower):
		score += 5
	score += min(6, len(topics) * 2)
	video_mentions = len(re.findall(r"\bvideos?\b", abstract_lower))
	if video_mentions >= 2:
		score += 1
	if video_mentions >= 5:
		score += 1
	return score


def request_feed(
	session: requests.Session,
	params: Dict[str, object],
	max_retries: int,
) -> str:
	for attempt in range(max_retries):
		try:
			response = session.get(
				ARXIV_API_URL,
				params=params,
				timeout=(10, 60),
			)
			if response.status_code == 429:
				retry_after = float(response.headers.get("Retry-After", 0) or 0)
				wait_seconds = max(retry_after, 20 * (attempt + 1))
				print(f"arXiv rate limited; retrying in {wait_seconds:.0f}s")
				time.sleep(wait_seconds)
				continue
			response.raise_for_status()
			return response.text
		except requests.RequestException as exc:
			if attempt == max_retries - 1:
				raise RuntimeError(f"arXiv request failed: {exc}") from exc
			wait_seconds = 10 * (2**attempt)
			print(f"arXiv request failed; retrying in {wait_seconds}s: {exc}")
			time.sleep(wait_seconds)
	raise RuntimeError("arXiv request failed without a response")


def parse_feed(xml_text: str) -> List[Dict[str, object]]:
	root = ET.fromstring(xml_text)
	results: List[Dict[str, object]] = []
	for entry in root.findall(f"{{{ATOM_NS}}}entry"):
		primary = entry.find(f"{{{ARXIV_NS}}}primary_category")
		primary_category = primary.attrib.get("term", "") if primary is not None else ""
		title = clean_text(entry.findtext(f"{{{ATOM_NS}}}title", default=""))
		abstract = clean_text(entry.findtext(f"{{{ATOM_NS}}}summary", default=""))
		topics = classify_topics(title, abstract)
		results.append(
			{
				"arxiv_id": normalize_arxiv_url(
					entry.findtext(f"{{{ATOM_NS}}}id", default="")
				).rsplit("/", 1)[-1],
				"title": title,
				"abstract": abstract,
				"published": entry.findtext(f"{{{ATOM_NS}}}published", default=""),
				"updated": entry.findtext(f"{{{ATOM_NS}}}updated", default=""),
				"url": normalize_arxiv_url(
					entry.findtext(f"{{{ATOM_NS}}}id", default="")
				),
				"authors": [
					clean_text(author.findtext(f"{{{ATOM_NS}}}name", default=""))
					for author in entry.findall(f"{{{ATOM_NS}}}author")
				],
				"categories": [
					category.attrib.get("term", "")
					for category in entry.findall(f"{{{ATOM_NS}}}category")
				],
				"primary_category": primary_category,
				"topics": topics,
				"relevance_score": relevance_score(title, abstract, topics),
			}
		)
	return results


def collect_slice(
	session: requests.Session,
	query: str,
	start: date,
	end: date,
	page_size: int,
	request_delay: float,
	max_retries: int,
) -> List[Dict[str, object]]:
	date_query = (
		f"({query}) AND submittedDate:"
		f"[{start.strftime('%Y%m%d')}0000 TO {end.strftime('%Y%m%d')}2359]"
	)
	results: List[Dict[str, object]] = []
	offset = 0
	while True:
		params = {
			"search_query": date_query,
			"start": offset,
			"max_results": page_size,
			"sortBy": "submittedDate",
			"sortOrder": "descending",
		}
		xml_text = request_feed(session, params, max_retries)
		page = parse_feed(xml_text)
		results.extend(page)
		print(f"{start}..{end}: fetched {len(page)} at offset {offset}")
		if len(page) < page_size:
			break
		offset += len(page)
		time.sleep(request_delay)
	return results


def collect_recent_without_server_date(
	session: requests.Session,
	query: str,
	start: date,
	end: date,
	page_size: int,
	request_delay: float,
	max_retries: int,
) -> List[Dict[str, object]]:
	results: List[Dict[str, object]] = []
	offset = 0
	while True:
		params = {
			"search_query": query,
			"start": offset,
			"max_results": page_size,
			"sortBy": "submittedDate",
			"sortOrder": "descending",
		}
		xml_text = request_feed(session, params, max_retries)
		page = parse_feed(xml_text)
		if not page:
			break
		page_dates: List[date] = []
		for paper in page:
			if not paper["published"]:
				continue
			paper_date = datetime.fromisoformat(
				str(paper["published"]).replace("Z", "+00:00")
			).date()
			page_dates.append(paper_date)
			if start <= paper_date <= end:
				results.append(paper)
		oldest = min(page_dates) if page_dates else None
		print(f"latest query: fetched {len(page)} at offset {offset}; oldest={oldest}")
		if len(page) < page_size or (oldest is not None and oldest < start):
			break
		offset += len(page)
		time.sleep(request_delay)
	return results


def main() -> None:
	args = parse_args()
	start = parse_date(args.start_date)
	end = parse_date(args.end_date)
	if start > end:
		raise ValueError("start-date must not be after end-date")
	if args.slice_days < 1:
		raise ValueError("slice-days must be at least 1")

	session = requests.Session()
	session.headers.update(
		{
			"User-Agent": (
				"daily-arxiv-video/1.0 "
				"(contact: shihongyuan99@gmail.com)"
			)
		}
	)

	by_id: Dict[str, Dict[str, object]] = {}
	if args.server_date_filter:
		batches = []
		for index, (slice_start, slice_end) in enumerate(
			iter_date_slices(start, end, args.slice_days)
		):
			if index:
				time.sleep(args.request_delay)
			batches.append(
				collect_slice(
					session,
					args.query,
					slice_start,
					slice_end,
					args.page_size,
					args.request_delay,
					args.max_retries,
				)
			)
	else:
		batches = [
			collect_recent_without_server_date(
				session,
				args.query,
				start,
				end,
				args.page_size,
				args.request_delay,
				args.max_retries,
			)
		]
	for batch in batches:
		for paper in batch:
			if paper["arxiv_id"]:
				by_id[str(paper["arxiv_id"])] = paper

	collected = sorted(
		by_id.values(),
		key=lambda paper: (str(paper["published"]), str(paper["arxiv_id"])),
		reverse=True,
	)
	filtered = [
		paper
		for paper in collected
		if paper["primary_category"] in ALLOWED_PRIMARY_CATEGORIES
		and int(paper["relevance_score"]) >= 4
	]
	payload = {
		"generated_at": datetime.now(timezone.utc).isoformat(),
		"start_date": start.isoformat(),
		"end_date": end.isoformat(),
		"query": args.query,
		"collected_count": len(collected),
		"filtered_count": len(filtered),
		"papers": filtered,
	}
	output = Path(args.output)
	output.parent.mkdir(parents=True, exist_ok=True)
	output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
	print(f"saved {len(filtered)}/{len(collected)} relevant papers to {output}")


if __name__ == "__main__":
	main()
