import asyncio
import requests
import json

def get_transcript_piped(video_id):
    # Piped API endpoints
    instances = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.syncpundit.io",
        "https://api.piped.projectsegfau.lt"
    ]
    for base in instances:
        try:
            print(f"Trying {base}")
            res = requests.get(f"{base}/streams/{video_id}", timeout=5)
            if res.status_code == 200:
                data = res.json()
                subtitles = data.get("subtitles", [])
                en_sub = next((s for s in subtitles if s.get("code") == "en" or s.get("code") == "en-US"), None)
                if en_sub:
                    sub_url = en_sub["url"]
                    sub_res = requests.get(sub_url)
                    if sub_res.status_code == 200:
                        # VTT format
                        return sub_res.text
        except Exception as e:
            print(e)
    return None

print(get_transcript_piped("185XGEMe"))
