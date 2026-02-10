import os
import json
import secrets
from fastapi import FastAPI, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()
security = HTTPBasic()

# Verzeichnisse
templates = Jinja2Templates(directory="templates")
PROMPTS_FILE = "prompts.json"

# --- SICHERHEIT ---
def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.getenv("TOOL_USERNAME", "admin")
    correct_password = os.getenv("TOOL_PASSWORD", "moderation2024")
    if not (secrets.compare_digest(credentials.username, correct_username) and
            secrets.compare_digest(credentials.password, correct_password)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Zugriff verweigert",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- PROMPT LOGIK ---
def load_prompts():
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_prompts(data):
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# --- ROUTES ---
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
    # Wähle den richtigen System Prompt
    if category == "wdr2_oneliner":
        system_msg = prompts["wdr2_oneliner"]["standard"]
    else:
        system_msg = prompts[category][mode]

    user_msg = f"Inhalt:\n{content}"
    if extra:
        user_msg += f"\n\nZusätzliche Anweisung: {extra}"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.7
        )
        return {"result": response.choices[0].message.content}
    except Exception as e:
        return {"result": f"Fehler: {str(e)}"}

@app.post("/save_settings")
async def update_settings(request: Request, username: str = Depends(get_current_username)):
    new_prompts = await request.json()
    save_prompts(new_prompts)
    return {"status": "success"}
