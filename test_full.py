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

# Test 2: AI engine action_type
print("=== Test 2: parse_intent ===")
routed = parse_intent("play samay raina latest video")
print("action_type    :", routed["action_type"])
print("action_payload :", routed["action_payload"])
print("spoken_response:", routed["spoken_response"])
print()

# Test 3: Executor
print("=== Test 3: _play_youtube executor ===")
r = _play_youtube(routed["action_payload"])
print("Executor result:", r)
