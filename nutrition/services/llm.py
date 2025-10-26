# nutrition/services/llm.py
import os
from openai import OpenAI

_client = None

def get_client():
    global _client
    if _client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("Set OPENAI_API_KEY in your environment")
        _client = OpenAI(api_key=key)
    return _client
