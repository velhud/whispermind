const wavefile = require('wavefile');

const audioService = {
  convertPcmChunksToWav(audioChunks, sampleRate) {
    const audioBuffer = Buffer.concat(audioChunks.map((chunk) => Buffer.from(chunk)));
    const wav = new wavefile.WaveFile();
    wav.fromScratch(1, sampleRate, '16', audioBuffer);
    return wav.toBuffer();
  },

  processAudioFile(fileBuffer) {
    return Buffer.from(fileBuffer);
  },
};

module.exports = { audioService };
