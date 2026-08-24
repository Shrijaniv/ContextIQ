"""
ContextIQ Voice Server - FastAPI WebSocket server using ContextIQ agent factory

Serves the React frontend and handles bidirectional voice/text via WebSocket.
Adapted from original agent module but using the cleaner ContextIQ agent structure.
"""
import asyncio
import os
import sys
import json
import base64
import logging
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Add parent for imports (must be before local imports)
sys.path.insert(0, str(Path(__file__).parent.parent))

from contextiq_agent.agent.contextiq_agent import create_contextiq_agent  # noqa: E402
from contextiq_agent.agent.config import load_config  # noqa: E402


# Configure structured logging
class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging"""

    def format(self, record):
        log_data = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }

        # Add extra fields if present
        for field in ['event_type', 'tool_name', 'execution_time', 'user_input',
                      'agent_response', 'error', 'audio_size', 'input_type', 'voice_id']:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)

        return json.dumps(log_data)


# Set up logger
logger = logging.getLogger("contextiq_voice_server")
logger.setLevel(logging.INFO)

# Console handler
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)

# File handler
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
file_handler = logging.FileHandler(
    log_dir / f"voice_server_{datetime.now().strftime('%Y%m%d')}.log"
)
file_handler.setFormatter(StructuredFormatter())
logger.addHandler(file_handler)


# Environment config
INPUT_SAMPLE_RATE = int(os.getenv("INPUT_SAMPLE_RATE", "16000"))
OUTPUT_SAMPLE_RATE = int(os.getenv("OUTPUT_SAMPLE_RATE", "16000"))
CHANNELS = int(os.getenv("CHANNELS", "1"))
FORMAT = os.getenv("FORMAT", "pcm")


# Create FastAPI app
app = FastAPI(
    title="ContextIQ Voice Server",
    description="Voice assistant powered by Nova Sonic with ContextIQ agent",
    version="3.0.0"
)

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "ContextIQ Voice Server",
        "version": "3.0.0",
        "websocket": "/ws",
        "health": "/health"
    }


@app.get("/ping")
@app.get("/health")
async def health():
    """Health check endpoint (required by AgentCore)"""
    return {
        "status": "Healthy",
        "agent": "contextiq_voice",
        "time_of_last_update": int(datetime.now().timestamp())
    }


@app.websocket("/ws")
async def voice_chat(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for bidirectional voice/text streaming.

    Accepts:
    - Binary frames: PCM audio data from React frontend
    - JSON frames: Text input or audio (base64)

    Returns:
    - Audio output (binary or base64)
    - Text transcripts
    - Usage/metadata events
    """

    # Get voice preference from query params
    voice = websocket.query_params.get("voice_id", "amy")

    try:
        # Load config
        config = load_config()
        logger.info(f"📋 Config loaded: region={config.aws_region}")

        # Callback: push reminder_created event to the frontend in real time
        async def on_reminder_created(text: str, due_date: str, result: dict) -> None:
            try:
                await websocket.send_json({
                    "type": "reminder_created",
                    "text": text,
                    "due_date": due_date,
                    "iso_date": result.get("iso_date"),
                })
                logger.info(f"📅 Sent reminder_created event: {text!r} due {due_date!r}")
            except Exception as exc:
                logger.warning(f"Could not send reminder_created event: {exc}")

        # Callback: push calendar_event_created event to the frontend in real time
        async def on_calendar_event_created(result: dict) -> None:
            try:
                await websocket.send_json({
                    "type": "calendar_event_created",
                    "title": result.get("title"),
                    "date": result.get("date"),
                    "time": result.get("time"),
                    "location": result.get("location"),
                    "notes": result.get("notes"),
                    "iso_datetime": result.get("iso_datetime"),
                })
                logger.info(f"📆 Sent calendar_event_created: title={result.get('title')!r} date={result.get('date')!r}")
            except Exception as exc:
                logger.warning(f"Could not send calendar_event_created event: {exc}")

        # Create ContextIQ agent using ContextIQ factory
        agent = create_contextiq_agent(
            config,
            voice_id=voice,
            on_reminder_created=on_reminder_created,
            on_calendar_event_created=on_calendar_event_created,
            event_loop=asyncio.get_event_loop(),
        )
        logger.info(f"🤖 ContextIQ agent created (voice: {voice})")

        # Custom input handler for hybrid voice/text (React frontend pattern)
        async def receive_hybrid_input():
            """
            Receive either audio or text input from browser.
            Converts both to the format expected by BidiAgent.
            """
            while True:
                message = await websocket.receive()

                if "bytes" in message:
                    # Binary frame = PCM audio
                    audio_bytes = message["bytes"]
                    audio_b64 = base64.b64encode(audio_bytes).decode("ascii")

                    logger.debug(
                        "Received binary audio",
                        extra={
                            "event_type": "audio_received",
                            "input_type": "binary",
                            "audio_size": len(audio_bytes),
                        }
                    )

                    return {
                        "type": "bidi_audio_input",
                        "audio": audio_b64,
                        "format": "pcm",
                        "sample_rate": INPUT_SAMPLE_RATE,
                        "channels": CHANNELS,
                    }

                elif "text" in message:
                    # JSON frame = could be audio event OR text input
                    try:
                        data = json.loads(message["text"])
                    except json.JSONDecodeError:
                        logger.warning(
                            "Invalid JSON received",
                            extra={"event_type": "invalid_json"}
                        )
                        continue

                    if data.get("type") == "bidi_audio_input":
                        # Audio as JSON (alternative format)
                        logger.debug(
                            "Received JSON audio event",
                            extra={
                                "event_type": "audio_received",
                                "input_type": "json",
                            }
                        )
                        return data

                    elif data.get("type") == "bidi_text_input":
                        # Text input (hybrid mode)
                        text_content = data.get("text", "")
                        if text_content:
                            logger.info(
                                "Received text input",
                                extra={
                                    "event_type": "text_input_received",
                                    "input_type": "text",
                                    "user_input": text_content[:200],
                                }
                            )
                            return {
                                "type": "bidi_text_input",
                                "text": text_content,
                                "role": "user"
                            }
                        else:
                            logger.warning(
                                "Empty text input",
                                extra={"event_type": "empty_text_input"}
                            )
                            continue

                    # Pass through any other valid event
                    if isinstance(data, dict) and "type" in data:
                        logger.debug(
                            "Passing through event",
                            extra={
                                "event_type": "passthrough_event",
                                "message_type": data.get("type"),
                            }
                        )
                        return data
                    else:
                        logger.warning(
                            "Unknown message type",
                            extra={"event_type": "unknown_message"}
                        )
                        continue

        # Accept WebSocket connection
        await websocket.accept()
        logger.info(f"🔌 WebSocket connected (voice: {voice})")

        # Run agent with custom input handler
        # ContextIQ agent has tools directly attached (simpler than dual-agent)
        await agent.run(
            inputs=[receive_hybrid_input],
            outputs=[websocket.send_json]
        )

    except WebSocketDisconnect:
        logger.info("🔌 Client disconnected")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {str(e)}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "error": str(e)
            })
        except Exception:
            pass
    finally:
        # Cleanup
        try:
            await websocket.close()
            await agent.stop()
        except Exception as cleanup_error:
            logger.error(f"Error during cleanup: {cleanup_error}")


if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("ContextIQ Voice Server - ContextIQ Agent")
    print("=" * 60)
    print("Agent: Nova Sonic with ContextIQ tools")
    print(f"Audio: {INPUT_SAMPLE_RATE}Hz, {CHANNELS}ch, {FORMAT}")
    print("=" * 60)
    print("WebSocket: ws://localhost:8080/ws")
    print("Health: http://localhost:8080/health")
    print("React Frontend: http://localhost:5173 (run separately)")
    print("=" * 60)

    # Use localhost for local dev, 0.0.0.0 in containers
    host = "0.0.0.0" if os.getenv("CONTAINER_ENV") else "127.0.0.1"
    port = int(os.getenv("PORT", "8080"))

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )
