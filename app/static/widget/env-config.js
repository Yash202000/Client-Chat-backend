// Fallback runtime config — used in dev or when Docker entrypoint hasn't run.
// In production this file is overwritten by env-config.sh at container startup.
window._env_ = {
  VITE_BACKEND_URL: "",
  VITE_LIVEKIT_URL: "",
  VITE_VOICE_ENGINE_URL: ""
};
