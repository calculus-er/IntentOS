import urllib.parse, urllib.request, re
url = 'https://www.youtube.com/results?search_query=' + urllib.parse.quote_plus('Samay Raina')
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
html = urllib.request.urlopen(req).read().decode('utf-8')
print(re.findall(r'"videoId":"([\w\-]{11})"', html)[:5])
