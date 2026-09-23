import requests
res = requests.get("https://corsproxy.io/?https://www.youtube.com/watch?v=185XGEMe")
print(res.status_code)
html = res.text
if "captions" in html:
    print("Captions found!")
else:
    print("No captions found!")
