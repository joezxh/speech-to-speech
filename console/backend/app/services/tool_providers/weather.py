"""天气 provider：有 OpenWeatherMap key 走实时，无 key 用城市样例。"""

from __future__ import annotations

import httpx

from app.config import tools

DEMO_CITIES = {
    "北京": (22, "晴", 55, "东南风 2 级"),
    "上海": (25, "多云", 70, "东风 3 级"),
    "深圳": (29, "阵雨", 85, "南风 2 级"),
    "杭州": (24, "晴间多云", 65, "东南风 2 级"),
}


def _api_key() -> str:
    return tools.openweather_api_key.strip()


async def weather(city: str) -> dict:
    key = _api_key()
    if key:
        try:
            async with httpx.AsyncClient(timeout=12.0) as http:
                response = await http.get(
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": city, "appid": key, "units": "metric", "lang": "zh_cn"},
                )
            response.raise_for_status()
            data = response.json()
            return {
                "mode": "live",
                "city": data.get("name", city),
                "temperature": data["main"]["temp"],
                "condition": data["weather"][0]["description"],
                "humidity": data["main"]["humidity"],
                "wind": f"{data.get('wind', {}).get('speed', 0)} m/s",
            }
        except Exception:
            pass
    for name, (temp, condition, humidity, wind) in DEMO_CITIES.items():
        if name in city or city in name:
            return {
                "mode": "demo",
                "city": city,
                "temperature": temp,
                "condition": condition,
                "humidity": humidity,
                "wind": wind,
            }
    return {
        "mode": "demo",
        "city": city,
        "temperature": 23,
        "condition": "晴（演示数据）",
        "humidity": 60,
        "wind": "微风",
    }
