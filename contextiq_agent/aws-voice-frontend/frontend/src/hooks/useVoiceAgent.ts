import { useState, useRef, useCallback, useEffect } from 'react';
import audioCaptureProcessorUrl from '../audio-processor.worklet.js?url';
import {
  connectToAgent,
  WebSocketAgentConnection,
  BidiAudioInputEvent,
  audioToBase64,
  base64ToAudioBlob
} from '../websocket-presigned';

// Set to true to enable verbose audio debug logging in the browser console
const DEBUG = (import.meta as any).env.VITE_WS_DEBUG === 'true';
const log = (...args: any[]) => DEBUG && console.log(...args);

export interface ConversationTurn {
  role: 'user' | 'assistant';
  transcript: string;
  timestamp: Date;
}

export interface VoiceAgentState {
  isConnected: boolean;
  isRecording: boolean;
  isSpeaking: boolean;
  isPaused: boolean; // Track pause state (pauses both mic and agent)
  error: string | null;
  userTranscript: string;
  agentTranscript: string;
  conversationHistory: ConversationTurn[];
  forceNewBubble: boolean; // Flag to force new bubble after interruption
}

export interface UseVoiceAgentReturn extends VoiceAgentState {
  connect: () => Promise<void>;
  disconnect: () => void;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  togglePause: () => void;
  sendTextMessage: (text: string) => void;
  clearError: () => void;
}

export interface UseVoiceAgentOptions {
  onReminderCreated?: (reminder: { text: string; due_date: string; iso_date?: string }) => void;
  onCalendarEventCreated?: (event: { title: string; date: string; time?: string; location?: string; notes?: string; iso_datetime?: string }) => void;
}

export function useVoiceAgent(options: UseVoiceAgentOptions = {}): UseVoiceAgentReturn {
  const { onReminderCreated, onCalendarEventCreated } = options;
  const [state, setState] = useState<VoiceAgentState>({
    isConnected: false,
    isRecording: false,
    isSpeaking: false,
    isPaused: false,
    error: null,
    userTranscript: '',
    agentTranscript: '',
    conversationHistory: [],
    forceNewBubble: false
  });

  const connectionRef = useRef<WebSocketAgentConnection | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordingAudioContextRef = useRef<AudioContext | null>(null);
  const playbackAudioContextRef = useRef<AudioContext | null>(null);
  const audioQueueRef = useRef<AudioBuffer[]>([]);
  const isPlayingRef = useRef(false);
  const isPausedRef = useRef(false);

  // Connect to WebSocket
  const connect = useCallback(async () => {
    try {
      setState(prev => ({ ...prev, error: null }));

      const connection = await connectToAgent({
        onAudioChunk: async (audio: string, format: string, sampleRate: number) => {
          // Queue audio for playback only if not paused
          if (!isPausedRef.current) {
            await queueAudio(audio, format, sampleRate);
          }
        },
        onTranscript: (text: string, isFinal: boolean, role: 'assistant' | 'user') => {
          if (role === 'assistant') {
            setState(prev => {
              const newState = { ...prev };
              const history = [...prev.conversationHistory];
              const lastEntry = history.length > 0 ? history[history.length - 1] : null;

              if (isFinal && text) {
                // Final sentence - append to existing assistant bubble or create new one
                const shouldAppend = lastEntry && 
                                    lastEntry.role === 'assistant' && 
                                    !prev.forceNewBubble;
                
                if (shouldAppend) {
                  // Append to existing assistant bubble with space separator
                  const separator = lastEntry.transcript.length > 0 ? ' ' : '';
                  history[history.length - 1] = {
                    ...lastEntry,
                    transcript: lastEntry.transcript + separator + text,
                  };
                } else {
                  // Create new assistant bubble
                  history.push({ role: 'assistant', transcript: text, timestamp: new Date() });
                  newState.forceNewBubble = false; // Reset flag after creating new bubble
                }
                newState.conversationHistory = history;
                newState.agentTranscript = '';
                newState.isSpeaking = false;
              } else {
                // Partial transcript - accumulate in agentTranscript
                newState.agentTranscript = prev.agentTranscript + text;
                newState.isSpeaking = true;
              }

              return newState;
            });
          } else {
            setState(prev => {
              const newState = {
                ...prev,
                userTranscript: isFinal ? text : prev.userTranscript + text
              };

              // When user transcript is final, add to history
              if (isFinal && text) {
                newState.conversationHistory = [
                  ...prev.conversationHistory,
                  { role: 'user', transcript: text, timestamp: new Date() }
                ];
                newState.userTranscript = ''; // Clear current transcript
              }

              return newState;
            });
          }
        },
        onInterruption: (reason: string) => {
          console.log('Interrupted:', reason);
          // Clear audio queue on interruption
          audioQueueRef.current = [];
          isPlayingRef.current = false;
          
          // Set flag to force next assistant response into a new bubble
          setState(prev => ({ 
            ...prev, 
            isSpeaking: false, 
            agentTranscript: '',
            forceNewBubble: true 
          }));
        },
        onError: (error: string) => {
          setState(prev => ({ ...prev, error }));
        },
        onConnected: () => {
          setState(prev => ({ ...prev, isConnected: true, error: null }));
        },
        onDisconnected: () => {
          setState(prev => ({ ...prev, isConnected: false, isRecording: false, isSpeaking: false }));
        },
        onReminderCreated: onReminderCreated,
        onCalendarEventCreated: onCalendarEventCreated,
      });

      connectionRef.current = connection;
    } catch (error: any) {
      setState(prev => ({ ...prev, error: error.message }));
    }
  }, []);

  // Disconnect from WebSocket
  const disconnect = useCallback(() => {
    // Stop recording
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    }
    
    // Close WebSocket
    if (connectionRef.current) {
      connectionRef.current.close();
      connectionRef.current = null;
    }
    
    // Clear audio queue and stop playback immediately
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    
    // Close audio contexts to stop any ongoing playback
    if (recordingAudioContextRef.current && recordingAudioContextRef.current.state !== 'closed') {
      recordingAudioContextRef.current.close();
    }
    if (playbackAudioContextRef.current && playbackAudioContextRef.current.state !== 'closed') {
      playbackAudioContextRef.current.close();
    }
    
    setState({
      isConnected: false,
      isRecording: false,
      isSpeaking: false,
      isPaused: false,
      error: null,
      userTranscript: '',
      agentTranscript: '',
      conversationHistory: [],
      forceNewBubble: false
    });
    isPausedRef.current = false;
  }, []);

  // Start recording audio
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ 
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true
        }
      });
      
      // Create AudioContext for PCM conversion (separate from playback)
      const audioContext = new AudioContext({ sampleRate: 16000 });
      recordingAudioContextRef.current = audioContext;
      
      // Load AudioWorklet module
      log('[Audio] Loading worklet from:', audioCaptureProcessorUrl);
      await audioContext.audioWorklet.addModule(audioCaptureProcessorUrl);
      log('[Audio] Worklet loaded, AudioContext state:', audioContext.state);
      
      const source = audioContext.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioContext, 'audio-capture-processor');
      log('[Audio] WorkletNode created');

      // Handle messages from the worklet
      workletNode.port.onmessage = (event) => {
        if (!connectionRef.current?.isConnected()) return;

        if (event.data.type === 'audio') {
          const pcmData = event.data.data as Int16Array;

          // Convert to base64
          const base64Audio = btoa(
            String.fromCharCode(...new Uint8Array(pcmData.buffer))
          );

          const audioEvent: BidiAudioInputEvent = {
            type: 'bidi_audio_input',
            audio: base64Audio,
            format: 'pcm',
            sample_rate: 16000,
            channels: 1
          };

          connectionRef.current.send(audioEvent);
        }
      };

      source.connect(workletNode);
      workletNode.connect(audioContext.destination);

      // Store references for cleanup
      mediaRecorderRef.current = { 
        stop: () => {
          workletNode.disconnect();
          source.disconnect();
          audioContext.close();
          stream.getTracks().forEach(track => track.stop());
        },
        state: 'recording',
        stream
      } as any;

      setState(prev => ({ ...prev, isRecording: true, userTranscript: '' }));
    } catch (error: any) {
      setState(prev => ({ ...prev, error: `Microphone error: ${error.message}` }));
    }
  }, []);

  // Stop recording audio
  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      setState(prev => ({ ...prev, isRecording: false }));
    }
  }, []);

  // Toggle pause/resume (pauses both mic and agent audio)
  const togglePause = useCallback(async () => {
    if (isPausedRef.current) {
      // Resume
      if (playbackAudioContextRef.current && playbackAudioContextRef.current.state === 'suspended') {
        await playbackAudioContextRef.current.resume();
      }
      isPausedRef.current = false;
      setState(prev => ({ ...prev, isPaused: false }));
      await startRecording();
    } else {
      // Pause
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
        mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      }
      audioQueueRef.current = [];
      isPlayingRef.current = false;
      if (playbackAudioContextRef.current && playbackAudioContextRef.current.state !== 'closed') {
        playbackAudioContextRef.current.suspend();
      }
      isPausedRef.current = true;
      setState(prev => ({
        ...prev,
        isPaused: true,
        isRecording: false,
        isSpeaking: false
      }));
    }
  }, [startRecording]);

  // Queue audio for playback
  const queueAudio = async (base64Audio: string, format: string, sampleRate: number) => {
    try {
      if (!playbackAudioContextRef.current || playbackAudioContextRef.current.state === 'closed') {
        playbackAudioContextRef.current = new AudioContext({ sampleRate });
      }

      // Resume audio context if suspended (can happen due to browser autoplay policies)
      if (playbackAudioContextRef.current.state === 'suspended') {
        await playbackAudioContextRef.current.resume();
      }

      let audioBuffer: AudioBuffer;

      if (format === 'pcm') {
        // Decode base64 to raw PCM bytes
        const binaryString = atob(base64Audio);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }

        // Convert Int16 PCM to Float32 for AudioBuffer
        const pcmData = new Int16Array(bytes.buffer);
        const floatData = new Float32Array(pcmData.length);
        for (let i = 0; i < pcmData.length; i++) {
          floatData[i] = pcmData[i] / (pcmData[i] < 0 ? 0x8000 : 0x7FFF);
        }

        // Create AudioBuffer from PCM data
        audioBuffer = playbackAudioContextRef.current.createBuffer(1, floatData.length, sampleRate);
        audioBuffer.getChannelData(0).set(floatData);
      } else {
        // For encoded formats (mp3, webm, etc.), use decodeAudioData
        const audioBlob = base64ToAudioBlob(base64Audio, `audio/${format}`);
        const arrayBuffer = await audioBlob.arrayBuffer();
        audioBuffer = await playbackAudioContextRef.current.decodeAudioData(arrayBuffer);
      }

      audioQueueRef.current.push(audioBuffer);

      if (!isPlayingRef.current) {
        playNextAudio().catch(err => console.error('Error playing audio:', err));
      }
    } catch (error) {
      console.error('Error queuing audio:', error);
    }
  };

  // Play next audio in queue
  const playNextAudio = async () => {
    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      setState(prev => ({ ...prev, isSpeaking: false }));
      return;
    }

    if (!playbackAudioContextRef.current || playbackAudioContextRef.current.state === 'closed') {
      console.warn('Playback AudioContext is closed, skipping audio playback');
      audioQueueRef.current = [];
      isPlayingRef.current = false;
      setState(prev => ({ ...prev, isSpeaking: false }));
      return;
    }

    // Resume audio context if suspended before playing
    if (playbackAudioContextRef.current.state === 'suspended') {
      await playbackAudioContextRef.current.resume();
    }

    isPlayingRef.current = true;
    setState(prev => ({ ...prev, isSpeaking: true }));

    const audioBuffer = audioQueueRef.current.shift()!;
    const source = playbackAudioContextRef.current.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(playbackAudioContextRef.current.destination);

    source.onended = () => {
      playNextAudio().catch(err => console.error('Error playing next audio:', err));
    };

    source.start();
  };

  // Send text message
  const sendTextMessage = useCallback((text: string) => {
    if (!connectionRef.current?.isConnected()) {
      setState(prev => ({
        ...prev,
        error: 'Not connected. Please start chatting first.'
      }));
      return;
    }

    if (!text.trim()) {
      return; // Ignore empty messages
    }

    // Send text via WebSocket
    connectionRef.current.sendText(text);

    // Add to conversation history immediately (optimistic update)
    setState(prev => ({
      ...prev,
      conversationHistory: [
        ...prev.conversationHistory,
        { role: 'user', transcript: text, timestamp: new Date() }
      ]
    }));
  }, []);

  const clearError = useCallback(() => {
    setState(prev => ({ ...prev, error: null }));
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
      if (recordingAudioContextRef.current) {
        recordingAudioContextRef.current.close();
      }
      if (playbackAudioContextRef.current) {
        playbackAudioContextRef.current.close();
      }
    };
  }, [disconnect]);

  return {
    ...state,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    togglePause,
    sendTextMessage,
    clearError
  };
}
