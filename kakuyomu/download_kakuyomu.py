import os
import re
import time
import requests
import subprocess
from bs4 import BeautifulSoup

DOWNLOAD_DIR_BASE = "/tmp/kakuyomu_dl"
HISTORY_FILE = "/tmp/カクヨムダウンロード経歴.txt"


def read_downloaded_urls():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f)


def write_downloaded_url(url):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def fetch_page(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Failed to fetch {url}: {e}")
        return None


def parse_novel_title(html):
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one(".widget-workTitle")
    return title_tag.text.strip() if title_tag else "Untitled"


def parse_episode_list(html):
    soup = BeautifulSoup(html, "html.parser")
    return [
        (a["href"], a.text.strip())
        for a in soup.select(".widget-toc-episode a")
    ]


def parse_episode_body(html):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".widget-episodeBody")
    return body.get_text("\n", strip=True) if body else ""


def split_sentences(text):
    blocks = []
    buffer = ""
    nesting = 0
    for c in text:
        buffer += c
        if c in "「『【（":
            nesting += 1
        elif c in "」』】）":
            nesting = max(0, nesting - 1)
        elif c in "。！？" and nesting == 0:
            blocks.append(buffer.strip())
            buffer = ""
    if buffer.strip():
        blocks.append(buffer.strip())
    return blocks


def try_translate(text, retries=3):
    for _ in range(retries):
        try:
            proc = subprocess.run(
                ["deepl", "translate", "-t", "EN", "--input", "-", "--output", "-"],
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            result = proc.stdout.decode("utf-8").strip()
            if is_translation_valid(result):
                return result
        except Exception:
            time.sleep(1)
    return None


def is_translation_valid(text):
    jp_count = sum(1 for c in text if "぀" <= c <= "ヿ" or "一" <= c <= "鿿")
    return jp_count / max(1, len(text)) < 0.1


def translate_text(japanese_text):
    blocks = split_sentences(japanese_text)
    translated_blocks = []
    for block in blocks:
        result = try_translate(block)
        translated_blocks.append(result if result else "[翻訳失敗]\n" + block)
    return "\n\n".join(translated_blocks)


def download_episode(episode_url, title, novel_title, index):
    full_url = "https://kakuyomu.jp" + episode_url
    html = fetch_page(full_url)
    if not html:
        return
    body = parse_episode_body(html)
    if not body:
        return

    folder_num = f"{(index // 1000) + 1:03d}"
    safe_novel_title = re.sub(r"[\\/:*?\"<>|]", "_", novel_title)
    folder_path = os.path.join(DOWNLOAD_DIR_BASE, safe_novel_title, folder_num)
    japanese_path = os.path.join(folder_path, "japanese")
    english_path = os.path.join(folder_path, "english")
    os.makedirs(japanese_path, exist_ok=True)
    os.makedirs(english_path, exist_ok=True)

    file_name = f"{index + 1:03d}.txt"
    jp_path = os.path.join(japanese_path, file_name)
    en_path = os.path.join(english_path, file_name)

    with open(jp_path, "w", encoding="utf-8") as f:
        f.write(body)

    translated = translate_text(body)
    if translated:
        with open(en_path, "w", encoding="utf-8") as f:
            f.write(translated)


def main():
    url = input("小説のURLを入力してください: ").strip()
    html = fetch_page(url)
    if not html:
        return

    novel_title = parse_novel_title(html)
    episode_list = parse_episode_list(html)
    downloaded = read_downloaded_urls()

    for i, (ep_url, ep_title) in enumerate(episode_list):
        full_url = "https://kakuyomu.jp" + ep_url
        if full_url in downloaded:
            print(f"[SKIP] {ep_title}")
            continue
        print(f"[DL  ] {ep_title}")
        download_episode(ep_url, ep_title, novel_title, i)
        write_downloaded_url(full_url)
        time.sleep(1)

    subprocess.run([
        "rclone", "copy", DOWNLOAD_DIR_BASE, "drive:",
        "--transfers=4", "--checkers=8", "--fast-list"
    ], check=True)

if __name__ == "__main__":
    main()
