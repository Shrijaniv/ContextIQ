import { useState, useEffect, useRef, useCallback } from 'react';
import { useVoiceAgent } from './hooks/useVoiceAgent';
import { getCurrentUser, signOut } from './auth';
import './App.css';

interface AuthUser { email: string; }

interface Reminder {
  id: string;
  text: string;
  dueDate?: string;   // ISO string
  completed: boolean;
  createdAt: string;
}

interface CalendarEvent {
  id: string;
  title: string;
  date: string;        // YYYY-MM-DD
  time?: string;
  location?: string;
  notes?: string;
  iso_datetime?: string;
  createdAt: string;
}

const CHIPS = [
  { label: 'Check weather',        text: 'What is the weather like today?' },
  { label: 'Shop on Amazon',        text: 'Help me find something on Amazon.' },
  { label: 'Set a reminder',        text: 'Set a reminder for me.' },
  { label: 'Search the web',        text: 'Search the web for me.' },
];

type Panel = 'reminders' | 'calendar' | null;

// ── Calendar helpers ──────────────────────────────────────────────────────────
const DAYS   = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}
function getFirstDayOfMonth(year: number, month: number) {
  return new Date(year, month, 1).getDay();
}


function getGreeting(): string {
  const h = new Date().getHours();
  if (h >= 5  && h < 12) return 'Good morning';
  if (h >= 12 && h < 17) return 'Good afternoon';
  if (h >= 17 && h < 21) return 'Good evening';
  return 'Good night';
}

// Alexa swirl SVG — matches the "a" ringmark from alexa.amazon.com
function AlexaSwirl({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="16" cy="16" r="14" stroke="#1a9be6" strokeWidth="3.2" strokeLinecap="round"
        strokeDasharray="70 18" strokeDashoffset="10" />
      <circle cx="16" cy="16" r="7" stroke="#1a9be6" strokeWidth="2.4" strokeLinecap="round"
        strokeDasharray="28 16" strokeDashoffset="4" />
    </svg>
  );
}

// Amazon smile SVG underline
function AlexaSmile() {
  return (
    <svg className="alexa-smile" width="54" height="9" viewBox="0 0 54 9" fill="none">
      <path d="M2 3 Q14 9 27 7 Q40 5 52 3" stroke="#1a9be6" strokeWidth="2.2"
        strokeLinecap="round" fill="none"/>
      <path d="M48 1 L52 3 L49 6" stroke="#1a9be6" strokeWidth="2" strokeLinecap="round"
        strokeLinejoin="round" fill="none"/>
    </svg>
  );
}

function App() {
  const isLocalDev = (import.meta as any).env.VITE_LOCAL_DEV === 'true';

  const setRemindersRef = useRef<React.Dispatch<React.SetStateAction<Reminder[]>> | null>(null);
  const setCalendarEventsRef = useRef<React.Dispatch<React.SetStateAction<CalendarEvent[]>> | null>(null);

  const voiceAgent = useVoiceAgent({
    onReminderCreated: ({ text, iso_date }) => {
      setRemindersRef.current?.(prev => {
        if (prev.some(r => r.text.toLowerCase() === text.toLowerCase())) return prev;
        return [...prev, {
          id: Date.now().toString(),
          text,
          dueDate: iso_date,
          completed: false,
          createdAt: new Date().toISOString(),
        }];
      });
    },
    onCalendarEventCreated: (event) => {
      setCalendarEventsRef.current?.(prev => {
        if (prev.some(e => e.title === event.title && e.date === event.date)) return prev;
        return [...prev, {
          id: Date.now().toString(),
          title: event.title,
          date: event.date,
          time: event.time,
          location: event.location,
          notes: event.notes,
          iso_datetime: event.iso_datetime,
          createdAt: new Date().toISOString(),
        }];
      });
    },
  });
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const pillInputRef = useRef<HTMLInputElement>(null);

  const [user,               setUser              ] = useState<AuthUser | null>(null);
  const [checkingAuth,       setCheckingAuth      ] = useState(true);
  const [showAuthModal,      setShowAuthModal     ] = useState(false);
  const [AuthModalComponent, setAuthModalComponent] = useState<any>(null);
  const [isConnecting,       setIsConnecting      ] = useState(false);
  const [textInput,          setTextInput         ] = useState('');
  const [error,              setError             ] = useState('');
  const [activePanel,        setActivePanel       ] = useState<Panel>(null);
  const [reminders,          setReminders         ] = useState<Reminder[]>(() => {
    try { return JSON.parse(localStorage.getItem('contextiq-reminders') || '[]'); }
    catch { return []; }
  });
  setRemindersRef.current = setReminders;
  const [calendarEvents,     setCalendarEvents    ] = useState<CalendarEvent[]>(() => {
    try { return JSON.parse(localStorage.getItem('contextiq-calendar-events') || '[]'); }
    catch { return []; }
  });
  setCalendarEventsRef.current = setCalendarEvents;
  const [showCompleted,      setShowCompleted     ] = useState(false);
  const [newReminderText,    setNewReminderText   ] = useState('');
  const [calendarDate,       setCalendarDate      ] = useState(new Date());
  const [selectedDate,       setSelectedDate      ] = useState(new Date());
  const [showAddEvent,       setShowAddEvent      ] = useState(false);
  const [eventForm,          setEventForm         ] = useState({
    name: '', allDay: false,
    startTime: '2:30 PM', startDate: new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }),
    endTime: '3:30 PM',   endDate:   new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }),
    location: '', notes: '',
  });

  // ── Auth ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (isLocalDev) { setUser({ email: 'M' }); setCheckingAuth(false); }
    else             { checkAuth(); }
  }, [isLocalDev]);

  useEffect(() => {
    if (!isLocalDev && showAuthModal && !AuthModalComponent)
      import('./AuthModal').then(m => setAuthModalComponent(() => m.default));
  }, [showAuthModal, AuthModalComponent, isLocalDev]);

  const checkAuth = async () => {
    try   { setUser(await getCurrentUser()); }
    catch { setUser(null); }
    finally { setCheckingAuth(false); }
  };

  const handleAuthSuccess = async () => { setShowAuthModal(false); await checkAuth(); };

  // ── Persist reminders and calendar events ────────────────────────────────────
  useEffect(() => {
    localStorage.setItem('contextiq-reminders', JSON.stringify(reminders));
  }, [reminders]);

  useEffect(() => {
    localStorage.setItem('contextiq-calendar-events', JSON.stringify(calendarEvents));
  }, [calendarEvents]);

  // ── Auto-scroll ───────────────────────────────────────────────────────────
  useEffect(() => {
    if (chatContainerRef.current)
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
  }, [voiceAgent.conversationHistory, voiceAgent.isSpeaking]);

  // ── Voice ─────────────────────────────────────────────────────────────────
  const handlePillClick = async () => {
    if (voiceAgent.isConnected || isConnecting) return;
    setIsConnecting(true);
    try {
      await voiceAgent.connect();
      setTimeout(() => voiceAgent.startRecording(), 1000);
    } finally {
      setIsConnecting(false);
    }
  };

  const handleStop = () => voiceAgent.disconnect();

  const handleSendText = () => {
    if (textInput.trim() && voiceAgent.isConnected) {
      voiceAgent.sendTextMessage(textInput.trim());
      setTextInput('');
    }
  };

  const handleChipClick = async (text: string) => {
    if (!user) { setShowAuthModal(true); return; }
    if (voiceAgent.isConnected) {
      voiceAgent.sendTextMessage(text);
    } else {
      setIsConnecting(true);
      try {
        await voiceAgent.connect();
        setTimeout(() => { voiceAgent.startRecording(); voiceAgent.sendTextMessage(text); }, 1000);
      } finally { setIsConnecting(false); }
    }
  };

  // ── State ─────────────────────────────────────────────────────────────────
  const pillState = (() => {
    if (isConnecting || (voiceAgent.isConnected && !voiceAgent.isRecording && !voiceAgent.isPaused)) return 'connecting';
    if (voiceAgent.isPaused)    return 'paused';
    if (voiceAgent.isSpeaking)  return 'speaking';
    if (voiceAgent.isRecording) return 'listening';
    return 'idle';
  })();

  const isActive = pillState !== 'idle' && pillState !== 'connecting';
  const showWaveform = pillState === 'listening' || pillState === 'speaking';

  const statusText = (() => {
    if (pillState === 'connecting') return 'Connecting…';
    if (pillState === 'listening')  return 'Listening';
    if (pillState === 'speaking')   return 'Speaking';
    if (pillState === 'paused')     return 'Paused';
    return '';
  })();

  const userInitial = user?.email?.[0]?.toUpperCase() ?? 'M';

  // ── Reminder helpers ──────────────────────────────────────────────────────
  const addReminder = useCallback(() => {
    if (!newReminderText.trim()) return;
    setReminders(prev => [...prev, { id: Date.now().toString(), text: newReminderText.trim(), completed: false, createdAt: new Date().toISOString() }]);
    setNewReminderText('');
  }, [newReminderText]);

  const toggleReminder = useCallback((id: string) => {
    setReminders(prev => prev.map(r => r.id === id ? { ...r, completed: !r.completed } : r));
  }, []);

  const deleteReminder = useCallback((id: string) => {
    setReminders(prev => prev.filter(r => r.id !== id));
  }, []);

  const deleteCalendarEvent = useCallback((id: string) => {
    setCalendarEvents(prev => prev.filter(e => e.id !== id));
  }, []);

  const togglePanel = useCallback((panel: Panel) => {
    setActivePanel(prev => prev === panel ? null : panel);
    setShowAddEvent(false);
  }, []);

  const saveEvent = useCallback(() => {
    if (!eventForm.name.trim()) return;
    setReminders(prev => [...prev, {
      id: Date.now().toString(),
      text: eventForm.name.trim(),
      dueDate: eventForm.allDay ? undefined : new Date(`${eventForm.startDate} ${eventForm.startTime}`).toISOString(),
      completed: false,
      createdAt: new Date().toISOString(),
    }]);
    setShowAddEvent(false);
    setEventForm(f => ({ ...f, name: '', location: '', notes: '' }));
  }, [eventForm]);

  // ── Calendar computed values ──────────────────────────────────────────────
  const today       = new Date();
  const calYear     = calendarDate.getFullYear();
  const calMonth    = calendarDate.getMonth();
  const daysInMonth = getDaysInMonth(calYear, calMonth);
  const firstDay    = getFirstDayOfMonth(calYear, calMonth);
  const todayEvents = reminders.filter(r => {
    if (!r.dueDate) return false;
    const d = new Date(r.dueDate);
    return d.getFullYear() === selectedDate.getFullYear() && d.getMonth() === selectedDate.getMonth() && d.getDate() === selectedDate.getDate();
  });
  const todayCalendarEvents = calendarEvents.filter(e => {
    if (!e.date) return false;
    // Parse as local time (not UTC) to avoid timezone-off-by-one-day bug
    const [y, m, d] = e.date.split('-').map(Number);
    return y === selectedDate.getFullYear() && (m - 1) === selectedDate.getMonth() && d === selectedDate.getDate();
  });
  const isToday = (d: Date) => d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
  const selectedLabel = isToday(selectedDate)
    ? `${selectedDate.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })} — Today`
    : selectedDate.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' });

  // ── Loading ───────────────────────────────────────────────────────────────
  if (checkingAuth) return (
    <div className="loading-screen">
      <div className="loading-spinner" />
      <span>Loading…</span>
    </div>
  );

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="app-shell">

      {!isLocalDev && AuthModalComponent && (
        <AuthModalComponent
          visible={showAuthModal}
          onDismiss={() => setShowAuthModal(false)}
          onSuccess={handleAuthSuccess}
        />
      )}

      {/* ── Sidebar ── */}
      <aside className="sidebar">
        <button className={`sidebar-icon${activePanel === null ? ' active' : ''}`} title="Home" onClick={() => setActivePanel(null)}>⌂</button>
        <button className="sidebar-icon" title="History">↺</button>
        <button className="sidebar-icon" title="Ideas">💡</button>
        <button className={`sidebar-icon${activePanel === 'reminders' ? ' active' : ''}`} title="Reminders & Tasks" onClick={() => togglePanel('reminders')}>
          ☑
          {reminders.filter(r => !r.completed).length > 0 && (
            <span className="sidebar-badge">{reminders.filter(r => !r.completed).length}</span>
          )}
        </button>
        <button className={`sidebar-icon${activePanel === 'calendar' ? ' active' : ''}`} title="Calendar" onClick={() => togglePanel('calendar')}>📅</button>
        <div className="sidebar-divider" />
        <button className="sidebar-icon" title="More">···</button>
      </aside>

      {/* ── Reminders Panel ── */}
      {activePanel === 'reminders' && (
        <div className="side-panel">
          <div className="side-panel-header">
            <div>
              <div className="side-panel-title">Reminders &amp; Tasks</div>
              <div className="side-panel-subtitle">{reminders.filter(r => !r.completed).length} item{reminders.filter(r => !r.completed).length !== 1 ? 's' : ''}</div>
            </div>
            <button className="side-panel-close" onClick={() => setActivePanel(null)}>×</button>
          </div>

          <div className="side-panel-body">
            <div className="reminder-toggle-row">
              <span className="reminder-toggle-label">Show Completed</span>
              <button className={`toggle-btn${showCompleted ? ' on' : ''}`} onClick={() => setShowCompleted(p => !p)}>
                <span className="toggle-thumb" />
              </button>
            </div>

            <div className="reminder-list">
              {reminders.filter(r => showCompleted || !r.completed).map(r => (
                <div key={r.id} className={`reminder-item${r.completed ? ' done' : ''}`}>
                  <button className="reminder-check" onClick={() => toggleReminder(r.id)}>
                    {r.completed ? '✓' : ''}
                  </button>
                  <div className="reminder-content">
                    <span className="reminder-text">{r.text}</span>
                    {r.dueDate && <span className="reminder-due">{new Date(r.dueDate).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}</span>}
                  </div>
                  <button className="reminder-delete" onClick={() => deleteReminder(r.id)}>×</button>
                </div>
              ))}
            </div>

            <div className="add-reminder-row">
              <input
                className="add-reminder-input"
                placeholder="+ Add Item"
                value={newReminderText}
                onChange={e => setNewReminderText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') addReminder(); }}
              />
            </div>
          </div>
        </div>
      )}

      {/* ── Calendar Panel ── */}
      {activePanel === 'calendar' && (
        <div className="side-panel">
          <div className="side-panel-header">
            {showAddEvent ? (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <button className="side-panel-back" onClick={() => setShowAddEvent(false)}>‹</button>
                  <div className="side-panel-title">Add Event</div>
                </div>
                <button className="side-panel-close" onClick={() => { setActivePanel(null); setShowAddEvent(false); }}>×</button>
              </>
            ) : (
              <>
                <div className="side-panel-title">Calendar</div>
                <button className="side-panel-close" onClick={() => setActivePanel(null)}>×</button>
              </>
            )}
          </div>

          <div className="side-panel-body">
            {showAddEvent ? (
              /* ── Add Event Form ── */
              <div className="add-event-form">
                <div className="event-field">
                  <input
                    className="event-input"
                    placeholder="What's happening?"
                    value={eventForm.name}
                    onChange={e => setEventForm(f => ({ ...f, name: e.target.value }))}
                    autoFocus
                  />
                </div>

                <div className="event-field event-allday-row">
                  <label className="event-label">All Day Event</label>
                  <button className={`toggle-btn${eventForm.allDay ? ' on' : ''}`} onClick={() => setEventForm(f => ({ ...f, allDay: !f.allDay }))}>
                    <span className="toggle-thumb" />
                  </button>
                </div>

                <div className="event-field">
                  <label className="event-label">Start</label>
                  <div className="event-datetime-row">
                    {!eventForm.allDay && (
                      <input className="event-time-input" value={eventForm.startTime} onChange={e => setEventForm(f => ({ ...f, startTime: e.target.value }))} />
                    )}
                    <input className="event-date-input" value={eventForm.startDate} onChange={e => setEventForm(f => ({ ...f, startDate: e.target.value }))} />
                  </div>
                </div>

                <div className="event-field">
                  <label className="event-label">End</label>
                  <div className="event-datetime-row">
                    {!eventForm.allDay && (
                      <input className="event-time-input" value={eventForm.endTime} onChange={e => setEventForm(f => ({ ...f, endTime: e.target.value }))} />
                    )}
                    <input className="event-date-input" value={eventForm.endDate} onChange={e => setEventForm(f => ({ ...f, endDate: e.target.value }))} />
                  </div>
                </div>

                <div className="event-field">
                  <label className="event-label">Calendar</label>
                  <div className="event-calendar-select">
                    <span>{userInitial.toLowerCase()}@amazon.com</span>
                    <span>▾</span>
                  </div>
                </div>

                <div className="event-field">
                  <input className="event-input" placeholder="📍  Add Location" value={eventForm.location} onChange={e => setEventForm(f => ({ ...f, location: e.target.value }))} />
                </div>

                <div className="event-field">
                  <textarea className="event-notes" placeholder="Add notes" value={eventForm.notes} onChange={e => setEventForm(f => ({ ...f, notes: e.target.value }))} rows={3} />
                </div>

                <button className="add-event-save-btn" onClick={saveEvent} disabled={!eventForm.name.trim()}>
                  Save Event
                </button>
              </div>
            ) : (
              <>
            <button className="add-event-btn" onClick={() => setShowAddEvent(true)}>
              + Add Event
            </button>

            <div className="cal-nav">
              <button className="cal-nav-btn" onClick={() => setCalendarDate(new Date(calYear, calMonth - 1, 1))}>‹</button>
              <span className="cal-month-label">{MONTHS[calMonth]} {calYear}</span>
              <button className="cal-nav-btn" onClick={() => setCalendarDate(new Date(calYear, calMonth + 1, 1))}>›</button>
              <button className="cal-today-btn" onClick={() => setCalendarDate(new Date())}>Today</button>
            </div>

            <div className="cal-grid">
              {DAYS.map(d => <div key={d} className="cal-day-header">{d}</div>)}
              {Array.from({ length: firstDay }).map((_, i) => <div key={`e${i}`} />)}
              {Array.from({ length: daysInMonth }).map((_, i) => {
                const day = i + 1;
                const isToday = day === today.getDate() && calMonth === today.getMonth() && calYear === today.getFullYear();
                const hasEvent = reminders.some(r => {
                  if (!r.dueDate) return false;
                  const d = new Date(r.dueDate);
                  return d.getDate() === day && d.getMonth() === calMonth && d.getFullYear() === calYear;
                }) || calendarEvents.some(e => {
                  if (!e.date) return false;
                  const [ey, em, ed] = e.date.split('-').map(Number);
                  return ed === day && (em - 1) === calMonth && ey === calYear;
                });
                const isSelected = day === selectedDate.getDate() && calMonth === selectedDate.getMonth() && calYear === selectedDate.getFullYear();
                return (
                  <div
                    key={day}
                    className={`cal-day${isToday ? ' today' : ''}${hasEvent ? ' has-event' : ''}${isSelected && !isToday ? ' selected' : ''}`}
                    onClick={() => setSelectedDate(new Date(calYear, calMonth, day))}
                    style={{ cursor: 'pointer' }}
                  >
                    {day}
                    {hasEvent && <span className="cal-dot" />}
                  </div>
                );
              })}
            </div>

            <div className="cal-events">
              <div className="cal-events-header">{selectedLabel}</div>
              {todayEvents.length === 0 && todayCalendarEvents.length === 0 ? (
                <div className="cal-no-events">No events</div>
              ) : (
                <>
                  {todayCalendarEvents.map(e => (
                    <div key={e.id} className="cal-event-item" style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                        <div className="cal-event-bar" style={{ background: '#0073bb' }} />
                        <div>
                          <div className="cal-event-title">{e.title}</div>
                          {e.time && <div className="cal-event-time">{e.time}</div>}
                          {e.location && <div className="cal-event-time">📍 {e.location}</div>}
                        </div>
                      </div>
                      <button className="reminder-delete" onClick={() => deleteCalendarEvent(e.id)}>×</button>
                    </div>
                  ))}
                  {todayEvents.map(r => (
                    <div key={r.id} className="cal-event-item">
                      <div className="cal-event-bar" />
                      <div>
                        <div className="cal-event-title">{r.text}</div>
                        {r.dueDate && <div className="cal-event-time">{new Date(r.dueDate).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}</div>}
                      </div>
                    </div>
                  ))}
                </>
              )}
            </div>
            </>
            )}
          </div>
        </div>
      )}

      {/* ── Main column ── */}
      <div className={`main-content${voiceAgent.conversationHistory.length === 0 ? ' initial' : ''}`}>

        {/* Header */}
        <header className="app-header">
          <div className="alexa-logo">
            <span className="alexa-wordmark">alexa<sup>+</sup></span>
            <AlexaSmile />
          </div>
          <div className="user-avatar">{userInitial}</div>
        </header>

        {/* ── Conversation area — scrollable, full width, no box ── */}
        <div className="conv-area" ref={chatContainerRef}>

          {/* Error */}
          {(voiceAgent.error || error) && (
            <div className="error-alert">
              <span>{voiceAgent.error || error}</span>
              <button className="error-dismiss" onClick={() => { voiceAgent.clearError(); setError(''); }}>×</button>
            </div>
          )}

          {/* Messages spread across full width */}
          {voiceAgent.conversationHistory.map((turn, i) => {
            const isLast = i === voiceAgent.conversationHistory.length - 1;
            const showTyping = turn.role === 'assistant' && isLast && voiceAgent.isSpeaking && !turn.transcript;
            return (
              <div key={i} className={`conv-msg ${turn.role}`}>
                {turn.role === 'assistant' && (
                  <div className="conv-avatar"><AlexaSwirl size={20} /></div>
                )}
                <div className="conv-bubble">
                  {showTyping ? (
                    <div className="typing-dots">
                      <div className="typing-dot" /><div className="typing-dot" /><div className="typing-dot" />
                    </div>
                  ) : turn.transcript}
                </div>
                {turn.role === 'user' && (
                  <div className="conv-avatar user">{userInitial}</div>
                )}
              </div>
            );
          })}
        </div>

        {/* ── Bottom bar — pinned at bottom ── */}
        <div className="bottom-bar">

          {/* Greeting — only when no conversation, sits above pill */}
          {voiceAgent.conversationHistory.length === 0 && (
            <section className="conv-greeting">
              <h1 className="hero-greeting">
                {getGreeting()}, <strong>Mitra</strong>, how can I help?
              </h1>
            </section>
          )}

          {/* Chips — only shown when no conversation yet */}
          {voiceAgent.conversationHistory.length === 0 && (
            <div className="chips">
              {CHIPS.map(({ label, text }) => (
                <button key={label} className="chip" disabled={!user} onClick={() => handleChipClick(text)}>
                  {label}
                </button>
              ))}
            </div>
          )}

          {/* Voice pill */}
          <div className="voice-pill-wrapper">
            <div
              className={`voice-pill${isActive ? ` ${pillState}` : ''}`}
              onClick={!isActive ? handlePillClick : undefined}
              role={!isActive ? 'button' : undefined}
              aria-label="Start voice conversation"
            >
              <AlexaSwirl size={28} />

              {voiceAgent.isConnected ? (
                <>
                  {showWaveform && (
                    <div className="pill-waveform-mini">
                      {Array.from({ length: 5 }).map((_, i) => <div key={i} className="wave-bar" />)}
                    </div>
                  )}
                  <input
                    ref={pillInputRef}
                    className="pill-input"
                    placeholder={showWaveform ? '' : 'Ask Alexa…'}
                    value={textInput}
                    onChange={e => setTextInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleSendText(); }}
                    onClick={e => e.stopPropagation()}
                    autoFocus
                  />
                </>
              ) : (
                <span className="pill-placeholder">
                  {pillState === 'connecting' ? 'Connecting…' : 'Ask Alexa'}
                </span>
              )}

              <div className="pill-actions" onClick={e => e.stopPropagation()}>
                {voiceAgent.isConnected && (
                  <>
                    {(pillState === 'listening' || pillState === 'speaking' || pillState === 'paused') && (
                      <button className="pill-btn" onClick={() => voiceAgent.togglePause()} title={voiceAgent.isPaused ? 'Resume' : 'Pause'}>
                        {voiceAgent.isPaused ? '▶' : '⏸'}
                      </button>
                    )}
                    {textInput.trim() && (
                      <button className="pill-btn send" onClick={handleSendText} title="Send">↑</button>
                    )}
                    <button className="pill-btn stop" onClick={handleStop} title="End conversation">■</button>
                  </>
                )}
                {!voiceAgent.isConnected && (
                  <button className="pill-btn" onClick={handlePillClick} disabled={!user || isConnecting} title="Start voice">
                    🎤
                  </button>
                )}
              </div>
            </div>

            {statusText && (
              <p className={`pill-status${pillState === 'speaking' ? ' speaking' : ''}`}>{statusText}</p>
            )}
          </div>

          <div className="powered-by">
            <span>Powered by Nova Sonic 2</span>
            <div className="powered-dot" />
            <span>Bee Pioneer</span>
            <div className="powered-dot" />
            <span>Amazon Bedrock</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
