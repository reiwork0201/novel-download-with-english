import os
import re
import time
import requests
import subprocess
from bs4 import BeautifulSoup

BASE_URL = "https://kakuyomu.jp"
HISTORY_FILE = "\u30ab\u30af\u30e8\u30e0\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u7d4c\u6b74.txt"
LOCAL_HISTORY_PATH = f"/tmp/{HISTORY_FILE}"
REMOTE_HISTORY_PATH = f"drive:{HISTORY_FILE}"
DOWNLOAD_DIR_BASE = "/tmp/kakuyomu_dl"

os.makedirs(DOWNLOAD_DIR_BASE, exist_ok=True)

def load_history():
    if not os.path.exists(LOCAL_HISTORY_PATH):
        subprocess.run(['rclone', 'copyto', REMOTE_HISTORY_PATH, LOCAL_HISTORY_PATH], check=False)

    history = {}
    if os.path.exists(LOCAL_HISTORY_PATH):
        with open(LOCAL_HISTORY_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                match = re.match(r'(https?://[^\s|]+)\s*\|\s*(\d+)', line.strip())
                if match:
                    url, last = match.groups()
                    history[url] = int(last)
    return history

def save_history(history):
    with open(LOCAL_HISTORY_PATH, 'w', encoding='utf-8') as f:
        for url, last in history.items():
            f.write(f'{url}  |  {last}\n')
    subprocess.run(['rclone', 'copyto', LOCAL_HISTORY_PATH, REMOTE_HISTORY_PATH], check=True)

def get_novel_title(novel_url):
    response = requests.get(novel_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    title_tag = soup.find("title")
    if title_tag:
        title_text = title_tag.text.strip()
        title_text = re.sub(r'\s*[-ー]?\s*\u30ab\u30af\u30e8\u30e0.*$', '', title_text)
        return title_text
    else:
        return "\u30bf\u30a4\u30c8\u30eb\u306a\u3057"

def get_episode_links(novel_url):
    response = requests.get(novel_url)
    response.raise_for_status()
    body = response.text
    print("\u5c0f\u8aac\u60c5\u5831\u3092\u53d6\u5f97\u4e2d...")
    ep_pattern = r'"__typename":"Episode","id":"(.*?)","title":"(.*?)"'
    matches = re.findall(ep_pattern, body)
    if not matches:
        print("\u6307\u5b9a\u3055\u308c\u305f\u30da\u30fc\u30b8\u304b\u3089\u30a8\u30d4\u30bd\u30fc\u30c9\u60c5\u5831\u3092\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002")
        return []
    base_url_match = re.match(r"(https://kakuyomu.jp/works/\d+)", novel_url)
    if not base_url_match:
        print("\u5c0f\u8aac\u306eURL\u304b\u3089\u30d9\u30fc\u30b9URL\u3092\u62bd\u51fa\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002")
        return []
    base_url = base_url_match.group(1)
    episode_links = []
    for ep_id, ep_title in matches:
        full_url = f"{base_url}/episodes/{ep_id}"
        episode_links.append((full_url, ep_title))
    print(f"{len(episode_links)} \u8a71\u306e\u76ee\u6a19\u60c5\u5831\u3092\u53d6\u5f97\u3057\u307e\u3057\u305f\u3002")
    return episode_links

def split_text_for_translation(text, max_chunk_len=1500):
    import regex as re
    pattern = r'(.*?[。！？])(?=(?![^「」]*」)(?![^『』]*』)(?![^【】]*】)(?![^（）]*）))'
    sentences = re.findall(pattern, text, flags=re.DOTALL)
    chunks = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) > max_chunk_len or current.count('。') >= 10:
            if current:
                chunks.append(current.strip())
            current = sent
        else:
            current += sent
    if current:
        chunks.append(current.strip())
    return chunks

def translate_text(text):
    chunks = split_text_for_translation(text)
    translated = []
    for chunk in chunks:
        try:
            result = subprocess.run(
                ['deepl', '--to', 'EN', '--formality', 'prefer-less', '-'],
                input=chunk, text=True, capture_output=True, check=True
            ).stdout.strip()
            if re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', result):
                retry = subprocess.run(
                    ['deepl', '--to', 'EN', '--formality', 'prefer-less', '-'],
                    input=chunk, text=True, capture_output=True, check=True
                ).stdout.strip()
                if not re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', retry):
                    result = retry
            translated.append(result)
        except Exception as e:
            print(f"\u7ffb\u8a33\u30a8\u30e9\u30fc: {e}")
            translated.append("[TRANSLATION FAILED]")
    return "\n\n".join(translated)

def download_episode(episode_url, title, novel_title, index):
    response = requests.get(episode_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    body = soup.select_one("div.widget-episodeBody").get_text("\n", strip=True)
    folder_num = (index // 999) + 1
    folder_name = f"{folder_num:03d}"
    safe_novel_title = re.sub(r'[\\/*?:"<>|]', '_', novel_title)[:30]
    base_folder_path = os.path.join(DOWNLOAD_DIR_BASE, safe_novel_title, folder_name)
    jp_path = os.path.join(base_folder_path, 'japanese')
    en_path = os.path.join(base_folder_path, 'english')
    os.makedirs(jp_path, exist_ok=True)
    os.makedirs(en_path, exist_ok=True)
    file_name = f"{index + 1:03d}.txt"
    jp_file = os.path.join(jp_path, file_name)
    en_file = os.path.join(en_path, file_name)
    with open(jp_file, "w", encoding="utf-8") as f:
        f.write(body)
    translated = translate_text(body)
    with open(en_file, "w", encoding="utf-8") as f:
        f.write(translated)
    if (index + 1) % 300 == 0:
        print(f"{index + 1}\u8a71\u30c0\u30a6\u30f3\u30ed\u30fc\u30c9\u5b8c\u4e86\u300230\u79d2\u306e\u4f11\u61a9\u3092\u53d6\u308a\u307e\u3059...")
        time.sleep(30)

def download_novels(urls, history):
    for novel_url in urls:
        try:
            print(f'\n--- \u51e6\u7406\u958b\u59cb: {novel_url} ---')
            novel_title = get_novel_title(novel_url)
            novel_title = re.sub(r'[\\/*?:"<>|]', '', novel_title).strip()
            episode_links = get_episode_links(novel_url)
            download_from = history.get(novel_url, 0)
            new_max = download_from
            for i, (episode_url, episode_title) in enumerate(episode_links):
                if i + 1 <= download_from:
                    continue
                print(f"{i + 1:03d}_{episode_title} downloading...")
                download_episode(episode_url, episode_title, novel_title, i)
                new_max = i + 1
            history[novel_url] = new_max
        except Exception as e:
            print(f"\u30a8\u30e9\u30fc\u767a\u751f: {novel_url} \u2192 {e}")
            continue

if __name__ == "__main__":
    script_dir = os.path.dirname(__file__)
    url_file_path = os.path.join(script_dir, 'カクヨム.txt')
    with open(url_file_path, 'r', encoding='utf-8') as f:
        urls = [line.strip().rstrip('/') for line in f if line.strip().startswith('http')]
    history = load_history()
    download_novels(urls, history)
    save_history(history)
    subprocess.run([
        'rclone', 'copy', '/tmp/kakuyomu_dl', 'drive:',
        '--transfers=4', '--checkers=8', '--fast-list'
    ], check=True)
