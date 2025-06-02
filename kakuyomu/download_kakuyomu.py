import os
import re
import time
import requests
import subprocess
from bs4 import BeautifulSoup
from deepl import DeepLCLI  # 自作のCLIラッパー

BASE_URL = "https://kakuyomu.jp"
HISTORY_FILE = "カクヨムダウンロード経歴.txt"
LOCAL_HISTORY_PATH = f"/tmp/{HISTORY_FILE}"
REMOTE_HISTORY_PATH = f"drive:{HISTORY_FILE}"
DOWNLOAD_DIR_BASE = "/tmp/kakuyomu_dl"

DEEPL = DeepLCLI("ja", "en")
DEEPL_RETRY = 3

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
        title_text = re.sub(r'\s*[-ー]?\s*カクヨム.*$', '', title_text)
        return title_text
    else:
        return "タイトルなし"

def get_episode_links(novel_url):
    response = requests.get(novel_url)
    response.raise_for_status()
    body = response.text
    print("小説情報を取得中...")
    ep_pattern = r'"__typename":"Episode","id":"(.*?)","title":"(.*?)"'
    matches = re.findall(ep_pattern, body)
    if not matches:
        print("指定されたページからエピソード情報を取得できませんでした。")
        return []
    base_url_match = re.match(r"(https://kakuyomu.jp/works/\d+)", novel_url)
    if not base_url_match:
        print("小説のURLからベースURLを抽出できませんでした。")
        return []
    base_url = base_url_match.group(1)
    episode_links = [(f"{base_url}/episodes/{ep_id}", ep_title) for ep_id, ep_title in matches]
    print(f"{len(episode_links)} 話のエピソード情報を取得しました。")
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
        for attempt in range(DEEPL_RETRY):
            try:
                result = DEEPL.translate(chunk).strip()
                if re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', result):
                    continue  # 日本語が残っていたら再試行
                translated.append(result)
                break
            except Exception as e:
                print(f"翻訳エラー (試行{attempt + 1}): {e}")
        else:
            translated.append("[TRANSLATION FAILED]")
    return "\n\n".join(translated)

def download_episode(episode_url, title, novel_title, index):
    response = requests.get(episode_url)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    body = soup.select_one("div.widget-episodeBody").get_text("\n", strip=True)
    safe_novel_title = re.sub(r'[\\/*?:"<>|]', '_', novel_title)[:30]
    base_path = os.path.join(DOWNLOAD_DIR_BASE, safe_novel_title, f"{index+1:03d}")
    jp_path = os.path.join(base_path, 'japanese')
    en_path = os.path.join(base_path, 'english')
    os.makedirs(jp_path, exist_ok=True)
    os.makedirs(en_path, exist_ok=True)
    with open(os.path.join(jp_path, "本文.txt"), "w", encoding="utf-8") as f:
        f.write(body)
    translated = translate_text(body)
    with open(os.path.join(en_path, "本文.txt"), "w", encoding="utf-8") as f:
        f.write(translated)
    if (index + 1) % 300 == 0:
        print(f"{index + 1}話ダウンロード完了。30秒の休憩を取ります...")
        time.sleep(30)

def download_novels(urls, history):
    for novel_url in urls:
        try:
            print(f'\n--- 処理開始: {novel_url} ---')
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
            print(f"エラー発生: {novel_url} → {e}")
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
