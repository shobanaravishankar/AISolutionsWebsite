# AI Solutions / JARVIS — local review website

Local review only. No public release, push, domain purchase or outbound email. Original specification incorporates Claude’s accepted design/copy recommendations; the later God Mode redesign and live-agent addition follow subsequent user direction and are not represented as newly approved by Claude.

## Run
Python 3.11+, standard library only. From this directory run `python server.py`, then open http://127.0.0.1:8765/ . Owner inbox: /owner. Choose your own password on first setup (12+ characters); it is hashed. Sessions expire after eight hours or server restart. This is a loopback development service, not an internet deployment architecture.

The former static http.server command and direct index.html opening cannot handle chat, enquiries or owner access.

## Connect JARVIS
The backend expects the separate JARVIS live-agent/ wrapper at http://127.0.0.1:8766. Set JARVIS_AGENT_TOKEN_FILE to a UTF-8 file containing the same random token (32+ characters) in both processes, or set JARVIS_AGENT_TOKEN in their environments. Keep tokens outside source control, dist/, browser code and URLs.

The wrapper lives inside an authorized JARVIS checkout, alongside jarvis_voice/. It imports existing LocalConversation and OllamaLocalProvider. No JARVIS core files are changed or packaged in this website. The JARVIS runtime needs an approved model installed and Ollama running on its own loopback port11434. This computer currently has no running model service. Until available, the panel reports the unavailable model and never substitutes a scripted AI reply. A different runtime computer needs an agreed local setup there; public/remote URLs are deliberately rejected. No model installation or external exposure occurs automatically.

GET /api/status distinguishes wrapper connectivity from model readiness. POST /api/command forwards bounded recent history. Only successful answers enter conversation context, which survives section changes and dismissal but resets on refresh or New conversation.

## Enquiries and review
- SQLite is outside this checkout: %LOCALAPPDATA%/AISolutionsWebsite/website.sqlite3. JARVIS_DATA_DIR overrides its directory.
- Analytics require opt-in: referrer domain only, no IP storage, fingerprinting or location. Visits are random tab sessions, not unique people.
- AI requests require processing consent. Topic/outcome metadata is retained; raw question text only if explicitly shared. History and model replies are not stored in the owner inbox.
- Enquiries require storage consent. Contact details are optional, with a separate follow-up preference. No marketing subscription.
- Records expire after 90 days when the service handles requests. Owner deletion removes individual records; separately created backups are outside that mechanism.
- Owner can inspect counts/records, save drafts/status/notes, copy a draft and delete records. Drafts never send automatically.
- Optional SMTP adapter is disabled unless explicitly configured/enabled in server environment. Review UI offers drafts only. No real mail was sent or tested. Saving a business address does not provision a mailbox.

## Checks
Run `python -B -m unittest test_server`. Five tests use disposable databases and dummy contacts, covering access/origin gates, persistence, context forwarding, opt-out, consent, analytics minimization, retention and email gates. No external model/mail calls.

See ../LIVE-AGENT-VERIFICATION.md for evidence and remaining live acceptance work. Contract responses do not prove model quality.

## Files
Only dist/ is publicly served. server.py provides local APIs; test_server.py verifies them. Credentials, databases, private JARVIS implementation and owner records must never accompany the website archive.

## Planning record and continuation
Start future work with [the editable project plan](docs/AI-Solutions-Website-and-AI-Guide-Plan.md), its [PDF snapshot](docs/AI-Solutions-Website-and-AI-Guide-Plan.pdf), and [project context](docs/PROJECT-CONTEXT.md). They are the exact reviewed Version1.0 planning baseline from September28,2026. The 80 open tasks are a roadmap, not a claim of completion. Current implementation and runtime evidence are summarized in [the implementation handoff](docs/IMPLEMENTATION-HANDOFF.md). Check-in is separately authorized; public deployment remains unapproved.
