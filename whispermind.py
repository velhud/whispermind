import datetime
import threading
import queue
import tkinter as tk
import tkinter.filedialog

import ai_utils
from ai_utils import translate_text, process_with_claude_sonnet, process_sonnet_response
from audio_utils import listen, process_audio
from settings_utils import load_settings, save_settings
from export_utils import export_markdown


class LayoutState:
    def __init__(self):
        self.show_original = True
        self.show_suggestions = True

    def update(self, show_original: bool, show_suggestions: bool):
        self.show_original = show_original
        self.show_suggestions = show_suggestions

layout_state = LayoutState()
transcription_texts = []

buffer = queue.Queue()
audio_data_available = threading.Event()
stop_event = threading.Event()
is_recording = False

def on_space_press(event):
    now = datetime.datetime.now()
    five_minutes_ago = now - datetime.timedelta(minutes=5)
    relevant = [text for ts, text in transcription_texts if ts >= five_minutes_ago]
    if relevant:
        personal = {k: personal_info_entries[k].get() for k in ['name', 'goal', 'style', 'length']}
        resp = process_with_claude_sonnet(' '.join(relevant), personal)
        processed = process_sonnet_response(resp, transliteration_language_var.get())
        timestamp = now.strftime('%Y-%m-%d %H:%M:%S')
        update_gui_third_box(f"[{timestamp}] {processed}")


def update_gui_third_box(text: str):
    result_text3.config(state=tk.NORMAL)
    result_text3.delete(1.0, tk.END)
    result_text3.insert(tk.END, text)
    if auto_scroll_var.get():
        result_text3.see(tk.END)
    result_text3.config(state=tk.DISABLED)

def save_to_file(text: str, timestamp: datetime.datetime):
    with open('transcriptions.txt', 'a', encoding='utf-8') as f:
        if timestamp:
            ts = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{ts}]\n{text}\n")
        else:
            f.write(f"{text}\n")


def update_gui(original_text: str, translated_text: str, timestamp: datetime.datetime):
    if timestamp:
        ts_text = f"[{timestamp.strftime('%Y-%m-%d %H:%M:%S')}] "
    else:
        ts_text = ''
    if show_original_var.get():
        result_text1.config(state=tk.NORMAL)
        result_text1.insert(tk.END, f"\n{ts_text}{original_text}")
        if auto_scroll_var.get():
            result_text1.see(tk.END)
        result_text1.config(state=tk.DISABLED)
    result_text2.config(state=tk.NORMAL)
    result_text2.insert(tk.END, f"\n{ts_text}{translated_text}")
    if auto_scroll_var.get():
        result_text2.see(tk.END)
    result_text2.config(state=tk.DISABLED)
    transcription_texts.append((timestamp, original_text))

def clear_text_boxes():
    result_text1.config(state=tk.NORMAL)
    result_text1.delete(1.0, tk.END)
    result_text1.insert(tk.END, 'Listening...')
    result_text1.config(state=tk.DISABLED)
    result_text2.config(state=tk.NORMAL)
    result_text2.delete(1.0, tk.END)
    result_text2.insert(tk.END, 'Listening... (translated)')
    result_text2.config(state=tk.DISABLED)
    result_text3.config(state=tk.NORMAL)
    result_text3.delete(1.0, tk.END)
    result_text3.insert(tk.END, 'Press space to see Claude suggestions')
    result_text3.config(state=tk.DISABLED)
    update_layout()

def transcribe_file():
    file_path = tkinter.filedialog.askopenfilename(filetypes=[('Audio files', '*.wav;*.mp3;*.flac')])
    if file_path:
        with open(file_path, 'rb') as file:
            transcription = ai_utils.groq_client.audio.transcriptions.create(
                file=(file_path, file.read()),
                model='whisper-large-v3',
                response_format='verbose_json',
            )
        text = transcription.text
        with open('transcription_from_file.txt', 'w') as f:
            f.write(text)
        translated = translate_text(text, translation_language_var.get())
        update_gui(text, translated, datetime.datetime.now())

def toggle_recording_key(event):
    toggle_recording()


def toggle_recording():
    global is_recording, listen_thread, process_audio_thread, transcription_texts
    if is_recording:
        is_recording = False
        stop_event.set()
        record_button.config(text='Start Recording', bg='SystemButtonFace')
    else:
        is_recording = True
        stop_event.clear()
        record_button.config(text='Stop Recording', bg='red')
        transcription_texts = []
        listen_thread = threading.Thread(target=listen, args=(buffer, audio_data_available, stop_event, lambda: is_recording))
        listen_thread.start()
        process_audio_thread = threading.Thread(
            target=process_audio,
            args=(buffer, audio_data_available, stop_event, lambda: is_recording, lambda: record_period_entry.get(), update_gui, lambda: translation_language_var.get())
        )
        process_audio_thread.start()

def handle_save_settings():
    settings = {
        'transliteration_language': transliteration_language_var.get(),
        'translation_language': translation_language_var.get(),
        'auto_scroll': auto_scroll_var.get(),
        'timestamp_mode': timestamp_mode_var.get(),
        'show_original': show_original_var.get(),
        'show_suggestions': show_suggestions_var.get(),
        'personal_info': {k: personal_info_entries[k].get() for k in ['name','goal','style','length']}
    }
    try:
        save_settings(settings)
        print('Settings saved successfully.')
    except ValueError as e:
        print(f'Error saving settings: {e}')


def handle_load_settings():
    settings = load_settings()
    if not settings:
        print('Settings file not found.')
        return
    transliteration_language_var.set(settings.get('transliteration_language', 'Russian'))
    translation_language_var.set(settings.get('translation_language', 'English'))
    auto_scroll_var.set(settings.get('auto_scroll', True))
    timestamp_mode_var.set(settings.get('timestamp_mode', False))
    show_original_var.set(settings.get('show_original', True))
    show_suggestions_var.set(settings.get('show_suggestions', True))
    personal_info = settings.get('personal_info', {})
    for k in ['name','goal','style','length']:
        personal_info_entries[k].delete(0, tk.END)
        personal_info_entries[k].insert(0, personal_info.get(k, ''))
    update_layout()
    print('Settings loaded successfully.')

def export_transcriptions():
    records = []
    end_line = int(float(result_text2.index('end-1c')))
    for idx in range(end_line):
        orig = result_text1.get(f'{idx}.0', f'{idx}.end').strip()
        trans = result_text2.get(f'{idx}.0', f'{idx}.end').strip()
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if orig:
            records.append((ts, orig, trans))
    export_markdown(records, 'transcriptions_export.md')
    print('Exported to transcriptions_export.md')

def update_layout():
    layout_state.update(show_original_var.get(), show_suggestions_var.get())
    if layout_state.show_original:
        result_text1.grid()
        scrollbar1.grid()
    else:
        result_text1.grid_remove()
        scrollbar1.grid_remove()
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
    if show_properties_var.get():
        controls_frame.grid()
    else:
        controls_frame.grid_remove()

def initialize_layout():
    result_text1.grid(row=1, column=0, sticky='nsew', padx=(10,5), pady=10)
    scrollbar1.grid(row=1, column=0, sticky='nse', pady=10)
    result_text2.grid(row=1, column=1, sticky='nsew', padx=5, pady=10)
    scrollbar2.grid(row=1, column=1, sticky='nse', pady=10)
    result_text3.grid(row=1, column=2, sticky='nsew', padx=(5,10), pady=10)
    scrollbar3.grid(row=1, column=2, sticky='nse', pady=10)
    if show_properties_var.get():
        controls_frame.grid(row=2, column=0, columnspan=3, pady=10, sticky='ew')
    else:
        controls_frame.grid_remove()

    recording_frame = tk.LabelFrame(controls_frame, text='Recording Controls', padx=5, pady=5)
    recording_frame.grid(row=0, column=0, padx=5, pady=5, sticky='w')
    tk.Label(recording_frame, text='Period (sec):', font=('Helvetica',12)).grid(row=0, column=0, padx=5, pady=2, sticky='w')
    global record_period_entry
    record_period_entry = tk.Entry(recording_frame, font=('Helvetica',12), width=10)
    record_period_entry.grid(row=0, column=1, padx=5, pady=2)
    record_period_entry.insert(0,'5')
    tk.Checkbutton(recording_frame, text='Auto-scroll', variable=auto_scroll_var).grid(row=0, column=2, padx=5, pady=2)
    tk.Checkbutton(recording_frame, text='Timestamp every minute', variable=timestamp_mode_var).grid(row=0, column=3, padx=5, pady=2)

    display_frame = tk.LabelFrame(controls_frame, text='Display Options', padx=5, pady=5)
    display_frame.grid(row=0, column=1, padx=5, pady=5, sticky='w')
    tk.Checkbutton(display_frame, text='Show Original', variable=show_original_var, command=update_layout).grid(row=0, column=0, padx=5, pady=2)
    tk.Checkbutton(display_frame, text='Show Suggestions', variable=show_suggestions_var, command=update_layout).grid(row=0, column=1, padx=5, pady=2)

    language_frame = tk.LabelFrame(controls_frame, text='Language Settings', padx=5, pady=5)
    language_frame.grid(row=0, column=2, padx=5, pady=5, sticky='w')
    tk.Label(language_frame, text='Transliteration:', font=('Helvetica',12)).grid(row=0, column=0, padx=5, pady=2, sticky='e')
    translit_options=['Russian','Spanish','French','German','Chinese']
    tk.OptionMenu(language_frame, transliteration_language_var, *translit_options).grid(row=0, column=1, padx=5, pady=2)
    tk.Label(language_frame, text='Translate To:', font=('Helvetica',12)).grid(row=1, column=0, padx=5, pady=2, sticky='e')
    translation_options=['English','Spanish','French','German','Chinese']
    tk.OptionMenu(language_frame, translation_language_var, *translation_options).grid(row=1, column=1, padx=5, pady=2)

    personal_info_frame = tk.LabelFrame(controls_frame, text='Personal Information', padx=5, pady=5)
    personal_info_frame.grid(row=1, column=0, columnspan=6, padx=5, pady=(10,5), sticky='w')
    for idx, key in enumerate(['name','goal','style','length']):
        tk.Label(personal_info_frame, text=f'{key.capitalize()}:', font=('Helvetica',12)).grid(row=0, column=idx*2, padx=5, pady=2, sticky='e')
        entry = tk.Entry(personal_info_frame, font=('Helvetica',12), width=15)
        entry.grid(row=0, column=idx*2+1, padx=5, pady=2)
        personal_info_entries[key] = entry

    buttons_frame = tk.Frame(controls_frame)
    buttons_frame.grid(row=2, column=5, padx=5, pady=5, sticky='e')
    tk.Button(buttons_frame, text='Transcribe File', command=transcribe_file, width=15).grid(row=0, column=0, padx=5, pady=5)
    tk.Button(buttons_frame, text='Clear Text', command=clear_text_boxes, width=15).grid(row=0, column=1, padx=5, pady=5)
    tk.Button(buttons_frame, text='Save Settings', command=handle_save_settings, width=15).grid(row=1, column=0, padx=5, pady=5)
    tk.Button(buttons_frame, text='Load Settings', command=handle_load_settings, width=15).grid(row=1, column=1, padx=5, pady=5)
    tk.Button(buttons_frame, text='Export', command=export_transcriptions, width=15).grid(row=2, column=0, padx=5, pady=5)

root = tk.Tk()
root.title('WhisperMind')
root.geometry('1200x400')
root.bind('<space>', on_space_press)
root.bind('<Return>', toggle_recording_key)

show_properties_var = tk.BooleanVar(value=True)
show_original_var = tk.BooleanVar(value=True)
show_suggestions_var = tk.BooleanVar(value=True)
auto_scroll_var = tk.BooleanVar(value=True)
timestamp_mode_var = tk.BooleanVar(value=False)
transliteration_language_var = tk.StringVar(value='Russian')
translation_language_var = tk.StringVar(value='English')

personal_info_entries = {}

root.grid_columnconfigure(0, weight=1)
root.grid_columnconfigure(1, weight=1)
root.grid_columnconfigure(2, weight=1)
root.grid_rowconfigure(1, weight=1)

top_frame = tk.Frame(root)
top_frame.grid(row=0, column=0, columnspan=3, pady=10, sticky='ew')
top_frame.columnconfigure(0, weight=1)
top_frame.columnconfigure(1, weight=1)
top_frame.columnconfigure(2, weight=1)

title_label = tk.Label(top_frame, text='WhisperMind', font=('Helvetica',16))
title_label.grid(row=0, column=0, pady=10, padx=5, sticky='w')
record_button = tk.Button(top_frame, text='Start/Stop Recording', command=toggle_recording)
record_button.grid(row=0, column=1, pady=10, padx=5)
show_properties_checkbox = tk.Checkbutton(top_frame, text='Show properties', variable=show_properties_var, command=toggle_properties)
show_properties_checkbox.grid(row=0, column=2, pady=10, padx=5, sticky='e')

result_text1 = tk.Text(root, font=('Helvetica',12), wrap=tk.WORD, height=10, width=50)
scrollbar1 = tk.Scrollbar(root, command=result_text1.yview)
result_text1.config(yscrollcommand=scrollbar1.set)
result_text1.insert(tk.END,'Listening...')

result_text2 = tk.Text(root, font=('Helvetica',12), wrap=tk.WORD, height=10, width=50)
scrollbar2 = tk.Scrollbar(root, command=result_text2.yview)
result_text2.config(yscrollcommand=scrollbar2.set)
result_text2.grid(row=1,column=1,sticky='nsew',padx=5,pady=10)
result_text2.insert(tk.END,'Listening... (translated)')

result_text3 = tk.Text(root, font=('Helvetica',12), wrap=tk.WORD, height=10, width=50)
scrollbar3 = tk.Scrollbar(root, command=result_text3.yview)
result_text3.config(yscrollcommand=scrollbar3.set)
result_text3.insert(tk.END,'Press space to see Claude suggestions')

controls_frame = tk.Frame(root)
separator = tk.Frame(controls_frame, height=2, bd=1, relief=tk.SUNKEN)
separator.grid(row=1, column=0, columnspan=6, padx=5, pady=5, sticky='ew')

initialize_layout()
update_layout()

root.protocol('WM_DELETE_WINDOW', root.destroy)
root.mainloop()
