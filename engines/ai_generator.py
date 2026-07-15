"""
AI email generation engine powered by Google Gemini.

No PySide6 imports.  Accepts raw, messy LinkedIn context and returns a
structured pitch (subject + body).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types


@dataclass
class GeneratedPitch:
    subject: str
    body: str


_SYSTEM_INSTRUCTION = """\
You are a world-class cold-email copywriter specialising in job-search outreach.
Your task is to write a hyper-personalised, zero-jargon cold email for the user.

Rules you must follow without exception:
1. The email body must be STRICTLY under 80 words — count them.
2. Write one punchy subject line (max 8 words, no clickbait).
3. Identify a single unique "hook": a genuine professional angle, shared interest,
   or specific recent activity gleaned from the provided context.
4. Ignore all UI artefacts, timestamps, button labels, or formatting noise in
   the context — extract only semantically meaningful information.
5. Tone: confident, direct, human.  No hollow phrases like "I hope this finds
   you well", "synergy", "leverage", "passionate", or "excited to connect".
6. Do NOT invent facts not present in the context.
7. Do NOT write any closing, sign-off, sender name, website, or signature.
   End the email with your final sentence. Do NOT mention SENDER WEBSITE
   anywhere in the body. A signature (closing + name + website) is appended
   automatically after your output, so leaving it out avoids duplication.

Output format — return exactly two labelled blocks and nothing else:
SUBJECT: <subject line here>
BODY:
<email body here>
"""


def _build_user_prompt(
    target_name: str,
    company: str,
    raw_context: str,
    sender_name: str = "",
    sender_website: str = "",
) -> str:
    return (
        f"TARGET NAME: {target_name}\n"
        f"COMPANY: {company}\n"
        f"SENDER NAME: {sender_name}\n"
        f"SENDER WEBSITE: {sender_website}\n\n"
        f"RAW CONTEXT FROM LINKEDIN (may be messy):\n{raw_context}"
    )


# Closings the model might still emit despite instructions — used to strip any
# stray sign-off before we append our own deterministic signature.
_CLOSINGS = (
    "best", "best regards", "regards", "kind regards", "warm regards",
    "thanks", "thank you", "cheers", "sincerely", "warmly", "all the best",
    "talk soon", "looking forward",
)


def _strip_trailing_signature(body: str) -> str:
    """Remove any closing/sign-off the model added at the end of the body."""
    lines = body.rstrip().splitlines()
    # Scan the last few lines for a closing word; cut from there down.
    for i in range(len(lines)):
        stripped = lines[i].strip().lower().rstrip(",.")
        if stripped in _CLOSINGS:
            return "\n".join(lines[:i]).rstrip()
    return body.rstrip()


def _apply_signature(pitch: "GeneratedPitch", sender_name: str,
                     sender_website: str) -> "GeneratedPitch":
    """Append a consistent 'Best, / Name / Website' signature to the body."""
    if not sender_name and not sender_website:
        return pitch

    body = _strip_trailing_signature(pitch.body)
    sig_lines = ["Best,"]
    if sender_name:
        sig_lines.append(sender_name)
    if sender_website:
        sig_lines.append(sender_website)

    new_body = body.rstrip() + "\n\n" + "\n".join(sig_lines)
    return GeneratedPitch(subject=pitch.subject, body=new_body)


def _parse_response(text: str) -> GeneratedPitch:
    """Extract SUBJECT and BODY from the model's raw text response."""
    subject = ""
    body_lines: list[str] = []
    in_body = False

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("SUBJECT:"):
            subject = stripped[len("SUBJECT:"):].strip()
        elif stripped.upper() == "BODY:":
            in_body = True
        elif in_body:
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    if not subject or not body:
        # Graceful fallback: return the whole response as body
        return GeneratedPitch(subject="(see body)", body=text.strip())
    return GeneratedPitch(subject=subject, body=body)


def default_instructions() -> str:
    """Return the built-in system instructions (shown in the editor as a starting point)."""
    return _SYSTEM_INSTRUCTION


def generate_pitch(
    target_name: str,
    company: str,
    raw_context: str,
    api_key: str | None = None,
    sender_name: str = "",
    sender_website: str = "",
    instructions: str = "",
    model_name: str = "gemini-3.5-flash",
) -> GeneratedPitch:
    """
    Call the Gemini API and return a structured cold-email pitch.

    *sender_name* signs off the email (avoids a "[Your Name]" placeholder).
    *sender_website* is appended under the name in the signature when non-empty.
    *instructions* fully overrides the system prompt when non-empty; otherwise the
    built-in default (``default_instructions()``) is used.
    *api_key* falls back to the ``GEMINI_API_KEY`` environment variable.
    Raises ``ValueError`` if no key is available.
    """
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "No Gemini API key found.  Set GEMINI_API_KEY in your environment "
            "or pass api_key= explicitly."
        )

    system_instruction = instructions.strip() or _SYSTEM_INSTRUCTION

    client = genai.Client(api_key=key)
    prompt = _build_user_prompt(
        target_name, company, raw_context, sender_name, sender_website
    )
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            system_instruction=system_instruction,
        ),
    )
    pitch = _parse_response(response.text)
    return _apply_signature(pitch, sender_name, sender_website)
