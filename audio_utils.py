import pyaudio
import wave
import io
import queue
import threading
import datetime
from typing import Callable

from ai_utils import groq_client, translate_text

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000


def listen(buffer: queue.Queue, audio_data_available: threading.Event, stop_event: threading.Event, is_recording: Callable[[], bool]):
    audio = pyaudio.PyAudio()
    stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    while is_recording() and not stop_event.is_set():
        data = stream.read(CHUNK, exception_on_overflow=False)
        buffer.put(data)
        audio_data_available.set()
    stream.stop_stream()
    stream.close()
    audio.terminate()


def process_audio(buffer: queue.Queue, audio_data_available: threading.Event, stop_event: threading.Event, is_recording: Callable[[], bool], record_seconds_getter: Callable[[], int], on_result: Callable[[str, str, datetime.datetime], None], translation_language_getter: Callable[[], str]):
    overlap_seconds = 0.5
    overlap_frames = int(RATE / CHUNK * overlap_seconds)
    overlap_buffer = []
    last_minute_timestamp = None
    audio = pyaudio.PyAudio()

    while is_recording() and not stop_event.is_set():
        try:
            record_seconds = int(record_seconds_getter())
        except ValueError:
            record_seconds = 5
        frames = []
        chunk_start_time = datetime.datetime.now()
        frames.extend(overlap_buffer)
        for _ in range(0, int(RATE / CHUNK * record_seconds)):
            if not is_recording() or stop_event.is_set():
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
                translated_text = translate_text(transcription_text, translation_language_getter())
                on_result(transcription_text, translated_text, chunk_start_time)
            except Exception as e:
                on_result(f"Error: {e}", "", chunk_start_time)
    audio.terminate()
