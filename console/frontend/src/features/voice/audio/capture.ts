/** Constraints that match the old page: the pipeline does its own AGC/NS. */
const MIC: MediaTrackConstraints = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true
}

export async function acquireMic(deviceId = ''): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw Object.assign(new Error('This browser cannot capture audio.'), { code: 'mic-unsupported' })
  }
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: deviceId ? { ...MIC, deviceId: { exact: deviceId } } : MIC })
  } catch (error: any) {
    // The three names the page distinguishes in MicGate.
    const code =
      error?.name === 'NotAllowedError' || error?.name === 'SecurityError'
        ? 'mic-denied'
        : error?.name === 'NotFoundError' || error?.name === 'OverconstrainedError'
          ? 'mic-missing'
          : 'mic-failed'
    throw Object.assign(new Error(error?.message ?? 'Microphone failed'), { code, cause: error })
  }
}

/** Released on unmount, otherwise the tab keeps the recording indicator on. */
export function releaseMic(stream: MediaStream | null): void {
  for (const track of stream?.getTracks() ?? []) track.stop()
}

export async function listAudioDevices(): Promise<MediaDeviceInfo[]> {
  const devices = (await navigator.mediaDevices?.enumerateDevices?.()) ?? []
  return devices.filter((device) => device.kind === 'audioinput')
}
