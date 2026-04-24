"""Full test of the entire youtube_play pipeline."""
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()  # MUST load before anything else

from backend.youtube_resolver import resolve_video
from backend.ai_engine import parse_intent
from backend.executor import _play_youtube

# Test 1: Resolver
print("=== Test 1: resolve_video ===")
result = resolve_video("Samay Raina latest video")
print("Result:", result)
print()

# Test 2: AI engine (multi-action shape)
print("=== Test 2: parse_intent ===")
routed = parse_intent("play samay raina latest video")
print("actions          :", routed["actions"])
print("spoken_response  :", routed["spoken_response"])
print()

# Test 3: Executor
print("=== Test 3: _play_youtube executor ===")
yt_payload = next(
    (a["action_payload"] for a in routed["actions"] if a["action_type"] == "youtube_play"),
    "",
)
r = _play_youtube(yt_payload)
print("Executor result:", r)
