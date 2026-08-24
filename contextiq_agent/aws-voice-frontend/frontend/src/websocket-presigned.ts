/**
 * WebSocket connection to AgentCore using presigned URLs
 * Uses @aws-sdk/signature-v4 for SigV4 signing (matching voice-shop reference implementation)
 */

import { getAWSCredentials } from './aws-credentials';
import { Sha256 } from '@aws-crypto/sha256-js';
import { SignatureV4 } from '@aws-sdk/signature-v4';
import { HttpRequest } from '@smithy/protocol-http';

// Set to true to enable verbose WebSocket debug logging in the browser console
const DEBUG = (import.meta as any).env.VITE_WS_DEBUG === 'true';
const log = (...args: any[]) => DEBUG && console.log(...args);

export interface WebSocketAgentConnection {
  send: (message: any) => void;
  sendText: (text: string) => void; // NEW: Send text message
  close: () => void;
  isConnected: () => boolean;
  sessionId: string; // Expose session ID for tracking
}

export interface ReminderCreatedPayload {
  text: string;
  due_date: string;
  iso_date?: string;
}

export interface CalendarEventCreatedPayload {
  title: string;
  date: string;
  time?: string;
  location?: string;
  notes?: string;
  iso_datetime?: string;
}

export interface ConnectOptions {
  onAudioChunk: (audio: string, format: string, sampleRate: number) => void;
  onTranscript: (text: string, isFinal: boolean, role: 'assistant' | 'user') => void;
  onInterruption?: (reason: string) => void;
  onError?: (error: string) => void;
  onConnected?: () => void;
  onDisconnected?: () => void;
  onReminderCreated?: (reminder: ReminderCreatedPayload) => void;
  onCalendarEventCreated?: (event: CalendarEventCreatedPayload) => void;
  sessionId?: string;
}

export interface BidiAudioInputEvent {
  type: 'bidi_audio_input';
  audio: string;
  format: 'pcm';
  sample_rate: number;
  channels: number;
}

/**
 * Generate a unique session ID for tracking and debugging
 * Must be at least 33 characters as per AWS requirements
 */
function generateSessionId(): string {
  // crypto.randomUUID() returns a standard UUID (36 characters with hyphens)
  // Supported in all modern browsers (Chrome 92+, Firefox 95+, Safari 15.4+)
  return crypto.randomUUID();
}

/**
 * Generate presigned WebSocket URL using AWS SDK SignatureV4
 */
async function fetchPresignedUrl(sessionId: string): Promise<string> {
  // Check if running in local dev mode
  const isLocalDev = (import.meta as any).env.VITE_LOCAL_DEV === 'true';
  const localUrl = (import.meta as any).env.VITE_AGENT_RUNTIME_URL;

  if (isLocalDev && localUrl) {
    log('[Presigned URL] Local dev mode, session ID:', `****${sessionId.slice(-4)}`);

    // Check if localUrl is already a full WebSocket URL
    if (localUrl.startsWith('ws://') || localUrl.startsWith('wss://')) {
      // Direct WebSocket URL - use as-is
      log('[Presigned URL] WebSocket URL (direct):', localUrl);
      return localUrl;
    } else {
      // Relative path - construct WebSocket URL from window.location
      // Use ws:// for HTTP, wss:// for HTTPS
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}${localUrl}`;
      log('[Presigned URL] WebSocket URL (proxied):', wsUrl);
      return wsUrl;
    }
  }

  const agentRuntimeArn = (import.meta as any).env.VITE_AGENT_RUNTIME_ARN;

  if (!agentRuntimeArn) {
    throw new Error('VITE_AGENT_RUNTIME_ARN not configured');
  }

  const region = (import.meta as any).env.VITE_REGION || 'us-east-1';

  // Get AWS credentials from Cognito
  log('[Presigned URL] Getting AWS credentials...');
  const credentials = await getAWSCredentials();

  log('[Presigned URL] Access Key:', `****${credentials.accessKeyId.slice(-4)}`);
  log('[Presigned URL] Has Session Token:', !!credentials.sessionToken);
  log('[Presigned URL] Session ID:', `****${sessionId.slice(-4)}`);

  // Build the base URL with properly encoded ARN
  // ARNs contain colons and slashes that should be URL-encoded in the path
  const encodedArn = encodeURIComponent(agentRuntimeArn);
  const baseUrl = `https://bedrock-agentcore.${region}.amazonaws.com/runtimes/${encodedArn}/ws`;
  const url = new URL(baseUrl);
  
  // Qualifier specifies the runtime endpoint (DEFAULT, staging, prod, etc.)
  url.searchParams.set('qualifier', 'DEFAULT');
  
  // Add session ID to query parameters for tracking in CloudWatch logs
  url.searchParams.set('X-Amzn-Bedrock-AgentCore-Runtime-Session-Id', sessionId);

  log('[Presigned URL] Base URL:', baseUrl);

  // Create HTTP request for signing
  const request = new HttpRequest({
    method: 'GET',
    protocol: 'https:',
    hostname: url.hostname,
    path: url.pathname,
    query: Object.fromEntries(url.searchParams),
    headers: {
      host: url.hostname,
    },
  });

  // Sign the request with SigV4
  const signer = new SignatureV4({
    service: 'bedrock-agentcore',
    region,
    credentials: {
      accessKeyId: credentials.accessKeyId,
      secretAccessKey: credentials.secretAccessKey,
      sessionToken: credentials.sessionToken,
    },
    sha256: Sha256,
  });

  const signedRequest = await signer.presign(request, {
    expiresIn: 3600,
  });

  // Convert signed request to WebSocket URL (wss://)
  const hostname = signedRequest.hostname;
  const path = signedRequest.path || '/';
  const query = signedRequest.query || {};

  const queryString = Object.entries(query)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join('&');

  const wsUrl = `wss://${hostname}${path}${queryString ? '?' + queryString : ''}`;

  log('[Presigned URL] Generated successfully');
  log('[Presigned URL] URL length:', wsUrl.length);

  return wsUrl;
}


/**
 * Connect to AgentCore using presigned URL
 */
export async function connectToAgent(options: ConnectOptions): Promise<WebSocketAgentConnection> {
  const { onAudioChunk, onTranscript, onInterruption, onError, onConnected, onDisconnected, sessionId: providedSessionId } = options;

  // Use provided session ID or generate a new one
  // Reusing session ID maintains context across reconnections
  const sessionId = providedSessionId || generateSessionId();
  log('[WebSocket] Session ID:', `****${sessionId.slice(-4)}`);
  log(providedSessionId ? '[WebSocket] Reusing existing session for continuity' : '[WebSocket] Generated new session ID');

  log('[WebSocket] Fetching presigned URL...');
  const presignedUrl = await fetchPresignedUrl(sessionId);
  log('[WebSocket] Got presigned URL, connecting...');

  const ws = new WebSocket(presignedUrl);

  return new Promise((resolve, reject) => {
    ws.onopen = () => {
      log('[WebSocket] Connected successfully');
      log('[WebSocket] Session ID:', `****${sessionId.slice(-4)}`);
      if (onConnected) onConnected();

      resolve({
        send: (message: any) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify(message));
          }
        },
        sendText: (text: string) => {
          if (ws.readyState === WebSocket.OPEN) {
            const textMessage = {
              type: 'bidi_text_input',
              text: text,
              role: 'user'
            };
            ws.send(JSON.stringify(textMessage));
            log('[WebSocket] Sent text message:', text.substring(0, 50) + '...');
          }
        },
        close: () => {
          ws.close();
        },
        isConnected: () => ws.readyState === WebSocket.OPEN,
        sessionId, // Return session ID for reuse
      });
    };

    ws.onerror = (event) => {
      console.error('[WebSocket] Error:', event);
      console.error('[WebSocket] ReadyState:', ws.readyState);
      console.error('[WebSocket] Session ID:', sessionId);
      const error = 'WebSocket connection failed';
      if (onError) onError(error);
      reject(new Error(error));
    };

    ws.onclose = (event) => {
      log('[WebSocket] Connection closed');
      log('[WebSocket] Close code:', event.code);
      log('[WebSocket] Close reason:', event.reason);
      log('[WebSocket] Was clean:', event.wasClean);
      log('[WebSocket] Session ID:', `****${sessionId.slice(-4)}`);
      if (onDisconnected) onDisconnected();
    };

    ws.onmessage = async (event) => {
      try {
        const data = JSON.parse(event.data);

        // Handle audio output
        if (data.type === 'bidi_audio_stream' && data.audio) {
          onAudioChunk(data.audio, data.format || 'pcm', data.sample_rate || 16000);
        }

        // Handle transcripts
        if (data.type === 'bidi_transcript_stream') {
          const role = data.role === 'user' ? 'user' : 'assistant';
          const isFinal = data.is_final !== false;
          onTranscript(data.text || '', isFinal, role);
        }

        // Handle text responses
        if (data.type === 'bidi_text_response' && data.text) {
          onTranscript(data.text, true, 'assistant');
        }

        // Handle interruptions
        if (data.type === 'bidi_interruption') {
          if (onInterruption) onInterruption(data.reason || 'interrupted');
        }

        // Handle reminder created by agent
        if (data.type === 'reminder_created') {
          if (options.onReminderCreated) {
            options.onReminderCreated({ text: data.text, due_date: data.due_date, iso_date: data.iso_date });
          }
        }

        // Handle calendar event created by agent
        if (data.type === 'calendar_event_created') {
          if (options.onCalendarEventCreated) {
            options.onCalendarEventCreated({
              title: data.title,
              date: data.date,
              time: data.time,
              location: data.location,
              notes: data.notes,
              iso_datetime: data.iso_datetime,
            });
          }
        }
      } catch (err) {
        console.error('[WebSocket] Error parsing message:', err);
        console.error('[WebSocket] Session ID:', sessionId);
      }
    };
  });
}

/**
 * Convert audio buffer to base64 PCM
 */
export function audioToBase64(audioBuffer: AudioBuffer): string {
  const channelData = audioBuffer.getChannelData(0);
  const pcmData = new Int16Array(channelData.length);

  for (let i = 0; i < channelData.length; i++) {
    const s = Math.max(-1, Math.min(1, channelData[i]));
    pcmData[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }

  return btoa(String.fromCharCode(...new Uint8Array(pcmData.buffer)));
}

/**
 * Convert base64 to audio blob
 */
export function base64ToAudioBlob(base64Audio: string, mimeType: string): Blob {
  const binaryString = atob(base64Audio);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return new Blob([bytes], { type: mimeType });
}
