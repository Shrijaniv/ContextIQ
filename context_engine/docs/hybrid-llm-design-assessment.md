# Hybrid Architecture Assessment: Claude Reasoning + Nova Sonic Voice

## Goal
Use Claude Sonnet for reasoning/tool execution (better instruction-following) while keeping Nova Sonic for voice I/O (STT/TTS).

## Current Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Current Flow                          │
└─────────────────────────────────────────────────────────────┘

Browser (React)
    ↓ WebSocket: PCM audio (16kHz)
FastAPI Server (voice_server.py)
    ↓ receive_hybrid_input()
BidiAgent (Strands framework)
    ↓ agent.run(inputs, outputs)
Nova Sonic (amazon.nova-2-sonic-v1:0)
    ├─ Speech-to-Text (STT)
    ├─ Reasoning + Tool Execution
    └─ Text-to-Speech (TTS)
    ↓ WebSocket: PCM audio out
Browser (React)
```

**Key findings from code analysis:**

1. **BidiAgent is tightly coupled to BidiModel**
   - File: `strands/experimental/bidi/agent.py`
   - `BidiAgent.run()` expects a `BidiModel` that handles entire conversation flow
   - No separation between transcription, reasoning, and synthesis

2. **Nova Sonic is end-to-end**
   - File: `strands/experimental/bidi/models/nova_sonic.py`
   - Uses `InvokeModelWithBidirectionalStreamOperationInput`
   - Single streaming connection handles: audio in → reasoning → audio out
   - No separate APIs for STT-only or TTS-only

3. **AWS Bedrock has no separate STT/TTS APIs**
   - Verified: `boto3.client('bedrock-runtime')` has no transcribe/synthesize methods
   - Nova Sonic is conversational AI, not a speech service

---

## Proposed Hybrid Architecture

### Option 2A: Sequential Pipeline (High Latency)

```
Browser (React)
    ↓ WebSocket: PCM audio (16kHz)
FastAPI Server
    ↓ Buffer audio until silence detected
Nova Sonic (STT only - NOT POSSIBLE)
    ↓ Transcribed text
Claude Sonnet 4.5 (via standard Strands Agent)
    ├─ Reasoning
    └─ Tool Execution
    ↓ Text response
Nova Sonic (TTS only - NOT POSSIBLE)
    ↓ Synthesized audio
Browser (React)
```

**Status:** ❌ **NOT FEASIBLE**

**Blockers:**
1. Nova Sonic cannot be used for STT-only or TTS-only
2. No AWS Bedrock APIs for separate transcription/synthesis
3. Would need to use external services (e.g., Amazon Transcribe + Amazon Polly)

### Option 2B: External STT/TTS Services

```
Browser (React)
    ↓ WebSocket: PCM audio
FastAPI Server
    ↓ Buffer audio
Amazon Transcribe Streaming (STT)
    ↓ Transcribed text
Claude Sonnet 4.5 (standard Agent)
    ├─ Reasoning
    └─ Tool Execution  
    ↓ Text response
Amazon Polly (TTS with neural voices)
    ↓ Synthesized audio
Browser (React)
```

**Status:** ✅ **FEASIBLE** but complex

**Implementation changes required:**

1. **Replace BidiAgent with standard Agent**
   ```python
   # keeper/agent/keeper_agent.py
   from strands import Agent
   from strands.models.bedrock import BedrockModel
   
   def create_keeper_agent(config):
       model = BedrockModel(
           model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
           region_name=config.aws_region
       )
       return Agent(model=model, system_prompt=..., tools=...)
   ```

2. **Add STT service integration**
   ```python
   # keeper/services/transcribe.py
   import boto3
   
   async def transcribe_audio_stream(audio_stream):
       """Use Amazon Transcribe Streaming for STT"""
       transcribe = boto3.client('transcribe-streaming')
       # Stream audio chunks, get back text
   ```

3. **Add TTS service integration**
   ```python
   # keeper/services/polly.py
   import boto3
   
   async def synthesize_speech(text: str, voice_id: str = "Amy"):
       """Use Amazon Polly Neural for TTS"""
       polly = boto3.client('polly')
       response = polly.synthesize_speech(
           Text=text,
           OutputFormat='pcm',
           VoiceId=voice_id,
           Engine='neural'
       )
       return response['AudioStream'].read()
   ```

4. **Refactor WebSocket handler**
   ```python
   # keeper/voice_server.py
   @app.websocket("/ws")
   async def voice_chat(websocket: WebSocket):
       # 1. Receive audio → buffer until silence
       # 2. Send to Transcribe → get text
       # 3. Pass text to Claude Agent → get response text
       # 4. Send response to Polly → get audio
       # 5. Stream audio back to browser
   ```

---

## Feasibility Concerns

### 1. **Latency**

| Component | Current (BidiAgent) | Option 2B (Sequential) |
|-----------|---------------------|------------------------|
| Audio buffering | Real-time streaming | Wait for silence detection (~1-3s) |
| STT | Integrated in stream | Separate API call (~500ms-1s) |
| Reasoning | Integrated in stream | Separate API call (~2-5s with tools) |
| TTS | Integrated in stream | Separate API call (~500ms-1s) |
| **Total perceived latency** | **~1-2s** | **~4-10s** |

**Concern:** User will notice 4-10 second delay between speaking and hearing response.

**Mitigation:**
- Use Amazon Transcribe Streaming (real-time, not batch)
- Implement aggressive silence detection (end-of-utterance)
- Stream Polly audio chunks as they arrive
- Show visual "thinking" indicator during processing

### 2. **WebSocket Protocol Changes**

**Current:** Bidirectional streaming (audio flows both ways simultaneously)

**Option 2B:** Half-duplex (audio flows one direction at a time)
- User speaks → stop output audio
- Agent speaks → ignore input audio

**Implementation:**
```python
# Add state machine to voice_server.py
class ConversationState(Enum):
    LISTENING = "listening"      # Accepting user audio
    PROCESSING = "processing"    # Running Claude
    SPEAKING = "speaking"        # Streaming agent audio
```

**Concern:** Loss of interruption/barge-in capability
- **Current:** User can interrupt agent mid-sentence (Nova Sonic detects this)
- **Option 2B:** Must wait for agent to finish speaking

**Mitigation:**
- Detect user audio during SPEAKING state
- Cancel ongoing Polly synthesis
- Restart from LISTENING state

### 3. **Cost**

| Service | Current (Nova Sonic) | Option 2B |
|---------|----------------------|-----------|
| STT | Included | Amazon Transcribe Streaming: $0.02/min |
| Reasoning | Nova Sonic: $0.012/1K tokens | Claude Sonnet: $0.003/1K tokens (cheaper!) |
| TTS | Included | Amazon Polly Neural: $0.016/1M chars |

**Impact:** Slightly higher cost (~$0.02 more per minute), but **Claude is cheaper than Nova Sonic for reasoning**.

### 4. **Voice Quality**

| Aspect | Nova Sonic | Polly Neural |
|--------|------------|--------------|
| Voice naturalness | Excellent (conversational AI) | Good (TTS-focused) |
| Emotion/prosody | Natural conversation flow | Limited expressiveness |
| Available voices | Matthew, Amy, etc. | 50+ voices (Ruth, Joanna, etc.) |

**Concern:** Polly may sound more robotic than Nova Sonic

**Mitigation:** Use Polly's Neural engine (better than Standard)

### 5. **Audio Format Handling**

**Current:**
- Browser sends: 16kHz PCM mono
- Nova Sonic expects: 16kHz PCM mono (native format)
- Nova Sonic outputs: 16kHz PCM mono
- Browser receives: 16kHz PCM mono

**Option 2B:**
- Browser sends: 16kHz PCM mono
- Transcribe expects: 16kHz PCM mono ✅
- Polly outputs: 16kHz PCM mono ✅
- Browser receives: 16kHz PCM mono ✅

**Status:** ✅ No format conversion needed (all use 16kHz PCM)

---

## Implementation Effort

### Phase 1: Core Architecture (2-3 days)
- [ ] Replace BidiAgent with standard Agent
- [ ] Integrate Amazon Transcribe Streaming
- [ ] Integrate Amazon Polly Neural
- [ ] Refactor WebSocket handler for sequential flow

### Phase 2: Quality Improvements (1-2 days)
- [ ] Implement silence detection for end-of-utterance
- [ ] Add conversation state machine
- [ ] Stream Polly audio chunks (reduce perceived latency)
- [ ] Add visual "thinking" indicators in UI

### Phase 3: Feature Parity (1-2 days)
- [ ] Implement interruption/barge-in detection
- [ ] Add audio buffering and retry logic
- [ ] Error handling and fallback to text mode
- [ ] Testing across different network conditions

**Total estimate:** 4-7 days of development

---

## Alternative: Option 1 (Strengthen Prompt)

**Effort:** 1-2 hours

**Approach:** Rewrite system prompt with:
- Explicit forbidden patterns
- More few-shot examples
- Shorter, more directive instructions
- Negative examples ("Never say...")

**Trade-off:** May not fully solve precision issues with Nova Sonic, but worth trying first.

---

## Recommendation

### Short-term (Next 1-2 hours)
✅ **Try Option 1 first:** Strengthen the system prompt for Nova Sonic

**Rationale:**
- Minimal effort (1-2 hours vs 4-7 days)
- No latency impact
- No cost increase
- Preserves barge-in capability
- May achieve 70-80% of desired improvement

### Medium-term (If Option 1 insufficient)
⚠️ **Consider Option 2B:** Sequential pipeline with external STT/TTS

**Only if:**
- Prompt strengthening proves insufficient
- User is willing to accept 4-10s latency
- Loss of barge-in is acceptable
- Budget allows for Transcribe + Polly costs

**Benefits:**
- Claude Sonnet's superior instruction-following
- Matches test_agent.py quality exactly
- Lower reasoning costs (Claude cheaper than Nova Sonic)

**Drawbacks:**
- Higher latency (4-10s vs 1-2s)
- No barge-in during agent speech
- More complex architecture
- 4-7 days development effort

---

## Verification Checklist

To confirm feasibility of Option 2B, verify:

- [x] AWS Bedrock has no separate STT/TTS APIs for Nova Sonic
- [x] BidiAgent requires BidiModel (can't use standard Agent)
- [x] Audio format compatibility (16kHz PCM works with Transcribe + Polly)
- [ ] Test Amazon Transcribe Streaming latency in us-west-2
- [ ] Test Amazon Polly Neural voice quality vs Nova Sonic
- [ ] Measure end-to-end latency with Claude Sonnet + tools
- [ ] Verify WebSocket can handle state machine (LISTENING/PROCESSING/SPEAKING)
- [ ] Test interruption detection during Polly playback

---

## Back-and-Forth Conversation Handling

### Current (BidiAgent + Nova Sonic)

**Real-time bidirectional streaming:**

```
Turn 1:
User speaks → [streaming STT] → [streaming reasoning] → [streaming TTS] → Agent speaks
             ↑ Can interrupt at any time ↑

Turn 2 (user interrupts mid-response):
User speaks → [Nova Sonic detects interruption] → [stops current response] → [new reasoning] → Agent speaks
             ↑ Seamless, no state machine needed ↑

Turn 3 (quick follow-up):
User: "and the second one?" → [immediate processing, no buffering delay] → Agent responds
```

**Characteristics:**
- ✅ User can interrupt agent at any time (barge-in)
- ✅ No visible state transitions (feels like talking to a person)
- ✅ Quick follow-ups feel natural (no waiting for "ready" state)
- ✅ Conversation context maintained across turns in single stream

### Option 2B (Sequential Pipeline)

**Half-duplex state machine:**

```
Turn 1:
State: LISTENING
User speaks → [wait for silence: 1-3s] → State: PROCESSING
→ Transcribe → Claude → Polly → State: SPEAKING
→ Agent speaks → [wait for audio to finish] → State: LISTENING

Turn 2 (user tries to interrupt):
State: SPEAKING (agent mid-sentence)
User speaks → [audio ignored or buffered] → [agent finishes speaking] → State: LISTENING
→ Process buffered audio → State: PROCESSING
→ Claude responds → State: SPEAKING

Turn 3 (quick follow-up):
State: LISTENING
User: "and the second one?" → [wait for silence: 1-3s] → State: PROCESSING
→ Transcribe (STT latency: ~500ms) → Claude (reasoning: 2-5s) → Polly (TTS: ~500ms)
→ State: SPEAKING → Agent responds (total: 4-9s delay)
```

**Characteristics:**
- ❌ User must wait for state = LISTENING before speaking
- ❌ Interruption requires buffering + waiting for agent to finish
- ❌ Silence detection adds 1-3s to every turn
- ❌ Each turn goes through full STT → reasoning → TTS pipeline
- ❌ Feels "walkie-talkie" style (you talk, then I talk, then you talk...)

### Multi-Turn Conversation Example

**Scenario:** User asks to order 3 items

**Current (BidiAgent):**
```
User: "order cilantro, limes, and tortillas"
Agent: "Found cilantro. Here are top options..." [speaking]
User: "first one" [interrupts mid-sentence]
Agent: [stops, processes] "Added. Searching limes..." [speaking]
User: "second one" [interrupts]
Agent: [stops, processes] "Added. Searching tortillas..." [speaking]
User: "first one" [interrupts]
Agent: [stops, processes] "All added to cart!"

Total time: ~15-20 seconds (fast, natural)
```

**Option 2B (Sequential):**
```
User: "order cilantro, limes, and tortillas"
[Wait for silence: 2s]
[STT: 500ms] [Claude: 3s] [TTS: 500ms]
Agent: "Found cilantro. Here are top options..." [speaking: 5s]
[Wait for agent to finish: 5s]
User: "first one"
[Wait for silence: 2s]
[STT: 500ms] [Claude: 3s] [TTS: 500ms]
Agent: "Added. Searching limes..." [speaking: 3s]
[Wait for agent to finish: 3s]
User: "second one"
[Wait for silence: 2s]
[STT: 500ms] [Claude: 3s] [TTS: 500ms]
Agent: "Added. Searching tortillas..." [speaking: 3s]
[Wait for agent to finish: 3s]
User: "first one"
[Wait for silence: 2s]
[STT: 500ms] [Claude: 3s] [TTS: 500ms]
Agent: "All added to cart!" [speaking: 2s]

Total time: ~45-60 seconds (slow, robotic)
```

### Conversation Context Preservation

| Aspect | Current (BidiAgent) | Option 2B (Sequential) |
|--------|---------------------|------------------------|
| **Context continuity** | Single streaming session maintains full context | Must pass conversation history to Claude on each turn |
| **Memory overhead** | Minimal (stream state only) | Accumulates (must send full history each call) |
| **Tool results** | Embedded in stream | Must be stored and replayed in context |
| **Interruption handling** | Automatic (Nova Sonic detects) | Manual (detect audio during SPEAKING, cancel, rebuild context) |

**Implementation for context:**

```python
# Option 2B requires explicit conversation history management
class ConversationSession:
    def __init__(self):
        self.messages = []  # Accumulate all turns
        self.agent = create_keeper_agent(config)
    
    async def process_turn(self, user_text: str) -> str:
        # Must include full conversation history on every Claude call
        self.messages.append({"role": "user", "content": user_text})
        
        # Claude needs all prior turns for context
        result = self.agent(
            user_text,
            conversation_history=self.messages  # Growing overhead
        )
        
        response_text = result.message["content"][0]["text"]
        self.messages.append({"role": "assistant", "content": response_text})
        
        return response_text
```

**Concern:** After 10-20 turns, conversation history becomes large:
- Increases Claude input tokens (costs money)
- Increases latency (more tokens to process)
- Risk of hitting context window limits

**Mitigation:** Implement conversation summarization or sliding window

### User Experience Impact

**Current (BidiAgent):**
- Feels like talking to a person
- Natural interruptions (like human conversations)
- Fast back-and-forth for multi-step tasks
- No visible "system is thinking" delays

**Option 2B:**
- Feels like using a walkie-talkie (over/out)
- Must wait your turn to speak
- Slow back-and-forth for multi-step tasks
- Visible "processing" delays between turns

**User frustration scenarios:**

1. **Rapid corrections:**
   ```
   User: "order milk"
   Agent: [starts speaking] "Searching for mil—"
   User: "wait, I meant almond milk!" [IGNORED, must wait]
   Agent: [finishes] "—k. Here are dairy milk options..."
   User: "no, almond milk!" [NOW processed, but wasted 10s]
   ```

2. **Quick follow-ups:**
   ```
   User: "what's the second option?"
   [2s silence detection]
   [4s processing]
   [2s TTS]
   Agent responds
   
   vs Current:
   User: "what's the second option?"
   [~1s] Agent responds immediately
   ```

3. **Multi-item ordering (shopping, restaurant search):**
   - Current: 3 items in ~20s (with interruptions)
   - Option 2B: 3 items in ~60s (must wait each turn)

---

## Conclusion

**Option 2 (hybrid architecture) is technically feasible but comes with significant trade-offs:**

✅ **Pros:**
- Claude Sonnet's superior instruction-following (matches test_agent.py)
- Lower reasoning costs
- Full control over conversation flow

❌ **Cons:**
- **4-10s latency** (vs 1-2s current)
- **No real-time barge-in** during agent speech
- **4-7 days development** effort
- More complex architecture to maintain

**Recommendation:** Start with Option 1 (prompt strengthening) before committing to Option 2's complexity and latency penalties.
