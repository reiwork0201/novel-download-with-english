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

deepl = DeepLCLI("ja", "en")  # 日本語→英語

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
        jp_base = f'{base_path}/japanese'
        en_base = f'{base_path}/english'
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
            jp_folder = f'{jp_base}/{folder_name}'
            en_folder = f'{en_base}/{folder_name}'
            os.makedirs(jp_folder, exist_ok=True)
            os.makedirs(en_folder, exist_ok=True)

            jp_file_path = f'{jp_folder}/{file_name}'
            en_file_path = f'{en_folder}/{file_name}'

            res = fetch_url(f'{BASE_URL}{link}')
            soup = BeautifulSoup(res.text, 'html.parser')
            sub_body = soup.select_one('.p-novel__body')
            sub_body_text = sub_body.get_text() if sub_body else '[本文が取得できませんでした]'

            # 日本語保存
            with open(jp_file_path, 'w', encoding='UTF-8') as f:
                f.write(f'{sub_title}\n\n{sub_body_text}')

            # 英訳生成
            try:
                en_text = deepl.translate(sub_body_text)
            except Exception as e:
                en_text = '[翻訳に失敗しました]'
                print(f'翻訳エラー: {e}')

            # 英語保存
            with open(en_file_path, 'w', encoding='UTF-8') as f:
                f.write(f'{sub_title}\n\n{en_text}')

            print(f'{file_name} downloaded & translated in folder {folder_name} ({i+1}/{sub_len})')
            new_max = i + 1

        history[novel_url] = new_max

    except Exception as e:
        print(f'エラー発生: {novel_url} → {e}')
        continue

save_history(history)

# Google Driveへアップロード
subprocess.run(['rclone', 'copy', '/tmp/narou_dl', 'drive:', '--transfers=4', '--checkers=8', '--fast-list'], check=True)
