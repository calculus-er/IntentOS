import urllib.request

def get_weather(city: str) -> str:
    # URL encode city
    import urllib.parse
    encoded = urllib.parse.quote_plus(city)
    url = f"https://wttr.in/{encoded}?format=%C+%t"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8")
            return data.strip()
    except Exception as e:
        return f"Error: {e}"

print("Mumbai:", get_weather("Mumbai"))
print("New York:", get_weather("New York"))
print("Empty (IP based):", get_weather(""))
