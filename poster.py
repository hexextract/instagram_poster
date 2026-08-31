#!/usr/bin/env python3
"""Post the next queued item from posts/ to Instagram via the Meta Graph API.

Queue layout:
    posts/<name>/image.jpg   (or clip.mp4 for a Reel)
    posts/<name>/caption.txt

Posts are published in alphabetical order of folder name; published ones are
tracked in posted.json. Media is served to Instagram via the public
raw.githubusercontent.com URL, so the repo must be public (or the media
hosted elsewhere and referenced via a `url.txt` file in the post folder).

Usage:
    python poster.py            # publish the next unposted item
    python poster.py whoami     # list your Pages and their IG account IDs

Required env vars:
    IG_USER_ID          Instagram professional account ID
    IG_ACCESS_TOKEN     long-lived access token
    GITHUB_REPOSITORY   owner/repo   (set automatically in Actions)
    GITHUB_SHA          commit sha   (set automatically in Actions)
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# Default: Instagram API with Instagram Login. Set GRAPH_BASE to
# https://graph.facebook.com/v23.0 if using a Facebook Login token instead.
GRAPH = os.environ.get("GRAPH_BASE", "https://graph.instagram.com/v23.0").rstrip("/")
ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
STATE_FILE = ROOT / "posted.json"

IMAGE_EXTS = {".jpg", ".jpeg"}
VIDEO_EXTS = {".mp4", ".mov"}

POLL_INTERVAL = 10          # seconds between container status checks
POLL_TIMEOUT = 600          # give up after 10 minutes (videos can be slow)


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        die(f"missing required environment variable {name}")
    return value


def graph_request(method: str, path: str, **params) -> dict:
    params["access_token"] = env("IG_ACCESS_TOKEN")
    resp = requests.request(method, f"{GRAPH}/{path}", params=params, timeout=60)
    try:
        data = resp.json()
    except ValueError:
        die(f"non-JSON response from Graph API (HTTP {resp.status_code})")
    if "error" in data:
        err = data["error"]
        die(f"Graph API error {err.get('code')}: {err.get('message')}")
    return data


def load_state() -> list:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return []


def find_next_post(posted: list) -> Path | None:
    if not POSTS_DIR.is_dir():
        return None
    for folder in sorted(p for p in POSTS_DIR.iterdir() if p.is_dir()):
        if folder.name not in posted:
            return folder
    return None


def raw_url(f: Path) -> str:
    repo = env("GITHUB_REPOSITORY")
    sha = env("GITHUB_SHA")
    rel = f.relative_to(ROOT).as_posix()
    return f"https://raw.githubusercontent.com/{repo}/{sha}/{rel}"


def find_media(folder: Path) -> list[tuple[str, str]]:
    """Return a list of (kind, url), kind is 'image' or 'video'.

    One entry publishes as a single post; 2-10 images publish as a carousel.
    """
    url_file = folder / "url.txt"
    if url_file.exists():
        media = []
        for line in url_file.read_text().splitlines():
            url = line.strip()
            if not url:
                continue
            kind = "video" if url.lower().split("?")[0].endswith(tuple(VIDEO_EXTS)) else "image"
            media.append((kind, url))
        if media:
            return media

    media = [
        ("video" if f.suffix.lower() in VIDEO_EXTS else "image", raw_url(f))
        for f in sorted(folder.iterdir())
        if f.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS
    ]
    if not media:
        die(f"no media found in {folder} (expected .jpg/.jpeg/.mp4/.mov or url.txt)")
    if len(media) > 10:
        die(f"{folder} has {len(media)} media files; carousels allow at most 10")
    return media


def create_container(ig_user: str, kind: str, url: str, caption: str) -> str:
    if kind == "video":
        params = {"media_type": "REELS", "video_url": url, "caption": caption}
    else:
        params = {"image_url": url, "caption": caption}
    data = graph_request("POST", f"{ig_user}/media", **params)
    return data["id"]


def create_carousel(ig_user: str, media: list[tuple[str, str]], caption: str) -> str:
    children = []
    for kind, url in media:
        if kind == "video":
            params = {"media_type": "VIDEO", "video_url": url, "is_carousel_item": "true"}
        else:
            params = {"image_url": url, "is_carousel_item": "true"}
        child = graph_request("POST", f"{ig_user}/media", **params)["id"]
        wait_until_ready(child)
        children.append(child)
    data = graph_request(
        "POST", f"{ig_user}/media",
        media_type="CAROUSEL", children=",".join(children), caption=caption,
    )
    return data["id"]


def wait_until_ready(container_id: str) -> None:
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        data = graph_request("GET", container_id, fields="status_code")
        status = data.get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            die(f"media container entered state {status}")
        print(f"container {container_id} is {status}, waiting...")
        time.sleep(POLL_INTERVAL)
    die("timed out waiting for media container to be ready")


def publish(ig_user: str, container_id: str) -> str:
    data = graph_request("POST", f"{ig_user}/media_publish", creation_id=container_id)
    return data["id"]


def whoami() -> None:
    """Print the Instagram account (or Pages) reachable with this token."""
    if "graph.instagram.com" in GRAPH:
        data = graph_request("GET", "me", fields="user_id,username,account_type")
        print(f"IG @{data.get('username')} ({data.get('account_type')})  "
              f"IG_USER_ID={data.get('user_id') or data.get('id')}")
        return
    data = graph_request(
        "GET", "me/accounts", fields="name,instagram_business_account{id,username}"
    )
    pages = data.get("data", [])
    if not pages:
        print("No Facebook Pages found for this token.")
        return
    for page in pages:
        ig = page.get("instagram_business_account")
        if ig:
            print(f"Page: {page['name']}  ->  IG @{ig.get('username')}  IG_USER_ID={ig['id']}")
        else:
            print(f"Page: {page['name']}  ->  no Instagram account linked")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "whoami":
        whoami()
        return

    ig_user = env("IG_USER_ID")
    posted = load_state()
    folder = find_next_post(posted)
    if folder is None:
        print("Queue is empty — nothing to post.")
        return

    caption_file = folder / "caption.txt"
    caption = caption_file.read_text().strip() if caption_file.exists() else ""

    media = find_media(folder)
    if len(media) > 1:
        print(f"Posting {folder.name}: carousel with {len(media)} items")
        container_id = create_carousel(ig_user, media, caption)
    else:
        kind, url = media[0]
        print(f"Posting {folder.name}: {kind} at {url}")
        container_id = create_container(ig_user, kind, url, caption)
    wait_until_ready(container_id)
    media_id = publish(ig_user, container_id)
    print(f"Published! media id {media_id}")

    posted.append(folder.name)
    STATE_FILE.write_text(json.dumps(posted, indent=2) + "\n")


if __name__ == "__main__":
    main()
