import asyncio
import requests
from youtube_transcript_api import YouTubeTranscriptApi

def get_free_proxies():
    try:
        res = requests.get("https://proxylist.geonode.com/api/proxy-list?limit=10&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps", timeout=5)
        if res.status_code == 200:
            return [f"http://{p['ip']}:{p['port']}" for p in res.json().get("data", [])]
    except Exception as e:
        print(f"Proxy fetch error: {e}")
    return []

def test_proxies():
    proxies = get_free_proxies()
    print(f"Got {len(proxies)} proxies")
    for p in proxies:
        print(f"Trying proxy {p}")
        try:
            session = requests.Session()
            session.proxies = {"http": p, "https": p}
            api = YouTubeTranscriptApi(http_client=session)
            transcript_list = api.list("185XGEMe")
            transcript = transcript_list.find_transcript(['en'])
            res = transcript.fetch()
            print("SUCCESS with proxy", p)
            return True
        except Exception as e:
            print("Failed:", e)
    return False

test_proxies()
