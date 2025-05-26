import os
import requests
from bs4 import BeautifulSoup
import re
import subprocess
from deepl import DeepLCLI

BASE_URL = 'https://ncode.syosetu.com'
HISTORY_FILE = '小説家になろうダウンロード経歴.txt'
LOCAL_HISTORY_PATH = f'/tmp/{HISTORY_FILE}'
REMOTE_HISTORY_PATH = f'drive:{HISTORY_FILE}'
deepl = DeepLCLI("en", "ja")  # 日本語→英語

def fetch_url(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    return requests.get(url, headers=headers)

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
                    history[url.rstrip('/')] = int(last)
    return history

def save_history(history):
    with open(LOCAL_HISTORY_PATH, 'w', encoding='utf-8') as f:
        for url, last in history.items():
            f.write(f'{url}  |  {last}\n')
    subprocess.run(['rclone', 'copyto', LOCAL_HISTORY_PATH, REMOTE_HISTORY_PATH], check=True)

def split_into_chunks(text, max_length=1500):
    sentences = re.split(r'(?<=[。！？\n])', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) <= max_length:
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = sentence

    if current_chunk:
        chunks.append(current_chunk)

    return chunks

def deepl_translate_chunked(text, max_length=1500):
    chunks = split_into_chunks(text, max_length)
    translated = []
    for chunk in chunks:
        try:
            result = deepl.translate(chunk)
            translated.append(result)
        except Exception as e:
            print(f'翻訳エラー: {e}')
            translated.append('[翻訳失敗]')
    return ''.join(translated)

# スクリプトと同じディレクトリにあるURL一覧ファイル
script_dir = os.path.dirname(__file__)
url_file_path = os.path.join(script_dir, '小説家になろう.txt')
with open(url_file_path, 'r', encoding='utf-8') as f:
    urls = [line.strip().rstrip('/') for line in f if line.strip().startswith('http')]

history = load_history()

for novel_url in urls:
    try:
        print(f'\n--- 処理開始: {novel_url} ---')
        url = novel_url
        sublist = []

        while True:
            res = fetch_url(url)
            soup = BeautifulSoup(res.text, 'html.parser')
            title_text = soup.find('title').get_text()
            sublist += soup.select('.p-eplist__sublist .p-eplist__subtitle')
            next = soup.select_one('.c-pager__item--next')
            if next and next.get('href'):
                url = f'{BASE_URL}{next.get("href")}'
            else:
                break

        for char in ['<', '>', ':', '"', '/', '\\', '|', '?', '*']:
            title_text = title_text.replace(char, '')
        title_text = title_text.strip()

        download_from = history.get(novel_url, 0)
        base_path = f'/tmp/narou_dl/{title_text}'
        jp_base = os.path.join(base_path, 'japanese')
        en_base = os.path.join(base_path, 'english')
        os.makedirs(jp_base, exist_ok=True)
        os.makedirs(en_base, exist_ok=True)

        sub_len = len(sublist)
        new_max = download_from

        for i, sub in enumerate(sublist):
            if i + 1 <= download_from:
                continue

            sub_title = sub.text.strip()
            link = sub.get('href')
            file_name = f'{i+1:03d}.txt'
            folder_num = (i // 999) + 1
            folder_name = f'{folder_num:03d}'
            jp_folder = os.path.join(jp_base, folder_name)
            en_folder = os.path.join(en_base, folder_name)
            os.makedirs(jp_folder, exist_ok=True)
            os.makedirs(en_folder, exist_ok=True)

            jp_file_path = os.path.join(jp_folder, file_name)
            en_file_path = os.path.join(en_folder, file_name)

            res = fetch_url(f'{BASE_URL}{link}')
            soup = BeautifulSoup(res.text, 'html.parser')
            sub_body = soup.select_one('.p-novel__body')
            sub_body_text = sub_body.get_text() if sub_body else '[本文が取得できませんでした]'

            translated_text = deepl_translate_chunked(sub_body_text)

            # 保存（日本語）
            with open(jp_file_path, 'w', encoding='UTF-8') as f:
                f.write(f'{sub_title}\n\n{sub_body_text}')

            # 保存（英語）
            with open(en_file_path, 'w', encoding='UTF-8') as f:
                f.write(f'{sub_title}\n\n{translated_text}')

            print(f'{file_name} downloaded and translated in folder {folder_name} ({i+1}/{sub_len})')
            new_max = i + 1

        history[novel_url] = new_max

    except Exception as e:
        print(f'エラー発生: {novel_url} → {e}')
        continue

save_history(history)

# Google Drive へアップロード
subprocess.run(['rclone', 'copy', '/tmp/narou_dl', 'drive:', '--transfers=4', '--checkers=8', '--fast-list'], check=True)
