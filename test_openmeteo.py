import urllib.request
import json
import urllib.parse

def get_weather_openmeteo(city: str) -> dict:
    # 1. If no city, get from IP
    if not city:
        try:
            req = urllib.request.Request("http://ip-api.com/json/", headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                city = data.get("city", "Bangalore") # fallback
        except:
            city = "Bangalore"
            
    # 2. Get lat/long
    try:
        url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote_plus(city)}&count=1&language=en&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            if not data.get("results"):
                return {"error": "City not found"}
            lat = data["results"][0]["latitude"]
            lon = data["results"][0]["longitude"]
            display_city = data["results"][0]["name"]
    except Exception as e:
        return {"error": f"Geocoding failed: {e}"}
        
    # 3. Get weather
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read().decode())
            temp = data["current"]["temperature_2m"]
            code = data["current"]["weather_code"]
            
            # WMO Weather interpretation codes
            # https://open-meteo.com/en/docs
            weather_map = {
                0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
                45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
                61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain", 71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
                77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
                85: "Slight snow showers", 86: "Heavy snow showers", 95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail"
            }
            condition = weather_map.get(code, "Unknown")
            
            return {
                "temp": temp,
                "condition": condition,
                "city": display_city
            }
    except Exception as e:
        return {"error": f"Weather fetch failed: {e}"}

if __name__ == "__main__":
    print("Testing openmeteo...")
    print("Empty city:", get_weather_openmeteo(""))
    print("Mumbai:", get_weather_openmeteo("Mumbai"))
    print("blr:", get_weather_openmeteo("blr"))
