import requests
import random
from youtube_transcript_api import YouTubeTranscriptApi

def test_proxy():
    print("Fetching proxies...")
    res = requests.get("https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt")
    proxies = res.text.strip().split("\n")
    # shuffle to get random proxies
    random.shuffle(proxies)
    proxies = proxies[:10] # test 10
    
    for p in proxies:
        proxy_url = f"http://{p.strip()}"
        print(f"Trying {proxy_url}")
        try:
            api = YouTubeTranscriptApi()
            t_list = api.list("185XGEMe", proxies={"http": proxy_url, "https": proxy_url})
            t = t_list.find_transcript(['en'])
            print(t.fetch()[:2])
            return True
        except Exception as e:
            print("Failed", type(e).__name__)
    return False

test_proxy()
