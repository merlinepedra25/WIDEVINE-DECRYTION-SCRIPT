# Standard Libraries
import base64
import binascii
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

# PyPI Dependencies
# Custom Scripts
from config import config
from shared import log

# Stubs, these are meant to be defined by the importee
args = None
helper = None


def start():
    helper.session.headers.update({
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:68.0) Gecko/20100101 Firefox/68.0"
    })
    # Parse Cookies
    Cookies = {}
    CookieFile = os.path.join(config.base.directories.cookies, "BOOMERANG", args.profile + ".txt")
    if not Path(CookieFile).exists() or not os.path.isfile(CookieFile):
        log.error(f"No cookie file is associated with the Profile \"{args.profile}\"")
        exit()
    with open(CookieFile, 'r') as f:
        for l in f:
            if not re.match(r'^\#', l) and not re.match(r'^\n', l):
                lineFields = l.strip().split('\t')
                Cookies[lineFields[5]] = lineFields[6]
    helper.session.cookies.update(Cookies)
    # If theres a US proxy, set it as Boomerang requires a US proxy
    if config.base.proxies.us is not None:
        log.info("US proxy exists, using " + str(config.base.proxies.us))
        helper.session.proxies.update(config.base.proxies.us)
    # Get the Consumer Secret (X-Consumer-Key Header Value) and Authorization Header
    helper.session.headers.update({
        "X-Consumer-Key": json.loads(helper.session.get(
            url="https://watch.boomerang.com/api/5/consumer/www",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
        ).text)["consumer_secret"],
        "Authorization": "Token " + json.loads(unquote(Cookies['pjs-user']))['token']
    })
    # Get Information on the Series by the Ttile ID
    Episodes = []
    page = 1
    while True:
        eps = json.loads(helper.session.get(
            url="https://watch.boomerang.com/api/5/series/" + str(args.title) + "/episodes/?page=" + str(
                page) + "&page_size=25&trans=en",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
        ).text)
        Episodes.extend(eps["values"])
        if eps["num_pages"] == page:
            break
        page += 1
    CurrentEpisode = 0
    for Episode in sorted(sorted([x for x in Episodes if (x["season"] == args.season if args.season else True)],
                                 key=lambda e: e['number']), key=lambda s: s['season']):
        CurrentEpisode += 1
        if args.skip and CurrentEpisode <= args.skip:
            continue
        if args.episode and CurrentEpisode != args.episode:
            continue
        # Get Filename
        args.filename = helper.FilenameTV(Source="BOOM", Title=Episodes[0]["series_title"], Season=Episode["season"],
                                          Episode=CurrentEpisode, Name=Episode['title'])
        log.info("Downloading: " + args.filename)
        # Get the Manifest
        Token = json.loads(helper.session.get(
            url="https://watch.boomerang.com/api/5/1/rights/episode/" + Episode["uuid"],
            headers={
                "Accept": "application/json"
            }
        ).text)
        Manifest = json.loads(helper.session.get(
            url="https://watch.boomerang.com/api/5/1/video_manifest_from_jwt/?cdn=cloudfront&drm=widevine&st=dash&subs=none&token=" + Token,
            headers={
                "Accept": "application/json"
            }
        ).text)
        # Create Track Dictionaries
        if not 'stream_url' in Manifest:
            log.error("Account doesnt have access to the requested content. Aborting. Error: " + Manifest['errors'][0][
                'message'])
            exit(0)
        VT = {'id': 0, 'type': 'video', 'encrypted': True, 'url': Manifest["stream_url"]}
        AT = {'id': 1, 'type': 'audio', 'encrypted': True, 'url': Manifest["stream_url"], 'ytdl_format_id': 'en'}
        STs = []
        if not args.keys:
            # Subtitles
            SubID = -1
            for Sub in json.loads(helper.session.get(
                    url="https://watch.boomerang.com/api/5/video/" + Episode["guid"] + "/subtitles/webvtt/",
                    headers={
                        "Accept": "application/json"
                    }
            ).text):
                SubID += 1
                STs.append({
                    'id': SubID,
                    'type': 'vtt',
                    'language_code': Sub["code"],
                    'name': Sub["language"],
                    'url': Sub["url"],
                    'default': False
                })
            # Download Tracks
            helper.DownloadTracks(VT, AT, STs, mode="youtube-dl")
        # Dump PSSH from encrypted videos CENC data
        PSSH = None
        for atom in json.loads(subprocess.check_output(
                [
                    'mp4dump',
                    '--format', 'json',
                    '--verbosity', '3',
                    config.base.filenames.encrypted.format(filename=args.filename, track_type=VT['type'],
                                                           track_no=VT['id'])
                ]
        )):
            if atom['name'] == 'moov':
                for child in atom['children']:
                    if child['name'] == 'pssh' and child[
                        'system_id'] == '[ed ef 8b a9 79 d6 4a ce a3 c8 27 dc d5 1d 21 ed]':
                        PSSH = base64.b64encode(binascii.unhexlify(
                            re.sub(r'\s+', '', re.sub(r'^\[08 01 ([a-f0-9 ]+)\]$', r'\1', child['data'])).strip(
                                '[]'))).decode('utf-8')
                        log.info("Obtained PSSH from CENC data")
                        break
        if not PSSH:
            log.error('ERROR! Unable to extract PSSH')
            exit(1)
        # Open CDM Session
        helper.OpenSession(PSSH)
        # Set Certificate
        helper.SetCertificate(base64.b64encode(helper.session.post(
            url="https://watch.boomerang.com/wvd/modlicense",
            data=helper.GetCertificateChallengeRaw()
        ).content).decode("utf-8"))
        # Set Licence
        helper.SetLicense(base64.b64encode(helper.session.post(
            url="https://watch.boomerang.com/wvd/modlicense",
            data=helper.GetLicenseChallengeRaw()
        ).content).decode("utf-8"))
        if args.keys:
            Keys.extend(helper.GetDecryptionKeys())
        else:
            # Decrypt Tracks
            helper.DecryptTracks(VT, AT)
            # Mux Tracks
            helper.Mux(VT, AT, STs)
            # Cleanup
            helper.Cleanup()
    if args.keys:
        print(json.dumps(Keys))
