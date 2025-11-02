"""Panopto transcript scraper suitable for public distribution."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Dict, Optional, Set
from urllib.parse import parse_qs, urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

VIDEO_CONTAINER_SELECTOR = "#listViewContainer"
VIDEO_ROW_SELECTOR = "tbody tr.list-view-row"
VIDEO_TITLE_LINK_SELECTOR = ".item-title.title-link a.detail-title"
VIDEO_TITLE_TEXT_SELECTOR = ".item-title.title-link span"
TRANSCRIPT_CONTAINER_SELECTOR = "div.event-tab-scroll-pane"
TRANSCRIPT_LINE_SELECTOR = "li.index-event"
TIMESTAMP_PATTERN = re.compile(r"\d{1,2}:\d{2}(?::\d{2})?")
VIDEO_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
DEFAULT_TIMEOUT = 30


def _ensure_parent_dir(path: Path) -> None:
    """Ensure the parent directory for the provided path exists."""
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def _load_scraped_records(state_path: Optional[Path]) -> Dict[str, Set[str]]:
    """Load previously scraped video identifiers to avoid duplicates."""
    records: Dict[str, Set[str]] = {"ids": set(), "titles": set()}
    if not state_path or not state_path.exists():
        return records

    with state_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            entry = raw_line.strip()
            if not entry:
                continue
            parts = entry.split("|", 1)
            candidate = parts[0].strip()
            if VIDEO_ID_PATTERN.fullmatch(candidate):
                records["ids"].add(candidate.lower())
                if len(parts) > 1 and parts[1].strip():
                    records["titles"].add(parts[1].strip())
            else:
                records["titles"].add(entry)
    return records


def _append_scraped_record(
    records: Dict[str, Set[str]],
    state_path: Optional[Path],
    video_id: Optional[str],
    title: str,
) -> None:
    """Update in-memory records and persist the entry if a state file is used."""
    clean_title = title.strip()
    if video_id:
        records["ids"].add(video_id.lower())
    if clean_title:
        records["titles"].add(clean_title)

    if not state_path:
        return

    _ensure_parent_dir(state_path)
    line = None
    if video_id:
        line = f"{video_id}|{clean_title}" if clean_title else video_id
    elif clean_title:
        line = clean_title

    if line:
        with state_path.open("a", encoding="utf-8") as handle:
            handle.write(line + os.linesep)


def _extract_transcript_line(element) -> Optional[str]:
    """Return a cleaned transcript line with an optional timestamp."""
    raw_text = element.get_attribute("innerText")
    if not raw_text:
        raw_text = element.text or element.get_attribute("textContent") or ""

    pieces = [piece.strip() for piece in raw_text.splitlines()]
    pieces = [piece for piece in pieces if piece and piece.lower() not in {"retry", "cancel"}]
    if not pieces:
        return None

    timestamp = None
    for idx in range(len(pieces) - 1, -1, -1):
        if TIMESTAMP_PATTERN.fullmatch(pieces[idx]):
            timestamp = pieces.pop(idx)
            break

    text = " ".join(pieces).strip()
    if not text:
        return None

    return f"{timestamp} {text}" if timestamp else text


def _extract_video_id(url: Optional[str]) -> Optional[str]:
    """Parse a Panopto video identifier from the supplied URL."""
    if not url:
        return None

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("id", "objectId", "contentID"):
        values = query.get(key)
        if values:
            candidate = values[0]
            if candidate and VIDEO_ID_PATTERN.fullmatch(candidate):
                return candidate.lower()

    last_segment = parsed.path.rstrip("/").split("/")[-1]
    if last_segment and VIDEO_ID_PATTERN.fullmatch(last_segment):
        return last_segment.lower()
    return None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return slug[:80] or "transcript"


def _build_transcript_path(
    output_dir: Path,
    title: Optional[str],
    video_id: Optional[str],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _slugify(title or "untitled-session")
    suffix = f"-{video_id[:8]}" if video_id else ""
    base = f"{safe_title}{suffix}" if suffix else safe_title
    path = output_dir / f"{base}.txt"
    counter = 1
    while path.exists():
        path = output_dir / f"{base}-{counter}.txt"
        counter += 1
    return path


def scrape_panopto_folder(
    folder_url: str,
    output_dir: Path,
    state_path: Optional[Path],
    *,
    headless: bool = True,
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """Scrape transcript files from the given Panopto course folder."""
    options = Options()
    if headless:
        # Use the modern headless flag when available; Chrome ignores unknown flags.
        options.add_argument("--headless=new")
        options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, timeout)

    try:
        driver.get(folder_url)
        print(f"Navigated to the course folder: {folder_url}")
        print("Waiting for the list of videos to load...")

        try:
            container = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, VIDEO_CONTAINER_SELECTOR))
            )
        except TimeoutException:
            print("Timed out waiting for the video table to render.")
            driver.save_screenshot("error_screenshot.png")
            return

        def rows_loaded(_driver):
            rows = container.find_elements(By.CSS_SELECTOR, VIDEO_ROW_SELECTOR)
            return rows if rows else False

        try:
            video_rows = wait.until(rows_loaded)
        except TimeoutException:
            print("Timed out waiting for video rows inside the container.")
            driver.save_screenshot("error_screenshot.png")
            return

        print(f"Found {len(video_rows)} video rows; collecting metadata.")

        scraped_records = _load_scraped_records(state_path)
        videos = []
        seen_ids: Set[str] = set()

        for row in video_rows:
            try:
                link = row.find_element(By.CSS_SELECTOR, VIDEO_TITLE_LINK_SELECTOR)
            except Exception:
                continue

            title = ""
            try:
                title_element = row.find_element(By.CSS_SELECTOR, VIDEO_TITLE_TEXT_SELECTOR)
                title = title_element.text.strip()
                if not title:
                    title = (title_element.get_attribute("innerText") or "").strip()
                    if not title:
                        title = (title_element.get_attribute("textContent") or "").strip()
            except Exception:
                pass

            if not title:
                title = link.text.strip()

            url = link.get_attribute("href")
            video_id = _extract_video_id(url)

            if video_id and video_id in seen_ids:
                continue
            if video_id:
                seen_ids.add(video_id)

            videos.append({"title": title, "url": url, "id": video_id})

        if not videos:
            print("Could not extract any video metadata. Check that the selectors still match the page.")
            driver.save_screenshot("error_screenshot.png")
            return

        print(f"Collected {len(videos)} videos from the list.")

        videos_to_scrape = []
        for video in videos:
            video_id = video["id"]
            title = video["title"] or "(untitled)"
            if video_id and video_id in scraped_records["ids"]:
                print(f"Skipping '{title}' (already scraped by ID).")
                continue
            if title in scraped_records["titles"]:
                print(f"Skipping '{title}' (already scraped by title).")
                continue
            if not video["url"]:
                print(f"Skipping '{title}' (no URL found).")
                continue
            videos_to_scrape.append(video)

        if not videos_to_scrape:
            print("No new videos to scrape. You're all caught up!")
            return

        print(f"Need to scrape {len(videos_to_scrape)} new video(s).")

        scraped_count = 0
        for video in videos_to_scrape:
            title = video["title"] or "Untitled Session"
            video_id = video["id"]
            print(f"Opening video page for '{title}'.")
            driver.get(video["url"])

            try:
                wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, TRANSCRIPT_CONTAINER_SELECTOR))
                )
                transcript_elements = wait.until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, TRANSCRIPT_LINE_SELECTOR))
                )
            except TimeoutException:
                print(f"Timed out waiting for transcript on '{title}'.")
                driver.save_screenshot(f"error_{_slugify(title)}.png")
                continue

            print(f"Found {len(transcript_elements)} transcript lines for '{title}'.")
            transcript_lines = []
            for element in transcript_elements:
                line_text = _extract_transcript_line(element)
                if line_text:
                    transcript_lines.append(line_text)

            print(f"Using {len(transcript_lines)} formatted transcript lines.")
            transcript_path = _build_transcript_path(output_dir, title, video_id)
            transcript_path.write_text("\n".join(transcript_lines), encoding="utf-8")

            print(f"Transcript saved to {transcript_path}")
            _append_scraped_record(scraped_records, state_path, video_id, title)
            scraped_count += 1

        print(f"Finished scraping {scraped_count} new video(s).")

    except Exception as exc:
        print(f"An unexpected error occurred: {exc}")
        driver.save_screenshot("error_screenshot.png")
    finally:
        driver.quit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download transcripts from a Panopto course folder."
    )
    parser.add_argument(
        "--folder-url",
        required=True,
        help="Panopto folder URL (open the course folder in list view and copy the address).",
    )
    parser.add_argument(
        "--output-dir",
        default="transcripts",
        help="Directory where transcript .txt files will be stored.",
    )
    parser.add_argument(
        "--state-file",
        default="data/scraped_sessions.txt",
        help="File used to track processed videos (set to an empty string to disable).",
    )
    parser.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run Chrome with a visible window (useful for first-time SSO login).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="Seconds to wait for elements to load before giving up.",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Delete the state file before scraping so every lecture is downloaded again.",
    )
    parser.set_defaults(headless=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    state_path = Path(args.state_file).expanduser().resolve() if args.state_file else None

    if args.reset_state and state_path and state_path.exists():
        print(f"Removing existing state file at {state_path}")
        state_path.unlink()

    scrape_panopto_folder(
        args.folder_url,
        output_dir,
        state_path,
        headless=args.headless,
        timeout=max(args.timeout, 1),
    )


if __name__ == "__main__":
    main()
