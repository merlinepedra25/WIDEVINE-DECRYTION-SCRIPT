# Standard Libraries
import os
from collections import namedtuple

class Directories:
    def __init__(self):
        self.base_dir = os.getcwd()
        self.data = os.path.join(self.base_dir, "data")
        self.configuration = os.path.join(self.base_dir, "config")
        self.output = os.path.join(self.base_dir, "Downloads")
        self.temp = os.path.join(self.data, ".tmp")
        self.cookies = os.path.join(self.data, "Cookies")
        self.login = os.path.join(self.data, "Login")
        self.cdm_devices = os.path.join(self.data, "CDM_Devices")
directories = Directories()
class Filenames:
    def __init__(self):
        self.track = "{filename}_{track_type}_{track_no}_"
        self.subtitles = os.path.join(directories.temp, "{filename}_subtitles_{language_code}_{id}.srt")
        self.encrypted = os.path.join(directories.temp, f"{self.track}encrypted.mp4")
        self.decrypted = os.path.join(directories.temp, f"{self.track}decrypted.mp4")
        self.muxed = os.path.join(directories.output, "{filename}.mkv")
filenames = Filenames()
class Proxies:
    def __init__(self):
        self.us = {"https": ""}
        self.ca = self.us
        self.de = None
        self.uk = None
        self.jp = None
proxies = Proxies()
common_headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/77.0.3865.75 Safari/537.36',
    'Accept': 'application/json',
    'Accept-Encoding': 'gzip, deflate, br',
    'Accept-Language': 'en-US,en;q=0.8'
}
iso639_2 = {
    'English': 'eng',
    'Spanish': 'spa',
    'European Spanish': 'spa',
    'Brazilian Portuguese': 'por',
    'Polish': 'pol',
    'Turkish': 'tur',
    'French': 'fre',
    'German': 'ger',
    'Italian': 'ita',
    'Czech': 'cze',
    'Japanese': 'jpn',
    'Hebrew': 'heb',
    'Norwegian': 'nor'
}
