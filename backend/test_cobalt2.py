import requests

headers = {
    "Accept": "application/json",
    "Content-Type": "application/json"
}

data = {
    "url": "https://www.youtube.com/watch?v=185XGEMe",
    "isAudioOnly": True
}

try:
    res = requests.post("https://api.cobalt.tools/", headers=headers, json=data, timeout=10)
    print(res.status_code)
    print(res.json())
except Exception as e:
    print(e)
