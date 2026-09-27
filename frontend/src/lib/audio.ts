let activeAudio: HTMLAudioElement | null = null;

export const stopPlayback = () => {
  if (activeAudio) {
    activeAudio.pause();
    activeAudio.currentTime = 0;
    activeAudio = null;
  }
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
};

export const playSpeech = (text: string, locale = "zh-CN") => {
  stopPlayback();
  if (!("speechSynthesis" in window)) return false;
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = locale;
  utterance.rate = 0.95;
  window.speechSynthesis.speak(utterance);
  return true;
};

export const playAudioOrSpeech = (audioUrl: string | undefined, text: string, locale = "zh-CN") => {
  stopPlayback();
  if (audioUrl) {
    activeAudio = new Audio(audioUrl);
    void activeAudio.play();
    return true;
  }
  return playSpeech(text, locale);
};
