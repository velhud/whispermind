import pyaudio
import wave
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import base64
import threading
import datetime
import queue
import os
import io
import json
import time
import re
import copy
from typing import List, Dict, Tuple, Optional, Any, Callable
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv
import anthropic
import websocket

LEGACY_GROQ_BACKEND = "Legacy Groq Whisper + Groq Translate"
OPENAI_CHUNKED_BACKEND = "OpenAI GPT-4o Transcribe + Translate"
OPENAI_REALTIME_BACKEND = "OpenAI Realtime Translation"

LANGUAGE_CODES = {
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Chinese": "zh",
    "Japanese": "ja",
    "Korean": "ko",
    "Arabic": "ar",
    "Russian": "ru",
    "Italian": "it",
    "Portuguese": "pt",
}

TRANSLITERATION_LANGUAGES = [
    "Russian",
    "Spanish",
    "French",
    "German",
    "Chinese",
    "Japanese",
    "Korean",
    "Arabic",
]

TEXT_TRANSLATION_LANGUAGES = [
    "English",
    "Spanish",
    "French",
    "German",
    "Chinese",
    "Japanese",
    "Korean",
    "Arabic",
    "Russian",
    "Italian",
    "Portuguese",
    "Hindi",
    "Indonesian",
    "Vietnamese",
]

REALTIME_OUTPUT_LANGUAGES = [
    "Spanish",
    "Portuguese",
    "French",
    "Japanese",
    "Russian",
    "Chinese",
    "German",
    "Korean",
    "Hindi",
    "Indonesian",
    "Vietnamese",
    "Italian",
    "English",
]


def language_code(language_name):
    """Return a best-effort language code for OpenAI realtime settings."""
    return LANGUAGE_CODES.get(language_name, language_name[:2].lower())


def extract_text(response):
    """Normalize SDK responses that may be strings or objects with text fields."""
    if isinstance(response, str):
        return response.strip()
    text = getattr(response, "text", None)
    if text is not None:
        return text.strip()
    if isinstance(response, dict):
        return str(response.get("text", "")).strip()
    return str(response).strip()


def extract_anthropic_text(message):
    """Extract plain text from Anthropic message content blocks."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(block["text"])
        return "\n".join(parts).strip()
    return str(content).strip()


class RealtimeTranslationSession:
    """Streams microphone audio to OpenAI realtime translation."""

    RATE = 24000
    CHUNK = 1200
    FORMAT = pyaudio.paInt16
    CHANNELS = 1

    def __init__(
        self,
        api_key,
        target_language,
        ui_delta_updater,
        add_transcription,
        status_callback=None,
        stop_callback=None,
    ):
        self.api_key = api_key
        self.target_language = target_language
        self.ui_delta_updater = ui_delta_updater
        self.add_transcription = add_transcription
        self.status_callback = status_callback
        self.stop_callback = stop_callback
        self.ws = None
        self.audio = None
        self.stream = None
        self.running = False
        self.sender_thread = None
        self.receiver_thread = None
        self.source_buffer = ""
        self.source_lock = threading.Lock()
        self.stop_notified = False

    def start(self):
        if self.running:
            return
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI realtime translation")

        self.ws = websocket.WebSocket()
        self.ws.connect(
            "wss://api.openai.com/v1/realtime/translations?model=gpt-realtime-translate",
            header=[
                f"Authorization: Bearer {self.api_key}",
                "OpenAI-Safety-Identifier: whispermind-local-user",
            ],
        )
        self.running = True
        self._send_session_update()

        self.receiver_thread = threading.Thread(target=self._receive_events, daemon=True)
        self.sender_thread = threading.Thread(target=self._send_audio, daemon=True)
        self.receiver_thread.start()
        self.sender_thread.start()

        if self.status_callback:
            self.status_callback("OpenAI realtime translation started")

    def stop(self):
        self.running = False
        self.flush_source_buffer()
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
        except Exception:
            pass
        try:
            if self.audio:
                self.audio.terminate()
        except Exception:
            pass
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        if self.stop_callback and not self.stop_notified:
            self.stop_notified = True
            self.stop_callback()

    def _send_session_update(self):
        self.ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "audio": {
                            "input": {
                                "transcription": {
                                    "model": "gpt-realtime-whisper",
                                },
                            },
                            "output": {
                                "language": language_code(self.target_language),
                            },
                        },
                    },
                }
            )
        )

    def _send_audio(self):
        try:
            self.audio = pyaudio.PyAudio()
            self.stream = self.audio.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK,
            )

            while self.running:
                data = self.stream.read(self.CHUNK, exception_on_overflow=False)
                self.ws.send(
                    json.dumps(
                        {
                            "type": "session.input_audio_buffer.append",
                            "audio": base64.b64encode(data).decode("ascii"),
                        }
                    )
                )
        except Exception as e:
            if self.running and self.status_callback:
                self.status_callback(f"Realtime audio error: {e}")
            self.stop()

    def _receive_events(self):
        try:
            while self.running:
                raw_event = self.ws.recv()
                if not raw_event:
                    continue
                event = json.loads(raw_event)
                event_type = event.get("type")

                if event_type == "session.output_transcript.delta":
                    self.ui_delta_updater("", event.get("delta", ""))
                elif event_type == "session.input_transcript.delta":
                    delta = event.get("delta", "")
                    self.ui_delta_updater(delta, "")
                    self._record_source_delta(delta)
                elif event_type == "error":
                    message = event.get("error", {}).get("message", event)
                    if self.status_callback:
                        self.status_callback(f"Realtime API error: {message}")
                    self.stop()
                    break
        except Exception as e:
            if self.running and self.status_callback:
                self.status_callback(f"Realtime receive error: {e}")
        finally:
            self.stop()

    def _record_source_delta(self, delta):
        if not delta:
            return

        with self.source_lock:
            self.source_buffer += delta
            should_flush = (
                len(self.source_buffer) >= 240
                or self.source_buffer.rstrip().endswith((".", "!", "?", "\n"))
            )
            if should_flush:
                text = self.source_buffer.strip()
                self.source_buffer = ""
                if text:
                    self.add_transcription(datetime.datetime.now(), text)

    def flush_source_buffer(self):
        """Persist any pending source transcript fragment before shutdown."""
        with self.source_lock:
            text = self.source_buffer.strip()
            self.source_buffer = ""
        if text:
            self.add_transcription(datetime.datetime.now(), text)

class AudioRecorder:
    """Handles audio recording and processing."""
    
    # Audio recording constants
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    
    def __init__(self, config_manager, status_callback=None, state_callback=None):
        """Initialize the audio recorder.
        
        Args:
            config_manager: The configuration manager instance
            status_callback: Function to call for status updates
        """
        self.config_manager = config_manager
        self.status_callback = status_callback
        self.state_callback = state_callback
        self.is_recording = False
        self.active_backend = None
        self.stop_event = threading.Event()
        self.audio_data_available = threading.Event()
        self.buffer = queue.Queue()
        self.audio = None
        self.recording_start_time = None
        self.listen_thread = None
        self.process_audio_thread = None
        self.overlap_buffer = []
        self.overlap_seconds = 0.5
        self.overlap_frames = int(self.RATE / self.CHUNK * self.overlap_seconds)
        self.last_minute_timestamp = None

    def start_recording(self):
        """Start audio recording and processing."""
        if self.is_recording:
            return

        if self.config_manager.get_translation_backend() == OPENAI_REALTIME_BACKEND:
            self.active_backend = OPENAI_REALTIME_BACKEND
            self.config_manager.transcription_manager.start_realtime_translation(
                self.status_callback,
                self._handle_realtime_stopped,
            )
            self.is_recording = True
            if self.state_callback:
                self.state_callback(True)
            if self.status_callback:
                self.status_callback("Recording with OpenAI realtime translation")
            return
            
        self.is_recording = True
        self.active_backend = self.config_manager.get_translation_backend()
        self.stop_event.clear()
        self.recording_start_time = datetime.datetime.now()
        self.buffer = queue.Queue()
        
        self.listen_thread = threading.Thread(target=self._listen)
        self.listen_thread.daemon = True
        self.listen_thread.start()
        
        self.process_audio_thread = threading.Thread(target=self._process_audio)
        self.process_audio_thread.daemon = True
        self.process_audio_thread.start()
        
        if self.status_callback:
            self.status_callback("Recording started")
        if self.state_callback:
            self.state_callback(True)

    def stop_recording(self):
        """Stop audio recording and processing."""
        if not self.is_recording:
            return
            
        self.is_recording = False
        self.stop_event.set()
        self.audio_data_available.set()  # Wake up waiting threads

        if self.active_backend == OPENAI_REALTIME_BACKEND:
            self.config_manager.transcription_manager.stop_realtime_translation()
        self.active_backend = None
        
        if self.status_callback:
            self.status_callback("Recording stopped")
        if self.state_callback:
            self.state_callback(False)

    def _handle_realtime_stopped(self):
        """Keep recorder/UI state in sync when realtime ends from an API error."""
        self.is_recording = False
        self.active_backend = None
        if self.state_callback:
            self.state_callback(False)
        if self.status_callback:
            self.status_callback("Realtime session stopped", "orange")

    def _listen(self):
        """Record audio and put it in the buffer."""
        try:
            self.audio = pyaudio.PyAudio()
            stream = self.audio.open(
                format=self.FORMAT, 
                channels=self.CHANNELS,
                rate=self.RATE, 
                input=True,
                frames_per_buffer=self.CHUNK
            )
            
            while self.is_recording and not self.stop_event.is_set():
                try:
                    data = stream.read(self.CHUNK, exception_on_overflow=False)
                    self.buffer.put(data)
                    self.audio_data_available.set()
                except Exception as e:
                    if self.status_callback:
                        self.status_callback(f"Error during recording: {e}")
                    time.sleep(0.1)
        except Exception as e:
            self.is_recording = False
            self.stop_event.set()
            if self.state_callback:
                self.state_callback(False)
            if self.status_callback:
                self.status_callback(f"Failed to initialize audio: {e}")
        finally:
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()
            if self.audio:
                self.audio.terminate()

    def _process_audio(self):
        """Process recorded audio chunks and send for transcription."""
        while self.is_recording and not self.stop_event.is_set():
            try:
                record_seconds = self.config_manager.get_recording_period()
                
                frames = []
                frames.extend(self.overlap_buffer)
                chunk_start_time = datetime.datetime.now()
                
                for i in range(0, int(self.RATE / self.CHUNK * record_seconds)):
                    if not self.is_recording or self.stop_event.is_set():
                        break
                    self.audio_data_available.wait(timeout=1)
                    if not self.buffer.empty():
                        data = self.buffer.get()
                        frames.append(data)
                        if self.buffer.empty():
                            self.audio_data_available.clear()
                
                if frames:
                    self.overlap_buffer = frames[-self.overlap_frames:]
                    audio_data = b''.join(frames)
                    
                    # Create WAV file in memory
                    wav_buffer = io.BytesIO()
                    with wave.open(wav_buffer, 'wb') as wf:
                        wf.setnchannels(self.CHANNELS)
                        wf.setsampwidth(self.audio.get_sample_size(self.FORMAT))
                        wf.setframerate(self.RATE)
                        wf.writeframes(audio_data)
                    
                    wav_buffer.seek(0)
                    
                    # Send for transcription
                    self.config_manager.transcription_manager.process_audio(
                        wav_buffer,
                        chunk_start_time,
                        self.active_backend,
                    )
            except Exception as e:
                if self.status_callback:
                    self.status_callback(f"Error processing audio: {e}")
                time.sleep(0.5)

    def transcribe_file(self, file_path):
        """Transcribe an audio file."""
        try:
            with open(file_path, "rb") as file:
                self.config_manager.transcription_manager.process_file(
                    file_path,
                    file.read(),
                    datetime.datetime.now()
                )
        except Exception as e:
            if self.status_callback:
                self.status_callback(f"Error transcribing file: {e}")


class TranscriptionManager:
    """Manages audio transcription and text processing."""
    
    def __init__(self, config_manager, ui_updater, realtime_ui_updater=None, status_callback=None):
        """Initialize the transcription manager.
        
        Args:
            config_manager: The configuration manager instance
            ui_updater: Function to update the UI with transcription results
        """
        self.config_manager = config_manager
        self.ui_updater = ui_updater
        self.realtime_ui_updater = realtime_ui_updater
        self.status_callback = status_callback
        self.transcription_texts = []
        self.transcription_lock = threading.Lock()
        self.last_minute_timestamp = None
        self.audio_worker_lock = threading.Lock()
        self.file_worker_lock = threading.Lock()
        self.groq_client = None
        self.openai_client = None
        self.anthropic_client = None
        self.realtime_translation_session = None
        self._initialize_clients()
        
    def _initialize_clients(self):
        """Initialize API clients."""
        try:
            # Initialize Groq client
            groq_api_key = os.getenv('GROQ_API_KEY')
            if groq_api_key:
                self.groq_client = Groq(api_key=groq_api_key)
                print("Groq API Key successfully retrieved")
            else:
                print("Groq API Key not found. Some features may not work.")

            # Initialize OpenAI client
            openai_api_key = os.getenv('OPENAI_API_KEY')
            if openai_api_key:
                self.openai_client = OpenAI(api_key=openai_api_key)
                print("OpenAI API Key successfully retrieved")
            else:
                print("OpenAI API Key not found. OpenAI translation backends may not work.")
                
            # Initialize Anthropic client
            anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
            if anthropic_api_key:
                self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
                print("Anthropic API Key successfully retrieved")
            else:
                print("Anthropic API Key not found. Suggestion features may not work.")
        except Exception as e:
            print(f"Error initializing API clients: {e}")

    def start_realtime_translation(self, status_callback=None, stop_callback=None):
        """Start a dedicated OpenAI realtime translation session."""
        if self.realtime_translation_session:
            return
        if not self.realtime_ui_updater:
            raise RuntimeError("Realtime UI updater is not initialized")
        if not os.getenv('OPENAI_API_KEY'):
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI realtime translation")

        self.realtime_translation_session = RealtimeTranslationSession(
            api_key=os.getenv('OPENAI_API_KEY'),
            target_language=self.config_manager.get_translation_language(),
            ui_delta_updater=self.realtime_ui_updater,
            add_transcription=self.add_transcription,
            status_callback=status_callback,
            stop_callback=stop_callback,
        )
        self.realtime_translation_session.start()

    def stop_realtime_translation(self):
        """Stop the active OpenAI realtime translation session."""
        if self.realtime_translation_session:
            self.realtime_translation_session.stop()
            self.realtime_translation_session = None

    def clear_history(self):
        """Clear suggestion context and timestamp grouping state."""
        with self.transcription_lock:
            self.transcription_texts = []
        self.last_minute_timestamp = None

    def add_transcription(self, timestamp, text):
        """Add a transcription to history with thread safety.
        
        Args:
            timestamp: The timestamp of the transcription
            text: The transcription text
        """
        with self.transcription_lock:
            max_items = 100  # Limit history size
            self.transcription_texts.append((timestamp, text))
            if len(self.transcription_texts) > max_items:
                self.transcription_texts = self.transcription_texts[-max_items:]

    def process_audio(self, audio_buffer, timestamp, backend=None):
        """Process audio data for transcription.
        
        Args:
            audio_buffer: The audio data buffer
            timestamp: The timestamp of the recording
        """
        acquired = False
        try:
            backend = backend or self.config_manager.get_translation_backend()
            if backend == OPENAI_REALTIME_BACKEND:
                return
            if backend == OPENAI_CHUNKED_BACKEND:
                if not self.openai_client:
                    raise Exception("OpenAI client not initialized")
            elif not self.groq_client:
                raise Exception("Groq client not initialized")

            acquired = self.audio_worker_lock.acquire(blocking=False)
            if not acquired:
                print("Skipping audio chunk because the previous transcription is still running.")
                if self.status_callback:
                    self.status_callback("Skipping chunk while previous transcription is still running", "orange")
                return
                
            # Use threading to avoid blocking
            threading.Thread(
                target=self._transcribe_audio_locked,
                args=(audio_buffer, timestamp, backend),
                daemon=True
            ).start()
        except Exception as e:
            if acquired:
                self.audio_worker_lock.release()
            print(f"Error processing audio: {e}")
            self.ui_updater(f"Error: {e}", "", "", timestamp)

    def process_file(self, file_path, file_data, timestamp):
        """Process an audio file for transcription.
        
        Args:
            file_path: Path to the audio file
            file_data: Raw file data
            timestamp: The timestamp of the transcription request
        """
        acquired = False
        try:
            backend = self.config_manager.get_file_backend()
            if backend == OPENAI_CHUNKED_BACKEND:
                if not self.openai_client:
                    raise Exception("OpenAI client not initialized")
            elif not self.groq_client:
                raise Exception("Groq client not initialized")

            acquired = self.file_worker_lock.acquire(blocking=False)
            if not acquired:
                raise Exception("Another file transcription is already running")
                
            threading.Thread(
                target=self._transcribe_file_locked,
                args=(file_path, file_data, timestamp, backend),
                daemon=True
            ).start()
        except Exception as e:
            if acquired:
                self.file_worker_lock.release()
            print(f"Error processing file: {e}")
            if self.status_callback:
                self.status_callback(f"File transcription failed: {e}", "red")
            self.ui_updater(f"Error: {e}", "", "", timestamp)

    def _transcribe_audio_locked(self, audio_buffer, timestamp, backend):
        try:
            self._transcribe_audio(audio_buffer, timestamp, backend)
        finally:
            try:
                self.audio_worker_lock.release()
            except RuntimeError:
                pass

    def _transcribe_file_locked(self, file_path, file_data, timestamp, backend):
        try:
            self._transcribe_file(file_path, file_data, timestamp, backend)
        finally:
            try:
                self.file_worker_lock.release()
            except RuntimeError:
                pass

    def _transcribe_audio(self, audio_buffer, timestamp, backend=None):
        """Transcribe audio data using Whisper API.
        
        Args:
            audio_buffer: The audio data buffer
            timestamp: The timestamp of the recording
        """
        try:
            backend = backend or self.config_manager.get_translation_backend()
            transcription_text = self.transcribe_audio_buffer(audio_buffer, "audio.wav", backend)
            
            # Translate the transcription
            translated_text = self.translate_text(transcription_text, backend)
            
            # Update UI based on timestamp mode
            timestamp_mode = self.config_manager.get_timestamp_mode()
            if timestamp_mode:
                current_minute = timestamp.replace(second=0, microsecond=0)
                if current_minute != self.last_minute_timestamp:
                    self.last_minute_timestamp = current_minute
                    self.ui_updater(transcription_text, translated_text, "", current_minute)
                    self.save_to_file(transcription_text, current_minute)
                else:
                    self.ui_updater(transcription_text, translated_text, "", None)
                    self.save_to_file(transcription_text, None)
            else:
                self.ui_updater(transcription_text, translated_text, "", timestamp)
                self.save_to_file(transcription_text, timestamp)
            
            # Add to transcription history
            self.add_transcription(timestamp, transcription_text)
            
        except Exception as e:
            print(f"Error during transcription: {e}")
            self.ui_updater(f"Error: {e}", "", "", timestamp)

    def _transcribe_file(self, file_path, file_data, timestamp, backend=None):
        """Transcribe an audio file.
        
        Args:
            file_path: Path to the audio file
            file_data: Raw file data
            timestamp: The timestamp of the transcription request
        """
        try:
            backend = backend or self.config_manager.get_file_backend()
            transcription_text = self.transcribe_audio_buffer(io.BytesIO(file_data), os.path.basename(file_path), backend)
            
            # Save transcription to file
            output_path = os.path.join(os.path.dirname(__file__), "transcription_from_file.txt")
            with open(output_path, "w", encoding='utf-8') as f:
                f.write(transcription_text)
            
            # Translate the transcription
            translated_text = self.translate_text(transcription_text, backend)
            
            # Update UI
            self.ui_updater(transcription_text, translated_text, "", timestamp)
            
            # Add to transcription history
            self.add_transcription(timestamp, transcription_text)
            if self.status_callback:
                self.status_callback("File transcription complete", "green")
            
        except Exception as e:
            print(f"Error transcribing file: {e}")
            if self.status_callback:
                self.status_callback(f"File transcription failed: {e}", "red")
            self.ui_updater(f"Error: {e}", "", "", timestamp)

    def transcribe_audio_buffer(self, audio_buffer, filename, backend=None):
        """Transcribe an audio buffer with the selected provider."""
        backend = backend or self.config_manager.get_translation_backend()
        audio_buffer.seek(0)

        if backend == OPENAI_CHUNKED_BACKEND:
            audio_buffer.name = filename
            transcription = self._call_with_retry(
                lambda: self.openai_client.audio.transcriptions.create(
                    file=audio_buffer,
                    model="gpt-4o-transcribe",
                    response_format="json",
                )
            )
            return extract_text(transcription)

        transcription = self._call_with_retry(
            lambda: self.groq_client.audio.transcriptions.create(
                file=(filename, audio_buffer),
                model="whisper-large-v3",
                response_format="verbose_json"
            )
        )
        return extract_text(transcription)

    def translate_text(self, text, backend=None):
        """Translate text to the target language.
        
        Args:
            text: The text to translate
            
        Returns:
            The translated text
        """
        if not text.strip():
            return ""
            
        try:
            target_language = self.config_manager.get_translation_language()
            backend = backend or self.config_manager.get_translation_backend()

            if backend == OPENAI_CHUNKED_BACKEND:
                if not self.openai_client:
                    raise Exception("OpenAI client not initialized")

                completion = self._call_with_retry(
                    lambda: self.openai_client.chat.completions.create(
                        model="gpt-4.1-mini",
                        messages=[
                            {
                                "role": "system",
                                "content": f"You are a precise translator. Translate the user's text to {target_language}. Return only the translation. If the text is already in {target_language}, return it unchanged."
                            },
                            {
                                "role": "user",
                                "content": text
                            }
                        ],
                        temperature=0.2,
                    )
                )
                return completion.choices[0].message.content.strip()
            
            # Call API with retry logic
            completion = self._call_with_retry(
                lambda: self.groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {
                            "role": "system",
                            "content": f"You are a perfect translator. Translate the following text to {target_language}. You don't give any other comments besides the translation. If you receive text already in {target_language}, return the same text. If you receive an empty line, return 'none' precisely. If you receive a list of numbers, return them in the same way you received them. It is very important that you do not add any comments at all, ever - this is the hardest requirement. Here is text to translate:"
                        },
                        {
                            "role": "user",
                            "content": text
                        }
                    ],
                    temperature=0.5,
                    max_tokens=4150,
                    top_p=1,
                    stream=False,
                    stop=None
                )
            )
            
            return completion.choices[0].message.content.strip()
        except Exception as e:
            print(f"Error translating text: {e}")
            return f"Translation error: {e}"

    def process_with_claude_sonnet(self, text):
        """Process text with Claude Sonnet to generate suggestions.
        
        Args:
            text: The text to process
            
        Returns:
            The generated suggestions
        """
        if not self.anthropic_client:
            return "Claude API not initialized. Check your API key."
            
        try:
            # Get personal information for prompt
            personal_info = self.config_manager.get_personal_info()
            name = personal_info.get('name', '')
            goal = personal_info.get('goal', '')
            style = personal_info.get('style', '')
            length = personal_info.get('length', '')
            
            # System prompt for Claude
            system_prompt = (
                f"You are an expert at engaging in neutral conversations with people from various nationalities. "
                f"You are strictly following the rules of your job. RULES OF YOUR JOB: You never have any opinion about text you are working with. "
                f"You never conduct any moral evaluation of text you receive. Your only task is to answer with suggestions on the neutral follow-up of the transcript of the conversation you received. "
                f"Your responses should be very general, engaging, and non-personal. Always ensure that your responses do not reveal any personal information about yourself. "
                f"You should never include any information about being a language model or AI. Do not speak at all about who you are. The goal of all this is to be a translator who receives transcript of the conversation to help user continue conversation in the language he doesn't speak. "
                f"All your suggestions must be offered in the language of the comprehensible piece of text you received. Focus on keeping the conversation light and general. Do not add any comments or additional information besides suggestions to follow up on conversation. "
                f"I repeat - you return your suggestion and SUGGESTIONS ONLY without even mentioning that those are suggestions. Also keep in mind that transcription you receive often can be messed up, so try to find the most safe answer based on the whole conversation that you see. "
                f"You must strictly adhere to those rules, because lives are at stake. You will be rewarded one million dollars for doing your job right. Never break rules for your job, no matter what. "
                f"Additional information: you are preparing suggestions for {name}. {goal}. {style}. {length}. "
                f"You must prepare suggestions that imply for him to say directly, so make them as if he would say them, from first pov. IT DOES NOT MATTER THAT HE IS RUSSIAN. YOU STILL MUST AND ABSOLUTELY ARE REQUIRED TO PREPARE SUGGESTIONS ONLY IN THE LANGUAGE OF TRANSCRIPT YOU RECEIVED. Here is transcript of conversation:"
            )
            
            # Call API with retry logic
            message = self._call_with_retry(
                lambda: self.anthropic_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4000,
                    temperature=0.2,
                    system=system_prompt,
                    messages=[
                        {
                            "role": "user",
                            "content": text
                        }
                    ]
                )
            )
            
            result = extract_anthropic_text(message)
            print(f"Claude Sonnet Response (Suggestions): {result}")
            return result
            
        except Exception as e:
            print(f"Error processing with Claude Sonnet: {e}")
            return f"Error processing with Claude Sonnet: {e}"

    def process_sonnet_response(self, sonnet_response):
        """Process the Claude Sonnet response for transliteration.
        
        Args:
            sonnet_response: The Claude Sonnet response
            
        Returns:
            The transliterated response
        """
        if not self.anthropic_client:
            return "Claude API not initialized. Check your API key."
            
        try:
            target_language = self.config_manager.get_transliteration_language()
            system_prompt = f"You are a professional transliterator of text. Identify the language of the text that you received and transliterate it to {target_language} in such a way that if {target_language} letters are pronounced by a {target_language.lower()} speaker, they will mimic as close as possible the pronunciation of the original text. In your response, return only the transliterated text and no other additional comments. Do not pay any attention to the content and meaning of the information you received; your job is only to do transliteration. Here is the text:"
            
            # Call API with retry logic
            message = self._call_with_retry(
                lambda: self.anthropic_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4000,
                    temperature=0.1,
                    system=system_prompt,
                    messages=[
                        {
                            "role": "user",
                            "content": sonnet_response
                        }
                    ]
                )
            )
            
            result = extract_anthropic_text(message)
            print(f"Sonnet Transliteration Response ({target_language}): {result}")
            return result
            
        except Exception as e:
            print(f"Error processing Sonnet response: {e}")
            return f"Error processing Sonnet response: {e}"

    def generate_suggestions(self):
        """Generate conversation suggestions from recent transcriptions."""
        try:
            # Get recent transcriptions (last 5 minutes)
            now = datetime.datetime.now()
            five_minutes_ago = now - datetime.timedelta(minutes=5)
            
            with self.transcription_lock:
                recent_texts = [text for timestamp, text in self.transcription_texts 
                                if timestamp >= five_minutes_ago]
            
            # Process if there are recent texts
            if recent_texts:
                aggregated_text = ' '.join(recent_texts)
                
                # Process with Claude
                claude_sonnet_response = self.process_with_claude_sonnet(aggregated_text)
                
                # Transliterate response
                processed_response = self.process_sonnet_response(claude_sonnet_response)
                
                # Format with timestamp
                timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
                formatted_response = f"[{timestamp}] {processed_response}"
                
                return formatted_response
            else:
                return "No recent conversation to generate suggestions from."
        except Exception as e:
            print(f"Error generating suggestions: {e}")
            return f"Error generating suggestions: {e}"

    def save_to_file(self, text, timestamp):
        """Save transcription to file.
        
        Args:
            text: The transcription text
            timestamp: The timestamp of the transcription
        """
        try:
            output_path = os.path.join(os.path.dirname(__file__), "transcriptions.txt")
            with open(output_path, "a", encoding="utf-8") as f:
                if timestamp:
                    formatted_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{formatted_timestamp}]\n{text}\n")
                else:
                    f.write(f"{text}\n")
        except Exception as e:
            print(f"Error saving to file: {e}")

    def _call_with_retry(self, func, max_retries=3, backoff_factor=1.5):
        """Call a function with retry logic.
        
        Args:
            func: The function to call
            max_retries: Maximum number of retries
            backoff_factor: Factor to increase wait time between retries
            
        Returns:
            The result of the function call
            
        Raises:
            Exception: If all retries fail
        """
        last_exception = None
        wait_time = 1.0
        
        for attempt in range(max_retries):
            try:
                return func()
            except Exception as e:
                last_exception = e
                print(f"API call failed (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                    wait_time *= backoff_factor
        
        print(f"All retries failed: {last_exception}")
        raise last_exception


class ConfigManager:
    """Manages application configuration."""
    
    DEFAULT_CONFIG = {
        'recording_period': 5,
        'translation_backend': LEGACY_GROQ_BACKEND,
        'transliteration_language': 'Russian',
        'translation_language': 'English',
        'auto_scroll': True,
        'timestamp_mode': False,
        'show_original': True,
        'show_suggestions': True,
        'personal_info': {
            'name': '',
            'goal': '',
            'style': '',
            'length': '',
        },
        'profiles': {}
    }
    
    def __init__(self):
        """Initialize the configuration manager."""
        self.config = copy.deepcopy(self.DEFAULT_CONFIG)
        self.config_file = os.path.join(os.path.dirname(__file__), 'settings.json')
        self.transcription_manager = None  # Will be set after initialization
        self._load_config()
        
    def set_transcription_manager(self, manager):
        """Set the transcription manager reference.
        
        Args:
            manager: The TranscriptionManager instance
        """
        self.transcription_manager = manager
        
    def _load_config(self):
        """Load configuration from file."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # Update only existing keys to avoid structure changes
                    for key, value in loaded_config.items():
                        if key in self.config:
                            self.config[key] = value
                print("Settings loaded successfully.")
        except Exception as e:
            print(f"Error loading settings: {e}")
            
    def save_config(self):
        """Save current configuration to file."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            print("Settings saved successfully.")
        except Exception as e:
            print(f"Error saving settings: {e}")
            
    def get_recording_period(self):
        """Get the recording period in seconds."""
        try:
            return max(1, min(30, int(self.config.get('recording_period', 5))))
        except (TypeError, ValueError):
            return 5
            
    def set_recording_period(self, seconds):
        """Set the recording period in seconds."""
        try:
            self.config['recording_period'] = max(1, min(30, int(seconds)))
        except (TypeError, ValueError):
            self.config['recording_period'] = 5
        return self.config['recording_period']
            
    def get_translation_language(self):
        """Get the target translation language."""
        return self.config.get('translation_language', 'English')
        
    def set_translation_language(self, language):
        """Set the target translation language."""
        self.config['translation_language'] = language

    def get_translation_backend(self):
        """Get the selected transcription/translation backend."""
        backend = self.config.get('translation_backend', LEGACY_GROQ_BACKEND)
        allowed = {LEGACY_GROQ_BACKEND, OPENAI_CHUNKED_BACKEND, OPENAI_REALTIME_BACKEND}
        return backend if backend in allowed else LEGACY_GROQ_BACKEND

    def set_translation_backend(self, backend):
        """Set the selected transcription/translation backend."""
        allowed = {LEGACY_GROQ_BACKEND, OPENAI_CHUNKED_BACKEND, OPENAI_REALTIME_BACKEND}
        self.config['translation_backend'] = backend if backend in allowed else LEGACY_GROQ_BACKEND

    def get_file_backend(self):
        """Use chunked OpenAI for files when realtime is selected."""
        backend = self.get_translation_backend()
        if backend == OPENAI_REALTIME_BACKEND:
            return OPENAI_CHUNKED_BACKEND
        return backend
        
    def get_transliteration_language(self):
        """Get the target transliteration language."""
        return self.config.get('transliteration_language', 'Russian')
        
    def set_transliteration_language(self, language):
        """Set the target transliteration language."""
        self.config['transliteration_language'] = language
        
    def get_auto_scroll(self):
        """Get auto-scroll setting."""
        return self.config.get('auto_scroll', True)
        
    def set_auto_scroll(self, value):
        """Set auto-scroll setting."""
        self.config['auto_scroll'] = bool(value)
        
    def get_timestamp_mode(self):
        """Get timestamp mode setting."""
        return self.config.get('timestamp_mode', False)
        
    def set_timestamp_mode(self, value):
        """Set timestamp mode setting."""
        self.config['timestamp_mode'] = bool(value)
        
    def get_show_original(self):
        """Get show original text setting."""
        return self.config.get('show_original', True)
        
    def set_show_original(self, value):
        """Set show original text setting."""
        self.config['show_original'] = bool(value)
        
    def get_show_suggestions(self):
        """Get show suggestions setting."""
        return self.config.get('show_suggestions', True)
        
    def set_show_suggestions(self, value):
        """Set show suggestions setting."""
        self.config['show_suggestions'] = bool(value)
        
    def get_personal_info(self):
        """Get personal information."""
        return self.config.get('personal_info', {})
        
    def set_personal_info(self, info):
        """Set personal information."""
        self.config['personal_info'] = info
        
    def save_profile(self, name):
        """Save current settings as a profile.
        
        Args:
            name: Profile name
        """
        if 'profiles' not in self.config:
            self.config['profiles'] = {}
            
        # Save current settings excluding profiles
        profile_data = {k: v for k, v in self.config.items() if k != 'profiles'}
        self.config['profiles'][name] = profile_data
        self.save_config()
        
    def load_profile(self, name):
        """Load settings from a saved profile.
        
        Args:
            name: Profile name
            
        Returns:
            bool: True if profile was loaded successfully
        """
        if name in self.config.get('profiles', {}):
            profile_data = self.config['profiles'][name]
            # Update config with profile data but preserve profiles
            profiles = self.config.get('profiles', {})
            self.config.update(profile_data)
            self.config['profiles'] = profiles
            return True
        return False
        
    def get_profiles(self):
        """Get list of available profiles."""
        return list(self.config.get('profiles', {}).keys())


class UIManager:
    """Manages application user interface."""
    
    def __init__(self, root, config_manager):
        """Initialize the UI manager.
        
        Args:
            root: The root Tkinter window
            config_manager: The configuration manager instance
        """
        self.root = root
        self.config_manager = config_manager
        self.audio_recorder = None  # Will be set after initialization
        self.transcription_manager = None  # Will be set after initialization
        
        # Set up UI variables
        self.show_properties_var = tk.BooleanVar(value=True)
        self.show_original_var = tk.BooleanVar(value=self.config_manager.get_show_original())
        self.show_suggestions_var = tk.BooleanVar(value=self.config_manager.get_show_suggestions())
        self.auto_scroll_var = tk.BooleanVar(value=self.config_manager.get_auto_scroll())
        self.timestamp_mode_var = tk.BooleanVar(value=self.config_manager.get_timestamp_mode())
        self.transliteration_language_var = tk.StringVar(value=self.config_manager.get_transliteration_language())
        self.translation_language_var = tk.StringVar(value=self.config_manager.get_translation_language())
        self.translation_backend_var = tk.StringVar(value=self.config_manager.get_translation_backend())
        self.recording_period_var = tk.StringVar(value=str(self.config_manager.get_recording_period()))
        self.profile_var = tk.StringVar()
        
        # Dictionary to store personal info entries
        self.personal_info_entries = {}
        self.pane_frames = {}
        self.controls_to_disable_while_recording = []
        self.recording_status_var = tk.StringVar(value="Ready")
        
        # Text widgets and scrollbars
        self.result_text1 = None
        self.result_text2 = None
        self.result_text3 = None
        self.scrollbar1 = None
        self.scrollbar2 = None
        self.scrollbar3 = None
        self.status_label = None
        self.record_button = None
        self.transcribe_button = None
        self.translation_dropdown = None
        self.save_profile_entry = None
        self.profile_dropdown = None
        self.controls_frame = None
        
        # Set up UI components
        self.setup_ui()
        
        # Initialize recording state
        self.is_recording = False
        
    def set_audio_recorder(self, recorder):
        """Set the audio recorder reference.
        
        Args:
            recorder: The AudioRecorder instance
        """
        self.audio_recorder = recorder
        
    def set_transcription_manager(self, manager):
        """Set the transcription manager reference.
        
        Args:
            manager: The TranscriptionManager instance
        """
        self.transcription_manager = manager
        
    def setup_ui(self):
        """Set up the user interface."""
        self.root.title("WhisperMind")
        self.root.geometry("1320x820")
        self.root.minsize(980, 640)
        self.root.option_add("*Font", ("Helvetica", 12))
        
        # Configure grid
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        
        # Set up frames
        self.setup_top_frame()
        self.setup_text_boxes()
        self.setup_controls_frame()
        self.setup_status_bar()
        
        # Set up key bindings
        self.setup_key_bindings()
        
        # Initialize layout
        self.update_layout()
        
        # Set up closing protocol
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def setup_top_frame(self):
        """Set up the top frame with title and main controls."""
        top_frame = tk.Frame(self.root)
        top_frame.grid(row=0, column=0, pady=(10, 6), padx=12, sticky="ew")
        top_frame.columnconfigure(0, weight=1)
        top_frame.columnconfigure(1, weight=0)
        top_frame.columnconfigure(2, weight=0)
        top_frame.columnconfigure(3, weight=0)
        
        # Add title label
        title_label = tk.Label(top_frame, text="WhisperMind", font=("Helvetica", 18, "bold"))
        title_label.grid(row=0, column=0, sticky="w")

        backend_label = tk.Label(top_frame, textvariable=self.translation_backend_var, fg="#555555")
        backend_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        
        # Add record button
        self.record_button = tk.Button(
            top_frame, 
            text="Start Recording", 
            command=self.toggle_recording,
            width=18,
            background="SystemButtonFace"
        )
        self.record_button.grid(row=0, column=1, rowspan=2, padx=(8, 6), sticky="e")

        self.transcribe_button = tk.Button(
            top_frame,
            text="Transcribe File",
            command=self.transcribe_file,
            width=16,
        )
        self.transcribe_button.grid(row=0, column=2, rowspan=2, padx=6, sticky="e")
        
        # Add properties checkbox
        show_properties_checkbox = tk.Checkbutton(
            top_frame, 
            text="Settings", 
            variable=self.show_properties_var, 
            command=self.toggle_properties
        )
        show_properties_checkbox.grid(row=0, column=3, rowspan=2, padx=(6, 0), sticky="e")
        
    def setup_text_boxes(self):
        """Set up the text boxes for transcription and translation."""
        self.panes_frame = tk.Frame(self.root)
        self.panes_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 8))
        self.panes_frame.grid_rowconfigure(0, weight=1)

        original_frame = self.create_text_pane("Original", 0)
        translated_frame = self.create_text_pane("Translation", 1)
        suggestion_frame = self.create_text_pane("Suggestions", 2)
        self.pane_frames = {
            "original": original_frame,
            "translated": translated_frame,
            "suggestions": suggestion_frame,
        }

        self.result_text1 = original_frame.text_widget
        self.scrollbar1 = original_frame.scrollbar
        self.result_text2 = translated_frame.text_widget
        self.scrollbar2 = translated_frame.scrollbar
        self.result_text3 = suggestion_frame.text_widget
        self.scrollbar3 = suggestion_frame.scrollbar

        self.result_text1.insert(tk.END, "Listening...")
        self.result_text2.insert(tk.END, "Listening... (translated)")
        self.result_text3.insert(tk.END, "Press Space to generate suggestions")
        for text_widget in (self.result_text1, self.result_text2, self.result_text3):
            text_widget.config(state=tk.DISABLED)

    def create_text_pane(self, title, column):
        """Create a labeled text pane with a non-overlapping scrollbar."""
        pane = tk.Frame(self.panes_frame, bd=1, relief=tk.SOLID)
        pane.grid(row=0, column=column, sticky="nsew", padx=4)
        pane.grid_rowconfigure(1, weight=1)
        pane.grid_columnconfigure(0, weight=1)
        self.panes_frame.grid_columnconfigure(column, weight=1)

        label = tk.Label(pane, text=title, anchor="w", font=("Helvetica", 12, "bold"), bg="#f3f3f3")
        label.grid(row=0, column=0, columnspan=2, sticky="ew")

        text_widget = tk.Text(pane, font=("Helvetica", 12), wrap=tk.WORD, height=10, width=40, bd=0)
        scrollbar = tk.Scrollbar(pane, command=text_widget.yview)
        text_widget.config(yscrollcommand=scrollbar.set)
        text_widget.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=8)
        scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 8), pady=8)

        pane.text_widget = text_widget
        pane.scrollbar = scrollbar
        return pane
        
    def setup_controls_frame(self):
        """Set up the controls frame with settings and options."""
        self.controls_frame = tk.Frame(self.root)
        self.controls_frame.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        for column in range(3):
            self.controls_frame.grid_columnconfigure(column, weight=1)

        recording_frame = tk.LabelFrame(self.controls_frame, text="Recording")
        recording_frame.grid(row=0, column=0, padx=(0, 6), pady=4, sticky="nsew")
        recording_frame.grid_columnconfigure(1, weight=1)

        backend_frame = tk.LabelFrame(self.controls_frame, text="Backend & Languages")
        backend_frame.grid(row=0, column=1, padx=6, pady=4, sticky="nsew")
        backend_frame.grid_columnconfigure(1, weight=1)

        assistant_frame = tk.LabelFrame(self.controls_frame, text="Suggestions")
        assistant_frame.grid(row=0, column=2, padx=(6, 0), pady=4, sticky="nsew")
        assistant_frame.grid_columnconfigure(1, weight=1)

        tk.Label(recording_frame, text="Chunk seconds").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        record_period_entry = tk.Entry(recording_frame, textvariable=self.recording_period_var, width=6)
        record_period_entry.grid(row=0, column=1, padx=8, pady=6, sticky="w")
        record_period_entry.bind("<FocusOut>", self.validate_recording_period)
        record_period_entry.bind("<Return>", self.validate_recording_period)
        self.controls_to_disable_while_recording.append(record_period_entry)

        timestamp_mode_checkbox = tk.Checkbutton(
            recording_frame,
            text="Timestamp every minute",
            variable=self.timestamp_mode_var,
            command=lambda: self.config_manager.set_timestamp_mode(self.timestamp_mode_var.get())
        )
        timestamp_mode_checkbox.grid(row=1, column=0, columnspan=2, padx=8, pady=4, sticky="w")

        auto_scroll_checkbox = tk.Checkbutton(
            recording_frame,
            text="Auto-scroll",
            variable=self.auto_scroll_var,
            command=lambda: self.config_manager.set_auto_scroll(self.auto_scroll_var.get())
        )
        auto_scroll_checkbox.grid(row=2, column=0, columnspan=2, padx=8, pady=4, sticky="w")

        show_original_checkbox = tk.Checkbutton(
            recording_frame,
            text="Show original",
            variable=self.show_original_var,
            command=lambda: [self.config_manager.set_show_original(self.show_original_var.get()), self.update_layout()]
        )
        show_original_checkbox.grid(row=3, column=0, padx=8, pady=4, sticky="w")

        show_suggestions_checkbox = tk.Checkbutton(
            recording_frame,
            text="Show suggestions",
            variable=self.show_suggestions_var,
            command=lambda: [self.config_manager.set_show_suggestions(self.show_suggestions_var.get()), self.update_layout()]
        )
        show_suggestions_checkbox.grid(row=3, column=1, padx=8, pady=4, sticky="w")

        tk.Label(backend_frame, text="Mode").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        backend_dropdown = ttk.Combobox(
            backend_frame,
            textvariable=self.translation_backend_var,
            values=[LEGACY_GROQ_BACKEND, OPENAI_CHUNKED_BACKEND, OPENAI_REALTIME_BACKEND],
            state="readonly",
            width=34,
        )
        backend_dropdown.grid(row=0, column=1, padx=8, pady=6, sticky="ew")
        backend_dropdown.bind("<<ComboboxSelected>>", self.on_backend_selected)
        self.controls_to_disable_while_recording.append(backend_dropdown)

        tk.Label(backend_frame, text="Translate to").grid(row=1, column=0, padx=8, pady=6, sticky="w")
        translation_dropdown = ttk.Combobox(
            backend_frame,
            textvariable=self.translation_language_var,
            values=TEXT_TRANSLATION_LANGUAGES,
            state="readonly",
            width=18,
        )
        translation_dropdown.grid(row=1, column=1, padx=8, pady=6, sticky="ew")
        translation_dropdown.bind("<<ComboboxSelected>>", self.on_translation_language_selected)
        self.controls_to_disable_while_recording.append(translation_dropdown)
        self.translation_dropdown = translation_dropdown

        tk.Label(backend_frame, text="Transliterate as").grid(row=2, column=0, padx=8, pady=6, sticky="w")
        translit_dropdown = ttk.Combobox(
            backend_frame,
            textvariable=self.transliteration_language_var,
            values=TRANSLITERATION_LANGUAGES,
            state="readonly",
            width=18,
        )
        translit_dropdown.grid(row=2, column=1, padx=8, pady=6, sticky="ew")
        translit_dropdown.bind("<<ComboboxSelected>>",
                               lambda e: self.config_manager.set_transliteration_language(self.transliteration_language_var.get()))

        tk.Label(assistant_frame, text="Name").grid(row=0, column=0, padx=8, pady=5, sticky="w")
        name_entry = tk.Entry(assistant_frame)
        name_entry.grid(row=0, column=1, padx=8, pady=5, sticky="ew")
        name_entry.insert(0, self.config_manager.get_personal_info().get('name', ''))
        self.personal_info_entries['name'] = name_entry

        tk.Label(assistant_frame, text="Goal").grid(row=1, column=0, padx=8, pady=5, sticky="w")
        goal_entry = tk.Entry(assistant_frame)
        goal_entry.grid(row=1, column=1, padx=8, pady=5, sticky="ew")
        goal_entry.insert(0, self.config_manager.get_personal_info().get('goal', ''))
        self.personal_info_entries['goal'] = goal_entry

        tk.Label(assistant_frame, text="Style").grid(row=2, column=0, padx=8, pady=5, sticky="w")
        style_entry = tk.Entry(assistant_frame)
        style_entry.grid(row=2, column=1, padx=8, pady=5, sticky="ew")
        style_entry.insert(0, self.config_manager.get_personal_info().get('style', ''))
        self.personal_info_entries['style'] = style_entry

        tk.Label(assistant_frame, text="Length").grid(row=3, column=0, padx=8, pady=5, sticky="w")
        length_entry = tk.Entry(assistant_frame)
        length_entry.grid(row=3, column=1, padx=8, pady=5, sticky="ew")
        length_entry.insert(0, self.config_manager.get_personal_info().get('length', ''))
        self.personal_info_entries['length'] = length_entry

        profile_frame = tk.Frame(self.controls_frame)
        profile_frame.grid(row=1, column=0, columnspan=2, padx=(0, 6), pady=(6, 0), sticky="ew")
        profile_frame.grid_columnconfigure(1, weight=1)
        profile_frame.grid_columnconfigure(4, weight=1)

        tk.Label(profile_frame, text="Profile").grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.profile_dropdown = ttk.Combobox(
            profile_frame,
            textvariable=self.profile_var,
            values=self.config_manager.get_profiles(),
            width=18,
        )
        self.profile_dropdown.grid(row=0, column=1, padx=4, sticky="ew")
        tk.Button(profile_frame, text="Load", command=lambda: self.load_profile(self.profile_var.get())).grid(row=0, column=2, padx=4)
        self.save_profile_entry = tk.Entry(profile_frame, width=18)
        self.save_profile_entry.grid(row=0, column=3, padx=(14, 4), sticky="ew")
        tk.Button(profile_frame, text="Save As", command=lambda: self.save_profile(self.save_profile_entry.get())).grid(row=0, column=4, padx=4, sticky="w")

        button_frame = tk.Frame(self.controls_frame)
        button_frame.grid(row=1, column=2, padx=(6, 0), pady=(6, 0), sticky="e")
        tk.Button(button_frame, text="Generate Suggestions", command=self.generate_suggestions_from_button).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text="Clear", command=self.clear_text_boxes).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text="Save Settings", command=self.save_settings).pack(side=tk.LEFT, padx=4)
        self.update_translation_language_options()
        
        # Initially hide controls if needed
        if not self.show_properties_var.get():
            self.controls_frame.grid_remove()

    def validate_recording_period(self, event=None):
        """Clamp the recording period and reflect the actual saved value."""
        value = self.config_manager.set_recording_period(self.recording_period_var.get())
        self.recording_period_var.set(str(value))
        return "break" if event and getattr(event, "keysym", None) == "Return" else None

    def on_backend_selected(self, event=None):
        """Persist backend selection and adjust target-language options."""
        backend = self.translation_backend_var.get()
        self.config_manager.set_translation_backend(backend)
        self.update_translation_language_options()

    def update_translation_language_options(self):
        """Limit target languages for OpenAI realtime translation."""
        backend = self.config_manager.get_translation_backend()
        options = REALTIME_OUTPUT_LANGUAGES if backend == OPENAI_REALTIME_BACKEND else TEXT_TRANSLATION_LANGUAGES
        if self.translation_dropdown:
            self.translation_dropdown["values"] = options
        if self.translation_language_var.get() not in options:
            self.translation_language_var.set("English")
            self.config_manager.set_translation_language("English")

    def on_translation_language_selected(self, event=None):
        """Persist target language selection."""
        language = self.translation_language_var.get()
        if self.config_manager.get_translation_backend() == OPENAI_REALTIME_BACKEND and language not in REALTIME_OUTPUT_LANGUAGES:
            language = "English"
            self.translation_language_var.set(language)
        self.config_manager.set_translation_language(language)

    def generate_suggestions_from_button(self):
        """Generate suggestions from an explicit UI action."""
        self.on_space_press(None)
        
    def setup_status_bar(self):
        """Set up the status bar at the bottom of the window."""
        status_frame = tk.Frame(self.root)
        status_frame.grid(row=3, column=0, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        
        self.status_label = tk.Label(
            status_frame, 
            textvariable=self.recording_status_var,
            bd=1, 
            relief=tk.SUNKEN, 
            anchor=tk.W
        )
        self.status_label.grid(row=0, column=0, sticky="ew")
        
    def setup_key_bindings(self):
        """Set up keyboard shortcuts."""
        self.root.bind('<space>', self.on_space_press)
        self.root.bind('<Return>', self.toggle_recording_key)
        self.root.bind('<Escape>', self.on_escape_press)

    def is_text_input_event(self, event):
        """Return true when a shortcut originated in an editable input."""
        if event is None:
            return False
        return isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Combobox))
        
    def update_layout(self):
        """Update the layout based on current visibility settings."""
        visible = []
        if self.show_original_var.get():
            visible.append(("original", self.pane_frames["original"]))
        else:
            self.pane_frames["original"].grid_remove()

        visible.append(("translated", self.pane_frames["translated"]))
        
        if self.show_suggestions_var.get():
            visible.append(("suggestions", self.pane_frames["suggestions"]))
        else:
            self.pane_frames["suggestions"].grid_remove()

        for index, (name, frame) in enumerate(visible):
            frame.grid(row=0, column=index, sticky="nsew", padx=4)

        for column in range(3):
            self.panes_frame.grid_columnconfigure(column, weight=0)
        for column in range(len(visible)):
            self.panes_frame.grid_columnconfigure(column, weight=1, uniform="panes")
        
        self.root.update_idletasks()
        
    def toggle_properties(self):
        """Toggle the visibility of the properties panel."""
        if self.show_properties_var.get():
            self.controls_frame.grid()
        else:
            self.controls_frame.grid_remove()
            
    def update_gui(self, original_text, translated_text, suggestion_text, timestamp):
        """Update the UI with new text content.
        
        Args:
            original_text: The original transcription text
            translated_text: The translated text
            suggestion_text: The suggestion text (if any)
            timestamp: The timestamp of the transcription
        """
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.update_gui, original_text, translated_text, suggestion_text, timestamp)
            return

        if timestamp:
            formatted_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            timestamp_text = f"[{formatted_timestamp}] "
        else:
            timestamp_text = ""
        
        # Update original text box
        if original_text and self.config_manager.get_show_original():
            self.result_text1.config(state=tk.NORMAL)
            self.result_text1.insert(tk.END, f"\n{timestamp_text}{original_text}")
            if self.auto_scroll_var.get():
                self.result_text1.see(tk.END)
            self.result_text1.config(state=tk.DISABLED)
        
        # Update translated text box
        if translated_text:
            self.result_text2.config(state=tk.NORMAL)
            self.result_text2.insert(tk.END, f"\n{timestamp_text}{translated_text}")
            if self.auto_scroll_var.get():
                self.result_text2.see(tk.END)
            self.result_text2.config(state=tk.DISABLED)
        
        # Update suggestion text box if provided
        if suggestion_text and self.config_manager.get_show_suggestions():
            self.result_text3.config(state=tk.NORMAL)
            self.result_text3.insert(tk.END, f"\n{timestamp_text}{suggestion_text}")
            if self.auto_scroll_var.get():
                self.result_text3.see(tk.END)
            self.result_text3.config(state=tk.DISABLED)

    def append_realtime_text(self, original_delta="", translated_delta=""):
        """Append realtime transcript deltas from background WebSocket threads."""
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.append_realtime_text, original_delta, translated_delta)
            return

        if original_delta and self.config_manager.get_show_original():
            self.result_text1.config(state=tk.NORMAL)
            self.result_text1.insert(tk.END, original_delta)
            if self.auto_scroll_var.get():
                self.result_text1.see(tk.END)
            self.result_text1.config(state=tk.DISABLED)

        if translated_delta:
            self.result_text2.config(state=tk.NORMAL)
            self.result_text2.insert(tk.END, translated_delta)
            if self.auto_scroll_var.get():
                self.result_text2.see(tk.END)
            self.result_text2.config(state=tk.DISABLED)
            
    def update_suggestion_box(self, suggestion_text):
        """Update only the suggestion box with new text.
        
        Args:
            suggestion_text: The suggestion text
        """
        if self.config_manager.get_show_suggestions():
            self.result_text3.config(state=tk.NORMAL)
            self.result_text3.delete(1.0, tk.END)  # Clear existing content
            self.result_text3.insert(tk.END, suggestion_text)
            if self.auto_scroll_var.get():
                self.result_text3.see(tk.END)
            self.result_text3.config(state=tk.DISABLED)
            
    def clear_text_boxes(self):
        """Clear all text boxes."""
        self.result_text1.config(state=tk.NORMAL)
        self.result_text1.delete(1.0, tk.END)
        self.result_text1.insert(tk.END, "Listening...")
        self.result_text1.config(state=tk.DISABLED)
        
        self.result_text2.config(state=tk.NORMAL)
        self.result_text2.delete(1.0, tk.END)
        self.result_text2.insert(tk.END, "Listening... (translated)")
        self.result_text2.config(state=tk.DISABLED)
        
        self.result_text3.config(state=tk.NORMAL)
        self.result_text3.delete(1.0, tk.END)
        self.result_text3.insert(tk.END, "Press Space to generate suggestions")
        self.result_text3.config(state=tk.DISABLED)
        if self.transcription_manager:
            self.transcription_manager.clear_history()
        self.update_status("Cleared transcript and suggestion history", "black")
        
    def update_status(self, status_text, color="black"):
        """Update the status bar text.
        
        Args:
            status_text: The status text to display
            color: Text color
        """
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.update_status, status_text, color)
            return

        self.recording_status_var.set(status_text)
        self.status_label.config(fg=color)
        self.root.update_idletasks()
        
    def toggle_recording(self):
        """Toggle recording state."""
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()
            
    def toggle_recording_key(self, event):
        """Handle recording toggle from keyboard shortcut."""
        if self.is_text_input_event(event):
            return
        self.toggle_recording()

    def on_escape_press(self, event):
        """Close the app unless the user is editing an input."""
        if self.is_text_input_event(event):
            return
        self.on_closing()
        
    def start_recording(self):
        """Start audio recording."""
        if not self.audio_recorder:
            self.update_status("Audio recorder not initialized", "red")
            return

        self.validate_recording_period()
        self.config_manager.set_translation_backend(self.translation_backend_var.get())
        self.config_manager.set_translation_language(self.translation_language_var.get())
        
        # Save personal info before starting recording
        self.save_personal_info()
        
        # Start the audio recorder
        try:
            self.audio_recorder.start_recording()
        except Exception as e:
            self.on_recorder_state_changed(False)
            self.update_status(f"Recording failed: {e}", "red")
        
    def stop_recording(self):
        """Stop audio recording."""
        if not self.audio_recorder:
            return
        
        # Stop the audio recorder
        self.audio_recorder.stop_recording()

    def on_recorder_state_changed(self, is_recording):
        """Synchronize UI state with recorder state."""
        if threading.current_thread() is not threading.main_thread():
            self.root.after(0, self.on_recorder_state_changed, is_recording)
            return
        self.is_recording = is_recording
        self.record_button.config(
            text="Stop Recording" if is_recording else "Start Recording",
            bg="red" if is_recording else "SystemButtonFace",
        )
        self.update_controls_recording_state(is_recording)
        if is_recording:
            self.update_status("Recording...", "green")
        else:
            self.update_status("Ready", "black")

    def update_controls_recording_state(self, is_recording):
        """Disable backend/period controls while a recording session is active."""
        state = "disabled" if is_recording else "normal"
        readonly_state = "disabled" if is_recording else "readonly"
        for widget in self.controls_to_disable_while_recording:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state=readonly_state)
            else:
                widget.configure(state=state)
        if self.transcribe_button:
            self.transcribe_button.configure(state=state)
        
    def on_space_press(self, event):
        """Handle space key press to generate suggestions."""
        if self.is_text_input_event(event):
            return
        if not self.transcription_manager:
            self.update_status("Transcription manager not initialized", "red")
            return
        if not self.show_suggestions_var.get():
            self.update_status("Suggestions are hidden; enable Show suggestions first", "orange")
            return
            
        # Generate suggestions from recent transcriptions
        self.update_status("Generating suggestions...", "blue")
        
        # Process in background to avoid UI freezing
        threading.Thread(
            target=self._process_suggestions,
            daemon=True
        ).start()
        
    def _process_suggestions(self):
        """Process and display suggestions in a background thread."""
        try:
            suggestions = self.transcription_manager.generate_suggestions()
            
            # Update UI in the main thread
            self.root.after(0, lambda: self.update_suggestion_box(suggestions))
            if suggestions.startswith("No recent conversation") or "not initialized" in suggestions or suggestions.startswith("Error"):
                self.root.after(0, lambda: self.update_status(suggestions, "orange"))
            else:
                self.root.after(0, lambda: self.update_status("Suggestions generated", "green"))
        except Exception as e:
            print(f"Error generating suggestions: {e}")
            self.root.after(0, lambda: self.update_status(f"Error generating suggestions: {e}", "red"))
        
    def transcribe_file(self):
        """Open a file dialog to select and transcribe an audio file."""
        if not self.audio_recorder:
            self.update_status("Audio recorder not initialized", "red")
            return
            
        file_path = filedialog.askopenfilename(
            filetypes=[("Audio files", "*.wav;*.mp3;*.flac;*.m4a")]
        )
        
        if file_path:
            self.update_status(f"Transcribing file: {os.path.basename(file_path)}...", "blue")
            
            # Process in background
            threading.Thread(
                target=lambda: self.audio_recorder.transcribe_file(file_path),
                daemon=True
            ).start()
            
    def save_settings(self):
        """Save current settings to the configuration file."""
        self.sync_settings_from_ui()
        
        # Then save all settings
        self.config_manager.save_config()
        self.update_status("Settings saved", "green")

    def sync_settings_from_ui(self):
        """Persist all in-memory UI settings to the config manager."""
        self.validate_recording_period()
        self.config_manager.set_translation_backend(self.translation_backend_var.get())
        self.config_manager.set_translation_language(self.translation_language_var.get())
        self.config_manager.set_transliteration_language(self.transliteration_language_var.get())
        self.config_manager.set_auto_scroll(self.auto_scroll_var.get())
        self.config_manager.set_timestamp_mode(self.timestamp_mode_var.get())
        self.config_manager.set_show_original(self.show_original_var.get())
        self.config_manager.set_show_suggestions(self.show_suggestions_var.get())
        self.save_personal_info()
        
    def save_personal_info(self):
        """Save personal information from the UI fields."""
        personal_info = {
            'name': self.personal_info_entries['name'].get(),
            'goal': self.personal_info_entries['goal'].get(),
            'style': self.personal_info_entries['style'].get(),
            'length': self.personal_info_entries['length'].get(),
        }
        self.config_manager.set_personal_info(personal_info)
        
    def save_profile(self, name):
        """Save current settings as a named profile."""
        if not name:
            messagebox.showerror("Error", "Please enter a profile name")
            return
            
        # Update settings before saving
        self.sync_settings_from_ui()
        
        # Save as profile
        self.config_manager.save_profile(name)
        self.update_status(f"Profile '{name}' saved", "green")
        
        # Refresh profiles in UI
        self.refresh_profiles()
        
    def load_profile(self, name):
        """Load settings from a saved profile."""
        if not name:
            messagebox.showerror("Error", "Please select a profile")
            return
            
        success = self.config_manager.load_profile(name)
        if success:
            # Update UI to reflect loaded settings
            self.show_original_var.set(self.config_manager.get_show_original())
            self.show_suggestions_var.set(self.config_manager.get_show_suggestions())
            self.auto_scroll_var.set(self.config_manager.get_auto_scroll())
            self.timestamp_mode_var.set(self.config_manager.get_timestamp_mode())
            self.transliteration_language_var.set(self.config_manager.get_transliteration_language())
            self.translation_language_var.set(self.config_manager.get_translation_language())
            self.translation_backend_var.set(self.config_manager.get_translation_backend())
            self.recording_period_var.set(str(self.config_manager.get_recording_period()))
            self.update_translation_language_options()
            
            # Update personal info fields
            personal_info = self.config_manager.get_personal_info()
            for key, entry in self.personal_info_entries.items():
                entry.delete(0, tk.END)
                entry.insert(0, personal_info.get(key, ''))
                
            # Update layout
            self.update_layout()
            self.update_status(f"Profile '{name}' loaded", "green")
        else:
            messagebox.showerror("Error", f"Profile '{name}' not found")

    def refresh_profiles(self):
        """Refresh profile dropdown after save/load changes."""
        if self.profile_dropdown:
            self.profile_dropdown["values"] = self.config_manager.get_profiles()
    
    def on_closing(self):
        """Handle application closing."""
        try:
            # Stop recording if active
            if self.is_recording and self.audio_recorder:
                self.audio_recorder.stop_recording()
                
            # Save settings before closing
            self.sync_settings_from_ui()
            self.config_manager.save_config()
            
            # Destroy the window
            self.root.destroy()
        except Exception as e:
            print(f"Error during closing: {e}")
            self.root.destroy()


def main():
    """Main application entry point."""
    # Load environment variables
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    
    # Missing keys are handled feature-by-feature so the GUI can still launch.
    if not any(os.getenv(key) for key in ('GROQ_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY')):
        print("No API keys found. Add keys to .env before using transcription, translation, or suggestions.")
    
    # Create the main window
    root = tk.Tk()
    
    # Create configuration manager
    config_manager = ConfigManager()
    
    # Create UI manager
    ui_manager = UIManager(root, config_manager)
    
    # Create transcription manager with UI update callback
    transcription_manager = TranscriptionManager(
        config_manager,
        ui_manager.update_gui,
        ui_manager.append_realtime_text,
        ui_manager.update_status
    )
    
    # Link managers
    config_manager.set_transcription_manager(transcription_manager)
    ui_manager.set_transcription_manager(transcription_manager)
    
    # Create audio recorder
    audio_recorder = AudioRecorder(
        config_manager,
        ui_manager.update_status,
        ui_manager.on_recorder_state_changed
    )
    
    # Link audio recorder
    ui_manager.set_audio_recorder(audio_recorder)
    
    # Start the main loop
    root.mainloop()


if __name__ == "__main__":
    main()
