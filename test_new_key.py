import os
from groq import Groq
from dotenv import load_dotenv

# Ensure we're reading the freshest .env
load_dotenv(override=True)

api_key = os.getenv("GROQ_API_KEY")
print(f"Loaded API Key starting with: {api_key[:8]}...")

client = Groq(api_key=api_key)

try:
    print("Testing llama-3.3-70b-versatile...")
    chat = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": "Hello, are you there?"}],
        max_tokens=50
    )
    print("Success! Response:", chat.choices[0].message.content.strip())
except Exception as e:
    print("Failed:", e)
