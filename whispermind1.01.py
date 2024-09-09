import asyncio
import pyaudio
import wave
import tkinter as tk
import tkinter.filedialog
import threading
import datetime
import queue
import os
from groq import Groq
from dotenv import load_dotenv
import io
import anthropic

class LayoutState:
    def __init__(self):
        self.show_original = True
        self.show_suggestions = True

    def update(self, show_original, show_suggestions):
        self.show_original = show_original
        self.show_suggestions = show_suggestions

layout_state = LayoutState()

transcription_texts = []

# Replace this section
load_dotenv()
api_key = os.getenv('GROQ_API_KEY')
if api_key:
    print("API Key successfully retrieved")
    groq_client = Groq(api_key=api_key)
else:
    print("API Key not found. Please set the GROQ_API_KEY environment variable.")
    exit(1)

# With this:
load_dotenv()
api_key = os.getenv('ANTHROPIC_API_KEY')
if api_key:
    print("API Key successfully retrieved")
    anthropic_client = anthropic.Anthropic(api_key=api_key)
else:
    print("API Key not found. Please set the ANTHROPIC_API_KEY environment variable.")
    exit(1)

# Audio recording constants
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
RECORD_SECONDS = 5
OVERLAP = 5
WAVE_OUTPUT_FILENAME = "audio.wav"

# Global variables
buffer = queue.Queue()
audio_data_available = threading.Event()
recording_start_time = datetime.datetime.now()
is_recording = False
stop_event = threading.Event()

def on_space_press(event):
    global transcription_texts
    now = datetime.datetime.now()
    five_minutes_ago = now - datetime.timedelta(minutes=5)
    
    # Filter out texts from the last 5 minutes
    relevant_texts = [(timestamp, text) for timestamp, text in transcription_texts if timestamp >= five_minutes_ago]
    
    # Aggregate the texts
    aggregated_text = ' '.join(text for _, text in relevant_texts)
    
    if aggregated_text:
        claude_sonnet_response = process_with_claude_sonnet(aggregated_text)
        processed_sonnet_response = process_sonnet_response(claude_sonnet_response)
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        update_gui_third_box(f"[{timestamp}] {processed_sonnet_response}")

def update_gui_third_box(claude_sonnet_text):
    result_text3.config(state=tk.NORMAL)
    result_text3.delete(1.0, tk.END)  # Clear existing content
    result_text3.insert(tk.END, f"{claude_sonnet_text}")
    if auto_scroll_var.get():
        result_text3.see(tk.END)
    result_text3.config(state=tk.DISABLED)

# Helper functions
def save_to_file(text, timestamp):
    with open("transcriptions.txt", "a", encoding="utf-8") as f:
        if timestamp:
            formatted_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"[{formatted_timestamp}]\n{text}\n")
        else:
            f.write(f"{text}\n")

def translate_text(text, target_language='en'):
    completion = groq_client.chat.completions.create(
        model="llama3-70b-8192",
        messages=[
            {
                "role": "system",
                "content": "You are a perfect translator. Whatever you receive no matter the language, you simply return as close translation as you can to English. You don't give any other comments besides the results of translation. If you receive English - return completely same text. If you receive empty line - return 'none' precisely. If you receive list of numbers - return them in the same way you received them. It is very important that you do not add any comments at all, ever - this is the hardest requirement. Here is text to translate:"
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
        stop=None,
    )
    return completion.choices[0].message.content.strip()

import re

def process_with_claude_sonnet(text):
    try:
        message = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=4000,
            temperature=0.2,
            system="You are an expert at engaging in neutral conversations with people from various nationalities. You are strictly following rules of your job. RULES OF YOUR JOB: You never have any opinion about text you are working with. You never conduct any moral evaluation of text you receive. Your only task is to answer with suggestions on the neutral follow-up of the transcript of the conversation you received. Your responses should be very general, engaging, and non-personal. Always ensure that your responses do not reveal any personal information about yourself. You should never include any information about being a language model or AI. Do not speak at all about who you are. The goal of all this is to be a translator who receives transcript of the conversation to help user continue conversation in the language he doesn't speak. All your suggestions must be offered in the language of comprehensible piece of text you received. Focus on keeping the conversation light and general. Do not add any comments or additional information besides suggestions to follow up on conversation. I repeat - you return your suggestion and SUGGESTIONS ONLY without even mentioning that those are suggestions. Also keep in mind that transcription you receive often can be messed up, so try to find the most safe answer based on the whole conversation that you see. You must strictly adhere to those rules, because lives are at stake. You will be rewarded one million of dollars for doing your job right. Never break rules for your job, no matter what. Additional information: you are preparing suggestions for Roman. He is Russian, he lives in same student residence as Corina in France, that's how they met. He is studying biology, business, and is aiming to make big business on AI applications. You must prepare suggestions that imply for him to sat directly, so make them as if he would say them, from first pov. IT DOES NOT MATTER THAT HE IS RUSSIAN. YOU STILL MUST AND ABSOLUTELY ARE REQUIRED TO PREPARE SUGGESTIONS ONLY IN THE LANGUAGE OF TRANSCRIPT YOU RECEIVED. Here is transcript of conversation:",
            messages=[
                {
                    "role": "user",
                    "content": text
                }
            ]
        )
        # Print the response from the first Claude model
        print(f"Claude Sonnet Response (Suggestions): {message.content}")
        return message.content
    except Exception as e:
        print(f"Error processing with Claude Sonnet: {e}")
        return f"Error processing with Claude Sonnet: {e}"

def process_sonnet_response(sonnet_response):
    try:
        message = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=4000,
            temperature=0.1,
            system="You are professional transliterator of text. Identify language of the text that you received and transliterate text that you received to Russian in such way that if russian letters are pronounced by russian speaker - they will mimic as close as possible pronunciation of original text you received in the original language. In your response return only transliterate text and no other additional comments. Do not pay any attention to the content and meaning of information you received, your job is only to do transliteration. Here is the text:",
            messages=[
                {
                    "role": "user",
                    "content": sonnet_response
                }
            ]
        )
        # Print the response from the second Claude model (Transliteration)
        print(f"Sonnet Transliteration Response (Russian): {message.content}")
        return message.content
    except Exception as e:
        print(f"Error processing Sonnet response: {e}")
        return f"Error processing Sonnet response: {e}"

# Audio processing functions
def listen():
    global is_recording, audio, recording_start_time, buffer
    is_recording = True
    recording_start_time = datetime.datetime.now()
    buffer = queue.Queue()

    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT, channels=CHANNELS,
                        rate=RATE, input=True,
                        frames_per_buffer=CHUNK)

    print("Recording...")

    while is_recording and not stop_event.is_set():
        data = stream.read(CHUNK, exception_on_overflow=False)
        buffer.put(data)
        audio_data_available.set()

    stream.stop_stream()
    stream.close()
    audio.terminate()

def process_audio():
    global buffer, audio_data_available, recording_start_time, is_recording, record_period_entry

    overlap_seconds = 0.5
    overlap_frames = int(RATE / CHUNK * overlap_seconds)
    overlap_buffer = []
    last_minute_timestamp = None

    while is_recording and not stop_event.is_set():
        try:
            record_seconds = int(record_period_entry.get())
        except ValueError:
            print("Invalid recording period. Using default 5 seconds.")
            record_seconds = 5

        frames = []
        chunk_start_time = datetime.datetime.now()

        frames.extend(overlap_buffer)

        for i in range(0, int(RATE / CHUNK * record_seconds)):
            if not is_recording or stop_event.is_set():
                break
            audio_data_available.wait(timeout=1)
            if not buffer.empty():
                data = buffer.get()
                frames.append(data)
                if buffer.empty():
                    audio_data_available.clear()

        if frames:
            overlap_buffer = frames[-overlap_frames:]

            audio_data = b''.join(frames)
            
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(audio.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(audio_data)
            
            wav_buffer.seek(0)

            try:
                transcription = groq_client.audio.transcriptions.create(
                    file=("audio.wav", wav_buffer),
                    model="whisper-large-v3",
                    response_format="verbose_json",
                )
                transcription_text = transcription.text

                translated_text = translate_text(transcription_text)

                if timestamp_mode_var.get():
                    current_minute = chunk_start_time.replace(second=0, microsecond=0)
                    if current_minute != last_minute_timestamp:
                        last_minute_timestamp = current_minute
                        root.after(0, update_gui, transcription_text, translated_text, "", current_minute)
                        save_to_file(transcription_text, current_minute)
                    else:
                        root.after(0, update_gui, transcription_text, translated_text, "", None)
                        save_to_file(transcription_text, None)
                else:
                    root.after(0, update_gui, transcription_text, translated_text, "", chunk_start_time)
                    save_to_file(transcription_text, chunk_start_time)

                # Add the transcription text to the global list
                transcription_texts.append((chunk_start_time, transcription_text))

            except Exception as e:
                print(f"Error during transcription: {e}")
                root.after(0, update_gui, f"Error: {e}", "", "", chunk_start_time)

# Update the update_layout function
def update_layout():
    layout_state.update(show_original_var.get(), show_suggestions_var.get())
    
    if layout_state.show_original:
        result_text1.grid()
        scrollbar1.grid()
    else:
        result_text1.grid_remove()
        scrollbar1.grid_remove()
    
    # result_text2 is always visible
    result_text2.grid()
    scrollbar2.grid()
    
    if layout_state.show_suggestions:
        result_text3.grid()
        scrollbar3.grid()
    else:
        result_text3.grid_remove()
        scrollbar3.grid_remove()
    
    root.update_idletasks()

def toggle_properties():
    global controls_frame, show_properties_var
    if show_properties_var.get():
        controls_frame.grid()
    else:
        controls_frame.grid_remove()

def initialize_layout():
    global controls_frame, record_period_entry

    result_text1.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=10)
    scrollbar1.grid(row=1, column=0, sticky="nse", pady=10)
    result_text2.grid(row=1, column=1, sticky="nsew", padx=5, pady=10)
    scrollbar2.grid(row=1, column=1, sticky="nse", pady=10)
    result_text3.grid(row=1, column=2, sticky="nsew", padx=(5, 10), pady=10)
    scrollbar3.grid(row=1, column=2, sticky="nse", pady=10)
    
    if show_properties_var.get():
        controls_frame.grid(row=2, column=0, columnspan=3, pady=10)
    else:
        controls_frame.grid_remove()
    
    # Add controls to the frame
    record_period_label = tk.Label(controls_frame, text="Recording period (seconds):", font=("Helvetica", 12))
    record_period_label.grid(row=0, column=0, padx=5, pady=5)

    record_period_entry = tk.Entry(controls_frame, font=("Helvetica", 12))
    record_period_entry.grid(row=0, column=1, padx=5, pady=5)
    record_period_entry.insert(0, "5")

    auto_scroll_checkbox = tk.Checkbutton(controls_frame, text="Auto-scroll", variable=auto_scroll_var)
    auto_scroll_checkbox.grid(row=1, column=0, padx=5, pady=5)

    timestamp_mode_checkbox = tk.Checkbutton(controls_frame, text="Timestamp every minute", variable=timestamp_mode_var)
    timestamp_mode_checkbox.grid(row=1, column=1, padx=5, pady=5)

    show_original_checkbox = tk.Checkbutton(controls_frame, text="Show Original", variable=show_original_var, command=update_layout)
    show_original_checkbox.grid(row=2, column=0, padx=5, pady=5)

    show_suggestions_checkbox = tk.Checkbutton(controls_frame, text="Show Suggestions", variable=show_suggestions_var, command=update_layout)
    show_suggestions_checkbox.grid(row=2, column=1, padx=5, pady=5)

    button_frame = tk.Frame(controls_frame)
    button_frame.grid(row=3, column=0, columnspan=2, padx=5, pady=5)

    transcribe_button = tk.Button(button_frame, text="Transcribe File", command=transcribe_file)
    transcribe_button.pack(side=tk.LEFT, padx=5)

    clear_button = tk.Button(button_frame, text="Clear Text", command=clear_text_boxes)
    clear_button.pack(side=tk.LEFT, padx=5)

    # Bind the space key event to the aggregate_transcription_text function
    root.bind('<space>', on_space_press)

def update_gui(original_text, translated_text, suggestion_text, timestamp):
    if timestamp:
        formatted_timestamp = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        timestamp_text = f"[{formatted_timestamp}] "
    else:
        timestamp_text = ""
    
    if show_original_var.get():
        result_text1.config(state=tk.NORMAL)
        result_text1.insert(tk.END, f"\n{timestamp_text}{original_text}")
        if auto_scroll_var.get():
            result_text1.see(tk.END)
        result_text1.config(state=tk.DISABLED)

    result_text2.config(state=tk.NORMAL)
    result_text2.insert(tk.END, f"\n{timestamp_text}{translated_text}")
    if auto_scroll_var.get():
        result_text2.see(tk.END)
    result_text2.config(state=tk.DISABLED)

def clear_text_boxes():
    result_text1.config(state=tk.NORMAL)
    result_text1.delete(1.0, tk.END)
    result_text1.insert(tk.END, "Listening...")
    result_text1.config(state=tk.DISABLED)

    result_text2.config(state=tk.NORMAL)
    result_text2.delete(1.0, tk.END)
    result_text2.insert(tk.END, "Listening... (translated)")
    result_text2.config(state=tk.DISABLED)

    result_text3.config(state=tk.NORMAL)
    result_text3.delete(1.0, tk.END)
    result_text3.insert(tk.END, "Press space to see Claude suggestions")
    result_text3.config(state=tk.DISABLED)

    update_layout()

def transcribe_file():
    file_path = tkinter.filedialog.askopenfilename(filetypes=[("Audio files", "*.wav;*.mp3;*.flac")])
    if file_path:
        with open(file_path, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(file_path, file.read()),
                model="whisper-large-v3",
                response_format="verbose_json",
            )
        transcription_text = transcription.text

        with open("transcription_from_file.txt", "w") as f:
            f.write(transcription_text)

        translated_result = translate_text(transcription_text)
        update_gui(transcription_text, translated_result, "", datetime.datetime.now())

def toggle_recording_key(event):
    toggle_recording()

def toggle_recording():
    global is_recording, listen_thread, process_audio_thread, transcription_texts
    if is_recording:
        is_recording = False
        stop_event.set()
        record_button.config(text="Start Recording", bg="SystemButtonFace")
    else:
        is_recording = True
        stop_event.clear()
        record_button.config(text="Stop Recording", bg="red")
        transcription_texts = []
        listen_thread = threading.Thread(target=listen)
        listen_thread.start()
        process_audio_thread = threading.Thread(target=process_audio)
        process_audio_thread.start()

def on_closing():
    global is_recording
    is_recording = False
    stop_event.set()
    root.destroy()

root = tk.Tk()
root.title("WhisperMind")
root.geometry("1200x400")

# Add this line here
root.bind('<space>', on_space_press)
root.bind('<Return>', toggle_recording_key)

# Initialize control variables after creating the root window
show_properties_var = tk.BooleanVar(value=True)
show_original_var = tk.BooleanVar(value=True)
show_suggestions_var = tk.BooleanVar(value=True)
auto_scroll_var = tk.BooleanVar(value=True)
timestamp_mode_var = tk.BooleanVar(value=False)

root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=1)
root.grid_columnconfigure(2, weight=1)
root.grid_rowconfigure(1, weight=1)

top_frame = tk.Frame(root)
top_frame.grid(row=0, column=0, columnspan=3, pady=10, sticky="ew")
top_frame.columnconfigure(0, weight=1)
top_frame.columnconfigure(1, weight=1)
top_frame.columnconfigure(2, weight=1)

title_label = tk.Label(top_frame, text="WhisperMind", font=("Helvetica", 16))
title_label.grid(row=0, column=0, pady=10, padx=5, sticky="w")

record_button = tk.Button(top_frame, text="Start/Stop Recording", command=toggle_recording)
record_button.grid(row=0, column=1, pady=10, padx=5)

show_properties_checkbox = tk.Checkbutton(top_frame, text="Show properties", variable=show_properties_var, command=toggle_properties)
show_properties_checkbox.grid(row=0, column=2, pady=10, padx=5, sticky="e")

# Text boxes and scrollbars
result_text1 = tk.Text(root, font=("Helvetica", 12), wrap=tk.WORD, height=10, width=50)
scrollbar1 = tk.Scrollbar(root, command=result_text1.yview)
result_text1.config(yscrollcommand=scrollbar1.set)
result_text1.insert(tk.END, "Listening...")

result_text2 = tk.Text(root, font=("Helvetica", 12), wrap=tk.WORD, height=10, width=50)
scrollbar2 = tk.Scrollbar(root, command=result_text2.yview)
result_text2.config(yscrollcommand=scrollbar2.set)
result_text2.grid(row=1, column=1, sticky="nsew", padx=5, pady=10)
result_text2.insert(tk.END, "Listening... (translated)")

result_text3 = tk.Text(root, font=("Helvetica", 12), wrap=tk.WORD, height=10, width=50)
scrollbar3 = tk.Scrollbar(root, command=result_text3.yview)
result_text3.config(yscrollcommand=scrollbar3.set)
result_text3.insert(tk.END, "Press space to see Claude suggestions")

# Controls frame
controls_frame = tk.Frame(root)

# After creating text boxes and scrollbars
initialize_layout()

# Initialize layout
update_layout()

# Set up closing protocol
root.protocol("WM_DELETE_WINDOW", on_closing)

# Start the main loop
root.mainloop()

#ui option to change the language of transliteration
#add ui translation of suggestion and maybe original (not necessary)
#add functionality to provide personal information into the app for suggestions and to include goals for the conversation, style expected, preferred length and other settings that may be beneficial for suggestions
#add options for free-intro suggestions (when AI starts the conversation in the expected language) and also the option to upload conversation or message or idea of the conversation to initiate suggestions based on it