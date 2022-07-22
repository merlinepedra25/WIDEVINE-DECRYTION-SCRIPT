# Standard
import base64
# Package Dependencies
import xmltodict
# Custom
from modules import Module


class VIDEOLAND(Module):

    def __init__(self, config, args):
        # Store various stuff to the parent class object
        self.args = args
        self.config = config
        self.source_tag = "VL"
        self.origin = "www.videoland.com"
        # videoland specific globals
        self.vl_lic_url = None
        self.vl_api_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "videoland-platform": "videoland"
        }
        # call base __init__
        Module.__init__(self)

    def get_titles(self):
        # Get Information on the title by the Title ID
        metadata = self.session.get(
            url=f"https://www.videoland.com/api/v3/{'movies' if self.args.movie else 'series'}/{self.args.title}",
            headers=self.vl_api_headers
        ).json()
        self.title_name = metadata["title"]
        self.titles = [metadata] if self.args.movie else sorted(
            sorted(
                [
                    Ep for Season in [
                        [
                            dict(x, **{'season': Season["position"]}) for i, x in self.session.get(
                                url=f"https://www.videoland.com/api/v3/episodes/{self.args.title}/{Season['id']}",
                                headers=self.vl_api_headers
                            ).json()["details"].items()
                        ] for Season in [
                            x for i, x in metadata["details"].items() if
                            x["type"] == "season" and (x["position"] == self.args.season if self.args.season else True)
                        ]
                    ] for Ep in Season
                ],
                key=lambda e: e['position']
            ),
            key=lambda e: e['season']
        )
        if not self.titles:
            raise Exception("No titles returned!")

    def get_title_information(self, title):
        season = title["season"] if not self.args.movie else 0
        episode = title["position"] if not self.args.movie else 0
        title_year = title["year"] if self.args.movie else None
        episode_name = title["title"] if not self.args.movie else None
        return season, episode, title_year, episode_name

    def get_title_tracks(self, title):
        # Get the Stream MPD and License Url from the VideoLand Manifest API
        Manifest = self.session.get(
            url=f"https://www.videoland.com/api/v3/stream/{title['id']}/widevine?edition=",
            headers=self.vl_api_headers
        ).json()
        if "code" in Manifest:
            raise Exception(f"Failed to fetch the manifest for \"{title['id']}\", {Manifest['code']}, {Manifest['message']}")
        mpd_url = Manifest["stream"]["dash"]
        mpd = xmltodict.parse(
            self.session.get(url=mpd_url).text
        )["MPD"]["Period"]["AdaptationSet"]
        self.vl_lic_url = Manifest["drm"]["widevine"]["license"]
        # Create Track Dictionaries
        videos = [{
            "id": 0,
            "type": "video",
            "encrypted": True,
            # todo ; this should be gotten from the MPD or Playback Manifest
            "language": None,
            "track_name": None,
            "url": mpd_url,
            "downloader": "youtube-dl",
            "codec": "?",
            "bitrate": 0,
            "width": 0,
            "height": 0,
            "default": True,
            "fix": False,
            "info": {
                "fps": "?"
            }
        }]
        audio = [{
            "id": 0,
            "type": "audio",
            "encrypted": True,
            # todo ; this should be gotten from the MPD or Playback Manifest
            "language": [x["@lang"] for x in mpd if x["@contentType"] == "audio"][0],
            "track_name": None,
            "url": mpd_url,
            "downloader": "youtube-dl",
            "codec": "?",
            "default": True,
            "fix": False
        }]
        subtitles = []
        # Download Tracks
        self.widevine_cdm.pssh = [x for x in mpd[0]["ContentProtection"]
                                  if x["@schemeIdUri"] == self.widevine_cdm.urn][0]["cenc:pssh"]
        return videos, audio, subtitles

    def certificate(self, title, challenge):
        return self.license(title, challenge)

    def license(self, title, challenge):
        return base64.b64encode(self.session.post(
            url=self.vl_lic_url,
            data=base64.b64decode(challenge)
        ).content).decode("utf-8")
