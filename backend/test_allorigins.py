import requests

res = requests.get("https://api.allorigins.win/get?url=https://www.youtube.com/watch?v=185XGEMe")
if res.status_code == 200:
    data = res.json()
    html = data.get("contents", "")
    print(len(html))
    if "captions" in html:
        print("Captions found!")
    else:
        print("No captions string in HTML")
else:
    print("Failed")
