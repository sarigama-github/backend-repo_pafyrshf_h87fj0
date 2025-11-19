import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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


# -----------------------------
# Nettolohn-Berechnung (CH/FL)
# -----------------------------
class NetCalcRequest(BaseModel):
    gross_chf: float = Field(..., gt=0, description="Bruttolohn in CHF/Monat")
    work_ch: str = Field(..., description="Arbeitsort: Kanton in CH oder Liechtenstein")
    residence_at: str = Field(..., description="Wohnsitz in Österreich (Bundesland)")
    age: Optional[int] = Field(None, ge=16, le=70)
    marital: Optional[str] = Field("single", description="single|married")
    children_count: Optional[int] = Field(0, ge=0, le=10)
    exchange_rate: Optional[float] = Field(0.95, gt=0, description="CHF→EUR Kurs")

class NetCalcResult(BaseModel):
    net_chf: float
    net_eur: float
    total_deductions: float
    breakdown: dict
    assumptions: dict


def estimate_bvg_rate(age: Optional[int]) -> float:
    # Very rough guideline by age band
    if age is None:
        return 0.07
    if age < 25:
        return 0.05
    if age < 35:
        return 0.07
    if age < 45:
        return 0.09
    if age < 55:
        return 0.11
    return 0.12


def estimate_quellensteuer_rate(work_ch_lower: str, marital: str, children_count: int) -> float:
    # Simplified non-resident withholding tax heuristic by canton
    base = 0.02  # default 2%
    if any(k in work_ch_lower for k in ["zh", "zürich", "zuerich"]):
        base = 0.045
    elif any(k in work_ch_lower for k in ["bs", "basel"]):
        base = 0.043
    elif any(k in work_ch_lower for k in ["ge", "genf"]):
        base = 0.05
    elif "liechtenstein" in work_ch_lower or work_ch_lower.strip() in ["fl", "li"]:
        base = 0.012  # FL: andere Logik – hier konservativ klein

    # Family relief (very rough): married -0.4pp, each kid -0.2pp (down to 0)
    relief = (0.004 if marital == "married" else 0.0) + 0.002 * min(3, children_count)
    return max(0.0, base - relief)


@app.post("/api/calc/net", response_model=NetCalcResult)
def calc_net(req: NetCalcRequest):
    try:
        gross = float(req.gross_chf)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid gross_chf")

    work = (req.work_ch or "").lower().strip()

    # Social security (employee part) – very rough, monthly
    ahv_iv_eo = gross * 0.053  # 5.3%
    alv = min(gross, 148200/12) * 0.011  # 1.1% up to cap
    nbu = gross * 0.011  # Non-occupational accident
    bvg = gross * estimate_bvg_rate(req.age)  # pension, age-dependent

    # Health insurance is not deducted from payroll in CH, but show budget hint (optional)
    health_hint = 0.0

    # Quellensteuer (if applicable)
    qs_rate = estimate_quellensteuer_rate(work, req.marital or "single", int(req.children_count or 0))
    quellensteuer = gross * qs_rate

    deductions = {
        "AHV/IV/EO": round(ahv_iv_eo, 2),
        "ALV": round(alv, 2),
        "NBU": round(nbu, 2),
        "BVG (Pension)": round(bvg, 2),
        "Quellensteuer (vereinfachte Schätzung)": round(quellensteuer, 2),
        "Krankenkasse (Hinweis, nicht Lohnabzug)": round(health_hint, 2),
    }

    total_deductions = sum([ahv_iv_eo, alv, nbu, bvg, quellensteuer])
    net_chf = max(0.0, gross - total_deductions)
    net_eur = net_chf * float(req.exchange_rate or 0.95)

    assumptions = {
        "exchange_rate": req.exchange_rate,
        "bvg_rate": round(estimate_bvg_rate(req.age), 3),
        "qs_rate": round(qs_rate, 3),
        "disclaimer": "Unverbindliche Richtwerte. Individuelle Situation (Kasse, Alter, BVG-Plan, Steuerstatus) kann stark abweichen.",
    }

    return NetCalcResult(
        net_chf=round(net_chf, 2),
        net_eur=round(net_eur, 2),
        total_deductions=round(total_deductions, 2),
        breakdown=deductions,
        assumptions=assumptions,
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
