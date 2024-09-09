# WhisperMind

WhisperMind is an audio transcription and translation application that utilizes AI models to provide real-time suggestions and translations based on recorded audio. The application is built using Python and leverages libraries such as `pyaudio`, `tkinter`, and `anthropic`.

## Features

- **Audio Recording**: Record audio for a specified duration.
- **Transcription**: Convert recorded audio into text using the Whisper model.
- **Translation**: Translate transcribed text into English using the Groq API.
- **Suggestions**: Generate conversation suggestions based on the transcribed text using the Claude model.
- **User Interface**: A simple GUI built with Tkinter for easy interaction.

## Requirements

- Python 3.x
- Required libraries:
  - `pyaudio`
  - `tkinter`
  - `wave`
  - `asyncio`
  - `dotenv`
  - `anthropic`
  - `groq`
  
You can install the required libraries using pip:

bash
pip install pyaudio python-dotenv anthropic groq


## Setup

1. Clone the repository or download the code.
2. Create a `.env` file in the project directory and add your API keys:

   ```plaintext
   ANTHROPIC_API_KEY=your_anthropic_api_key
   GROQ_API_KEY=your_groq_api_key
   ```

3. Run the application:

   ```bash
   python whispermind1.01.py
   ```

## Usage

- Start the application and use the "Start/Stop Recording" button to record audio.
- Press the spacebar to aggregate and view suggestions based on the last 5 minutes of transcriptions.
- The application will display the original transcription, its translation, and suggestions in the GUI.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any enhancements or bug fixes.

## License

This project is licensed under the [Creative Commons Attribution-NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/) - see the LICENSE file for details.