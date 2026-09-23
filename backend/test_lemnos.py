import requests
res = requests.get("https://yt.lemnoslife.com/noKey/captions?part=snippet&videoId=185XGEMe")
print(res.status_code)
print(res.text[:200])
