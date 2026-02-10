import os
import json
import secrets
import asyncio
from fastapi import FastAPI, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv
from openai import OpenAI
import google.generativeai as genai

# 1. Umgebungsvariablen laden
load_dotenv()

# --- CLIENTS SETUP ---
# OpenAI
openai_key = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=openai_key) if openai_key else None

# Google Gemini
google_key = os.getenv("GOOGLE_API_KEY")
if google_key:
    genai.configure(api_key=google_key)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash') # Schnelles, gutes Modell
else:
    gemini_model = None

app = FastAPI()
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")
PROMPTS_FILE = "prompts.json"

# --- HELFER: Prompts laden/speichern ---
def load_prompts():
    if not os.path.exists(PROMPTS_FILE):
        return {}
    try:
        with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_prompts(data):
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- SICHERHEIT ---
def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("TOOL_USERNAME", "admin")
    correct_password = os.getenv("TOOL_PASSWORD", "passwort")
    if not (secrets.compare_digest(credentials.username, correct_username) and
            secrets.compare_digest(credentials.password, correct_password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Zugriff verweigert",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- ROUTEN ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, username: str = Depends(get_current_username)):
    prompts = load_prompts()
    return templates.TemplateResponse("index.html", {"request": request, "prompts": prompts})

@app.post("/generate")
async def generate(
    category: str = Form(...),
    mode: str = Form(...),
    content: str = Form(...),
    extra: str = Form(None),
    username: str = Depends(get_current_username)
):
    prompts = load_prompts()
    
    # Prompt auswählen
    try:
        if category == "wdr2_oneliner":
            system_msg = prompts["wdr2_oneliner"]["standard"]
        else:
            system_msg = prompts[category][mode]
    except KeyError:
        return {"result": "Fehler: Prompt-Kategorie nicht gefunden."}

    user_msg = f"Inhalt:\n{content}"
    if extra and extra.strip():
        user_msg += f"\n\nZusatzanweisung: {extra}"

    # --- LOGIK: Soll Gemini dazu geschaltet werden? ---
    # Wir nutzen Gemini zusätzlich NUR bei WDR2 One-Linern (Comedy)
    use_gemini = (category == "wdr2_oneliner") and (gemini_model is not None)

    results = []

    # 1. OpenAI Abfrage
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg}
                ],
                temperature=0.7
            )
            gpt_text = response.choices[0].message.content
            results.append(f"🤖 --- GPT-4o VORSCHLÄGE ---\n\n{gpt_text}")
        except Exception as e:
            results.append(f"GPT Fehler: {str(e)}")
    
    # 2. Gemini Abfrage (Parallel möglich, hier sequenziell der Einfachheit halber)
    if use_gemini:
        try:
            # Gemini braucht den System-Prompt oft im Context oder als erste Nachricht
            full_prompt = f"SYSTEM ANWEISUNG:\n{system_msg}\n\nUSER ANFRAGE:\n{user_msg}"
            response = gemini_model.generate_content(full_prompt)
            gemini_text = response.text
            results.append(f"\n\n✨ --- GEMINI VORSCHLÄGE ---\n\n{gemini_text}")
        except Exception as e:
            results.append(f"\n\nGemini Fehler: {str(e)}")

    if not results:
        return {"result": "Keine KI-Modelle konfiguriert (API Keys fehlen)."}

    return {"result": "".join(results)}

@app.post("/save_settings")
async def update_settings(request: Request, username: str = Depends(get_current_username)):
    try:
        new_prompts = await request.json()
        save_prompts(new_prompts)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}