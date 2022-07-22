# Standard Libraries
import base64
import gzip
import json
import os
import random
import re
import time
import urllib
import zlib
from collections import namedtuple
from datetime import datetime
from io import BytesIO
# PyPI Dependencies
from Cryptodome.Cipher import AES, PKCS1_OAEP
from Cryptodome.Hash import HMAC, SHA256
from Cryptodome.PublicKey import RSA
from Cryptodome.Random import get_random_bytes
from Cryptodome.Util import Padding
# Custom Scripts
from services import Service
import config as appcfg


class NETFLIX(Service):

    def __init__(self, cfg, args):
        # Store various stuff to the parent class object
        self.args = args
        self.cfg = cfg
        self.source_tag = "NF"
        self.origin = "netflix.com"
        # call base __init__
        Service.__init__(self)

    def get_titles(self):
        # Get an MSL object
        self.msl = MSL(
            cdm=self.widevine_cdm,
            session=self.session,
            msl_bin=os.path.join(appcfg.directories.cookies, self.args.service, "msl.bin"),
            rsa_bin=os.path.join(appcfg.directories.cookies, self.args.service, "rsa.bin"),
            esn=self.args.esn,
            widevine_key_exchange=self.args.cdm_ke is not None,
            manifest_endpoint=self.cfg.endpoints.manifest
        )
        build_txt = os.path.join(appcfg.directories.cookies, self.args.service, "build.txt")
        if not os.path.exists(build_txt) or not os.path.isfile(build_txt):
            # No Cached Cookies/Build, Login and get them
            build = re.search(
                r'"BUILD_IDENTIFIER":"([a-z0-9]+)"',
                self.session.get(appcfg.common_headers["Origin"]).text
            )
            if build:
                build = build.group(1)
                with open(build_txt, "w") as f:
                    f.write(build)
        else:
            with open(build_txt, "r") as f:
                build = f.read().strip()
        if not build:
            raise Exception(
                "Couldn't find a Build ID from the homepage or cache, cookies or cache file may be invalid.")
        # fetch metadata from shakti
        metadata = self.session.get(
            f"https://www.netflix.com/api/shakti/{build}/metadata?movieid={self.args.title}"
        ).text
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            print(
                "Failed to fetch Metadata via Shakti API for " + self.args.title + " using BUILD Identifier " + build +
                ", is this title available on your IP's region?")
            exit(1)

        # For every title
        self.title_name = metadata["video"]["title"]
        self.titles = [metadata["video"]] if self.args.movie else [
            Ep for Season in [
                [
                    dict(x, **{"season": Season["seq"]}) for x in Season["episodes"]
                ] for Season in [
                    x for x in metadata["video"]["seasons"]
                    if (x["seq"] == self.args.season if self.args.season else True)
                ]
            ] for Ep in Season
        ]
        if not self.titles:
            raise Exception("No titles returned!")

    def get_title_information(self, title):
        season = title["season"] if not self.args.movie else 0
        episode = title["seq"] if not self.args.movie else 0
        title_year = title["year"] if self.args.movie else None
        episode_name = title["title"] if not self.args.movie else None
        return season, episode, title_year, episode_name

    def get_title_tracks(self, title):
        profiles = self.cfg.profiles.video.h264.bpl + self.cfg.profiles.video.h264.mpl
        if self.args.vcodec == "H264@HPL":
            profiles += self.cfg.profiles.video.h264.hpl
        if self.args.vcodec == "H265":
            profiles += self.cfg.profiles.video.h265.sdr
        if self.args.vcodec == "H265-HDR":
            profiles += self.cfg.profiles.video.h265.hdr.hdr10 + \
                        self.cfg.profiles.video.h265.hdr.dolbyvision.dv1 + \
                        self.cfg.profiles.video.h265.hdr.dolbyvision.dv5
        if self.args.vcodec == "VP9":
            profiles += self.cfg.profiles.video.vp9.p0 + \
                        self.cfg.profiles.video.vp9.p1 + \
                        self.cfg.profiles.video.vp9.p2
        if self.args.vcodec == "AV1":
            profiles += self.cfg.profiles.video.av1
        if self.args.acodec == "AAC":
            profiles += self.cfg.profiles.audio.aac
        if self.args.acodec == "VORB":
            profiles += self.cfg.profiles.audio.vorb
        if self.args.acodec == "DOLBY":
            profiles += self.cfg.profiles.audio.dolby
        manifest_response = self.session.post(
            url=self.cfg.endpoints.manifest,
            data=self.msl.generate_msl_request_data({
                "method": "manifest",
                "lookupType": "PREPARE",
                "viewableIds": [title["episodeId"] if "episodeId" in title else title["id"]],
                "profiles": profiles + self.cfg.profiles.subtitles,
                "drmSystem": "widevine",
                "appId": "14673889385265",
                "sessionParams": {
                    "pinCapableClient": False,
                    "uiplaycontext": "null"
                },
                "sessionId": "14673889385265",
                "trackId": 0,
                "flavor": "PRE_FETCH",
                "secureUrls": True,
                "supportPreviewContent": True,
                "forceClearStreams": False,
                "languages": ["en-US"],
                "clientVersion": "6.0011.511.011",  # 4.0004.899.011
                "uiVersion": "shakti-vb45817f4",  # akira
                "titleSpecificData": {
                    title["episodeId"] if "episodeId" in title else title["id"]: {"unletterboxed": False}
                },
                "videoOutputInfo": [{
                    "type": "DigitalVideoOutputDescriptor",
                    "outputType": "unknown",
                    "supportedHdcpVersions": [],
                    "isHdcpEngaged": True
                }],
                "isNonMember": False,
                "showAllSubDubTracks": True,
                "preferAssistiveAudio": False,
                "supportsPreReleasePin": True,
                "supportsWatermark": True,
                "isBranching": False,
                "useHttpsStreams": False,
                "imageSubtitleHeight": 1080,
            })
        )
        try:
            # if the json() does not fail we have an error because the manifest response is a chunked json response
            raise Exception("Failed to retrieve Manifest: " +
                            json.loads(
                                base64.standard_b64decode(manifest_response.json()["errordata"]).decode('utf-8')
                            )["errormsg"]
                            )
        except ValueError:
            manifest = self.msl.decrypt_payload_chunk(
                self.msl.parse_chunked_msl_response(manifest_response.text)["payloads"])
            try:
                self.playback_context_id = manifest["result"]["viewables"][0]["playbackContextId"]
                self.drm_context_id = manifest["result"]["viewables"][0]["drmContextId"]
            except (KeyError, IndexError):
                if "errorDisplayMessage" in manifest["result"]:
                    raise Exception(f"MSL Error Message: {manifest['result']['errorDisplayMessage']}")
                else:
                    raise Exception("Unknown error occurred.")

        # --------------------------------
        # Looking good, time to compile information on the Titles
        # This will just make it easier for the rest of the code
        # --------------------------------
        manifest = manifest["result"]["viewables"][0]
        # Video
        videos = []
        for i, rep in enumerate(manifest["videoTracks"][0]["downloadables"]):
            videos.append({
                "id": i,
                "type": "video",
                "encrypted": rep['isEncrypted'],
                # todo ; this should be gotten from the MPD or Playback Manifest
                "language": None,
                "track_name": None,
                # todo ; size isn't really needed anymore, we might not need this
                "size": rep["size"],
                "url": next(iter(rep["urls"].values())),
                "codec": rep["contentProfile"],
                "bitrate": rep["bitrate"],
                "width": rep["width"],
                "height": rep["height"],
                "default": True,
                "fix": True
            })
        # Audio
        audio = []
        original_language = [x for x in manifest["orderedAudioTracks"]
                             if x.endswith("[Original]")][0].replace("[Original]", "").strip()
        audio_tracks = []
        for audio_track in [t for t in manifest["audioTracks"]
                            if t["trackType"] == "PRIMARY"]:
            audio_track["language"] = audio_track["language"].replace("[Original]", "").strip()
            for downloadable in audio_track["downloadables"]:
                new_audio_track = audio_track.copy()
                new_audio_track["downloadables"] = downloadable
                audio_tracks.append(new_audio_track)
        for i, rep in enumerate([t for t in audio_tracks if t["language"] == original_language]):
            audio.append({
                "id": i,
                "type": "audio",
                "encrypted": False,
                "language": rep["language"],
                "track_name": None,
                # todo ; size isn't really needed anymore, we might not need this
                "size": rep["downloadables"]["size"],
                "url": next(iter(rep["downloadables"]["urls"].values())),
                "codec": rep["downloadables"]["contentProfile"],
                "bitrate": rep["downloadables"]["bitrate"],
                "default": True,  # this is fine as long as there's only one audio track
                "fix": True
            })
        # Subtitles
        subtitles = []
        for i, sub in enumerate([x for x in manifest["textTracks"]
                                 if x["downloadables"] is not None and x["language"] != "Off"]):
            subtitles.append({
                "id": i,
                "type": "subtitle",
                "encrypted": False,
                "language": sub["bcp47"],
                "track_name": f"{sub['language']} "
                              f"[{sub['trackType'].replace('CLOSEDCAPTIONS', 'CC').replace('SUBTITLES', 'SUB')}]",
                "url": next(iter(sub["downloadables"][0]["urls"].values())),
                "codec": "vtt" if sub["downloadables"][0]["contentProfile"].startswith("webvtt") else "srt",
                "default": sub["language"] == original_language,
                "fix": False
            })
        self.widevine_cdm.pssh = manifest["psshb64"][0]
        self.cert = manifest["cert"]
        return videos, audio, subtitles

    def certificate(self, title, challenge):
        return self.cert

    def license(self, title, challenge):
        challenge_response = self.session.post(
            url=self.cfg.endpoints.licence,
            data=self.msl.generate_msl_request_data({
                'method': 'license',
                'licenseType': 'STANDARD',
                'clientVersion': '4.0004.899.011',
                'uiVersion': 'akira',
                'languages': ['en-US'],
                'playbackContextId': self.playback_context_id,
                'drmContextIds': [self.drm_context_id],
                'challenges': [{
                    'dataBase64': challenge,
                    'sessionId': "14673889385265"
                }],
                'clientTime': int(time.time()),
                'xid': int((int(time.time()) + 0.1612) * 1000)
            })
        )
        try:
            # If is valid json the request for the license failed
            challenge_response.json()
            raise Exception(f"Error getting license (A): {challenge_response.text}")
        except ValueError:
            # json() failed so we have a chunked json response
            payload = self.msl.decrypt_payload_chunk(self.msl.parse_chunked_msl_response(
                challenge_response.text
            )["payloads"])
            if payload["success"] is False:
                raise Exception(f"Error getting license (B): {json.dumps(payload)}")
            return payload["result"]["licenses"][0]["data"]


class MSL:

    files = namedtuple("_", "msl rsa")

    def __init__(self, cdm, session, msl_bin, rsa_bin, esn, widevine_key_exchange, manifest_endpoint):
        # settings
        self.cdm = cdm
        self.session = session
        self.files.msl = msl_bin
        self.files.rsa = rsa_bin
        self.esn = esn
        self.widevine_key_exchange = widevine_key_exchange
        self.manifest_endpoint = manifest_endpoint
        # msl stuff
        self.message_id = 0
        self.keys = namedtuple("_", "encryption sign rsa")
        self.master_token = None
        self.sequence_number = None
        # create an end-to-end encryption by negotiating encryption keys
        self.negotiate_keys()

    def load_cached_data(self):
        # Check if one exists
        if not os.path.isfile(self.files.msl):
            return False
        # Load it
        with open(self.files.msl, "r") as f:
            msl_bin = json.JSONDecoder().decode(f.read())
        # If its expired or close to, return None as its unusable
        if ((datetime.utcfromtimestamp(int(json.JSONDecoder().decode(
                base64.standard_b64decode(msl_bin["tokens"]["mastertoken"]["tokendata"]).decode("utf-8")
                )["expiration"])) - datetime.now()).total_seconds() / 60 / 60) < 10:
            return False
        # Set the MasterToken of this Cached BIN
        self.set_master_token(msl_bin["tokens"]["mastertoken"])
        self.keys.encryption = base64.standard_b64decode(msl_bin["encryption_key"])
        self.keys.sign = base64.standard_b64decode(msl_bin["sign_key"])
        print("Cached MSL data found and loaded")
        return True

    def load_cached_rsa_key(self):
        if not os.path.isfile(self.files.rsa):
            return False
        with open(self.files.rsa, "rb") as f:
            self.keys.rsa = RSA.importKey(f.read())
        print("Cached RSA Key found and loaded")
        return True

    def generate_msl_header(self, is_handshake=False, is_key_request=False, compression="GZIP"):
        """
        Function that generates a MSL header dict
        :return: The base64 encoded JSON String of the header
        """
        self.message_id = random.randint(0, pow(2, 52))
        header_data = {
            "sender": self.esn,
            "renewable": True,
            "capabilities": {
                "languages": ["en-US"],
                "compressionalgos": [],
                "encoderformats": ["JSON"],
            },
            "handshake": is_handshake,
            "nonreplayable": False,
            "recipient": "Netflix",
            "messageid": self.message_id,
            "timestamp": int(time.time()),  # verify later
        }
        # Add compression algorithm if being requested
        if compression:
            header_data["capabilities"]["compressionalgos"].append(compression)
        if is_key_request:
            if self.widevine_key_exchange:
                self.cdm.pssh = None
                self.cdm.pssh_raw = b'\x0A\x7A\x00\x6C\x38\x2B'
                self.cdm.open(offline=True)
            # key request
            header_data["keyrequestdata"] = [{
                "scheme": ("WIDEVINE" if self.widevine_key_exchange else "ASYMMETRIC_WRAPPED"),
                "keydata": ({
                    "keyrequest": self.cdm.get_license()
                } if self.widevine_key_exchange else {
                    "keypairid": "superKeyPair",
                    "mechanism": "JWK_RSA",
                    "publickey": base64.standard_b64encode(
                        self.keys.rsa.publickey().exportKey(format="DER")
                    ).decode("utf-8")
                })
            }]
        else:
            # regular request (identity proof)
            header_data["userauthdata"] = {
                "scheme": "EMAIL_PASSWORD",
                "authdata": {
                    "email": urllib.parse.unquote(self.session.cookies.get_dict()["auth_data_email"]),
                    "password": urllib.parse.unquote(self.session.cookies.get_dict()["auth_data_pass"])
                }
            }
        # Return completed Header
        return json.dumps(header_data)

    def set_master_token(self, master_token):
        self.master_token = master_token
        self.sequence_number = json.JSONDecoder().decode(
            base64.standard_b64decode(master_token["tokendata"]).decode("utf-8")
        )["sequencenumber"]

    @staticmethod
    def get_widevine_key(kid, keys, permissions):
        for key in keys:
            if key.kid != kid:
                continue
            if key.type != "OPERATOR_SESSION":
                print("wv key exchange: Wrong key type (not operator session) key %s" % key)
                continue
            if not set(permissions) <= set(key.permissions):
                print("wv key exchange: Incorrect permissions, key %s, needed perms %s" % (key, permissions))
                continue
            return key.key
        return None

    def negotiate_keys(self):
        if not self.load_cached_data():
            # Ok no saved MSL BIN, that's OK!
            if not self.widevine_key_exchange:
                # Let's either use a Cached RSA Key, or create a new random 2048 bit key
                if not self.load_cached_rsa_key():
                    self.keys.rsa = RSA.generate(2048)  # create
                    with open(self.files.rsa, "wb") as f:
                        f.write(self.keys.rsa.exportKey())  # cache #.exportKey(format='DER')????
            # We now have the necessary data to perform a key handshake (either via widevine or an rsa key)
            # We don't need to do this if we have cached MSL Data as long as it hasn't expired
            key_exchange = self.session.post(
                url=self.manifest_endpoint,
                data=json.dumps({
                    "entityauthdata": {
                        "scheme": "NONE",
                        "authdata": {
                            "identity": self.esn
                        }
                    },
                    "headerdata": base64.standard_b64encode(
                        self.generate_msl_header(
                            is_key_request=True,
                            is_handshake=True,
                            compression=""
                        ).encode("utf-8")
                    ).decode("utf-8"),
                    "signature": ""
                }, sort_keys=True)
            )
            if key_exchange.status_code != 200:
                raise Exception(f"Key Exchange failed, response data is unexpected: {key_exchange.text}")
            key_exchange = key_exchange.json()
            if "errordata" in key_exchange:
                raise Exception("Key Exchange failed (A): " + base64.standard_b64decode(
                    key_exchange["errordata"]
                ).decode('utf-8'))
            # parse the crypto keys
            key_response_data = json.JSONDecoder().decode(base64.standard_b64decode(
                key_exchange["headerdata"]
            ).decode('utf-8'))["keyresponsedata"]
            self.set_master_token(key_response_data["mastertoken"])
            if key_response_data["scheme"] != ("WIDEVINE" if self.widevine_key_exchange else "ASYMMETRIC_WRAPPED"):
                raise Exception("Key Exchange scheme mismatch occurred")
            key_data = key_response_data["keydata"]
            if self.widevine_key_exchange:
                self.cdm.provide_license(key_data["cdmkeyresponse"])
                keys = self.cdm.get_keys(content_only=False)
                self.keys.encryption = self.get_widevine_key(
                    kid=base64.standard_b64decode(key_data["encryptionkeyid"]),
                    keys=keys,
                    permissions=["AllowEncrypt", "AllowDecrypt"]
                )
                self.keys.sign = self.get_widevine_key(
                    kid=base64.standard_b64decode(key_data["hmackeyid"]),
                    keys=keys,
                    permissions=["AllowSign", "AllowSignatureVerify"]
                )
            else:
                cipher_rsa = PKCS1_OAEP.new(self.keys.rsa)
                self.keys.encryption = self.base64key_decode(
                    json.JSONDecoder().decode(cipher_rsa.decrypt(
                        base64.standard_b64decode(key_data["encryptionkey"])
                    ).decode("utf-8"))["k"]
                )
                self.keys.sign = self.base64key_decode(
                    json.JSONDecoder().decode(cipher_rsa.decrypt(
                        base64.standard_b64decode(key_data["hmackey"])
                    ).decode("utf-8"))["k"]
                )
            with open(self.files.msl, "wb") as f:
                f.write(json.JSONEncoder().encode({
                    "encryption_key": base64.standard_b64encode(self.keys.encryption).decode("utf-8"),
                    "sign_key": base64.standard_b64encode(self.keys.sign).decode("utf-8"),
                    "tokens": {
                        "mastertoken": self.master_token,
                    }
                }).encode("utf-8"))
        print("E2E-Negotiation Successful")
        return True

    def generate_msl_request_data(self, data):
        header = self.encrypt(self.generate_msl_header())
        payload_chunk = self.encrypt(json.dumps({
            "messageid": self.message_id,
            "data": self.gzip_compress(
                '[{},{"headers":{},"path":"/cbp/cadmium-13","payload":{"data":"' +
                json.dumps(data).replace('"', '\\"') +
                '"},"query":""}]\n'
            ).decode('utf-8'),
            "compressionalgo": "GZIP",
            "sequencenumber": 1,  # todo ; use self.sequence_number from master token instead?
            "endofmsg": True
        }))
        # Header and Payload Chunk - E2E Encrypted, with Signatures
        return json.dumps({
            "headerdata": base64.standard_b64encode(header.encode("utf-8")).decode("utf-8"),
            "signature": self.sign(header).decode("utf-8"),
            "mastertoken": self.master_token,
        }) + json.dumps({
            "payload": base64.standard_b64encode(payload_chunk.encode("utf-8")).decode("utf-8"),
            "signature": self.sign(payload_chunk).decode("utf-8"),
        })

    @staticmethod
    def parse_chunked_msl_response(message):
        payloads = re.split(',\"signature\":\"[0-9A-Za-z=/+]+\"}', message.split('}}')[1])
        payloads = [x + "}" for x in payloads][:-1]
        return {
            "header": message.split("}}")[0] + "}}",
            "payloads": payloads
        }

    def decrypt_payload_chunk(self, payload_chunks):
        """
        Decrypt and merge payload chunks into a JSON Object
        :param payload_chunks:
        :return: json object
        """
        merged_payload = ""
        for payload in [
            json.JSONDecoder().decode(
                base64.standard_b64decode(json.JSONDecoder().decode(x).get('payload')).decode('utf-8')
            ) for x in payload_chunks
        ]:
            # Decrypt the payload
            payload_decrypted = AES.new(
                self.keys.encryption,
                AES.MODE_CBC,
                base64.standard_b64decode(payload["iv"])
            ).decrypt(base64.standard_b64decode(payload.get("ciphertext")))
            # un-pad the decrypted payload
            payload_decrypted = json.JSONDecoder().decode(Padding.unpad(payload_decrypted, 16).decode("utf-8"))
            payload_data = base64.standard_b64decode(payload_decrypted.get("data"))
            # uncompress data if compressed
            if payload_decrypted.get("compressionalgo") == "GZIP":
                payload_data = zlib.decompress(payload_data, 16 + zlib.MAX_WBITS)
            # decode decrypted payload chunks' bytes to a utf-8 string, and append it to the merged_payload string
            merged_payload += payload_data.decode("utf-8")
        return json.JSONDecoder().decode(base64.standard_b64decode(
            json.JSONDecoder().decode(merged_payload)[1]["payload"]["data"]
        ).decode('utf-8'))

    @staticmethod
    def gzip_compress(data):
        out = BytesIO()
        with gzip.GzipFile(fileobj=out, mode="w") as f:
            f.write(data.encode("utf-8"))
        return base64.standard_b64encode(out.getvalue())

    @staticmethod
    def base64key_decode(payload):
        length = len(payload) % 4
        if length == 2:
            payload += "=="
        elif length == 3:
            payload += "="
        elif length != 0:
            raise ValueError("Invalid base64 string")
        return base64.urlsafe_b64decode(payload.encode("utf-8"))

    def encrypt(self, plaintext):
        """
        Encrypt the given Plaintext with the encryption key
        :param plaintext:
        :return: Serialized JSON String of the encryption Envelope
        """
        iv = get_random_bytes(16)
        return json.dumps({
            "ciphertext": base64.standard_b64encode(
                AES.new(
                    self.keys.encryption,
                    AES.MODE_CBC,
                    iv
                ).encrypt(
                    Padding.pad(plaintext.encode("utf-8"), 16)
                )
            ).decode("utf-8"),
            "keyid": f"{self.esn}_{self.sequence_number}",
            "sha256": "AA==",
            "iv": base64.standard_b64encode(iv).decode("utf-8")
        })

    def sign(self, text):
        """
        Calculates the HMAC signature for the given text with the current sign key and SHA256
        :param text:
        :return: Base64 encoded signature
        """
        return base64.standard_b64encode(HMAC.new(self.keys.sign, text.encode("utf-8"), SHA256).digest())
