import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime

from database import db, create_document, get_documents
from schemas import Lead

app = FastAPI(title="Grenzgänger-Service API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "Grenzgänger-Service API running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response


# Simple scoring logic (no health data stored beyond category choice)
def compute_score_and_recommendation(lead: Lead):
    score = 50

    # Age factor (approx from birth_date)
    if lead.birth_date:
        years = (datetime.utcnow().date() - lead.birth_date).days // 365
        if years < 30:
            score += 10
        elif years > 55:
            score -= 5

    # Status intent
    if lead.status == "Neu-Grenzgänger":
        score += 15
    elif lead.status == "Plane Wechsel":
        score += 5

    # Family
    if lead.family == "Mit Kindern":
        score += 10
    elif lead.family == "Mit Partner":
        score += 5

    # Consents indicate contactability
    if lead.consent_email:
        score += 5
    if lead.consent_whatsapp:
        score += 10

    # Work canton rough heuristic for recommendation
    recommended_model = "Hybrid"
    canton = (lead.work_ch or "").lower()
    if "liechtenstein" in canton or "fl" == canton:
        recommended_model = "AT"
    elif any(k in canton for k in ["zh", "zürich", "zuerich", "basel", "bs", "ge", "genf"]):
        recommended_model = "CH"

    category = "hot" if score >= 75 else "warm"
    return max(0, min(100, score)), category, recommended_model


class LeadCreate(BaseModel):
    lead: Lead


@app.post("/api/lead")
def create_lead(payload: LeadCreate):
    lead = payload.lead
    score, category, recommended = compute_score_and_recommendation(lead)

    doc = lead.model_dump()
    doc.update({
        "score": score,
        "category": category,
        "recommended_model": recommended,
        "source": "web-form"
    })

    try:
        lead_id = create_document("lead", doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    return {"id": lead_id, "score": score, "category": category, "recommended_model": recommended}


@app.get("/api/leads")
def list_leads(limit: Optional[int] = 20):
    try:
        docs = get_documents("lead", {}, limit=limit)
        # Convert ObjectId to string for safe JSON
        for d in docs:
            if "_id" in d:
                d["_id"] = str(d["_id"])
        return {"items": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
