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
        self.transcription_manager = None  # Will be set after initialization
        
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
        
        # Text widgets and scrollbars
        self.result_text1 = None
        self.result_text2 = None
        self.result_text3 = None
        self.scrollbar1 = None
        self.scrollbar2 = None
        self.scrollbar3 = None
        self.status_label = None
        self.record_button = None
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
        
    def setup_top_frame(self):
        """Set up the top frame with title and main controls."""
        top_frame = tk.Frame(self.root)
        top_frame.grid(row=0, column=0, columnspan=3, pady=10, sticky="ew")
        top_frame.columnconfigure(0, weight=1)
        top_frame.columnconfigure(1, weight=1)
        top_frame.columnconfigure(2, weight=1)
        
        # Add title label
        title_label = tk.Label(top_frame, text="WhisperMind 2.0", font=("Helvetica", 16))
        title_label.grid(row=0, column=0, pady=10, padx=5, sticky="w")
        
        # Add record button
        self.record_button = tk.Button(
            top_frame, 
            text="Start Recording", 
            command=self.toggle_recording,
            background="SystemButtonFace"
        )
        self.record_button.grid(row=0, column=1, pady=10, padx=5)
        
        # Add properties checkbox
        show_properties_checkbox = tk.Checkbutton(
            top_frame, 
            text="Show properties", 
            variable=self.show_properties_var, 
            command=self.toggle_properties
        )
        show_properties_checkbox.grid(row=0, column=2, pady=10, padx=5, sticky="e")
        
    def setup_text_boxes(self):
        """Set up the text boxes for transcription and translation."""
        # Original text box
        self.result_text1 = tk.Text(self.root, font=("Helvetica", 12), wrap=tk.WORD, height=10, width=50)
        self.scrollbar1 = tk.Scrollbar(self.root, command=self.result_text1.yview)
        self.result_text1.config(yscrollcommand=self.scrollbar1.set)
        self.result_text1.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=10)
        self.scrollbar1.grid(row=1, column=0, sticky="nse", pady=10)
        self.result_text1.insert(tk.END, "Listening...")
        self.result_text1.config(state=tk.DISABLED)
        
        # Translated text box
        self.result_text2 = tk.Text(self.root, font=("Helvetica", 12), wrap=tk.WORD, height=10, width=50)
        self.scrollbar2 = tk.Scrollbar(self.root, command=self.result_text2.yview)
        self.result_text2.config(yscrollcommand=self.scrollbar2.set)
        self.result_text2.grid(row=1, column=1, sticky="nsew", padx=5, pady=10)
        self.scrollbar2.grid(row=1, column=1, sticky="nse", pady=10)
        self.result_text2.insert(tk.END, "Listening... (translated)")
        self.result_text2.config(state=tk.DISABLED)
        
        # Suggestions text box
        self.result_text3 = tk.Text(self.root, font=("Helvetica", 12), wrap=tk.WORD, height=10, width=50)
        self.scrollbar3 = tk.Scrollbar(self.root, command=self.result_text3.yview)
        self.result_text3.config(yscrollcommand=self.scrollbar3.set)
        self.result_text3.grid(row=1, column=2, sticky="nsew", padx=(5, 10), pady=10)
        self.scrollbar3.grid(row=1, column=2, sticky="nse", pady=10)
        self.result_text3.insert(tk.END, "Press space to see Claude suggestions")
        self.result_text3.config(state=tk.DISABLED)
        
    def setup_controls_frame(self):
        """Set up the controls frame with settings and options."""
        self.controls_frame = tk.Frame(self.root)
        self.controls_frame.grid(row=2, column=0, columnspan=3, pady=10, sticky="ew")
        
        # Recording period
        record_period_label = tk.Label(self.controls_frame, text="Recording period (seconds):", font=("Helvetica", 12))
        record_period_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")
        
        record_period_entry = tk.Entry(self.controls_frame, font=("Helvetica", 12), width=5)
        record_period_entry.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        record_period_entry.insert(0, str(self.config_manager.get_recording_period()))
        record_period_entry.bind("<FocusOut>", lambda e: self.config_manager.set_recording_period(record_period_entry.get()))
        
        # Checkboxes for options
        auto_scroll_checkbox = tk.Checkbutton(
            self.controls_frame, 
            text="Auto-scroll", 
            variable=self.auto_scroll_var,
            command=lambda: self.config_manager.set_auto_scroll(self.auto_scroll_var.get())
        )
        auto_scroll_checkbox.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        
        timestamp_mode_checkbox = tk.Checkbutton(
            self.controls_frame, 
            text="Timestamp every minute", 
            variable=self.timestamp_mode_var,
            command=lambda: self.config_manager.set_timestamp_mode(self.timestamp_mode_var.get())
        )
        timestamp_mode_checkbox.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        
        show_original_checkbox = tk.Checkbutton(
            self.controls_frame, 
            text="Show Original", 
            variable=self.show_original_var, 
            command=lambda: [self.config_manager.set_show_original(self.show_original_var.get()), self.update_layout()]
        )
        show_original_checkbox.grid(row=2, column=0, padx=5, pady=5, sticky="w")
        
        show_suggestions_checkbox = tk.Checkbutton(
            self.controls_frame, 
            text="Show Suggestions", 
            variable=self.show_suggestions_var, 
            command=lambda: [self.config_manager.set_show_suggestions(self.show_suggestions_var.get()), self.update_layout()]
        )
        show_suggestions_checkbox.grid(row=2, column=1, padx=5, pady=5, sticky="w")
        
        # Language selections
        translit_label = tk.Label(self.controls_frame, text="Transliteration Language:", font=("Helvetica", 12))
        translit_label.grid(row=3, column=0, padx=5, pady=5, sticky="w")
        
        translit_options = ['Russian', 'Spanish', 'French', 'German', 'Chinese', 'Japanese', 'Korean', 'Arabic']
        translit_dropdown = ttk.Combobox(
            self.controls_frame, 
            textvariable=self.transliteration_language_var,
            values=translit_options,
            state="readonly"
        )
        translit_dropdown.grid(row=3, column=1, padx=5, pady=5, sticky="w")
        translit_dropdown.bind("<<ComboboxSelected>>", 
                               lambda e: self.config_manager.set_transliteration_language(self.transliteration_language_var.get()))
        
        translation_label = tk.Label(self.controls_frame, text="Translate To:", font=("Helvetica", 12))
        translation_label.grid(row=4, column=0, padx=5, pady=5, sticky="w")
        
        translation_options = ['English', 'Spanish', 'French', 'German', 'Chinese', 'Japanese', 'Korean', 'Arabic']
        translation_dropdown = ttk.Combobox(
            self.controls_frame, 
            textvariable=self.translation_language_var,
            values=translation_options,
            state="readonly"
        )
        translation_dropdown.grid(row=4, column=1, padx=5, pady=5, sticky="w")
        translation_dropdown.bind("<<ComboboxSelected>>", 
                                  lambda e: self.config_manager.set_translation_language(self.translation_language_var.get()))
        
        # Personal information section
        personal_info_label = tk.Label(self.controls_frame, text="Personal Info:", font=("Helvetica", 12, "bold"))
        personal_info_label.grid(row=5, column=0, padx=5, pady=(15, 5), columnspan=2)
        
        # Name field
        name_label = tk.Label(self.controls_frame, text="Name:", font=("Helvetica", 12))
        name_label.grid(row=6, column=0, padx=5, pady=5, sticky="w")
        name_entry = tk.Entry(self.controls_frame, font=("Helvetica", 12))
        name_entry.grid(row=6, column=1, padx=5, pady=5, sticky="ew")
        name_entry.insert(0, self.config_manager.get_personal_info().get('name', ''))
        self.personal_info_entries['name'] = name_entry
        
        # Goal field
        goal_label = tk.Label(self.controls_frame, text="Conversation Goal:", font=("Helvetica", 12))
        goal_label.grid(row=7, column=0, padx=5, pady=5, sticky="w")
        goal_entry = tk.Entry(self.controls_frame, font=("Helvetica", 12))
        goal_entry.grid(row=7, column=1, padx=5, pady=5, sticky="ew")
        goal_entry.insert(0, self.config_manager.get_personal_info().get('goal', ''))
        self.personal_info_entries['goal'] = goal_entry
        
        # Style field
        style_label = tk.Label(self.controls_frame, text="Preferred Style:", font=("Helvetica", 12))
        style_label.grid(row=8, column=0, padx=5, pady=5, sticky="w")
        style_entry = tk.Entry(self.controls_frame, font=("Helvetica", 12))
        style_entry.grid(row=8, column=1, padx=5, pady=5, sticky="ew")
        style_entry.insert(0, self.config_manager.get_personal_info().get('style', ''))
        self.personal_info_entries['style'] = style_entry
        
        # Length field
        length_label = tk.Label(self.controls_frame, text="Preferred Length:", font=("Helvetica", 12))
        length_label.grid(row=9, column=0, padx=5, pady=5, sticky="w")
        length_entry = tk.Entry(self.controls_frame, font=("Helvetica", 12))
        length_entry.grid(row=9, column=1, padx=5, pady=5, sticky="ew")
        length_entry.insert(0, self.config_manager.get_personal_info().get('length', ''))
        self.personal_info_entries['length'] = length_entry
        
        # Add profile management UI
        profile_frame = tk.Frame(self.controls_frame)
        profile_frame.grid(row=10, column=0, columnspan=2, padx=5, pady=10)
        
        profile_label = tk.Label(profile_frame, text="Profile:", font=("Helvetica", 12))
        profile_label.pack(side=tk.LEFT, padx=5)
        
        profiles = self.config_manager.get_profiles()
        profile_var = tk.StringVar()
        profile_dropdown = ttk.Combobox(
            profile_frame, 
            textvariable=profile_var,
            values=profiles,
            width=15
        )
        profile_dropdown.pack(side=tk.LEFT, padx=5)
        
        load_profile_button = tk.Button(
            profile_frame, 
            text="Load", 
            command=lambda: self.load_profile(profile_var.get())
        )
        load_profile_button.pack(side=tk.LEFT, padx=5)
        
        save_profile_entry = tk.Entry(profile_frame, width=15)
        save_profile_entry.pack(side=tk.LEFT, padx=5)
        
        save_profile_button = tk.Button(
            profile_frame, 
            text="Save As", 
            command=lambda: self.save_profile(save_profile_entry.get())
        )
        save_profile_button.pack(side=tk.LEFT, padx=5)
        
        # Buttons frame for actions
        button_frame = tk.Frame(self.controls_frame)
        button_frame.grid(row=11, column=0, columnspan=2, padx=5, pady=10)
        
        transcribe_button = tk.Button(button_frame, text="Transcribe File", command=self.transcribe_file)
        transcribe_button.pack(side=tk.LEFT, padx=5)
        
        clear_button = tk.Button(button_frame, text="Clear Text", command=self.clear_text_boxes)
        clear_button.pack(side=tk.LEFT, padx=5)
        
        save_settings_button = tk.Button(button_frame, text="Save Settings", command=self.save_settings)
        save_settings_button.pack(side=tk.LEFT, padx=5)
        
        # Initially hide controls if needed
        if not self.show_properties_var.get():
            self.controls_frame.grid_remove()
        
    def setup_status_bar(self):
        """Set up the status bar at the bottom of the window."""
        status_frame = tk.Frame(self.root)
        status_frame.grid(row=3, column=0, columnspan=3, sticky="ew")
        status_frame.columnconfigure(0, weight=1)
        
        self.status_label = tk.Label(
            status_frame, 
            text="Ready", 
            bd=1, 
            relief=tk.SUNKEN, 
            anchor=tk.W
        )
        self.status_label.grid(row=0, column=0, sticky="ew")
        
    def setup_key_bindings(self):
        """Set up keyboard shortcuts."""
        self.root.bind('<space>', self.on_space_press)
        self.root.bind('<Return>', self.toggle_recording_key)
        self.root.bind('<Escape>', lambda e: self.on_closing())
        
    def update_layout(self):
        """Update the layout based on current visibility settings."""
        if self.show_original_var.get():
            self.result_text1.grid()
            self.scrollbar1.grid()
        else:
            self.result_text1.grid_remove()
            self.scrollbar1.grid_remove()
        
        # result_text2 is always visible
        self.result_text2.grid()
        self.scrollbar2.grid()
        
        if self.show_suggestions_var.get():
            self.result_text3.grid()
            self.scrollbar3.grid()
        else:
            self.result_text3.grid_remove()
            self.scrollbar3.grid_remove()
        
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
        self.result_text3.insert(tk.END, "Press space to see Claude suggestions")
        self.result_text3.config(state=tk.DISABLED)
        
    def update_status(self, status_text, color="black"):
        """Update the status bar text.
        
        Args:
            status_text: The status text to display
            color: Text color
        """
        self.status_label.config(text=status_text, fg=color)
        self.root.update_idletasks()
        
    def toggle_recording(self):
        """Toggle recording state."""
        if self.is_recording:
            self.stop_recording()
        else:
            self.start_recording()
            
    def toggle_recording_key(self, event):
        """Handle recording toggle from keyboard shortcut."""
        self.toggle_recording()
        
    def start_recording(self):
        """Start audio recording."""
        if not self.audio_recorder:
            self.update_status("Audio recorder not initialized", "red")
            return
            
        self.is_recording = True
        self.record_button.config(text="Stop Recording", bg="red")
        self.update_status("Recording...", "green")
        
        # Save personal info before starting recording
        self.save_personal_info()
        
        # Start the audio recorder
        self.audio_recorder.start_recording()
        
    def stop_recording(self):
        """Stop audio recording."""
        if not self.audio_recorder:
            return
            
        self.is_recording = False
        self.record_button.config(text="Start Recording", bg="SystemButtonFace")
        self.update_status("Ready", "black")
        
        # Stop the audio recorder
        self.audio_recorder.stop_recording()
        
    def on_space_press(self, event):
        """Handle space key press to generate suggestions."""
        if not self.transcription_manager:
            self.update_status("Transcription manager not initialized", "red")
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
        # First update personal info
        self.save_personal_info()
        
        # Then save all settings
        self.config_manager.save_config()
        self.update_status("Settings saved", "green")
        
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
            
        # Update personal info before saving
        self.save_personal_info()
        
        # Save as profile
        self.config_manager.save_profile(name)
        self.update_status(f"Profile '{name}' saved", "green")
        
        # Refresh profiles in UI
        profiles = self.config_manager.get_profiles()
        for widget in self.controls_frame.winfo_children():
            if isinstance(widget, tk.Frame):
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Combobox):
                        child['values'] = profiles
        
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
    
    def on_closing(self):
        """Handle application closing."""
        try:
            # Stop recording if active
            if self.is_recording and self.audio_recorder:
                self.audio_recorder.stop_recording()
                
            # Save settings before closing
            self.save_personal_info()
            self.config_manager.save_config()
            
            # Destroy the window
            self.root.destroy()
        except Exception as e:
            print(f"Error during closing: {e}")
            self.root.destroy()


def main():
    """Main application entry point."""
    # Load environment variables
    load_dotenv()
    
    # Check required environment variables
    if not os.getenv('GROQ_API_KEY') and not os.getenv('ANTHROPIC_API_KEY'):
        print("Neither GROQ_API_KEY nor ANTHROPIC_API_KEY found in environment variables.")
        print("Please set at least one of these in your .env file.")
        sys.exit(1)
    
    # Create the main window
    root = tk.Tk()
    
    # Create configuration manager
    config_manager = ConfigManager()
    
    # Create UI manager
    ui_manager = UIManager(root, config_manager)
    
    # Create transcription manager with UI update callback
    transcription_manager = TranscriptionManager(
        config_manager,
        ui_manager.update_gui
    )
    
    # Link managers
    config_manager.set_transcription_manager(transcription_manager)
    ui_manager.set_transcription_manager(transcription_manager)
    
    # Create audio recorder
    audio_recorder = AudioRecorder(
        config_manager,
        ui_manager.update_status
    )
    
    # Link audio recorder
    ui_manager.set_audio_recorder(audio_recorder)
    
    # Start the main loop
    root.mainloop()


if __name__ == "__main__":
    main()