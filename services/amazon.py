# Standard Libraries
import hashlib
import os
import re
# PyPI Dependencies
import xmltodict
# Custom Scripts
from services import Service
import config as appcfg

class AMAZON(Service):

    def __init__(self, cfg, args):
        # Store various stuff to the parent class object
        self.args = args
        self.cfg = cfg
        self.source_tag = "AMZN"
        # Discover region from cookies
        with open(os.path.join(
            appcfg.directories.cookies, self.args.service, f"{self.args.profile}.txt"
        ), "r") as f:
            match = None
            while match is None:
                # todo ; if no match occurs, it will infinitely loop
                match = re.search(r"^\.amazon.([^\t]*)", f.readline())
            tld = match.group(1)
            if tld == "com":
                region = "us"
            elif tld == "co.uk":
                region = "uk"
            else:
                region = tld
            self.cfg.region = getattr(self.cfg.regions, region)
            self.cfg.region.code = region
            print(f"Selected the region \"{region}\" based on, {tld} domain tld found inside the profile's cookies")
        # If the region uses a proxy, set it
        self.args.proxy = getattr(appcfg.proxies, self.cfg.region.code)
        if self.args.proxy is not None:
            print(f"Global Configuration for the Region {self.cfg.region.code} has a proxy configured, "
                  f"set {str(self.args.proxy)}")
        # Set Marketplace ID if provided via argument
        if self.args.marketid:
            self.cfg.region.marketplace_id = self.args.marketid
        # Set Various Variables
        self.origin = self.cfg.region.base
        # call base __init__
        Service.__init__(self)

    def get_titles(self):
        # create a device id based on user agent
        self.cfg.device_id = hashlib.sha224(
            ("CustomerID" + appcfg.common_headers["User-Agent"]).encode('utf-8')
        ).hexdigest()
        browse_request = self.session.get(
            url=self.cfg.endpoints.browse.format(
                base_url=self.cfg.region.base_manifest,
                deviceTypeID=self.cfg.device_type,
                deviceID=self.cfg.device_id,
                series_asin=self.args.title,
                marketplace_id=self.cfg.region.marketplace_id
            ),
            headers={
                "Accept": "application/json"
            }
        )
        if browse_request.status_code == 403:
            raise Exception(
                "Amazon refused your connection to the Browse Endpoint!\n"
                "This can often happen if your cookies are invalid or expired."
            )
        browse_request = browse_request.json()
        # todo ; add a check for an error response here in json
        self.titles = browse_request["message"]["body"]["titles"]
        self.title_name = (self.titles if self.args.movie else
                           [x for x in self.titles[0]['ancestorTitles'] if x["contentType"] == "SERIES"])[0]["title"] if self.titles else None
        self.titles = [
            t for t in self.titles
            if t["contentType"] == ("MOVIE" if self.args.movie else "EPISODE") and (t["number"] != 0 if "number" in t else True)
        ]
        if not self.titles:
            raise Exception(
                "No titles returned!\n"
                "Correct ASIN?\n"
                "Is the title available in the same region as the profile?\n"
                f"This title is a {('movie' if self.args.movie else 'tv show/episode')} right?"
            )

    def get_title_information(self, title):
        season = [x for x in title["ancestorTitles"] if x["contentType"] == "SEASON"][0]["number"] \
            if not self.args.movie else 0
        episode = title["number"] if not self.args.movie else 0
        title_year = title["releaseOrFirstAiringDate"]["valueFormatted"][:4] if self.args.movie and "releaseOrFirstAiringDate" in title else None
        episode_name = title["title"] if not self.args.movie else None
        return season, episode, title_year, episode_name

    def get_title_tracks(self, title):
        # Get Manifest
        # todo ; support primevideo.com by appending &gascEnabled=true when using primevideo.com cookies
        manifest = self.session.get(
            url=self.cfg.endpoints.playback.format(
                asin=title["titleId"],
                base_url=self.cfg.region.base_manifest,
                marketplace_id=self.cfg.region.marketplace_id,
                customer_id=self.cfg.region.account_id,
                token=self.cfg.region.account_token,
                profile=self.args.vcodec,
                client_id=self.cfg.region.client_id,
                bitrate=self.args.vbitrate.replace("+", "%2C"),
                deviceTypeID=self.cfg.device_type,
                deviceID=self.cfg.device_id
            ) + ("&deviceVideoQualityOverride=UHD&deviceHdrFormatsOverride=Hdr10"
                 if self.args.quality and self.args.quality >= 2160 else "")
        ).json()
        if "error" in manifest:
            raise Exception(
                "Amazon reported an error when obtaining the Playback Manifest.\n" +
                f"Error message: {manifest['error']['message']}"
            )
        if "rightsException" in manifest['returnedTitleRendition']['selectedEntitlement']:
            raise Exception(
                "Amazon denied this profile from receiving playback information.\n" +
                "This is usually caused by not purchasing or renting the content.\n" +
                "Error code: " +
                manifest['returnedTitleRendition']['selectedEntitlement']['rightsException']['errorCode']
            )
        if "errorsByResource" in manifest:
            raise Exception(
                "Amazon had an error occur with the resource.\n" +
                "These errors tend to be on Amazon's end and can sometimes be worked around by changing --vbitrate.\n" +
                "Error code: " +
                manifest['errorsByResource']['AudioVideoUrls']['errorCode'] + ", " + manifest['errorsByResource']['AudioVideoUrls']['message']
            )
        # List Audio Tracks
        av_cdn_url_sets = manifest["audioVideoUrls"]["avCdnUrlSets"]
        # Choose CDN to use
        print("CDN's: {}".format(", ".join([f"{x['cdn']} ({x['cdnWeightsRank']})" for x in av_cdn_url_sets])))
        if self.args.cdn is not None:
            self.args.cdn = self.args.cdn.lower()
            cdn = [x for x in av_cdn_url_sets if x["cdn"].lower() == self.args.cdn]
            if not cdn:
                raise Exception(f"Selected CDN does not exist, CDN {self.args.cdn} is not an option.")
            cdn = cdn[0]
        else:
            # use whatever cdn amazon recommends
            cdn = sorted(av_cdn_url_sets, key=lambda x: int(x['cdnWeightsRank']))[0]
        # Obtain and parse MPD Manifest from CDN
        mpd_url = re.match(r'(https?://.*/)d.{0,1}/.*~/(.*)', cdn['avUrlInfoList'][0]['url'])
        mpd_url = mpd_url.group(1) + mpd_url.group(2)
        mpd = xmltodict.parse(self.session.get(mpd_url).text)
        adaptation_sets = mpd['MPD']['Period']['AdaptationSet']
        # Video
        videos = []
        for i, rep in enumerate(self.flatten([x['Representation'] for x in
                                              [x for x in adaptation_sets if x['@group'] == "2"]])):
            videos.append({
                "id": i,
                "type": "video",
                "encrypted": True,
                "language": None,
                "track_name": None,
                "size": sorted(
                    rep["SegmentList"]["SegmentURL"],
                    key=lambda x: int(x["@mediaRange"].split('-')[1]),
                    reverse=True
                )[0]["@mediaRange"].split('-')[1],
                "url": mpd_url.rsplit('/', 1)[0] + "/" + rep["BaseURL"],
                "codec": rep["@codecs"],
                "bitrate": rep["@bandwidth"],
                "width": rep["@width"],
                "height": rep["@height"],
                "default": True,
                "fix": False,
                "info": {
                    "fps": rep['@frameRate']
                }
            })
        # Audio
        audio = []
        audio_meta = [x for x in manifest["audioVideoUrls"]["audioTrackMetadata"] if x["audioSubtype"] == "dialog"]
        for i, rep in enumerate(sorted(
            self.flatten([x["Representation"] for x in [x for x in adaptation_sets if x["@group"] == "1" and (x["@audioTrackSubtype"] == "dialog" if "@audioTrackSubtype" in x else True)]]),
            key=lambda x: int(x["BaseURL"].split('_')[-1][:-4])
        )):
            audio.append({
                "id": i,
                "type": "audio",
                "encrypted": True,
                "language": audio_meta[0]["languageCode"],
                "track_name": audio_meta[0]["displayName"],
                "size": sorted(
                    rep["SegmentList"]["SegmentURL"],
                    key=lambda x: int(x["@mediaRange"].split('-')[1]),
                    reverse=True
                )[0]["@mediaRange"].split("-")[1],
                "url": f"{mpd_url.rsplit('/', 1)[0]}/{rep['BaseURL']}",
                "codec": rep["@codecs"],
                "bitrate": rep["@bandwidth"],
                "default": True,  # this is fine as long as there's only one audio track
                "fix": False,
                "info": {
                    "sampling_rate": rep["@audioSamplingRate"]
                }
            })
        # Subtitles
        subtitles = []
        for i, sub in enumerate(manifest["subtitleUrls"]):
            subtitles.append({
                "id": i,
                "type": "subtitle",
                "encrypted": False,
                "language": sub["languageCode"],
                "track_name": sub["displayName"],
                "url": sub["url"],
                "codec": sub["format"].lower(),
                "default": sub["languageCode"] == audio_meta[0]["languageCode"] and sub["index"] == 0,
                "fix": False
            })
        self.widevine_cdm.pssh = [x for x in mpd["MPD"]["Period"]["AdaptationSet"][0]["ContentProtection"]
                                  if x["@schemeIdUri"] == self.widevine_cdm.urn][0]["cenc:pssh"]
        return videos, audio, subtitles

    def certificate(self, title, challenge):
        return self.license(title, challenge)

    def license(self, title, challenge):
        # todo ; support primevideo.com by appending &gascEnabled=true when using primevideo.com cookies
        lic = self.session.post(
            url=self.cfg.endpoints.licence.format(
                asin=title["titleId"],
                base_url=self.cfg.region.base_manifest,
                marketplace_id=self.cfg.region.marketplace_id,
                customer_id=self.cfg.region.account_id,
                token=self.cfg.region.account_token,
                deviceTypeID=self.cfg.device_type,
                deviceID=self.cfg.device_id
            ),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "widevine2Challenge": challenge,
                "includeHdcpTestKeyInLicense": "true"
            }
        ).json()
        if "errorsByResource" in lic:
            if lic["errorsByResource"]["Widevine2License"]["errorCode"] == "PRS.NoRights.AnonymizerIP":
                raise Exception(
                    f"Amazon detected a Proxy/VPN and refused to return a license!\n" +
                    lic["errorsByResource"]["Widevine2License"]["errorCode"]
                )
            raise Exception(
                "Amazon reported an error when obtaining the License.\n"
                f"Error message: {lic['errorsByResource']['Widevine2License']['errorCode']}"
                f", {lic['errorsByResource']['Widevine2License']['message']}"
            )
        return lic["widevine2License"]["license"]
