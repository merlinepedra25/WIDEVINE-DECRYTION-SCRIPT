# Standard
import uuid
# Custom
from modules import Module
from downloaders.m3u8 import M3U8


class DISNEYPLUS(Module):

    def __init__(self, config, args):
        # Store various stuff to the parent class object
        self.args = args
        self.config = config
        self.source_tag = "DSNP"
        self.origin = "www.disneyplus.com"
        # call base __init__
        Module.__init__(self)

    def get_titles(self):
        device_assertion_key = self.session.post(
            url=self.config.endpoints.devices,
            json={
                "deviceFamily": "browser",
                "applicationRuntime": "chrome",
                "deviceProfile": "windows",
                "attributes": {}
            },
            headers={
                "authorization": f"Bearer {self.config.device_api_key}"
            }
        ).json()["assertion"]
        device_exchange_access_token = self.session.post(
            url=self.config.endpoints.token,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "latitude": 0, "longitude": 0,
                "platform": "browser",
                "subject_token": device_assertion_key,
                "subject_token_type": "urn:bamtech:params:oauth:token-type:device"
            },
            headers={
                "TE": "Trailers",
                "Referer": "https://www.disneyplus.com/nl/login/password",
                "authorization": f"Bearer {self.config.device_api_key}",
                "Accept": "application/json",
                "x-bamsdk-version": "3.10",
                "x-bamsdk-platform": "windows"
            }
        ).json()
        if "error" in device_exchange_access_token:
            raise Exception(f"Failed to login, {device_exchange_access_token['error']}, "
                            f"{device_exchange_access_token['error_description']}")
        device_exchange_access_token = device_exchange_access_token["access_token"]
        login = self.get_login()
        login_bearer = self.session.post(
            url=self.config.endpoints.login,
            json={
                "email": login[0],
                "password": login[1]
            },
            headers={
                "TE": "Trailers",
                "Referer": "https://www.disneyplus.com/login/password",
                "authorization": "Bearer " + device_exchange_access_token,
                "Accept": "application/json; charset=utf-8",
                "x-bamsdk-version": "3.10",
                "x-bamsdk-platform": "windows"
            }
        ).json()
        if "errors" in login_bearer:
            raise Exception(f"Failed to login, {login_bearer['errors'][0]['code']}, "
                            f"{login_bearer['errors'][0]['description']}")
        login_bearer = login_bearer["id_token"]
        grant_bearer = self.session.post(
            url=self.config.endpoints.grant,
            json={"id_token": login_bearer},
            headers={
                "TE": "Trailers",
                "Referer": "https://www.disneyplus.com/login/password",
                "authorization": "Bearer " + device_exchange_access_token,
                "Accept": "application/json; charset=utf-8",
                "x-bamsdk-version": "3.10",
                "x-bamsdk-platform": "windows"
            }
        ).json()["assertion"]
        self.account_exchange_access_token = self.session.post(
            url=self.config.endpoints.token,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "latitude": 0,
                "longitude": 0,
                "platform": "browser",
                "subject_token": grant_bearer,
                "subject_token_type": "urn:bamtech:params:oauth:token-type:account"
            },
            headers={
                "TE": "Trailers",
                "Referer": "https://www.disneyplus.com/nl/login/password",
                "authorization": f"Bearer {self.config.device_api_key}",
                "Accept": "application/json",
                "x-bamsdk-version": "3.10",
                "x-bamsdk-platform": "windows"
            }
        ).json()["access_token"]
        print("Logged into Disney+ and obtained all required tokens")

        # ====================================================== #
        # 2. Ask Disney Dmc Video Bundle Endpoint for content information
        # ====================================================== #
        print("Asking Disney+ for the title manifest...")
        dmc_bundle_url = "https://search-api-disney.svcs.dssott.com/svc/search/v2/graphql/persisted/query/core/Dmc" + \
                         ("Video" if self.args.movie else "Series") + \
                         "Bundle?variables=%7B%22preferredLanguage%22%3A%5B%22en%22%2C%22nl%22%5D%2C%22" + \
                         ("family" if self.args.movie else "series") + f"Id%22%3A%22{self.args.title}%22" + \
                         ("%2C%22episodePageSize%22%3A12" if not self.args.movie else "") + \
                         f"%2C%22contentTransactionId%22%3A%22{uuid.uuid4()}%22%7D"
        dmc_bundle = self.session.get(
            url=dmc_bundle_url,
            headers={
                "authorization": "Bearer " + device_exchange_access_token
            }
        ).json()
        dmc_bundle = dmc_bundle["data"]["Dmc" + ("Video" if self.args.movie else "Series") + "Bundle"]

        # Get Filename
        self.title_name = [x for x in (dmc_bundle["video"] if self.args.movie else dmc_bundle["series"])["texts"] if
                           x["field"] == "title" and x["type"] == "full" and x["language"] == "en"][0]["content"]
        self.titles = [dmc_bundle["video"]] if self.args.movie else dmc_bundle["episodes"]["videos"]
        if not self.titles:
            raise Exception("No titles returned!")

    def get_title_information(self, title):
        season = title["seasonSequenceNumber"] if not self.args.movie else 0
        episode = title["episodeSequenceNumber"] if not self.args.movie else 0
        # dmc_bundle["video"]["releases"][0]["releaseYear"]
        title_year = title["releases"][0]["releaseYear"] if self.args.movie else None
        episode_name = [x for x in title["texts"]
                        if x["field"] == "title" and
                        x["type"] == "full" and
                        x["sourceEntity"] == "program" and
                        x["language"] == "en"][0]["content"] if not self.args.movie else None
        return season, episode, title_year, episode_name

    def get_title_tracks(self, title):
        # this is web api, restricted to 720p, some sd content get restricted to 384p when >384p is available
        restricted_drm_ctr_sw = self.session.get(
            url=f"https://us.edge.bamgrid.com/media/{title['mediaId']}/scenarios/{self.args.ctr}",
            headers={
                "TE": "Trailers",
                "Referer": "https://www.disneyplus.com/nl/video/4da34214-4803-4c80-8e66-b9b4b46e1bf8",
                "authorization": self.account_exchange_access_token,
                "Accept": "application/vnd.media-service+json; version=2",
                "x-bamsdk-version": "3.10",
                "x-bamsdk-platform": "windows"
            }
        ).json()
        # ================================ #
        # 2d. Parse Received Playback M3U8
        # ================================ #
        master = M3U8(self.session)
        master.load(restricted_drm_ctr_sw["stream"]["complete"])

        # ========================================================== #
        # 2e. Parse M3U8 and select tracks based on what's available
        # ========================================================== #
        bitrates, streams = master.getStreams()
        stream = streams[bitrates[0]]
        for bitrate in bitrates:
            rep = streams[bitrate].copy()
            del rep["VIDEO"]
            rep["AUDIO"] = rep["AUDIO"]["CODEC"]
            rep["SUBTITLES"] = ",".join([x["NAME"] for x in rep["SUBTITLES"]])
        # Video
        videos = []
        for i, rep in enumerate(streams):
            bitrate = rep
            rep = streams[bitrate]
            videos.append({
                "id": i,
                "type": "video",
                "encrypted": True,
                # todo ; this should be gotten from the MPD or Playback Manifest
                "language": None,
                "track_name": None,
                "m3u8": rep["VIDEO"],
                "downloader": "m3u8",
                "codec": rep["CODEC"],
                "bitrate": bitrate,
                "width": rep['RESOLUTION'].split('x')[0],
                "height": rep['RESOLUTION'].split('x')[1],
                "default": True,
                "fix": True,
                "info": {
                    "fps": rep["FRAMERATE"]
                }
            })
        # Audio
        audio = []
        for i, rep in enumerate(stream["AUDIO"]["STREAMS"]):
            audio.append({
                "id": i,
                "type": "audio",
                "encrypted": True,
                "language": rep["LANGUAGE"],
                "track_name": rep["NAME"],
                "m3u8": rep["URI"],
                "downloader": "m3u8",
                "codec": rep["GROUP-ID"],
                "default": rep["LANGUAGE"] == "en",
                "fix": False
            })
        # Subtitles
        subtitles = []
        for i, sub in enumerate(stream["SUBTITLES"]):
            subtitles.append({
                "id": i,
                "type": "subtitle",
                "encrypted": False,
                "language": sub["LANGUAGE"],
                "track_name": sub["LANGUAGE"],
                "m3u8": sub["URI"],
                "downloader": "m3u8",
                "codec": "vtt",
                "default": sub["LANGUAGE"] == "en",  # todo ; this will set every subtitle as default, this is bad!!!
                "fix": False
            })
        self.widevine_cdm.pssh = [x for x in master.getSessionKeys() if x["KEYFORMAT"] ==
                                  "urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"][0]["URI"].split(',')[-1]
        return videos, audio, subtitles

    def certificate(self, title, challenge):
        return self.license(title, challenge)

    def license(self, title, challenge):
        import base64
        return base64.b64encode(self.session.post(
            url=self.config.endpoints.licence,
            headers={
                "TE": "Trailers",
                "Referer": "https://www.disneyplus.com/nl/video/4da34214-4803-4c80-8e66-b9b4b46e1bf8",
                "authorization": self.account_exchange_access_token,
                "Accept": "application/vnd.media-service+json; version=2",
                "x-bamsdk-version": "3.10",
                "x-bamsdk-platform": "windows"
            },
            data=base64.b64decode(challenge)  # needs to be raw/bytes
        ).content)
