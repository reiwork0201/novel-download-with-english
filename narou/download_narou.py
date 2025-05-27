import subprocess

class DeepLCLI:
    def __init__(self, source_lang, target_lang):
        self.source = source_lang
        self.target = target_lang

    def translate(self, text):
        result = subprocess.run(
            ['deepl', 'translate', '-s', self.source, '-t', self.target],
            input=text, text=True, capture_output=True, check=True
        )
        return result.stdout.strip()
