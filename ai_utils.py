import os
from dotenv import load_dotenv
import anthropic
from groq import Groq

load_dotenv()
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def translate_text(text: str, target_language: str = 'English') -> str:
    if not groq_client:
        return text
    completion = groq_client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[
            {"role": "system", "content": f"You are a perfect translator. Translate the following text to {target_language}."},
            {"role": "user", "content": text}
        ],
        temperature=0.5,
        max_tokens=4150,
        top_p=1,
        stream=False,
    )
    return completion.choices[0].message.content.strip()


def process_with_claude_sonnet(text: str, personal_info: dict) -> str:
    if not anthropic_client:
        return ""
    system_prompt = (
        f"You are an expert at engaging in neutral conversations with people from various nationalities. "
        f"Additional information: you are preparing suggestions for {personal_info.get('name','')}."
        f"{personal_info.get('goal','')}. {personal_info.get('style','')}. {personal_info.get('length','')}. "
        f"Here is transcript of conversation:"
    )
    message = anthropic_client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=4000,
        temperature=0.2,
        system=system_prompt,
        messages=[{"role": "user", "content": text}],
    )
    return message.content


def process_sonnet_response(sonnet_response: str, target_language: str) -> str:
    if not anthropic_client:
        return sonnet_response
    system_prompt = (
        f"You are a professional transliterator of text. Transliterate the following text to {target_language}."
    )
    message = anthropic_client.messages.create(
        model="claude-3-5-sonnet-20240620",
        max_tokens=4000,
        temperature=0.1,
        system=system_prompt,
        messages=[{"role": "user", "content": sonnet_response}],
    )
    return message.content
