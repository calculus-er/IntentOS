import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

models_to_test = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
    "gemma2-9b-it"
]

for model in models_to_test:
    print(f"Testing model: {model}")
    try:
        chat = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=10
        )
        print(f"  Success! Response: {chat.choices[0].message.content.strip()}")
    except Exception as e:
        print(f"  Failed: {e}")
    print("-" * 40)
