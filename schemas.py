"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal
from datetime import date

# Lead schema for Grenzgänger-Vergleichsrechner
class Lead(BaseModel):
    # Personal data
    first_name: str = Field(..., description="Vorname")
    last_name: str = Field(..., description="Nachname")
    email: EmailStr = Field(..., description="E-Mail")
    phone: Optional[str] = Field(None, description="Telefonnummer im Format +43...")
    birth_date: Optional[date] = Field(None, description="Geburtsdatum")
    residence_at: Literal["Vorarlberg", "Tirol", "andere"] = Field(..., description="Wohnort in Österreich")
    work_ch: str = Field(..., description="Arbeitsort (Kanton CH oder Liechtenstein)")

    # Consents
    consent_email: bool = Field(False, description="E-Mail Kontakt erlaubt")
    consent_whatsapp: bool = Field(False, description="WhatsApp/Telefon erlaubt")

    # Situation
    status: Literal["Neu-Grenzgänger", "Bereits Grenzgänger", "Plane Wechsel"] = Field(..., description="Status")
    family: Literal["Allein", "Mit Partner", "Mit Kindern"] = Field(..., description="Familiensituation")
    children_count: Optional[int] = Field(0, ge=0, le=10, description="Anzahl Kinder")
    health: Literal["Keine Vorerkrankungen", "Chronisch krank", "Bespreche ich persönlich"] = Field(..., description="Gesundheit")

    # Derived/analysis fields
    score: Optional[int] = Field(None, ge=0, le=100, description="Lead-Score 0-100")
    category: Optional[Literal["hot", "warm"]] = Field(None, description="Lead-Kategorie")
    recommended_model: Optional[Literal["CH", "AT", "Hybrid"]] = Field(None, description="Empfohlenes Modell")


# Example schemas (kept for reference)
class User(BaseModel):
    name: str
    email: str
    address: str
    age: Optional[int] = None
    is_active: bool = True

class Product(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    category: str
    in_stock: bool = True
