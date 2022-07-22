# Standard
import re
import urllib.parse
# Package Dependencies
import xmltodict
# Custom
from modules import Module


class RTE(Module):

    def __init__(self, config, args):
        # Store various stuff to the parent class object
        self.args = args
        self.config = config
        self.source_tag = "RTE"
        self.origin = "www.rte.ie"
        # rte specific globals
        self.rte_feed = None
        self.rte_media_smil = None
        # call base __init__
        Module.__init__(self)

    def get_titles(self):
        print("Asking RTE Player for the title manifest...")
        self.rte_feed = self.session.get(
            url="https://feed.entertainment.tv.theplatform.eu/f/1uC-gC/rte-prd-prd-all-movies-series?byGuid=" +
                self.args.title
        ).json()["entries"][0]
        series_id = self.rte_feed["id"].split("/")[-1]
        available_season_ids = "|".join(
            x.split("/")[-1] for x in self.rte_feed["plprogramavailability$availableTvSeasonIds"])
        self.title_name = self.rte_feed["title"]
        self.titles = self.session.get(
            "https://feed.entertainment.tv.theplatform.eu/f/1uC-gC/rte-prd-prd-all-programs?bySeriesId=" + series_id +
            ("&bytvSeasonId=" + available_season_ids if available_season_ids else "") +
            "&byProgramType=episode&sort=tvSeasonEpisodeNumber&byMediaAvailabilityTags=ROI|IOI|Europe%2015"
            "|WW%20ex%20US.CA|WW|WW%20ex%20GB.NIR|WW%20ex%20CN|WW%20ex%20France|WW%20ex%20Aus.%20Asia,desktop"
            "&range=-500"
        ).json()["entries"]
        if not self.titles:
            raise Exception("No titles returned!")

    def get_title_information(self, title):
        self.rte_media_smil = self.session.get(
            title["plprogramavailability$media"][0]["plmedia$publicUrl"] +
            "?assetTypes=default:isl&sdk=PDK%205.9.3&formats=mpeg-dash&format=SMIL&tracking=true"
        ).text
        actual_sxxexx = re.search(
            r'<meta name="title" content="[^"]* S([^"]*) E([^"]*)',
            self.rte_media_smil
        )
        season = actual_sxxexx.group(1) if not self.args.movie else 0
        episode = actual_sxxexx.group(2) if not self.args.movie else 0
        title_year = self.rte_feed['plprogram$year'] if self.args.movie else None
        episode_name = "" if not self.args.movie else None
        return season, episode, title_year, episode_name

    def get_title_tracks(self, title):
        mpd_url = re.search(
            r"<video src=\"([^\"]*)",
            self.rte_media_smil
        ).group(1)
        videos = [{
            "id": 0,
            "type": "video",
            "encrypted": True,
            # todo ; this should be gotten from the MPD or Playback Manifest
            "language": None,
            "track_name": None,
            "url": mpd_url,
            "downloader": "youtube-dl",
            # todo ; add the stream info
            "codec": "?",
            "bitrate": 0,
            "width": 0,
            "height": 0,
            "default": True,
            "fix": True,
            "info": {
                "fps": "?"
            }
        }]
        audio = [{
            "id": 0,
            "type": "audio",
            "encrypted": True,
            "language": "en",
            "track_name": "English",
            "url": mpd_url,
            "downloader": "youtube-dl",
            "codec": "?",
            "default": True,
            "fix": False
        }]
        subtitles = [{
            "id": 0,
            "type": "subtitle",
            "encrypted": False,
            "language": "en",
            "track_name": "English",
            "url": re.search(
                r"<textstream src=\"([^\"]*)",
                self.rte_media_smil
            ).group(1),
            "downloader": "curl",
            "codec": "vtt",
            "default": True,
            "fix": False
        }]
        self.widevine_cdm.pssh = [
            x for x in xmltodict.parse(self.session.get(mpd_url).text)
            ["MPD"]["Period"]["AdaptationSet"][0]["ContentProtection"] if x["@schemeIdUri"] == self.widevine_cdm.urn
        ][0]["cenc:pssh"]
        return videos, audio, subtitles

    def certificate(self, title, challenge):
        return self.license(title, challenge)

    def license(self, title, challenge):
        media_pid = re.search(
            r'\|pid=([^|]*)',
            self.rte_media_smil
        ).group(1)
        return self.session.post(
            url="https://widevine.entitlement.eu.theplatform.com/wv/web/ModularDrm?form=json&schema=1.0&token=" +
                urllib.parse.quote_plus(self.session.cookies["mpx_token"]) +
                "&account=http://access.auth.theplatform.com/data/Account/2700894001",
            json={"getWidevineLicense": {"releasePid": media_pid, "widevineChallenge": challenge}}
        ).json()["getWidevineLicenseResponse"]["license"]
