# LOOMCYCLE AI

A Flask-based sustainable textile reuse website. It includes account registration/login, image upload with optional AI-assisted visual fabric estimation and basic image metrics, reuse recommendations, tutorials, a community gallery, a personal material-reuse log, an artwork concept prompt generator, an upcycled product showcase and Loom Bot with optional OpenAI-powered responses.

## 1. Requirements

- Python 3.10 or newer
- Internet connection for the Google Fonts used by the interface (the site still works if fonts cannot load)

## 2. Project structure

```text
LOOMCYCLE_AI/
├── app.py
├── requirements.txt
├── README.md
├── .env.example          # optional server-side AI configuration template
├── loomcycle.db          # created automatically on first run
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   ├── app.js
│   └── images/             # hero textile + upcycled product showcase
└── uploads/              # uploaded images are stored here
```

## 3. Run on Windows

Open Command Prompt or the VS Code terminal and move into the project folder:

```bash
cd path\to\LOOMCYCLE_AI
```

Create a virtual environment:

```bash
py -m venv .venv
```

Activate it:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Start the app:

```bash
python app.py
```

Open this address in your browser:

```text
http://127.0.0.1:5000
```

To verify the backend, open:

```text
http://127.0.0.1:5000/api/health
```

Expected response:

```json
{"service":"LOOMCYCLE AI","status":"ok"}
```

## 4. Main API routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Website |
| GET | `/api/health` | Health check |
| POST | `/api/register` | Create an account |
| POST | `/api/login` | Log in |
| POST | `/api/logout` | Log out |
| GET | `/api/me` | Current session |
| POST | `/api/analyze` | Upload a fabric image; return basic image metrics and optional AI visual estimate |
| POST | `/api/recommendations` | Return reuse ideas |
| GET | `/api/tutorials` | Tutorial list |
| POST | `/api/artwork/prompt` | Create a text concept prompt |
| GET | `/api/gallery` | Community gallery |
| POST | `/api/gallery` | Add a gallery item (login required) |
| POST | `/api/sustainability` | Save a material reuse record (login required) |
| GET | `/api/sustainability/history` | Personal reuse history (login required) |
| GET | `/api/dashboard` | Personal dashboard counts (login required) |
| POST | `/api/loom-bot` | Ask the rule-based Loom Bot |

## 5. Important implementation notes

- Fabric analysis always calculates average RGB colour, brightness, contrast and a simple edge score using Pillow/NumPy. These measurements do not identify fabric or fibre.
- When `OPENAI_API_KEY` is configured, `/api/analyze` sends a resized version of the uploaded image to the configured OpenAI vision model (`OPENAI_VISION_MODEL`, or `OPENAI_MODEL` as a fallback) and returns a cautious visual estimate, visible features and project suggestions. The API key stays on the Flask server.
- AI output is an image-based estimate, not a calibrated probability or laboratory fibre test. It cannot reliably determine exact fibre percentages, blends, stretch, weight or fabric strength from one photo. Check the care label or use an appropriate textile test.
- If no API key is configured, the page explicitly says the AI fabric type was not identified and shows only basic metrics plus generic reuse ideas. It does not pretend those metrics classify the fabric.
- The AI image request may incur API charges. Do not upload private images. Existing analysis records receive an additive database column; the app does not delete existing records.
- The artwork endpoint returns a **text prompt only**. It does not render an image.
- Loom Bot uses a small set of keyword-based responses. It is not connected to an LLM or external AI API.
- Sustainability records count reused textile mass and pieces. The app does **not** calculate carbon or water savings.
- The gallery and uploaded image URLs are public in this starter implementation. Do not upload private or sensitive images.

## 6. Before public deployment

This project is a functional college-project starter, not a hardened production service. Before publishing it for real users:

1. Set a long random `SECRET_KEY` environment variable. Never use the development fallback in a public deployment.
2. Add CSRF protection, login rate limiting, email verification and password reset.
3. Restrict and moderate public uploads; consider virus scanning and image re-encoding.
4. Use PostgreSQL or another persistent database for deployment.
5. Store uploaded images in persistent object storage or a persistent disk.
6. Configure HTTPS and secure cookie settings.
7. Add backups and privacy/retention rules.

A basic Render start command is:

```bash
gunicorn --workers 1 --bind 0.0.0.0:$PORT app:app
```

The SQLite database and `uploads/` directory are local filesystem storage. On hosts with ephemeral filesystems, they can be lost during restarts or redeployments unless persistent storage is configured.

## 7. Troubleshooting

**`ModuleNotFoundError: No module named 'flask'`**

Activate the virtual environment, then run:

```bash
python -m pip install -r requirements.txt
```

Make sure VS Code is using the same Python interpreter as the terminal.

**Port 5000 is already in use**

Stop the other process using port 5000, or run with another port:

```bash
set PORT=5001
python app.py
```

Then visit `http://127.0.0.1:5001`.

**Image upload fails**

Use PNG, JPG, JPEG or WEBP and keep the upload under 8 MB.

## 8. Website refresh and reuse-log fix

This version includes a refreshed textile-inspired colour system, a real fabric photo in the hero, an upcycled product showcase, and a direct link to Bing Image Creator from the artwork prompt panel. The generated concept prompt must be copied and pasted into the external image creator; the external site does not receive the prompt automatically.

The reuse form now captures its form element before awaiting the server response. This fixes the JavaScript `Cannot read properties of null (reading 'reset')` error that occurred after the server had already saved a record. The form also blocks repeated submissions while a save is in progress. Existing database records are preserved; the page begins with a zero preview and displays the totals after a new successful save.

## 9. Optional AI-powered Loom Bot

Loom Bot works in two modes:

- **Textile knowledge mode:** built-in practical reuse guidance works without an API key.
- **AI mode:** if an OpenAI API key is configured on the Flask server, Loom Bot sends the question to the OpenAI Responses API and returns a generated answer.

To enable AI mode on Windows:

1. Create an API key in the OpenAI API platform. API usage is billed separately from a ChatGPT subscription and may incur charges.
2. In your project folder, make a copy of `.env.example` and name the copy `.env`.
3. Open `.env` in VS Code and replace `your_api_key_here` with your own API key. Keep this file private and never upload it to GitHub or include it in a shared ZIP.
4. Keep `OPENAI_MODEL=gpt-5.5`, or change it to a model available to your API account.
5. Save `.env`, restart Flask with `python app.py`, and ask Loom Bot a question. Its response label will show whether AI mode or built-in textile knowledge mode answered.
If the key is missing or the AI service cannot be reached, Loom Bot falls back to its built-in textile guidance. Keep API keys private and do not upload them to GitHub or Firebase frontend files.

## 10. Product images

Product showcase images are stored in `static/images/`. The hero uses a fabric photograph already included in the project uploads. The four product example images are illustrative AI-generated examples of possible upcycled products, not photos of items manufactured or sold by LOOMCYCLE AI.


## 8. Enable AI fabric visual estimates

1. Copy `.env.example` to `.env` in the same folder as `app.py` (if `.env` already exists, edit it rather than replacing it).
2. Put your own API key after `OPENAI_API_KEY=`. Keep `.env` private and never upload it to GitHub.
3. Set `OPENAI_VISION_MODEL` to an image-capable model available to your API account. The default is `gpt-5.5`; you can change it if your account uses a different supported model.
4. Stop Flask with `Ctrl+C`, then run `python app.py` again.
5. Upload a clear close-up of one fabric, preferably with a plain background and good lighting.

The first analysis may send the uploaded image to OpenAI. API usage is billed separately according to your API account.
