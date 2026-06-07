import requests
import json

def call_ollama(system: str, user: str, model: str = "phi3") -> str:
    url = "http://localhost:11434/api/generate"
    payload = {
        "model": model,
        "prompt": user,
        "system": system,
        "stream": False,
        "options": {
            "temperature": 0.0
        }
    }

    print(f"\n[OLLAMA DEBUG] Running model '{model}'...")
    try:
        response = requests.post(url, json=payload, timeout=None)
        if response.status_code != 200:
            return ""
        res_json = response.json()
        return res_json.get("response", "").strip()
    except Exception as e:
        print(f"[OLLAMA DEBUG] Connection error: {str(e)}")
        return ""

def explain_match(patient: dict, match_result: dict) -> str:
    if not patient or not match_result:
        return "• Patient profile or match data is unavailable for evaluation."

    system = (
        "You are a clinical decision support assistant for HemoGrid in Hyderabad, India.\n"
        "Your absolute ONLY job is to write a short, professional bulleted summary explaining the patient matching results to a doctor.\n"
        "CRITICAL NO-CODE RULES:\n"
        "- NEVER write Python code, JSON blocks, functions, loops, variables, or backticks (```).\n"
        "- Do NOT explain the underlying programming logic, filtering code, or data structures.\n"
        "- Write only in plain, human, professional clinical English phrases.\n"
        "CLINICAL DIRECTIONS:\n"
        "- State why the top units are ranked where they are based on their match percentage.\n"
        "- Briefly summarize if any units were excluded due to antibody/ABO compatibility.\n"
        "Output format: 2 to 4 clean, short bullet points using standard text dashes (-) or stars (*)."
    )
    user = f"Patient Profile: {patient}\nCalculated Match Data: {match_result}"
    return call_ollama(system, user)

def generate_issue_summary(patient: dict, bag: dict, bank_name: str) -> str:
    if not patient or not bag:
        return "Unit issued successfully."

    system = (
        "You are a clinical documentation clerk for HemoGrid in Hyderabad.\n"
        "Write exactly one short, single-sentence activity log entry for a blood unit transaction.\n"
        "CRITICAL RULES:\n"
        "- NEVER write programming code, backticks, or script terms.\n"
        "- State precisely which bag ID was issued, which bank it originated from, and which patient ID received it.\n"
        "Example format: 'Unit BAG0001234 issued from BNK0012 to Patient PAT-00123 successfully.'"
    )
    user = f"Patient: {patient}\nBag: {bag}\nBank: {bank_name}"
    return call_ollama(system, user)
