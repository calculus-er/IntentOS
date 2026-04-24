import sys
sys.path.insert(0, ".")

from backend.executor import _check_weather

print(_check_weather("what is the weather in Mumbai"))
print()
print(_check_weather("what is the weather"))
