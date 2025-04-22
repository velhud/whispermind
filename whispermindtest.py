import asyncio
import pyaudio
import wave
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import datetime
import queue
import os
import io
import json
import time
import re
from typing import List, Dict, Tuple, Optional, Any, Callable
from groq import Groq
from dotenv import load_dotenv
import anthropic

class AudioRecorder:
    """Handles audio recording and processing."""
    
    # Audio recording constants
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    
    def __init__(self, config_manager, status_callback=None):
        """Initialize the audio recorder.
        
        Args:
            config_manager: The configuration manager instance
            status_callback: Function to call for status updates
        """
        self.config_manager = config_manager
        self.status_callback = status_callback
        self.is_recording = False
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
            
        self.is_recording = True
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

    def stop_recording(self):
        """Stop audio recording and processing."""
        if not self.is_recording:
            return
            
        self.is_recording = False
        self.stop_event.set()
        self.audio_data_available.set()  # Wake up waiting threads
        
        if self.status_callback:
            self.status_callback("Recording stopped")

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
                        chunk_start_time
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
    
    def __init__(self, config_manager, ui_updater):
        """Initialize the transcription manager.
        
        Args:
            config_manager: The configuration manager instance
            ui_updater: Function to update the UI with transcription results
        """
        self.config_manager = config_manager
        self.ui_updater = ui_updater
        self.transcription_texts = []
        self.transcription_lock = threading.Lock()
        self.groq_client = None
        self.anthropic_client = None
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
                
            # Initialize Anthropic client
            anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')
            if anthropic_api_key:
                self.anthropic_client = anthropic.Anthropic(api_key=anthropic_api_key)
                print("Anthropic API Key successfully retrieved")
            else:
                print("Anthropic API Key not found. Suggestion features may not work.")
        except Exception as e:
            print(f"Error initializing API clients: {e}")

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

    def process_audio(self, audio_buffer, timestamp):
        """Process audio data for transcription.
        
        Args:
            audio_buffer: The audio data buffer
            timestamp: The timestamp of the recording
        """
        try:
            if not self.groq_client:
                raise Exception("Groq client not initialized")
                
            # Use threading to avoid blocking
            threading.Thread(
                target=self._transcribe_audio,
                args=(audio_buffer, timestamp),
                daemon=True
            ).start()
        except Exception as e:
            print(f"Error processing audio: {e}")
            self.ui_updater(f"Error: {e}", "", "", timestamp)

    def process_file(self, file_path, file_data, timestamp):
        """Process an audio file for transcription.
        
        Args:
            file_path: Path to the audio file
            file_data: Raw file data
            timestamp: The timestamp of the transcription request
        """
        try:
            if not self.groq_client:
                raise Exception("Groq client not initialized")
                
            threading.Thread(
                target=self._transcribe_file,
                args=(file_path, file_data, timestamp),
                daemon=True
            ).start()
        except Exception as e:
            print(f"Error processing file: {e}")
            self.ui_updater(f"Error: {e}", "", "", timestamp)

    def _transcribe_audio(self, audio_buffer, timestamp):
        """Transcribe audio data using Whisper API.
        
        Args:
            audio_buffer: The audio data buffer
            timestamp: The timestamp of the recording
        """
        try:
            # Call API with retry logic
            transcription = self._call_with_retry(
                lambda: self.groq_client.audio.transcriptions.create(
                    file=("audio.wav", audio_buffer),
                    model="whisper-large-v3",
                    response_format="verbose_json"
                )
            )
            
            transcription_text = transcription.text
            
            # Translate the transcription
            translated_text = self.translate_text(transcription_text)
            
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

    def _transcribe_file(self, file_path, file_data, timestamp):
        """Transcribe an audio file.
        
        Args:
            file_path: Path to the audio file
            file_data: Raw file data
            timestamp: The timestamp of the transcription request
        """
        try:
            transcription = self._call_with_retry(
                lambda: self.groq_client.audio.transcriptions.create(
                    file=(file_path, file_data),
                    model="whisper-large-v3",
                    response_format="verbose_json"
                )
            )
            
            transcription_text = transcription.text
            
            # Save transcription to file
            with open("transcription_from_file.txt", "w", encoding='utf-8') as f:
                f.write(transcription_text)
            
            # Translate the transcription
            translated_text = self.translate_text(transcription_text)
            
            # Update UI
            self.ui_updater(transcription_text, translated_text, "", timestamp)
            
            # Add to transcription history
            self.add_transcription(timestamp, transcription_text)
            
        except Exception as e:
            print(f"Error transcribing file: {e}")
            self.ui_updater(f"Error: {e}", "", "", timestamp)

    def translate_text(self, text):
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
            
            # Call API with retry logic
            completion = self._call_with_retry(
                lambda: self.groq_client.chat.completions.create(
                    model="llama3-70b-8192",
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
                    model="claude-3-5-sonnet-20240620",
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
            
            print(f"Claude Sonnet Response (Suggestions): {message.content}")
            return message.content
            
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
                    model="claude-3-5-sonnet-20240620",
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
            
            print(f"Sonnet Transliteration Response ({target_language}): {message.content}")
            return message.content
            
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
            with open("transcriptions.txt", "a", encoding="utf-8") as f:
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
        self.config = self.DEFAULT_CONFIG.copy()
        self.config_file = 'settings.json'
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
            return int(self.config.get('recording_period', 5))
        except ValueError:
            return 5
            
    def set_recording_period(self, seconds):
        """Set the recording period in seconds."""
        try:
            self.config['recording_period'] = int(seconds)
        except ValueError:
            self.config['recording_period'] = 5
            
    def get_translation_language(self):
        """Get the target translation language."""
        return self.config.get('translation_language', 'English')
        
    def set_translation_language(self, language):
        """Set the target translation language."""
        self.config['translation_language'] = language
        
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
        
        # Set up UI variables
        self.show_properties_var = tk.BooleanVar(value=True)
        self.show_original_var = tk.BooleanVar(value=self.config_manager.get_show_original())
        self.show_suggestions_var = tk.BooleanVar(value=self.config_manager.get_show_suggestions())
        self.auto_scroll_var = tk.BooleanVar(value=self.config_manager.get_auto_scroll())
        self.timestamp_mode_var = tk.BooleanVar(value=self.config_manager.get_timestamp_mode())
        self.transliteration_language_var = tk.StringVar(value=self.config_manager.get_transliteration_language())
        self.translation_language_var = tk.StringVar(value=self.config_manager.get_translation_language())
        
        # Dictionary to store personal info entries
        self.personal_info_entries = {}
        
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
        
    def setup_ui(self):
        """Set up the user interface."""
        self.root.title("WhisperMind 2.0")
        self.root.geometry("1200x700")  # Larger default size
        
        # Configure grid
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_columnconfigure(2, weight=1)
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
        
    def setup_top_frame(import asyncio