#!/usr/bin/env python3
"""Ghost voice assistant.

This project intentionally avoids executing arbitrary shell commands from voice input.
It only opens a strict allowlist of safe URLs and local home-directory paths.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import re
import sys
import webbrowser
from typing import Any, Optional
from urllib.parse import urlparse

try:
    import pyttsx3
except Exception:  # pragma: no cover - optional runtime dependency
    pyttsx3 = None

try:
    import speech_recognition as sr
except Exception:  # pragma: no cover - optional runtime dependency
    sr = None

try:
    import wikipedia
except Exception:  # pragma: no cover - optional runtime dependency
    wikipedia = None


ALLOWED_DOMAINS = {
    "youtube.com",
    "www.youtube.com",
    "google.com",
    "www.google.com",
    "github.com",
    "www.github.com",
    "stackoverflow.com",
    "www.stackoverflow.com",
    "spotify.com",
    "www.spotify.com",
    "wikipedia.org",
    "www.wikipedia.org",
}


def sanitize_text(value: object) -> str:
    """Remove control chars and unsafe whitespace while keeping a compact string."""
    if value is None:
        return ""
    cleaned = str(value)
    cleaned = "".join(ch for ch in cleaned if ch.isprintable() and ch not in "\r\n\t\x00")
    cleaned = cleaned.strip()
    return cleaned[:200]


def normalize_query(value: object) -> str:
    """Convert voice text into a lower-case command string suitable for matching."""
    cleaned = sanitize_text(value).lower()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def safe_url(raw_url: object) -> Optional[str]:
    """Accept only safe HTTP(S) URLs on a small allowlist."""
    candidate = sanitize_text(raw_url)
    if not candidate:
        return None
    if not (candidate.startswith("http://") or candidate.startswith("https://")):
        return None

    parsed = urlparse(candidate)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None

    allowed = hostname in ALLOWED_DOMAINS or any(hostname.endswith(f".{domain}") for domain in ALLOWED_DOMAINS)
    if not allowed:
        return None

    return candidate


def sanitize_path(raw_path: object) -> Optional[str]:
    """Keep file access restricted to the current user's home directory."""
    candidate = sanitize_text(raw_path)
    if not candidate:
        return None

    expanded = os.path.expanduser(candidate)
    absolute = os.path.abspath(expanded)
    home = os.path.expanduser("~")

    try:
        common = os.path.commonpath([home, absolute])
    except ValueError:
        return None

    if common != home:
        return None

    if ".." in candidate.split(os.sep):
        return None

    return absolute


class GhostAssistant:
    def __init__(self, use_tts: bool = True) -> None:
        self.use_tts = use_tts
        self.engine: Any | None = None
        self.recognizer: Any = sr.Recognizer() if sr is not None else None
        self._initialize_engine()

    def _initialize_engine(self) -> None:
        if pyttsx3 is None or not self.use_tts:
            return
        try:
            self.engine = pyttsx3.init()
            voices = self.engine.getProperty("voices") or []
            if voices:
                preferred = next((voice for voice in voices if "female" in voice.name.lower()), voices[0])
                self.engine.setProperty("voice", preferred.id)
            self.engine.setProperty("rate", 170)
        except Exception as exc:  # pragma: no cover - environment specific
            logging.warning("TTS initialization failed: %s", exc)
            self.engine = None

    def speak(self, text: object) -> None:
        message = sanitize_text(text)
        if not message:
            return

        print(f"[Assistant] {message}")
        if self.engine is not None:
            try:
                self.engine.say(message)
                self.engine.runAndWait()
            except Exception as exc:  # pragma: no cover - runtime voice layer
                logging.warning("Voice output failed: %s", exc)

    def listen(self) -> str:
        if self.recognizer is None or sr is None:
            raise RuntimeError("Speech recognition is not available because the microphone dependency is missing.")

        with sr.Microphone() as source:
            print("Listening...")
            self.recognizer.pause_threshold = 1
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = self.recognizer.listen(source, timeout=10, phrase_time_limit=10)

        try:
            print("Recognizing...")
            recognizer_fn = getattr(self.recognizer, "recognize_google", None)
            if not callable(recognizer_fn):
                raise RuntimeError("Google speech recognizer is unavailable.")
            return sanitize_text(recognizer_fn(audio, language="en-US"))
        except Exception as exc:
            if sr is not None and isinstance(exc, sr.UnknownValueError):
                self.speak("I did not catch that. Please say it again.")
                return ""
            if sr is not None and isinstance(exc, sr.RequestError):
                self.speak("The speech service is unavailable right now.")
                logging.error("Speech recognition request failed: %s", exc)
                return ""
            self.speak("I could not process that audio input.")
            logging.exception("Speech recognition error: %s", exc)
            return ""

    def open_url(self, target: str) -> bool:
        safe = safe_url(target)
        if not safe:
            self.speak("That website is not on the approved list for safety.")
            return False
        webbrowser.open(safe, new=2)
        return True

    def open_home_directory(self, directory_name: str) -> bool:
        mapping = {
            "home": os.path.expanduser("~"),
            "desktop": os.path.expanduser("~/Desktop"),
            "downloads": os.path.expanduser("~/Downloads"),
            "documents": os.path.expanduser("~/Documents"),
            "project": os.path.expanduser("~/Desktop/voice_assistant-master"),
        }
        target = mapping.get(directory_name)
        if not target:
            return False

        safe_target = sanitize_path(target)
        if safe_target is None:
            self.speak("That location is not allowed.")
            return False

        webbrowser.open(f"file://{safe_target}")
        return True

    def search_wikipedia(self, topic: str) -> None:
        if wikipedia is None:
            self.speak("Wikipedia support is not installed in this environment.")
            return

        query = normalize_query(topic).replace("wikipedia", "").strip()
        if not query:
            self.speak("Please say the topic you want to search.")
            return

        try:
            self.speak("Searching Wikipedia for the requested topic.")
            summary = wikipedia.summary(query, sentences=2)
            self.speak(summary)
        except Exception as exc:
            logging.warning("Wikipedia lookup failed: %s", exc)
            self.speak("I could not find a reliable result for that topic.")

    def handle_query(self, query: str) -> bool:
        normalized = normalize_query(query)
        if not normalized:
            return True

        if normalized in {"hello", "hi", "hey", "good morning", "good evening"}:
            self.speak("Hello. I am Ghost. How can I help you today?")
            return True

        if "who are you" in normalized or "are you" in normalized:
            self.speak("I am Ghost, your privacy-aware voice assistant for quick browsing and local tasks.")
            return True

        if "help" in normalized:
            self.speak("I can search Wikipedia, open safe sites, tell the time, and open your home folders.")
            return True

        if "time" in normalized:
            current = dt.datetime.now().strftime("%I:%M %p")
            self.speak(f"The current time is {current}.")
            return True

        if "date" in normalized:
            current = dt.datetime.now().strftime("%A, %B %d, %Y")
            self.speak(f"Today is {current}.")
            return True

        if "wikipedia" in normalized:
            self.search_wikipedia(normalized)
            return True

        if "open youtube" in normalized:
            self.open_url("https://www.youtube.com")
            return True

        if "open google" in normalized:
            self.open_url("https://www.google.com")
            return True

        if "open github" in normalized:
            self.open_url("https://www.github.com")
            return True

        if "open stack overflow" in normalized:
            self.open_url("https://stackoverflow.com")
            return True

        if "open spotify" in normalized:
            self.open_url("https://www.spotify.com")
            return True

        if "open desktop" in normalized:
            self.open_home_directory("desktop")
            return True

        if "open downloads" in normalized:
            self.open_home_directory("downloads")
            return True

        if "open project" in normalized or "open workspace" in normalized:
            self.open_home_directory("project")
            return True

        if "sleep" in normalized or "exit" in normalized or "shutdown" in normalized:
            self.speak("Goodbye. Ghost is going to sleep.")
            raise SystemExit(0)

        self.speak("I did not recognize that command. Try asking for help, the time, or to open a supported website.")
        return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ghost Voice Assistant")
    parser.add_argument("--demo", action="store_true", help="Run a small interactive command demo without microphone access.")
    parser.add_argument("--no-tts", action="store_true", help="Disable text-to-speech output.")
    return parser


def print_banner() -> None:
    banner = r"""
    .--.  .--.  .--.  .--.  .-. .-.  .--.  .-. .-.  .-. .-. 
    | {}  | |  | |  | |  |  | | | | |  | |  | |  | | | | 
    |  |  | |  | |  | |  |  | | | |  | |  | |  | | | | 
    |  |  | |  | |  | |  | | | | |  | |  | |  | | | | 
    |  |_ | |_| |_| |_| |_| |_|_|_|_| |  | |  |_|_|_|_|_|
    |_____|\____/\____/\____/\____/\____/\____/\____/\____/\____/ 
    """
    print(banner)
    print("Ghost voice assistant is ready.")


def run_demo() -> None:
    assistant = GhostAssistant(use_tts=False)
    demo_queries = [
        "hello",
        "what time is it",
        "open youtube",
        "open project",
        "help",
    ]
    for text in demo_queries:
        print(f"\nUser: {text}")
        assistant.handle_query(text)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    print_banner()

    if args.demo:
        run_demo()
        return

    assistant = GhostAssistant(use_tts=not args.no_tts)
    assistant.speak("Ghost assistance activated. How can I help you?")

    while True:
        try:
            spoken_text = assistant.listen()
            if not spoken_text:
                continue
            assistant.handle_query(spoken_text)
        except KeyboardInterrupt:
            print("\nStopping Ghost assistant.")
            break
        except SystemExit:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            logging.exception("Unexpected runtime error: %s", exc)
            assistant.speak("I hit an unexpected issue. Please try again.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()
