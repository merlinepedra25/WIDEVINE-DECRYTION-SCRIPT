#!/usr/bin/python3

# Standard Libraries
import sys
import os.path
import argparse
# PyPI Dependencies
import yaml
# Custom Scripts
from utils import DictToObj
import config as appcfg

# --------------------------------
# Arguments
# --------------------------------
ArgParser = argparse.ArgumentParser()
sps = ArgParser.add_subparsers(help='sub-command help', dest='service')
# global
ArgParser.add_argument('-v', '--verbose', help='Verbose Mode, used for debugging', action='store_true', required=False)
ArgParser.add_argument('--proxy', help='Proxy to make the all requests under', required=False)
ArgParser.add_argument('--cdm', help='Override which Widevine Content Decryption Module to use for decryption',
                       default='nexus6_lvl1', required=False)  # With Netflix, chromecdm_903 + cdm_ke == 1080p @ MPL
ArgParser.add_argument('--keys', help='Only obtain the keys, skip downloading and all logic behind it',
                       action='store_true', required=False)
ArgParser.add_argument('--keysonly', help='Disable all logs except for the output of the keys from --keys',
                       action='store_true', required=False)
ArgParser.add_argument('--quiet',
                       help='Silent operation, does not return any logs during usage',
                       action='store_true', required=False)
ArgParser.add_argument('-p', '--profile',
                       help='Cookies and settings will be applied based on the profile',
                       required=True)
ArgParser.add_argument('-t', '--title', help='Title ID of the content you wish to download', required=True)
ArgParser.add_argument('-q', '--quality', help='Download Resolution, defaults to best available', type=int)
ArgParser.add_argument('-m', '--movie', help='If it\'s a movie, use this flag', action='store_true', required=False)
ArgParser.add_argument('-s', '--season', help='Season Number to download, exclude it to download all seasons', type=int,
                       required=False)
ArgParser.add_argument('-e', '--episode', help='Episode Number to download, exclude it to download all episodes',
                       type=int, required=False)
ArgParser.add_argument('--skip', help='Skip n Episodes', type=int)
# netflix
sp_netflix = sps.add_parser('NETFLIX', help='https://netflix.com')
sp_netflix.add_argument('--vcodec', help='Video Codec - H264 will retrieve BPL and MPL AVC profiles', default='H264',
                        choices=['H264', 'H264@HPL', 'H265', 'H265-HDR', 'VP9', 'AV1'])
sp_netflix.add_argument('--acodec', help='Audio Codec', default='DOLBY', choices=['AAC', 'VORB', 'DOLBY'])
sp_netflix.add_argument('--esn', help='Netflix ESN to use for the Manifest and License API\'s',
                        default='NFANDROID1-PRV-P-XIAOMMI=9=SE-12034-6EA8A15D39427309D0A97686A1A315C6A0ABFE46BECD14BB740EC56C65168E44')
sp_netflix.add_argument('--cdm_ke', help='Use Widevine Content Decryption Module Key Exchange', action='store_true',
                        default=False, required=False)
# amazon
sp_amazon = sps.add_parser('AMAZON', help='https://amazon.com')
sp_amazon.add_argument('--marketid', help='Marketplace ID (mid)', required=False)
sp_amazon.add_argument('--vcodec', help='Video Codec', default='H264', choices=['H264', 'H265'])
sp_amazon.add_argument('--vbitrate', help='Video Bitrate Mode to download in (CVBR recommended)', default='CVBR',
                       choices=['CVBR+CBR', 'CVBR', 'CBR'])
sp_amazon.add_argument('--cdn', help='CDN to download from, defaults to the cdn with the highest weight set by Amazon')
# videoland
sp_videoland = sps.add_parser('VIDEOLAND', help='https://videoland.com')
# boomerang
sp_boomerang = sps.add_parser('BOOMERANG', help='https://boomerang.com')
# disney+
sp_disneyplus = sps.add_parser('DISNEYPLUS', help='https://disneyplus.com')
sp_disneyplus.add_argument('ctr', help='DRM CTR AES Counter Block Encryption Mode', default='handset-drm-ctr', choices=['handset-drm-ctr', 'restricted-drm-ctr-sw'])
# rte
sp_rte = sps.add_parser('RTE', help='https://rte.ie/player')
# rakutentv
sp_rakutentv = sps.add_parser('RAKUTENTV', help='https://rakuten.tv')
sp_rakutentv.add_argument('--hdr', help='Audio Channels', default='HDR10', choices=['NONE', 'HDR10'])
sp_rakutentv.add_argument('--vquality', help='Video Quality', default='UHD', choices=['SD', 'HD', 'FHD', 'UHD'])
sp_rakutentv.add_argument('--achannels', help='Audio Channels', default='5.1', choices=['2.0', '5.1'])

args = ArgParser.parse_args()

# --------------------------------
# Load Service
# From there, the service will take care of the rest
# --------------------------------
if args.keysonly:
    sys.stdout = open(os.devnull, 'w')
print(f"Starting {args.service} Service")
config_path = os.path.join(appcfg.directories.configuration, f"{args.service}.yml")
if os.path.exists(config_path) and os.path.isfile(config_path):
    with open(config_path, "r") as f:
        cfg = DictToObj(yaml.safe_load(f))
else:
    cfg = None
m = getattr(
    __import__("services." + args.service.lower(), globals(), locals(), [args.service], 0),
    args.service
)(cfg, args)
