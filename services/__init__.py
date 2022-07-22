# Standard Libraries
import os.path
import requests
import re
import subprocess
import time
import unicodedata
from collections import namedtuple, Sequence
# PyPI Dependencies
import pycaption
import pycountry
import urllib3
from tqdm import tqdm
# Custom Scripts
import config as appcfg

class Service:

    # stubbed, set by an inheriting class, just here to prevent linter warnings
    # we can't pop these in __init__ or it will overwrite whats passed by the inheritor
    args = None
    source_tag = None
    origin = None

    def __init__(self):
        # settings
        appcfg.common_headers["Origin"] = f"https://{self.origin}"
        # create a requests session
        self.session = self.get_session()
        # create a widevine cdm
        self.widevine_cdm = self.get_cdm()
        # title data
        self.title_name = ""
        self.titles = []
        # tracks
        self.tracks = namedtuple("_", "selected videos audio subtitles")
        self.tracks.selected = namedtuple("_", "video audio subtitles")
        self.tracks.selected.audio = []
        self.tracks.selected.subtitles = []
        self.tracks.videos = []
        self.tracks.audio = []
        self.tracks.subtitles = []
        # let's fucking go!
        print(f"Retrieving Titles from {self.args.service} for '{self.args.title}'...")
        self.get_titles()
        if not self.args.movie:
            print(f"{len(self.titles)} Titles for {self.title_name} received...")
        for title in self.titles:
            season, episode, title_year, episode_name = self.get_title_information(title)
            # Is this a requested title or should it be skipped?
            if not self.args.movie and \
                    (self.args.season is not None and season != self.args.season) or \
                    (self.args.skip is not None and episode <= self.args.skip) or \
                    (self.args.episode is not None and episode != self.args.episode):
                continue
            # Parse a filename
            self.filename = self.title_name + " "
            if season and episode and episode_name:
                self.filename += f"S{str(season).zfill(2)}E{str(episode).zfill(2)}.{episode_name}"
            else:
                self.filename += str(title_year)
            self.filename = re.sub(r"[\\*!?,'’\"()<>:|]", "", "".join(
                (c for c in unicodedata.normalize(
                    "NFD",
                    self.filename + f".{self.source_tag}.WEB-DL-PHOENiX"
                ) if unicodedata.category(c) != "Mn")
            )).replace(" ", ".").replace(".-.", ".").replace("/", ".&.").replace("..", ".")
            print(f"Downloading to \"{self.filename}\"")
            # Get Tracks for the current Title
            videos, audio, subtitles = self.get_title_tracks(title)
            self.tracks.videos = [Track(x) for x in videos]
            self.tracks.audio = [Track(x) for x in audio]
            self.tracks.subtitles = [Track(x) for x in subtitles]
            self.list_tracks()
            if self.widevine_cdm.IDENTITY == "widevine_cdm_api":
                self.widevine_cdm.title_id = self.args.title
                self.widevine_cdm.title_type = "MOVIE" if self.args.movie else "EPISODE"
                self.widevine_cdm.season = season
                self.widevine_cdm.episode = episode
            elif self.widevine_cdm.IDENTITY == "widevine_cdm":
                self.widevine_cdm.certificate = lambda challenge: self.certificate(title, challenge)
                self.widevine_cdm.license = lambda challenge: self.license(title, challenge)
            if self.args.keys:
                import json
                print(json.dumps(self.widevine_cdm.get_decryption_keys()))
                continue
            # start process of downloading the content
            if not isinstance(self.tracks.videos, list) or len(self.tracks.videos) == 0:
                raise Exception("No video track to download...")
            if not isinstance(self.tracks.audio, list) or len(self.tracks.audio) == 0:
                raise Exception("No audio tracks to download...")
            # Cleanup interrupted files from a previous session
            self.cleanup()
            # Download tracks
            video_track, audio_tracks, subtitle_tracks = self.select_tracks()
            self.download_tracks(video_track, audio_tracks, subtitle_tracks)
            # Decrypt encrypted tracks if cdm addon exists
            encrypted_tracks = [t for t in ([video_track] + audio_tracks) if t.encrypted]
            if not encrypted_tracks:
                raise Exception("No tracks provided are encrypted, this isn't right! Aborting!")
            # Create a Command Line argument list for mp4decrypt containing all the decryption keys
            cl = ["mp4decrypt"]
            for key in self.widevine_cdm.get_decryption_keys():
                cl.append("--key")
                cl.append(key)
            for track in encrypted_tracks:
                print(f"Decrypting {track.type} track #{track.id + 1}...")
                t_cl = cl.copy()
                t_cl.extend([
                    appcfg.filenames.encrypted.format(
                        filename=self.filename,
                        track_type=track.type,
                        track_no=track.id
                    ),
                    appcfg.filenames.decrypted.format(
                        filename=self.filename,
                        track_type=track.type,
                        track_no=track.id
                    )
                ])
                subprocess.Popen(
                    t_cl,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT
                ).wait()
            print("Decrypted all tracks")
            for track in ([video_track] + audio_tracks + subtitle_tracks):
                if track.fix:
                    original_file = appcfg.filenames.decrypted.format(
                        filename=self.filename,
                        track_type=track.type,
                        track_no=track.id
                    )
                    print(f"Fixing {os.path.basename(original_file)} via FFMPEG")
                    fixed_file = (appcfg.filenames.decrypted + "_fixed.mkv").format(
                        filename=self.filename,
                        track_type=track.type,
                        track_no=track.id
                    )
                    subprocess.run([
                        "ffmpeg", "-hide_banner",
                        "-loglevel", "panic",
                        "-i", original_file,
                        "-codec", "copy",
                        fixed_file
                    ])
                    os.remove(original_file)
                    os.rename(fixed_file, original_file)
            # Mux Tracks
            self.mux(video_track, audio_tracks, subtitle_tracks)
            # Cleanup
            self.cleanup()
        print("Processed all titles...")

    # stubs
    # these should be defined by the service
    # just here to prevent linter warnings
    def get_titles(self):
        pass

    def get_title_information(self, title):
        return 0, 0, 0, ""

    def get_title_tracks(self, title):
        return [], [], []

    def certificate(self, title, challenge):
        return None

    def license(self, title, challenge):
        return None

    def get_session(self):
        """
        Creates requests session, disables certificate verification (and it's warnings), and adds any proxies, headers
        and cookies that may exist.
        :return: prepared request session
        """
        session = requests.Session()
        session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        if self.args.proxy:
            session.proxies.update({"https": f"http://{self.args.proxy}"} if isinstance(self.args.proxy, str) else
                                    self.args.proxy)
        session.headers.update(appcfg.common_headers)
        session.cookies.update(self.get_cookies())
        return session

    def get_cookies(self):
        """
        Obtain cookies for the given profile
        :return: dictionary list of cookies
        """
        cookie_file = os.path.join(
            appcfg.directories.cookies,
            self.args.service,
            self.args.profile + ".txt"
        )
        cookies = {}
        if os.path.exists(cookie_file) and os.path.isfile(cookie_file):
            with open(cookie_file, "r") as f:
                for l in f:
                    if not re.match(r"^#", l) and not re.match(r"^\n", l):
                        line_fields = l.strip().split('\t')
                        cookies[line_fields[5]] = line_fields[6]
                print(f"Loaded cookies from Profile: \"{self.args.profile}\"")
        return cookies

    def get_login(self):
        """
        If login data exists, return them
        :return: login data as a list, 0 = user, 1 = password
        """
        # self.session.cookies.get_dict()["vt_user"] ["vt_pass"] from profiles as a cookie file instead maybe
        data_file = os.path.join(appcfg.directories.login, self.args.service, self.args.profile + ".txt")
        if not os.path.exists(data_file) or not os.path.isfile(data_file):
            return None
        with open(data_file, 'r') as f:
            for l in [x for x in f if ":" in x]:
                return l.strip().split(':')

    def get_cdm(self):
        """
        Attempt to load a Widevine CDM handler if one exists, throws FileNotFoundError on fail
        :return: CDM Handler
        """
        for addon in ['widevine_cdm', 'widevine_cdm_api']:
            try:
                addon_import = __import__("utils.cdms." + addon, globals(), locals(), [addon], 0)
                print(f"Created a Widevine CDM Object using {addon}")
                if addon == "widevine_cdm":
                    return addon_import.AddOn(os.path.join(appcfg.directories.cdm_devices, self.args.cdm))
                elif addon == "widevine_cdm_api":
                    return addon_import.AddOn(
                        service=self.args.service,
                        profile=self.args.profile,
                        device=self.args.cdm,
                        proxy=self.args.proxy or None
                    )
            except ImportError:
                pass
        raise ImportError(
            "Cannot create a widevine cdm instance, a widevine cdm addon is required but none are found.")

    def cleanup(self):
        """
        Delete all files from the temporary data directory, including the directory itself
        """
        if os.path.exists(appcfg.directories.temp):
            for f in os.listdir(appcfg.directories.temp):
                os.remove(os.path.join(appcfg.directories.temp, f))
            os.rmdir(appcfg.directories.temp)

    def mux(self, video_track, audio_tracks, subtitle_tracks):
        """
        Takes the Video, Audio and Subtitle Tracks, and muxes them into an MKV file.
        It will attempt to detect Forced/Default tracks, and will try to parse the language codes of the Tracks
        """
        print("Muxing Video, Audio and Subtitles to an MKV")
        # Initialise the Command Line Arguments for MKVMERGE
        cl = [
            "mkvmerge",
            "-q",
            "--output",
            appcfg.filenames.muxed.format(filename=self.filename)
        ]
        # Add the Video Track
        cl = cl + [
            "--language", "0:und",
            "(", appcfg.filenames.decrypted.format(
                filename=self.filename,
                track_type=video_track.type,
                track_no=video_track.id
            ), ")"
        ]
        # Add the Audio Tracks
        for at in audio_tracks:
            # todo ; 0: track id may need to be properly offset
            if at.track_name:
                cl = cl + ["--track-name", "0:" + at.track_name]
            cl = cl + [
                "--language", ("0:" + pycountry.languages.lookup(at.language.lower().split('-')[0]).alpha_3),
                "(", appcfg.filenames.decrypted.format(
                    filename=self.filename,
                    track_type=at.type,
                    track_no=at.id
                ), ")"
            ]
        # Add the Subtitle Tracks
        if subtitle_tracks is not None:
            for st in subtitle_tracks:
                forced = ("yes" if st.track_name and "forced" in st.track_name.lower() else "no")
                lang_code = st.language.lower().split('-')[0]
                try:
                    lang_code = pycountry.languages.get(alpha_2=lang_code).bibliographic
                except AttributeError:
                    pass
                # todo ; 0: track id may need to be properly offset
                if st.track_name:
                    cl = cl + ["--track-name", "0:" + st.track_name]
                cl = cl + [
                    "--language", "0:" + lang_code,
                    "--sub-charset", "0:UTF-8",
                    "--forced-track", "0:" + forced,
                    "--default-track", "0:" + ("yes" if (st.default or forced == "yes") else "no"),
                    "(", appcfg.filenames.subtitles.format(
                        filename=self.filename,
                        language_code=st.language,
                        id=st.id
                    ), ")"
                ]
        # Run MKVMERGE with the arguments
        subprocess.run(cl)
        print("Muxed")

    def download_tracks(self, video_track, audio_tracks, subtitle_tracks):
        """
        Takes the Video, Audio and Subtitle Tracks, and download them.
        If needed, it will convert the subtitles to SRT.
        """
        os.makedirs(appcfg.directories.temp)
        if not os.path.exists(appcfg.directories.output):
            os.makedirs(appcfg.directories.output)
        # Download Video, Audio and Subtitle Tracks
        for track in [video_track] + audio_tracks + subtitle_tracks:
            filename = appcfg.filenames.encrypted if track.encrypted else appcfg.filenames.decrypted
            filename = filename.format(filename=self.filename, track_type=track.type, track_no=track.id)
            print(f"Downloading {track.type} track #{track.id + 1}...")
            if track.downloader == "curl":
                curl = [
                    "curl",
                    "-o", filename,
                    "--url", track.url
                ]
                #if self.args.proxy:
                #    curl.append("--proxy")
                #    curl.append(list(self.args.proxy.values())[0])
                if track.size:
                    curl.append("--range")
                    curl.append(f"0-{track.size}")
                failures = 0
                while subprocess.run(curl).returncode != 0:
                    failures += 1
                    if failures == 5:
                        print("Curl failed too many time's. Aborting.")
                        exit(1)
                    print(f"Curl failed, retrying in {3 * failures} seconds...")
                    time.sleep(3 * failures)
            elif track.downloader == "youtube-dl":
                from utils.parsers.youtube_dl import YoutubeDL
                with YoutubeDL({
                    "listformats": False,
                    "format": "best" + track.type + (
                            f"[format_id*={track.arguments['format_id']}]"
                            if "format_id" in track.arguments else ""),
                    "output": filename,
                    "retries": 25,
                    "fixup": "never",
                    "outtmpl": filename,
                    "force_generic_extractor": True,
                    "no_warnings": True
                }) as ydl:
                    ydl.download([track.url])
            elif track.downloader == "m3u8":
                from utils.parsers.m3u8 import M3U8
                m3u8 = M3U8(self.session)
                m3u8.load(track.m3u8)
                f = open(filename, "wb")
                for i in tqdm(m3u8.media_segment, unit="segments"):
                    try:
                        if "EXT-X-MAP" in i:
                            f.write(self.session.get(m3u8.get_full_url(i["EXT-X-MAP"]["URI"])).content)
                        f.write(self.session.get(m3u8.get_full_url(i["URI"])).content)
                    except requests.exceptions.RequestException as e:
                        print(e)
                        exit(1)
                f.close()
            else:
                print(f"{track.downloader} is an invalid downloader")
                exit(1)
            if track.type == "subtitle":
                with open(filename, "r") as sc:
                    s = sc.read()
                    if track.codec == "dfxp":
                        s = pycaption.SRTWriter().write(pycaption.DFXPReader().read(s.replace('tt:', '')))
                    elif track.codec == "vtt":
                        try:
                            s = pycaption.SRTWriter().write(
                                pycaption.WebVTTReader().read(
                                    s.replace('\r', '').replace('\n\n\n', '\n \n\n').replace('\n\n<', '\n<')
                                )
                            )
                        except pycaption.exceptions.CaptionReadSyntaxError:
                            print("Syntax error occurred with the subtitle file, is the subtitle invalid?")
                            exit(1)
                    elif track.codec != "srt":
                        print("Unknown Subtitle Format. Aborting.")
                        exit(1)
                    with open(appcfg.filenames.subtitles.format(
                            filename=self.filename,
                            language_code=track.language,
                            id=track.id
                    ), 'w', encoding='utf-8') as f:
                        f.write(s)
        print("Downloaded")

    def select_tracks(self):
        # Video
        # let's just take the best bitrate track of the requested resolution (or best resolution)
        if self.args.quality is not None:
            selected_video = sorted([x for x in self.tracks.videos if
                                     x.height == self.args.quality or
                                     x.width == int((self.args.quality / 9) * 16)],
                                    key=lambda x: x.bitrate,
                                    reverse=True)
            if selected_video:
                selected_video = selected_video[0]
            else:
                print(f"There's no {self.args.quality}p resolution video track. Aborting.")
                exit(1)
        else:
            selected_video = sorted(self.tracks.videos, key=lambda x: int(x.bitrate), reverse=True)[0]
        # Audio
        # we are only selecting the best audio track, perhaps there's multiple tracks of interest?
        selected_audio = [sorted(
            sorted(
                self.tracks.audio,
                key=lambda x: ("" if x.language == "en" else (x.language if x.language else "")),
                reverse=False
            ),
            key=lambda x: (int(x.bitrate) if x.bitrate else 0),
            reverse=True
        )[0]]
        # Subtitle Track Selection
        # don't need to do anything, as we want all of them

        # print the string representations
        print("Selected Tracks:")
        for track in [selected_video] + selected_audio + self.tracks.subtitles:
            print(track)
        return selected_video, selected_audio, self.tracks.subtitles

    def order_tracks(self, tracks):
        sort = sorted(
            sorted(
                tracks,
                key=lambda x: ("" if x.language == "en" else x.language) if x.language else ""
            ),
            key=lambda x: x.bitrate if x.bitrate else 0,
            reverse=True
        )
        for i, _ in enumerate(sort):
            sort[i].id = i
        return sort

    def list_tracks(self):
        self.tracks.videos = self.order_tracks(self.tracks.videos)
        self.tracks.audio = self.order_tracks(self.tracks.audio)
        self.tracks.subtitles = self.order_tracks(self.tracks.subtitles)
        for track in self.tracks.videos + self.tracks.audio + self.tracks.subtitles:
            if track.id == 0:
                count = len(self.tracks.videos if track.type == 'video' else self.tracks.audio
                if track.type == 'audio' else self.tracks.subtitles)
                print(f"{count} {track.type.title()} Tracks:")
            print(track)

    def flatten(self, l):
        return list(self.flatten_g(l))

    def flatten_g(self, l):
        basestring = (str, bytes)
        for el in l:
            if isinstance(el, Sequence) and not isinstance(el, basestring):
                for sub in self.flatten_g(el):
                    yield sub
            else:
                yield el


class Track:

    def __init__(self, arguments):
        self.id = arguments["id"] if "id" in arguments else None
        self.type = arguments["type"] if "type" in arguments else None
        self.encrypted = bool(arguments["encrypted"]) if "encrypted" in arguments else None
        self.language = arguments["language"] if "language" in arguments else None
        self.track_name = arguments["track_name"] if "track_name" in arguments else None
        self.size = int(arguments["size"]) if "size" in arguments else None
        self.url = arguments["url"] if "url" in arguments else None
        self.m3u8 = arguments["m3u8"] if "m3u8" in arguments else None
        self.codec = arguments["codec"] if "codec" in arguments else None
        self.bitrate = int(arguments["bitrate"]) if "bitrate" in arguments else None
        self.width = int(arguments["width"]) if "width" in arguments else None
        self.height = int(arguments["height"]) if "height" in arguments else None
        self.default = bool(arguments["default"]) if "default" in arguments else None
        self.fix = bool(arguments["fix"]) if "fix" in arguments else False
        self.info = arguments["info"] if "info" in arguments else {}
        # optional
        self.downloader = arguments["downloader"] if "downloader" in arguments else "curl"
        self.arguments = arguments["arguments"] if "arguments" in arguments else {}

    def __str__(self):
        if self.type == "video":
            return f"{self.type.upper()[:3]} | BR: {self.bitrate} - " \
                   f"{self.width}x{self.height}{(' @ ' + self.info['fps'] if 'fps' in self.info else '')} / " \
                   f"{self.codec}"
        if self.type == "audio":
            return f"{self.type.upper()[:3]} | BR: {self.bitrate} - " \
                   f"{self.language} / {self.codec}"
        if self.type == "subtitle":
            return f"{self.type.upper()[:3]} | Language: {self.language} / {self.track_name}"
