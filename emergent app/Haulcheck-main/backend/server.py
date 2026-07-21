from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Response, UploadFile, File, Query
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import secrets
import asyncio
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import List, Optional
import uuid
import jwt
import httpx
import requests
import json
import re
import base64
import tempfile
from passlib.context import CryptContext
from datetime import datetime, timezone, timedelta
from pdf_export import build_report_pdf, merge_pack, build_letter_pdf, build_pmi_sheet_pdf, concat_pdfs, build_weekly_walkaround_pdf
from tacho_engine import parse_ddd, parse_ddd_last_timestamp, detect_ddd_infringements, _DDD_EXTS
import reports

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

JWT_SECRET = os.environ['JWT_SECRET']
EMERGENT_LLM_KEY = os.environ['EMERGENT_LLM_KEY']
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------- Object storage ----------
STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
APP_NAME = "haulcheck"
storage_key = None
MIME_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "pdf": "application/pdf", "heic": "image/heic",
}


def init_storage():
    global storage_key
    if storage_key:
        return storage_key
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_LLM_KEY}, timeout=30)
    resp.raise_for_status()
    storage_key = resp.json()["storage_key"]
    return storage_key


def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = requests.put(f"{STORAGE_URL}/objects/{path}",
                        headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
    resp.raise_for_status()
    return resp.json()


def get_object(path: str):
    key = init_storage()
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


app = FastAPI()
api_router = APIRouter(prefix="/api")


# ---------- Helpers ----------
def now_iso():
    return datetime.now(timezone.utc).isoformat()


def days_until(date_str: Optional[str]) -> Optional[int]:
    if not date_str:
        return None
    try:
        d = datetime.fromisoformat(date_str).date()
        return (d - datetime.now(timezone.utc).date()).days
    except Exception:
        return None


def compliance_status(days: Optional[int], soon_days: int = 30) -> str:
    if days is None:
        return "unknown"
    if days < 0:
        return "expired"
    if days <= soon_days:
        return "due_soon"
    return "valid"


TACHO_SOON_DAYS = 7


# ---------- Models ----------
class RegisterInput(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "manager"


class LoginInput(BaseModel):
    email: EmailStr
    password: str


class InviteInput(BaseModel):
    email: EmailStr
    base_url: str = ""


class ForgotPasswordInput(BaseModel):
    email: EmailStr
    base_url: str = ""


class ResetPasswordInput(BaseModel):
    token: str
    password: str


class AcceptInviteInput(BaseModel):
    token: str
    name: str
    password: str


class User(BaseModel):
    user_id: str
    email: str
    name: str
    role: str = "manager"
    region: str = "UK"
    picture: Optional[str] = None


class Attachment(BaseModel):
    file_id: str
    filename: str = ""
    content_type: str = ""


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: f"alrt_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    type: str = "defect"  # walkaround_defect | defect_report | pmi_fail
    severity: str = "major"  # minor | major | safety_critical
    title: str = ""
    message: str = ""
    vehicle_reg: str = ""
    driver_name: str = ""
    link: str = ""
    read: bool = False
    dedup_key: str = ""
    created_at: str = Field(default_factory=now_iso)


class Vehicle(BaseModel):
    id: str = Field(default_factory=lambda: f"veh_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    registration: str
    make: str = ""
    model: str = ""
    type: str = "HGV"
    mot_due: Optional[str] = None
    service_due: Optional[str] = None
    tax_due: Optional[str] = None
    first_use_date: Optional[str] = None
    tacho_calibration_due: Optional[str] = None
    speed_limiter_due: Optional[str] = None
    vor: bool = False
    vor_reason: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)


class VehicleInput(BaseModel):
    registration: str
    make: str = ""
    model: str = ""
    type: str = "HGV"
    mot_due: Optional[str] = None
    service_due: Optional[str] = None
    tax_due: Optional[str] = None
    first_use_date: Optional[str] = None
    tacho_calibration_due: Optional[str] = None
    speed_limiter_due: Optional[str] = None
    vor: bool = False
    vor_reason: str = ""
    notes: str = ""


class Trailer(BaseModel):
    id: str = Field(default_factory=lambda: f"trl_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    trailer_number: str
    type: str = "Curtainsider"
    mot_due: Optional[str] = None
    service_due: Optional[str] = None
    vor: bool = False
    vor_reason: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)


class TrailerInput(BaseModel):
    trailer_number: str
    type: str = "Curtainsider"
    mot_due: Optional[str] = None
    service_due: Optional[str] = None
    vor: bool = False
    vor_reason: str = ""
    notes: str = ""


class Driver(BaseModel):
    id: str = Field(default_factory=lambda: f"drv_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    name: str
    licence_number: str = ""
    licence_expiry: Optional[str] = None
    cpc_expiry: Optional[str] = None
    tacho_card_expiry: Optional[str] = None
    licence_check_date: Optional[str] = None
    licence_check_code: str = ""
    penalty_points: int = 0
    licence_check_due: Optional[str] = None
    weekly_hours: float = 0.0
    max_weekly_hours: float = 56.0
    access_code: str = ""
    assigned_vehicle_reg: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)


class DriverInput(BaseModel):
    name: str
    licence_number: str = ""
    licence_expiry: Optional[str] = None
    cpc_expiry: Optional[str] = None
    tacho_card_expiry: Optional[str] = None
    licence_check_date: Optional[str] = None
    licence_check_code: str = ""
    penalty_points: int = 0
    licence_check_due: Optional[str] = None
    weekly_hours: float = 0.0
    max_weekly_hours: float = 56.0
    assigned_vehicle_reg: str = ""
    notes: str = ""


class DefectReport(BaseModel):
    id: str = Field(default_factory=lambda: f"def_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    vehicle_reg: str
    reported_by: str = ""
    category: str = "General"
    severity: str = "minor"
    description: str
    ai_summary: str = ""
    status: str = "open"
    defect_date: Optional[str] = None
    odometer: str = ""
    rectified_date: Optional[str] = None
    rectified_by: str = ""
    rectification_notes: str = ""
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class DefectRectifyInput(BaseModel):
    rectified_date: Optional[str] = None
    rectified_by: str = ""
    rectification_notes: str = ""


class DefectInput(BaseModel):
    vehicle_reg: str
    reported_by: str = ""
    category: str = "General"
    severity: str = "minor"
    description: str
    defect_date: Optional[str] = None
    odometer: str = ""
    attachments: List[Attachment] = []


class ComplianceDoc(BaseModel):
    id: str = Field(default_factory=lambda: f"doc_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    title: str
    doc_type: str = "Operator Licence"
    reference: str = ""
    expiry_date: Optional[str] = None
    notes: str = ""
    link_url: str = ""
    driver_id: str = ""
    driver_name: str = ""
    letter_data: Optional[dict] = None
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class DocInput(BaseModel):
    title: str
    doc_type: str = "Operator Licence"
    reference: str = ""
    expiry_date: Optional[str] = None
    notes: str = ""
    link_url: str = ""
    driver_id: str = ""
    driver_name: str = ""
    attachments: List[Attachment] = []


class LetterDraftInput(BaseModel):
    template: str = "Warning Letter"
    recipient_name: str = ""
    points: str = ""


class LetterGenerateInput(BaseModel):
    template: str = "Warning Letter"
    title: str = ""
    recipient_name: str = ""
    recipient_address: str = ""
    subject: str = ""
    body: str = ""
    signoff_name: str = ""
    signoff_role: str = ""


class TradeUnion(BaseModel):
    id: str = Field(default_factory=lambda: f"tu_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    union_name: str
    branch: str = ""
    rep_name: str = ""
    rep_role: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    membership_number: str = ""
    agreement_ref: str = ""
    notes: str = ""
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class TradeUnionInput(BaseModel):
    union_name: str
    branch: str = ""
    rep_name: str = ""
    rep_role: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    membership_number: str = ""
    agreement_ref: str = ""
    notes: str = ""
    attachments: List[Attachment] = []


class WebLink(BaseModel):
    id: str = Field(default_factory=lambda: f"link_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    title: str
    url: str
    category: str = "General"
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)


class WebLinkInput(BaseModel):
    title: str
    url: str
    category: str = "General"
    notes: str = ""


class FuelRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"fuel_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    vehicle_reg: str
    fill_type: str = "diesel"  # diesel | adblue
    fill_date: Optional[str] = None
    litres: float = 0
    cost: float = 0
    odometer: float = 0
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)


class FuelInput(BaseModel):
    vehicle_reg: str
    fill_type: str = "diesel"
    fill_date: Optional[str] = None
    litres: float = 0
    cost: float = 0
    odometer: float = 0
    notes: str = ""


class InsurancePolicy(BaseModel):
    id: str = Field(default_factory=lambda: f"ins_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    policy_type: str = "Motor — Truck"
    insurer: str = ""
    policy_number: str = ""
    start_date: Optional[str] = None
    expiry_date: Optional[str] = None
    cover_amount: str = ""
    notes: str = ""
    needs_review: bool = False
    ai_extracted: bool = False
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class InsuranceInput(BaseModel):
    policy_type: str = "Motor — Truck"
    insurer: str = ""
    policy_number: str = ""
    start_date: Optional[str] = None
    expiry_date: Optional[str] = None
    cover_amount: str = ""
    notes: str = ""
    needs_review: bool = False
    attachments: List[Attachment] = []


class TachoRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"tac_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    source_type: str = "Driver Card"  # Driver Card | Vehicle Unit
    reference: str = ""  # driver name or vehicle reg
    frequency_days: int = 28
    last_download: Optional[str] = None
    next_due: Optional[str] = None
    infringements: int = 0
    notes: str = ""
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class TachoInput(BaseModel):
    source_type: str = "Driver Card"
    reference: str = ""
    frequency_days: int = 28
    last_download: Optional[str] = None
    infringements: int = 0
    notes: str = ""
    attachments: List[Attachment] = []


class TachoParseInput(BaseModel):
    file_id: str


class TachoAnalyseInput(BaseModel):
    file_id: str
    driver_name: str = ""


class TachoAnalysis(BaseModel):
    id: str = Field(default_factory=lambda: f"tan_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    driver_name: str = ""
    period: str = ""
    summary: str = ""
    total_infringements: int = 0
    infringements: List[dict] = []
    confidence: float = 0.0
    file_id: str = ""
    created_at: str = Field(default_factory=now_iso)


class OperatorInput(BaseModel):
    company_name: str = ""
    company_number: str = ""
    operator_licence_number: str = ""
    licence_type: str = "Standard National"
    address: str = ""
    authorised_vehicles: int = 0
    authorised_trailers: int = 0
    tm_name: str = ""
    tm_cpc_number: str = ""
    tm_email: str = ""
    tm_phone: str = ""
    logo_file_id: str = ""
    notes: str = ""


class PMISchedule(BaseModel):
    id: str = Field(default_factory=lambda: f"pmi_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    vehicle_reg: str
    frequency_weeks: int = 6
    next_due: Optional[str] = None
    inspector: str = ""
    notes: str = ""
    created_at: str = Field(default_factory=now_iso)


class PMIInput(BaseModel):
    vehicle_reg: str
    frequency_weeks: int = 6
    next_due: Optional[str] = None
    inspector: str = ""
    notes: str = ""


class PMICompleteInput(BaseModel):
    inspection_date: str
    result: str = "pass"  # pass | advisory | fail

    @field_validator("inspection_date")
    @classmethod
    def _valid_date(cls, v):
        if v:
            try:
                y = int(str(v)[:4])
            except (ValueError, TypeError):
                raise ValueError("invalid inspection_date")
            if y < 2015 or y > datetime.now(timezone.utc).year + 1:
                raise ValueError("inspection_date year out of range")
        return v
    inspector: str = ""
    rectified_by: str = ""
    notes: str = ""
    brake_test_type: str = "none"  # none | roller | decelerometer
    laden: bool = False
    service_brake_pct: str = ""
    secondary_brake_pct: str = ""
    parking_brake_pct: str = ""
    checklist: List[dict] = []
    attachments: List[Attachment] = []
    inspector_signature: str = ""
    rectifier_signature: str = ""
    odometer: str = ""
    make_model: str = ""


class PMIInterimInput(PMICompleteInput):
    vehicle_reg: str


class TrainingRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"trn_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    driver_id: str = ""
    driver_name: str = ""
    course_name: str
    category: str = "Driver CPC"
    completed_date: Optional[str] = None
    expiry_date: Optional[str] = None
    provider: str = ""
    hours: float = 0.0
    notes: str = ""
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class TrainingInput(BaseModel):
    driver_id: str = ""
    driver_name: str = ""
    course_name: str
    category: str = "Driver CPC"
    completed_date: Optional[str] = None
    expiry_date: Optional[str] = None
    provider: str = ""
    hours: float = 0.0
    notes: str = ""
    attachments: List[Attachment] = []


class WheelAudit(BaseModel):
    id: str = Field(default_factory=lambda: f"wsa_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    vehicle_reg: str
    audit_date: Optional[str] = None
    result: str = "pass"  # pass | advisory | fail
    torque_setting: str = ""
    checked_by: str = ""
    next_due: Optional[str] = None
    notes: str = ""
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class WheelAuditInput(BaseModel):
    vehicle_reg: str
    audit_date: Optional[str] = None
    result: str = "pass"
    torque_setting: str = ""
    checked_by: str = ""
    next_due: Optional[str] = None
    notes: str = ""
    attachments: List[Attachment] = []


class ServiceRecord(BaseModel):
    id: str = Field(default_factory=lambda: f"svc_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    vehicle_reg: str
    service_date: Optional[str] = None
    service_type: str = "Full service"
    odometer: float = 0
    provider: str = ""
    cost: float = 0
    next_service_due: Optional[str] = None
    notes: str = ""
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class ServiceInput(BaseModel):
    vehicle_reg: str
    service_date: Optional[str] = None
    service_type: str = "Full service"
    odometer: float = 0
    provider: str = ""
    cost: float = 0
    next_service_due: Optional[str] = None
    notes: str = ""
    attachments: List[Attachment] = []


class WalkaroundCheck(BaseModel):
    id: str = Field(default_factory=lambda: f"wac_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    vehicle_reg: str
    driver_name: str = ""
    check_date: Optional[str] = None
    result: str = "nil_defect"  # nil_defect | defects_found
    mileage: str = ""
    defects_noted: str = ""
    checklist: List[dict] = []
    rectified: bool = False
    rectified_date: Optional[str] = None
    rectified_notes: str = ""
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class WalkaroundRectifyInput(BaseModel):
    rectified_date: Optional[str] = None
    rectified_notes: str = ""


class WalkaroundInput(BaseModel):
    vehicle_reg: str
    driver_name: str = ""
    check_date: Optional[str] = None
    result: str = "nil_defect"
    mileage: str = ""
    defects_noted: str = ""
    checklist: List[dict] = []
    attachments: List[Attachment] = []


WEEK_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def week_start_of(d: Optional[str] = None) -> str:
    """Monday (ISO date) of the week containing d (or today if None)."""
    dt = datetime.fromisoformat(d).date() if d else datetime.now(timezone.utc).date()
    return (dt - timedelta(days=dt.weekday())).isoformat()


class WeeklyWalkaround(BaseModel):
    id: str = Field(default_factory=lambda: f"wwc_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    vehicle_reg: str = ""
    driver_name: str = ""
    week_start: str = ""
    mileage_start: str = ""
    mileage_finish: str = ""
    days: dict = {}  # { "mon": {date, result, checklist:[...], submitted_at}, ... }
    fault_reporting: str = ""
    driver_signature: str = ""
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class WeeklyCreateInput(BaseModel):
    vehicle_reg: str
    driver_name: str = ""
    week_start: Optional[str] = None
    mileage_start: str = ""
    mileage_finish: str = ""


class WeeklyUpdateInput(BaseModel):
    driver_name: Optional[str] = None
    mileage_start: Optional[str] = None
    mileage_finish: Optional[str] = None
    days: Optional[dict] = None
    fault_reporting: Optional[str] = None
    driver_signature: Optional[str] = None


class WeeklyDayInput(BaseModel):
    vehicle_reg: str = ""
    checklist: List[dict] = []
    mileage: str = ""
    signature: str = ""


class TestHistory(BaseModel):
    id: str = Field(default_factory=lambda: f"thr_{uuid.uuid4().hex[:10]}")
    user_id: str = ""
    vehicle_reg: str
    event_type: str = "annual_test"  # annual_test | prohibition
    event_date: Optional[str] = None
    result: str = "pass"  # pass | fail | pg9 | advisory | cleared
    reference: str = ""
    notes: str = ""
    attachments: List[Attachment] = []
    created_at: str = Field(default_factory=now_iso)


class TestHistoryInput(BaseModel):
    vehicle_reg: str
    event_type: str = "annual_test"
    event_date: Optional[str] = None
    result: str = "pass"
    reference: str = ""
    notes: str = ""
    attachments: List[Attachment] = []


# ---------- Auth ----------
def create_jwt(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


_CODE_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


async def _generate_driver_code() -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_CHARS) for _ in range(6))
        if not await db.drivers.find_one({"access_code": code}):
            return code
    return "".join(secrets.choice(_CODE_CHARS) for _ in range(8))


def create_driver_jwt(driver_id: str, owner_id: str) -> str:
    payload = {"driver_id": driver_id, "user_id": owner_id, "role": "driver",
               "exp": datetime.now(timezone.utc) + timedelta(days=30)}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


async def get_current_driver(request: Request) -> dict:
    auth = request.headers.get("Authorization")
    bearer = auth.split(" ", 1)[1] if auth and auth.startswith("Bearer ") else None
    if not bearer:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(bearer, JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("role") != "driver":
        raise HTTPException(status_code=403, detail="Driver access only")
    driver = await db.drivers.find_one({"id": payload.get("driver_id")}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=401, detail="Driver not found")
    return driver


async def create_alert(user_id, type_, severity, title, message, vehicle_reg="", driver_name="", link=""):
    """Create an in-app defect alert and email the operator for major/safety-critical ones."""
    alert = Alert(user_id=user_id, type=type_, severity=severity, title=title, message=message,
                  vehicle_reg=vehicle_reg, driver_name=driver_name, link=link)
    await db.alerts.insert_one(alert.model_dump())
    if severity in ("major", "safety_critical"):
        try:
            owner = await db.users.find_one({"user_id": user_id}, {"_id": 0, "email": 1})
            if owner and owner.get("email"):
                import resend
                resend.api_key = os.environ['RESEND_API_KEY']
                sev = severity.replace("_", " ").title()
                html = (f"<h2 style='font-family:Arial'>⚠️ {sev} defect reported</h2>"
                        f"<p style='font-family:Arial;font-size:15px'><b>{title}</b></p>"
                        f"<p style='font-family:Arial;color:#475569'>{message}</p>"
                        f"<p style='font-family:Arial;color:#64748b'>Vehicle: {vehicle_reg or '—'}{(' · Driver: ' + driver_name) if driver_name else ''}</p>"
                        f"<p style='font-family:Arial;font-size:12px;color:#94a3b8'>Log in to HaulCheck to review and action this.</p>")
                await asyncio.to_thread(resend.Emails.send, {
                    "from": os.environ['SENDER_EMAIL'], "to": [owner["email"]],
                    "subject": f"HaulCheck: {sev} defect — {vehicle_reg or 'vehicle'}", "html": html,
                })
        except Exception as e:
            logging.error(f"Alert email failed: {e}")
    return alert


async def _authenticate(cookie_token: Optional[str], bearer: Optional[str]) -> Optional[User]:
    # Prefer an explicit Bearer JWT: it is set by the current email/password/invite
    # login and must take precedence over any stale Google session cookie left in
    # the browser (otherwise an invited user on a shared browser sees the inviter's data).
    if bearer:
        try:
            payload = jwt.decode(bearer, JWT_SECRET, algorithms=["HS256"])
            if payload.get("role") != "driver":
                user_doc = await db.users.find_one({"user_id": payload["user_id"]}, {"_id": 0})
                if user_doc and user_doc.get("active", True):
                    return User(**user_doc)
        except jwt.PyJWTError:
            pass
    # Fall back to Google session token (cookie, or a session token sent as bearer)
    candidate = cookie_token or bearer
    if candidate:
        session = await db.user_sessions.find_one({"session_token": candidate}, {"_id": 0})
        if session:
            expires_at = session["expires_at"]
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at)
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                return None
            user_doc = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
            if user_doc and user_doc.get("active", True):
                return User(**user_doc)
    return None


async def get_current_user(request: Request) -> User:
    cookie_token = request.cookies.get("session_token")
    auth = request.headers.get("Authorization")
    bearer = auth.split(" ", 1)[1] if auth and auth.startswith("Bearer ") else None
    user = await _authenticate(cookie_token, bearer)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@api_router.post("/auth/register")
async def register(data: RegisterInput, response: Response):
    email = data.email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    await db.users.insert_one({
        "user_id": user_id,
        "email": email,
        "name": data.name,
        "role": data.role,
        "region": "UK",
        "picture": None,
        "password_hash": pwd_context.hash(data.password),
        "created_at": now_iso(),
    })
    response.delete_cookie("session_token", path="/")
    token = create_jwt(user_id)
    return {"token": token, "user": {"user_id": user_id, "email": email, "name": data.name, "role": data.role, "region": "UK"}}


async def _seed_template(new_user_id: str, inviter_id: str, new_email: str):
    inviter = await db.users.find_one({"user_id": inviter_id}, {"_id": 0}) or {}
    await db.users.update_one({"user_id": new_user_id}, {"$set": {"region": inviter.get("region", "UK")}})
    for l in await db.links.find({"user_id": inviter_id}, {"_id": 0}).to_list(1000):
        await db.links.insert_one({**l, "id": f"link_{uuid.uuid4().hex[:10]}", "user_id": new_user_id, "created_at": now_iso()})
    rs = await db.reminder_settings.find_one({"user_id": inviter_id}, {"_id": 0})
    if rs and rs.get("recipients"):
        base = rs["recipients"][0]
        await db.reminder_settings.update_one(
            {"user_id": new_user_id},
            {"$set": {"user_id": new_user_id, "recipients": [{"email": new_email, "areas": base.get("areas", []), "schedule": base.get("schedule", "weekly")}]}},
            upsert=True,
        )


@api_router.post("/invitations")
async def create_invitation(data: InviteInput, user: User = Depends(get_current_user)):
    email = data.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="That email already has an account")
    token = secrets.token_urlsafe(32)
    inv = {
        "id": f"inv_{uuid.uuid4().hex[:10]}", "email": email, "token": token,
        "invited_by": user.user_id, "inviter_name": user.name, "status": "pending",
        "created_at": now_iso(), "expires_at": (datetime.now(timezone.utc) + timedelta(days=14)).isoformat(),
    }
    await db.invitations.insert_one(inv)
    link = f"{(data.base_url or '').rstrip('/')}/accept-invite?token={token}"
    html = (
        "<div style='background:#f1f5f9;padding:32px 0;font-family:Arial,Helvetica,sans-serif;'>"
        "<table role='presentation' width='560' align='center' cellpadding='0' cellspacing='0' style='background:#fff;border-radius:12px;padding:32px;margin:0 auto;'>"
        f"<tr><td><p style='margin:0;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#64748b;font-weight:700;'>HaulCheck Compliance</p>"
        f"<h1 style='margin:6px 0 0;font-size:22px;color:#0f172a;'>You've been invited</h1>"
        f"<p style='margin:16px 0 0;font-size:14px;color:#334155;line-height:1.6;'>{user.name} has invited you to set up your own HaulCheck compliance account. Click below to choose a password and get started.</p>"
        f"<p style='margin:24px 0;'><a href='{link}' style='background:#0f172a;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-size:14px;font-weight:600;'>Accept invitation</a></p>"
        f"<p style='margin:8px 0 0;font-size:12px;color:#94a3b8;'>Or paste this link: {link}</p>"
        "<p style='margin:16px 0 0;font-size:12px;color:#94a3b8;'>This invitation expires in 14 days.</p>"
        "</td></tr></table></div>"
    )
    email_sent = False
    email_error = ""
    try:
        import resend
        resend.api_key = os.environ['RESEND_API_KEY']
        await asyncio.to_thread(resend.Emails.send, {
            "from": os.environ['SENDER_EMAIL'], "to": [email],
            "subject": f"{user.name} invited you to HaulCheck", "html": html,
        })
        email_sent = True
    except Exception as e:
        email_error = str(e)
        logging.error(f"Invite email failed: {e}")
    return {"ok": True, "id": inv["id"], "invite_link": link, "email_sent": email_sent, "email_error": email_error}


@api_router.get("/invitations")
async def list_invitations(user: User = Depends(get_current_user)):
    invites = await db.invitations.find({"invited_by": user.user_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    for inv in invites:
        if inv.get("status") == "accepted":
            u = await db.users.find_one({"email": inv["email"]}, {"_id": 0, "last_login_at": 1, "name": 1, "active": 1})
            if u:
                inv["last_login_at"] = u.get("last_login_at")
                inv["member_name"] = u.get("name")
                inv["active"] = u.get("active", True)
    return invites


@api_router.delete("/invitations/{iid}")
async def delete_invitation(iid: str, user: User = Depends(get_current_user)):
    await db.invitations.delete_one({"id": iid, "invited_by": user.user_id})
    return {"ok": True}


async def _resolve_member(inv: dict, inviter_id: str):
    mid = inv.get("accepted_user_id")
    if mid:
        return await db.users.find_one({"user_id": mid, "invited_by": inviter_id}, {"_id": 0})
    return await db.users.find_one({"email": inv["email"], "invited_by": inviter_id}, {"_id": 0})


@api_router.put("/invitations/{iid}/member-status")
async def set_member_status(iid: str, payload: dict, user: User = Depends(get_current_user)):
    inv = await db.invitations.find_one({"id": iid, "invited_by": user.user_id}, {"_id": 0})
    if not inv or inv.get("status") != "accepted":
        raise HTTPException(status_code=404, detail="Active member not found for this invitation")
    member = await _resolve_member(inv, user.user_id)
    if not member:
        raise HTTPException(status_code=404, detail="Member account not found")
    active = bool(payload.get("active", True))
    await db.users.update_one({"user_id": member["user_id"]}, {"$set": {"active": active}})
    if not active:
        await db.user_sessions.delete_many({"user_id": member["user_id"]})
    return {"ok": True, "active": active}


@api_router.get("/invitations/verify")
async def verify_invitation(token: str):
    inv = await db.invitations.find_one({"token": token}, {"_id": 0})
    if not inv or inv.get("status") != "pending":
        raise HTTPException(status_code=404, detail="Invitation not found or already used")
    if inv["expires_at"] < now_iso():
        raise HTTPException(status_code=400, detail="This invitation has expired")
    return {"email": inv["email"], "inviter_name": inv.get("inviter_name", "")}


@api_router.post("/auth/accept-invite")
async def accept_invite(data: AcceptInviteInput, response: Response):
    inv = await db.invitations.find_one({"token": data.token})
    if not inv or inv.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Invitation not found or already used")
    if inv["expires_at"] < now_iso():
        raise HTTPException(status_code=400, detail="This invitation has expired")
    email = inv["email"]
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    await db.users.insert_one({
        "user_id": user_id, "email": email, "name": data.name, "role": "manager",
        "region": "UK", "picture": None, "password_hash": pwd_context.hash(data.password),
        "invited_by": inv["invited_by"], "created_at": now_iso(), "last_login_at": now_iso(),
    })
    await _seed_template(user_id, inv["invited_by"], email)
    await db.invitations.update_one({"id": inv["id"]}, {"$set": {"status": "accepted", "accepted_at": now_iso(), "accepted_user_id": user_id}})
    fresh = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    response.delete_cookie("session_token", path="/")
    return {"token": create_jwt(user_id), "user": {"user_id": user_id, "email": email, "name": data.name, "role": "manager", "region": fresh.get("region", "UK")}}


@api_router.put("/settings/region")
async def set_region(payload: dict, user: User = Depends(get_current_user)):
    region = payload.get("region", "UK")
    if region not in ("UK", "IE"):
        raise HTTPException(status_code=400, detail="Invalid region")
    await db.users.update_one({"user_id": user.user_id}, {"$set": {"region": region}})
    return {"ok": True, "region": region}


@api_router.get("/operator")
async def get_operator(user: User = Depends(get_current_user)):
    doc = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0})
    return doc or {}


@api_router.put("/operator")
async def update_operator(data: OperatorInput, user: User = Depends(get_current_user)):
    payload = data.model_dump()
    payload["user_id"] = user.user_id
    payload["updated_at"] = now_iso()
    await db.operator.update_one({"user_id": user.user_id}, {"$set": payload}, upsert=True)
    return {"ok": True}


@api_router.post("/auth/login")
async def login(data: LoginInput, response: Response):
    user_doc = await db.users.find_one({"email": data.email.lower().strip()})
    if not user_doc or not user_doc.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not pwd_context.verify(data.password, user_doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user_doc.get("active", True) is False:
        raise HTTPException(status_code=403, detail="Your account has been deactivated. Please contact the operator who invited you.")
    await db.users.update_one({"user_id": user_doc["user_id"]}, {"$set": {"last_login_at": now_iso()}})
    response.delete_cookie("session_token", path="/")
    token = create_jwt(user_doc["user_id"])
    return {"token": token, "user": {"user_id": user_doc["user_id"], "email": user_doc["email"], "name": user_doc["name"], "role": user_doc.get("role", "manager")}}


@api_router.post("/auth/forgot-password")
async def forgot_password(data: ForgotPasswordInput):
    email = data.email.lower().strip()
    user_doc = await db.users.find_one({"email": email}, {"_id": 0})
    # Always respond ok to avoid leaking which emails are registered.
    if user_doc and user_doc.get("password_hash"):
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "token": token,
            "user_id": user_doc["user_id"],
            "email": email,
            "used": False,
            "created_at": now_iso(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        link = f"{(data.base_url or '').rstrip('/')}/reset-password?token={token}"
        name = user_doc.get("name") or "there"
        html = (
            "<div style='background:#f1f5f9;padding:32px 0;font-family:Arial,Helvetica,sans-serif;'>"
            "<table role='presentation' width='560' align='center' cellpadding='0' cellspacing='0' style='background:#fff;border-radius:12px;padding:32px;margin:0 auto;'>"
            "<tr><td><p style='margin:0;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:#64748b;font-weight:700;'>HaulCheck Compliance</p>"
            "<h1 style='margin:6px 0 0;font-size:22px;color:#0f172a;'>Reset your password</h1>"
            f"<p style='margin:16px 0 0;font-size:14px;color:#334155;line-height:1.6;'>Hi {name}, we received a request to reset the password for your HaulCheck account. Click the button below to choose a new password.</p>"
            f"<p style='margin:24px 0;'><a href='{link}' style='background:#0f172a;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-size:14px;font-weight:600;'>Reset password</a></p>"
            f"<p style='margin:8px 0 0;font-size:12px;color:#94a3b8;'>Or paste this link: {link}</p>"
            "<p style='margin:16px 0 0;font-size:12px;color:#94a3b8;'>This link expires in 1 hour. If you didn't request this, you can safely ignore this email.</p>"
            "</td></tr></table></div>"
        )
        try:
            import resend
            resend.api_key = os.environ['RESEND_API_KEY']
            await asyncio.to_thread(resend.Emails.send, {
                "from": os.environ['SENDER_EMAIL'], "to": [email],
                "subject": "Reset your HaulCheck password", "html": html,
            })
        except Exception as e:
            logging.error(f"Password reset email failed: {e}")
    return {"ok": True}


@api_router.get("/auth/reset-password/verify")
async def verify_reset_token(token: str):
    rec = await db.password_reset_tokens.find_one({"token": token}, {"_id": 0})
    if not rec or rec.get("used") or rec["expires_at"] < now_iso():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    return {"email": rec["email"]}


@api_router.post("/auth/reset-password")
async def reset_password(data: ResetPasswordInput):
    rec = await db.password_reset_tokens.find_one({"token": data.token})
    if not rec or rec.get("used") or rec["expires_at"] < now_iso():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    await db.users.update_one({"user_id": rec["user_id"]}, {"$set": {"password_hash": pwd_context.hash(data.password)}})
    await db.password_reset_tokens.update_one({"token": data.token}, {"$set": {"used": True, "used_at": now_iso()}})
    return {"ok": True}


@api_router.post("/auth/session")
async def google_session(request: Request, response: Response):
    session_id = request.headers.get("X-Session-ID")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session id")
    async with httpx.AsyncClient() as http:
        r = await http.get(
            "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
            headers={"X-Session-ID": session_id},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid session")
    data = r.json()
    email = (data.get("email") or "").lower().strip()
    user_doc = await db.users.find_one({"email": email}, {"_id": 0})
    if not user_doc:
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id, "email": email, "name": data.get("name", ""),
            "role": "manager", "picture": data.get("picture"), "created_at": now_iso(),
        }
        await db.users.insert_one(dict(user_doc))
    else:
        user_id = user_doc["user_id"]
    await db.users.update_one({"user_id": user_id}, {"$set": {"last_login_at": now_iso()}})
    session_token = data["session_token"]
    await db.user_sessions.insert_one({
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        "created_at": now_iso(),
    })
    response.set_cookie(key="session_token", value=session_token, httponly=True,
                        secure=True, samesite="none", path="/", max_age=7 * 24 * 60 * 60)
    return {"user": {"user_id": user_id, "email": email, "name": data.get("name", ""),
                     "role": "manager", "picture": data.get("picture")}}


@api_router.get("/auth/me", response_model=User)
async def me(user: User = Depends(get_current_user)):
    return user


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_many({"session_token": token})
    response.delete_cookie("session_token", path="/")
    return {"ok": True}


# ---------- Vehicles ----------
@api_router.get("/vehicles")
async def list_vehicles(user: User = Depends(get_current_user)):
    docs = await db.vehicles.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    for d in docs:
        d["mot_status"] = compliance_status(days_until(d.get("mot_due")))
        d["service_status"] = compliance_status(days_until(d.get("service_due")))
        d["tax_status"] = compliance_status(days_until(d.get("tax_due")))
        d["tacho_cal_status"] = compliance_status(days_until(d.get("tacho_calibration_due")))
        d["speed_limiter_status"] = compliance_status(days_until(d.get("speed_limiter_due")))
    return docs


@api_router.post("/vehicles")
async def create_vehicle(data: VehicleInput, user: User = Depends(get_current_user)):
    v = Vehicle(**data.model_dump(), user_id=user.user_id)
    await db.vehicles.insert_one(v.model_dump())
    return v.model_dump()


@api_router.put("/vehicles/{vid}")
async def update_vehicle(vid: str, data: VehicleInput, user: User = Depends(get_current_user)):
    res = await db.vehicles.update_one({"id": vid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return {"ok": True}


@api_router.delete("/vehicles/{vid}")
async def delete_vehicle(vid: str, user: User = Depends(get_current_user)):
    await db.vehicles.delete_one({"id": vid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Trailers ----------
@api_router.get("/trailers")
async def list_trailers(user: User = Depends(get_current_user)):
    docs = await db.trailers.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    for d in docs:
        d["mot_status"] = compliance_status(days_until(d.get("mot_due")))
        d["service_status"] = compliance_status(days_until(d.get("service_due")))
    return docs


@api_router.post("/trailers")
async def create_trailer(data: TrailerInput, user: User = Depends(get_current_user)):
    t = Trailer(**data.model_dump(), user_id=user.user_id)
    await db.trailers.insert_one(t.model_dump())
    return t.model_dump()


@api_router.put("/trailers/{tid}")
async def update_trailer(tid: str, data: TrailerInput, user: User = Depends(get_current_user)):
    res = await db.trailers.update_one({"id": tid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Trailer not found")
    return {"ok": True}


@api_router.delete("/trailers/{tid}")
async def delete_trailer(tid: str, user: User = Depends(get_current_user)):
    await db.trailers.delete_one({"id": tid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Files (object storage) ----------
@api_router.post("/upload")
async def upload_file(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    file_id = uuid.uuid4().hex
    path = f"{APP_NAME}/uploads/{user.user_id}/{file_id}.{ext}"
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 15MB)")
    content_type = file.content_type or MIME_TYPES.get(ext, "application/octet-stream")
    try:
        result = put_object(path, data, content_type)
    except Exception as e:
        logging.error(f"Upload failed: {e}")
        raise HTTPException(status_code=502, detail="Upload failed")
    await db.files.insert_one({
        "id": file_id,
        "user_id": user.user_id,
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "is_deleted": False,
        "created_at": now_iso(),
    })
    return {"file_id": file_id, "filename": file.filename, "content_type": content_type,
            "url": f"/api/files/{file_id}"}


@api_router.get("/files/{file_id}")
async def download_file(file_id: str, request: Request, auth: Optional[str] = Query(None)):
    cookie_token = request.cookies.get("session_token")
    header_auth = request.headers.get("Authorization")
    bearer = (header_auth.split(" ", 1)[1] if header_auth and header_auth.startswith("Bearer ") else None) or auth
    user = await _authenticate(cookie_token, bearer)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rec = await db.files.find_one({"id": file_id, "user_id": user.user_id, "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    data, ct = get_object(rec["storage_path"])
    return Response(content=data, media_type=rec.get("content_type") or ct,
                    headers={"Content-Disposition": f'inline; filename="{rec.get("original_filename", file_id)}"'})


# ---------- Drivers ----------
@api_router.get("/drivers")
async def list_drivers(user: User = Depends(get_current_user)):
    docs = await db.drivers.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    training = await db.training.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000)
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=365 * 5)).isoformat()
    for d in docs:
        d["licence_status"] = compliance_status(days_until(d.get("licence_expiry")))
        d["cpc_status"] = compliance_status(days_until(d.get("cpc_expiry")))
        d["tacho_status"] = compliance_status(days_until(d.get("tacho_card_expiry")))
        d["licence_check_status"] = compliance_status(days_until(d.get("licence_check_due")))
        d["hours_status"] = "expired" if d.get("weekly_hours", 0) > d.get("max_weekly_hours", 56) else "valid"
        cpc_hours = sum(
            float(t.get("hours") or 0) for t in training
            if (t.get("driver_id") == d["id"] or t.get("driver_name") == d.get("name"))
            and "cpc" in (t.get("category") or "").lower()
            and (t.get("completed_date") or "9999") >= cutoff
        )
        d["cpc_hours"] = cpc_hours
    return docs


@api_router.post("/drivers")
async def create_driver(data: DriverInput, user: User = Depends(get_current_user)):
    d = Driver(**data.model_dump(), user_id=user.user_id)
    await db.drivers.insert_one(d.model_dump())
    return d.model_dump()


@api_router.put("/drivers/{did}")
async def update_driver(did: str, data: DriverInput, user: User = Depends(get_current_user)):
    res = await db.drivers.update_one({"id": did, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Driver not found")
    return {"ok": True}


@api_router.delete("/drivers/{did}")
async def delete_driver(did: str, user: User = Depends(get_current_user)):
    await db.drivers.delete_one({"id": did, "user_id": user.user_id})
    return {"ok": True}


@api_router.post("/drivers/{did}/access-code")
async def issue_driver_code(did: str, user: User = Depends(get_current_user)):
    driver = await db.drivers.find_one({"id": did, "user_id": user.user_id}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    code = await _generate_driver_code()
    await db.drivers.update_one({"id": did, "user_id": user.user_id}, {"$set": {"access_code": code}})
    return {"ok": True, "access_code": code}


@api_router.delete("/drivers/{did}/access-code")
async def revoke_driver_code(did: str, user: User = Depends(get_current_user)):
    await db.drivers.update_one({"id": did, "user_id": user.user_id}, {"$set": {"access_code": ""}})
    return {"ok": True}


# ---------- Defect alerts (manager) ----------
# ---------- Overdue auto-alerts (items past their due date) ----------
_OVERDUE_LINK = {
    "vehicle": "/vehicles", "trailer": "/vehicles", "driver": "/drivers",
    "training": "/office", "pmi": "/maintenance", "document": "/office",
    "insurance": "/office", "tacho": "/tacho", "wheel": "/maintenance",
}
_last_overdue_sync: dict = {}


def _overdue_severity(a: dict) -> str:
    t, item = a.get("type"), a.get("item", "")
    if t == "insurance":
        return "safety_critical"
    if t == "vehicle" and item in ("MOT", "Tax"):
        return "safety_critical" if item == "MOT" else "major"
    if t == "driver" and item == "Licence":
        return "safety_critical"
    if t == "training" or item == "Licence Check" or t == "tacho":
        return "minor"
    return "major"


async def sync_overdue_alerts(user_id: str, force: bool = False):
    """Reconcile the alerts panel with items that are past their due date (dedup + auto-clear on renewal)."""
    import time
    now = time.time()
    if not force and now - _last_overdue_sync.get(user_id, 0) < 120:
        return
    _last_overdue_sync[user_id] = now
    stats = await gather_stats(user_id)
    overdue = {}
    for a in stats["alerts"]:
        if a.get("status") != "expired":
            continue
        key = f"overdue|{a.get('type')}|{a.get('name')}|{a.get('item')}"
        overdue[key] = a
    existing = await db.alerts.find({"user_id": user_id, "dedup_key": {"$ne": ""}}, {"_id": 0}).to_list(1000)
    existing_keys = {e["dedup_key"] for e in existing}
    dismissed_doc = await db.dismissed_alerts.find_one({"user_id": user_id}, {"_id": 0}) or {}
    dismissed = set(dismissed_doc.get("keys", []))
    for key, a in overdue.items():
        if key in existing_keys or key in dismissed:
            continue
        days = a.get("days")
        overdue_txt = f"{abs(days)} day(s) overdue" if isinstance(days, int) else "action needed"
        veh = a["name"] if a.get("type") in ("vehicle", "trailer", "pmi", "wheel") else ""
        alert = Alert(
            user_id=user_id, type="overdue", severity=_overdue_severity(a),
            title=f"{a['name']} — {a['item']} {overdue_txt}",
            message=f"{a['item']} for {a['name']} is past its due date. Renew it to restore compliance.",
            vehicle_reg=veh, link=_OVERDUE_LINK.get(a.get("type"), ""), dedup_key=key,
        )
        await db.alerts.insert_one(alert.model_dump())
    stale = [k for k in existing_keys if k not in overdue]
    if stale:
        await db.alerts.delete_many({"user_id": user_id, "dedup_key": {"$in": stale}})
    kept_dismissed = dismissed & set(overdue.keys())
    if kept_dismissed != dismissed:
        await db.dismissed_alerts.update_one(
            {"user_id": user_id}, {"$set": {"user_id": user_id, "keys": list(kept_dismissed)}}, upsert=True)


@api_router.get("/alerts")
async def list_alerts(user: User = Depends(get_current_user)):
    await sync_overdue_alerts(user.user_id)
    return await db.alerts.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", -1).to_list(200)


@api_router.get("/alerts/unread-count")
async def alerts_unread_count(user: User = Depends(get_current_user)):
    await sync_overdue_alerts(user.user_id)
    return {"count": await db.alerts.count_documents({"user_id": user.user_id, "read": False})}


@api_router.patch("/alerts/{aid}/read")
async def mark_alert_read(aid: str, user: User = Depends(get_current_user)):
    await db.alerts.update_one({"id": aid, "user_id": user.user_id}, {"$set": {"read": True}})
    return {"ok": True}


@api_router.post("/alerts/read-all")
async def mark_all_alerts_read(user: User = Depends(get_current_user)):
    await db.alerts.update_many({"user_id": user.user_id, "read": False}, {"$set": {"read": True}})
    return {"ok": True}


@api_router.delete("/alerts/{aid}")
async def delete_alert(aid: str, user: User = Depends(get_current_user)):
    doc = await db.alerts.find_one({"id": aid, "user_id": user.user_id}, {"_id": 0})
    await db.alerts.delete_one({"id": aid, "user_id": user.user_id})
    if doc and doc.get("dedup_key"):
        await db.dismissed_alerts.update_one(
            {"user_id": user.user_id}, {"$addToSet": {"keys": doc["dedup_key"]}}, upsert=True)
    return {"ok": True}


# ---------- Driver mobile app (PIN/code auth) ----------
def _driver_profile(driver: dict) -> dict:
    return {
        "id": driver["id"], "name": driver.get("name"),
        "assigned_vehicle_reg": driver.get("assigned_vehicle_reg", ""),
        "licence_number": driver.get("licence_number", ""),
        "licence_expiry": driver.get("licence_expiry"),
        "cpc_expiry": driver.get("cpc_expiry"),
        "tacho_card_expiry": driver.get("tacho_card_expiry"),
        "licence_status": compliance_status(days_until(driver.get("licence_expiry"))),
        "cpc_status": compliance_status(days_until(driver.get("cpc_expiry"))),
        "tacho_status": compliance_status(days_until(driver.get("tacho_card_expiry"))),
    }


@api_router.post("/driver/login")
async def driver_login(payload: dict):
    code = (payload.get("code") or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Enter your access code")
    driver = await db.drivers.find_one({"access_code": code}, {"_id": 0})
    if not driver:
        raise HTTPException(status_code=401, detail="Invalid access code")
    token = create_driver_jwt(driver["id"], driver["user_id"])
    return {"token": token, "driver": _driver_profile(driver)}


@api_router.get("/driver/me")
async def driver_me(driver: dict = Depends(get_current_driver)):
    profile = _driver_profile(driver)
    docs = await db.documents.find(
        {"user_id": driver["user_id"], "$or": [{"driver_id": driver["id"]}, {"driver_name": driver.get("name")}]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(200)
    profile["documents"] = [{"id": d["id"], "title": d.get("title"), "doc_type": d.get("doc_type"),
                             "attachments": d.get("attachments", [])} for d in docs]
    return profile


@api_router.get("/driver/vehicle")
async def driver_vehicle(driver: dict = Depends(get_current_driver)):
    reg = driver.get("assigned_vehicle_reg")
    if not reg:
        return {"vehicle": None, "documents": []}
    veh = await db.vehicles.find_one({"user_id": driver["user_id"], "registration": reg}, {"_id": 0})
    if veh:
        for k, f in [("mot_status", "mot_due"), ("service_status", "service_due"), ("tax_status", "tax_due")]:
            veh[k] = compliance_status(days_until(veh.get(f)))
    docs = await db.documents.find({"user_id": driver["user_id"], "reference": reg}, {"_id": 0}).to_list(50)
    return {"vehicle": veh, "documents": [{"id": d["id"], "title": d.get("title"), "attachments": d.get("attachments", [])} for d in docs]}


@api_router.get("/driver/vehicles")
async def driver_vehicles(driver: dict = Depends(get_current_driver)):
    docs = await db.vehicles.find({"user_id": driver["user_id"]}, {"_id": 0, "registration": 1}).to_list(1000)
    return [d["registration"] for d in docs]


@api_router.post("/driver/upload")
async def driver_upload(file: UploadFile = File(...), driver: dict = Depends(get_current_driver)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
    file_id = uuid.uuid4().hex
    path = f"{APP_NAME}/uploads/{driver['user_id']}/{file_id}.{ext}"
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 15MB)")
    content_type = file.content_type or MIME_TYPES.get(ext, "application/octet-stream")
    try:
        result = put_object(path, data, content_type)
    except Exception as e:
        logging.error(f"Driver upload failed: {e}")
        raise HTTPException(status_code=502, detail="Upload failed")
    await db.files.insert_one({
        "id": file_id, "user_id": driver["user_id"], "storage_path": result["path"],
        "original_filename": file.filename, "content_type": content_type,
        "size": result.get("size", len(data)), "is_deleted": False, "created_at": now_iso(),
    })
    return {"file_id": file_id, "filename": file.filename, "content_type": content_type}


@api_router.post("/driver/walkaround")
async def driver_walkaround(data: WalkaroundInput, driver: dict = Depends(get_current_driver)):
    payload = data.model_dump()
    payload["user_id"] = driver["user_id"]
    payload["driver_name"] = driver.get("name", "")
    if not payload.get("vehicle_reg"):
        payload["vehicle_reg"] = driver.get("assigned_vehicle_reg", "")
    check = WalkaroundCheck(**payload)
    await db.walkaround_checks.insert_one(check.model_dump())
    if check.result == "defects_found":
        failed = [c.get("item") for c in (check.checklist or []) if not c.get("ok")]
        await create_alert(driver["user_id"], "walkaround_defect", "major",
                           f"Walkaround defect — {check.vehicle_reg}",
                           check.defects_noted or (", ".join(failed) if failed else "Defects found on daily walkaround"),
                           vehicle_reg=check.vehicle_reg, driver_name=check.driver_name, link="/maintenance")
    return check.model_dump()


@api_router.post("/driver/defect")
async def driver_defect(payload: dict, driver: dict = Depends(get_current_driver)):
    payload["user_id"] = driver["user_id"]
    payload["reported_by"] = driver.get("name", "")
    if not payload.get("vehicle_reg"):
        payload["vehicle_reg"] = driver.get("assigned_vehicle_reg", "")
    if not payload.get("description"):
        raise HTTPException(status_code=400, detail="Describe the defect")
    d = DefectReport(**{k: v for k, v in payload.items() if k in DefectReport.model_fields})
    await db.defects.insert_one(d.model_dump())
    await create_alert(driver["user_id"], "defect_report", d.severity or "major",
                       f"Defect reported — {d.vehicle_reg}", d.description or "Defect reported by driver",
                       vehicle_reg=d.vehicle_reg, driver_name=d.reported_by, link="/maintenance")
    return d.model_dump()


@api_router.post("/driver/tacho/analyse")
async def driver_tacho_analyse(payload: dict, driver: dict = Depends(get_current_driver)):
    file_id = payload.get("file_id")
    rec = await db.files.find_one({"id": file_id, "user_id": driver["user_id"], "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    fdata, ct = get_object(rec["storage_path"])
    ct = rec.get("content_type") or ct
    ext = (rec.get("original_filename") or "").rsplit(".", 1)[-1].lower()
    region_doc = await db.users.find_one({"user_id": driver["user_id"]}, {"_id": 0, "region": 1}) or {}
    result = await run_tacho_analysis(fdata, ct, ext, region_doc.get("region", "UK"), driver.get("name", "")) or {}
    infr = result.get("infringements") or []
    analysis = TachoAnalysis(
        user_id=driver["user_id"], driver_name=driver.get("name", ""),
        period=result.get("period") or "", summary=result.get("summary") or "",
        total_infringements=result.get("total_infringements") if isinstance(result.get("total_infringements"), int) else len(infr),
        infringements=infr, confidence=float(result.get("confidence") or 0), file_id=file_id,
    )
    await db.tacho_analyses.insert_one(analysis.model_dump())
    return analysis.model_dump()


@api_router.get("/driver/files/{file_id}")
async def driver_download_file(file_id: str, request: Request, auth: Optional[str] = Query(None)):
    driver = None
    token = auth or (request.headers.get("Authorization", "").split(" ", 1)[1] if request.headers.get("Authorization", "").startswith("Bearer ") else None)
    if token:
        try:
            p = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            if p.get("role") == "driver":
                driver = await db.drivers.find_one({"id": p.get("driver_id")}, {"_id": 0})
        except jwt.PyJWTError:
            pass
    if not driver:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rec = await db.files.find_one({"id": file_id, "user_id": driver["user_id"], "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    fdata, ct = get_object(rec["storage_path"])
    return Response(content=fdata, media_type=rec.get("content_type") or ct,
                    headers={"Content-Disposition": f'inline; filename="{rec.get("original_filename", file_id)}"'})


# ---------- Driver Training ----------
@api_router.get("/training")
async def list_training(driver_id: Optional[str] = Query(None), user: User = Depends(get_current_user)):
    q = {"user_id": user.user_id}
    if driver_id:
        q["driver_id"] = driver_id
    docs = await db.training.find(q, {"_id": 0}).sort("expiry_date", 1).to_list(1000)
    for d in docs:
        d["status"] = compliance_status(days_until(d.get("expiry_date")))
        d["days_left"] = days_until(d.get("expiry_date"))
    return docs


@api_router.post("/training")
async def create_training(data: TrainingInput, user: User = Depends(get_current_user)):
    t = TrainingRecord(**data.model_dump(), user_id=user.user_id)
    await db.training.insert_one(t.model_dump())
    return t.model_dump()


@api_router.put("/training/{tid}")
async def update_training(tid: str, data: TrainingInput, user: User = Depends(get_current_user)):
    res = await db.training.update_one({"id": tid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Training record not found")
    return {"ok": True}


@api_router.delete("/training/{tid}")
async def delete_training(tid: str, user: User = Depends(get_current_user)):
    await db.training.delete_one({"id": tid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Documents ----------
@api_router.get("/documents")
async def list_documents(user: User = Depends(get_current_user)):
    docs = await db.documents.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    for d in docs:
        d["status"] = compliance_status(days_until(d.get("expiry_date")))
        d["days_left"] = days_until(d.get("expiry_date"))
    return docs


@api_router.post("/documents")
async def create_document(data: DocInput, user: User = Depends(get_current_user)):
    doc = ComplianceDoc(**data.model_dump(), user_id=user.user_id)
    await db.documents.insert_one(doc.model_dump())
    return doc.model_dump()


@api_router.put("/documents/{docid}")
async def update_document(docid: str, data: DocInput, user: User = Depends(get_current_user)):
    res = await db.documents.update_one({"id": docid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@api_router.delete("/documents/{docid}")
async def delete_document(docid: str, user: User = Depends(get_current_user)):
    await db.documents.delete_one({"id": docid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Web links (reference bookmarks) ----------
@api_router.get("/links")
async def list_links(user: User = Depends(get_current_user)):
    docs = await db.links.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@api_router.post("/links")
async def create_link(data: WebLinkInput, user: User = Depends(get_current_user)):
    payload = data.model_dump()
    if payload["url"] and not payload["url"].startswith(("http://", "https://")):
        payload["url"] = "https://" + payload["url"]
    link = WebLink(**payload, user_id=user.user_id)
    await db.links.insert_one(link.model_dump())
    return link.model_dump()


@api_router.put("/links/{lid}")
async def update_link(lid: str, data: WebLinkInput, user: User = Depends(get_current_user)):
    payload = data.model_dump()
    if payload["url"] and not payload["url"].startswith(("http://", "https://")):
        payload["url"] = "https://" + payload["url"]
    res = await db.links.update_one({"id": lid, "user_id": user.user_id}, {"$set": payload})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"ok": True}


@api_router.delete("/links/{lid}")
async def delete_link(lid: str, user: User = Depends(get_current_user)):
    await db.links.delete_one({"id": lid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Trade unions ----------
@api_router.get("/trade-unions")
async def list_trade_unions(user: User = Depends(get_current_user)):
    return await db.trade_unions.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@api_router.post("/trade-unions")
async def create_trade_union(data: TradeUnionInput, user: User = Depends(get_current_user)):
    tu = TradeUnion(**data.model_dump(), user_id=user.user_id)
    await db.trade_unions.insert_one(tu.model_dump())
    return tu.model_dump()


@api_router.put("/trade-unions/{tid}")
async def update_trade_union(tid: str, data: TradeUnionInput, user: User = Depends(get_current_user)):
    res = await db.trade_unions.update_one({"id": tid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Trade union not found")
    return {"ok": True}


@api_router.delete("/trade-unions/{tid}")
async def delete_trade_union(tid: str, user: User = Depends(get_current_user)):
    await db.trade_unions.delete_one({"id": tid, "user_id": user.user_id})
    return {"ok": True}


STARTER_LINKS = {
    "UK": [
        {"title": "Vehicle Operator Licensing (VOL) self-service", "url": "https://www.vehicle-operator-licensing.service.gov.uk", "category": "Portal / Login"},
        {"title": "GOV.UK — Vehicle operator licensing", "url": "https://www.gov.uk/vehicle-operator-licensing", "category": "Government / Authority"},
        {"title": "DVSA — Guide to maintaining roadworthiness", "url": "https://www.gov.uk/government/publications/guide-to-maintaining-roadworthiness", "category": "Legislation"},
        {"title": "Check MOT history", "url": "https://www.check-mot.service.gov.uk", "category": "Portal / Login"},
        {"title": "DVSA Earned Recognition", "url": "https://www.gov.uk/government/collections/dvsa-earned-recognition", "category": "Government / Authority"},
        {"title": "Drivers' hours & tachograph rules", "url": "https://www.gov.uk/drivers-hours", "category": "Legislation"},
    ],
    "IE": [
        {"title": "RSA — CVRT (Commercial Vehicle Roadworthiness Test)", "url": "https://www.cvrt.ie", "category": "Government / Authority"},
        {"title": "Road Transport Operator Licence (gov.ie)", "url": "https://www.gov.ie/en/service/8fcb1-apply-for-a-road-transport-operator-licence/", "category": "Portal / Login"},
        {"title": "RSA — Commercial vehicle owners", "url": "https://www.rsa.ie/services/commercial-vehicle-owners", "category": "Government / Authority"},
        {"title": "RSA — EU drivers' hours & tachograph", "url": "https://www.rsa.ie/services/professional-drivers/eu-drivers-hours-and-tachograph", "category": "Legislation"},
        {"title": "Certificate of Roadworthiness (CRW)", "url": "https://www.cvrt.ie/en/crw", "category": "Government / Authority"},
    ],
}


@api_router.post("/links/seed")
async def seed_links(user: User = Depends(get_current_user)):
    region = "IE" if user.region == "IE" else "UK"
    existing = {l.get("url") for l in await db.links.find({"user_id": user.user_id}, {"_id": 0, "url": 1}).to_list(1000)}
    added = 0
    for s in STARTER_LINKS[region]:
        if s["url"] in existing:
            continue
        await db.links.insert_one(WebLink(**s, user_id=user.user_id).model_dump())
        added += 1
    return {"ok": True, "added": added, "region": region}


# ---------- Company document generator ----------
LETTER_GUIDES = {
    "Warning Letter": "a formal disciplinary warning letter to an employee driver. Reference the conduct/incident, state this is a formal warning, note expected improvement, consequences of repeat, and right to appeal.",
    "Employment Offer Letter": "a formal job offer letter for a driver/employee. State the role, start date, salary/rate, hours, and that a contract will follow. Warm but professional.",
    "Contract of Employment": "a concise contract of employment summary covering job title, start date, place of work, hours, pay, holiday, notice period and reference to company policies.",
    "Reference Letter": "a professional employment reference confirming the person's role, dates of employment, conduct and reliability.",
    "Disciplinary Invite": "a formal letter inviting the employee to a disciplinary hearing: date/time/place, the matter to be discussed, right to be accompanied, and possible outcomes.",
    "Disciplinary Outcome": "a formal letter confirming the outcome of a disciplinary hearing, the decision reached, any sanction, improvement required and appeal rights.",
    "Return to Work": "a return-to-work / fitness confirmation letter after absence, confirming duties resumed and any adjustments.",
    "PRSI Letter": "a formal PRSI (Pay Related Social Insurance, Ireland) letter for an employee driver. Cover the employee's PRSI class/contributions, their PPS number where provided, employer registration details, and confirm the employer's PRSI obligations. Use Irish employment terminology.",
    "CMR Consignment Note": "a CMR international road consignment note (per the CMR Convention). Lay out clearly labelled fields for: Sender (consignor) name & address, Consignee name & address, Place & date of taking over the goods, Place designated for delivery, Carrier name & address, Successive carriers, Marks & numbers / number of packages, Method of packing, Nature of the goods, Gross weight, Volume, Sender's instructions (customs/other), Carriage charges, Reservations & observations of the carrier, Documents attached, and Signatures/stamps of sender, carrier and consignee. Present it as a structured consignment note using the details provided.",
    "Proof of Delivery (POD)": "a Proof of Delivery (POD) note confirming goods were delivered. Include: consignment/reference number, date & time of delivery, collection & delivery addresses, description and quantity of goods/packages, vehicle registration, driver name, any damages/shortages/discrepancies noted on delivery, and signature lines for the receiver (name in capitals, signature, date/time) and the driver. Use the details provided.",
    "Waste Transfer Note": "a Duty of Care Waste Transfer Note (UK Environmental Protection Act 1990 / relevant waste regs). Include: transferor (producer/holder) name, address & waste carrier registration if applicable, transferee (carrier/receiver) name, address & waste carrier/broker licence number, description of the waste, EWC/waste code where given, quantity, container/packaging type, the SIC code, place & date of transfer, and declarations plus signatures for both parties confirming compliance with the duty of care. Use the details provided.",
    "Driver Infringement": "a formal Driver Infringement notification to a driver following a tachograph / drivers' hours infringement. Clearly set out each infringement (type, date/time, and the specific EU 561/2006 or GB domestic rule breached), explain why it matters for road safety and the operator's licence, require the driver's signature to acknowledge, and state the corrective action / re-training expected. Professional and factual.",
    "Adhoc Note": "a short, dated ad-hoc file note recording a one-off event, conversation or observation relating to a driver or vehicle (e.g. a verbal reminder, a minor issue raised, an informal discussion). Keep it concise, factual and suitable for the compliance file.",
    "Attestation Record": "a driver attestation / declaration record confirming the driver has read, understood and will comply with the operator's drivers' hours, tachograph, working time and vehicle-use policies. Include statements to be signed and dated by the driver, and a space for the transport manager to countersign.",
    "Indoctrination Document": "a new-driver induction / indoctrination record documenting the operator's induction of a driver: company policies covered (drivers' hours, tachograph use, walkaround checks, defect reporting, working time, load security, drug & alcohol), licence/CPC/tacho card checks carried out, and vehicle familiarisation. Provide signature and date lines for both driver and transport manager.",
    "Infringement Report": "a formal Infringement Report summarising tachograph / drivers' hours infringements identified over a period for a driver or the fleet. Present the infringements clearly (type, date, rule breached, severity), the total count, the pattern/analysis, the action taken by the operator, and a sign-off by the transport manager. Suitable as evidence of the operator's infringement management for DVSA/RSA.",
}


@api_router.post("/documents/draft")
async def draft_document(data: LetterDraftInput, user: User = Depends(get_current_user)):
    op = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    guide = LETTER_GUIDES.get(data.template, f"a formal '{data.template}' business letter")
    company = op.get("company_name") or "the company"
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        system = (
            "You are a UK road-haulage HR and compliance assistant. You draft professional, legally-sensible "
            "business letters for a transport operator. Use British English, a formal but human tone. "
            "Do NOT include the date, addresses, 'Dear ...' greeting or 'Yours sincerely' sign-off — ONLY the subject line "
            "and the body paragraphs (those are added by the template). "
            "Return STRICT JSON: {\"subject\": \"...\", \"body\": \"...\"} where body uses \\n\\n between paragraphs."
        )
        prompt = (
            f"Company: {company}. Draft {guide}\n"
            f"Recipient: {data.recipient_name or 'the employee'}.\n"
            f"Context / key points to include:\n{data.points or '(no specific points provided — write a sensible standard version)'}"
        )
        chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"letter_{uuid.uuid4().hex[:8]}", system_message=system).with_model("openai", "gpt-5.4")
        resp = await chat.send_message(UserMessage(text=prompt))
        text = resp if isinstance(resp, str) else str(resp)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(m.group(0)) if m else {"subject": data.template, "body": text}
        return {"subject": parsed.get("subject", data.template), "body": parsed.get("body", "")}
    except Exception as e:
        logging.error(f"Letter draft failed: {e}")
        raise HTTPException(status_code=502, detail="Could not draft letter")


@api_router.post("/documents/generate")
async def generate_document(data: LetterGenerateInput, user: User = Depends(get_current_user)):
    att = await _render_letter_attachment(user, data)
    doc = ComplianceDoc(
        user_id=user.user_id,
        title=data.title or f"{data.template} — {data.recipient_name}".strip(" —"),
        doc_type=data.template,
        reference=data.subject,
        notes=f"v1 · generated {datetime.now(timezone.utc).strftime('%d %b %Y')}",
        letter_data={**data.model_dump(), "version": 1},
        attachments=[att],
    )
    await db.documents.insert_one(doc.model_dump())
    return doc.model_dump()


@api_router.put("/documents/{docid}/regenerate")
async def regenerate_document(docid: str, data: LetterGenerateInput, user: User = Depends(get_current_user)):
    existing = await db.documents.find_one({"id": docid, "user_id": user.user_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail="Document not found")
    for old in (existing.get("attachments") or []):
        if old.get("file_id"):
            await db.files.update_one({"id": old["file_id"], "user_id": user.user_id}, {"$set": {"is_deleted": True}})
    version = ((existing.get("letter_data") or {}).get("version", 1) or 1) + 1
    att = await _render_letter_attachment(user, data)
    await db.documents.update_one({"id": docid, "user_id": user.user_id}, {"$set": {
        "title": data.title or f"{data.template} — {data.recipient_name}".strip(" —"),
        "doc_type": data.template,
        "reference": data.subject,
        "notes": f"v{version} · updated {datetime.now(timezone.utc).strftime('%d %b %Y')}",
        "letter_data": {**data.model_dump(), "version": version},
        "attachments": [att.model_dump()],
    }})
    return {"ok": True, "version": version}


async def _render_letter_attachment(user: User, data: LetterGenerateInput) -> Attachment:
    op = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    signoff_name = data.signoff_name or op.get("tm_name") or ""
    signoff_role = data.signoff_role or ("Transport Manager" if op.get("tm_name") else "")
    date_str = datetime.now(timezone.utc).strftime("%d %B %Y")
    logo_bytes = await _get_logo_bytes(user.user_id, op)
    try:
        pdf_bytes = await asyncio.to_thread(
            build_letter_pdf, op, data.recipient_name, data.recipient_address, data.subject, data.body,
            date_str, data.template, signoff_name, signoff_role, logo_bytes,
        )
    except Exception as e:
        logging.error(f"Letter PDF build failed: {e}")
        raise HTTPException(status_code=500, detail="Could not build PDF")
    file_id = uuid.uuid4().hex
    fname = f"{data.template.replace(' ', '_')}_{(data.recipient_name or 'letter').replace(' ', '_')}.pdf"
    path = f"{APP_NAME}/uploads/{user.user_id}/{file_id}.pdf"
    try:
        result = await asyncio.to_thread(put_object, path, pdf_bytes, "application/pdf")
    except Exception as e:
        logging.error(f"Letter upload failed: {e}")
        raise HTTPException(status_code=502, detail="Upload failed")
    await db.files.insert_one({
        "id": file_id, "user_id": user.user_id, "storage_path": result["path"],
        "original_filename": fname, "content_type": "application/pdf",
        "size": result.get("size", len(pdf_bytes)), "is_deleted": False, "created_at": now_iso(),
    })
    return Attachment(file_id=file_id, filename=fname, content_type="application/pdf")


LITRES_PER_GALLON = 4.54609
CO2_PER_LITRE_DIESEL = 2.64


def _enrich_fuel(records: list) -> list:
    """Diesel fills drive MPG/CO2 (miles from odometer between diesel fills). AdBlue fills are usage-only."""
    diesel = [r for r in records if (r.get("fill_type") or "diesel") == "diesel"]
    adblue = [r for r in records if (r.get("fill_type") or "diesel") == "adblue"]
    by_veh = {}
    for r in diesel:
        by_veh.setdefault(r.get("vehicle_reg"), []).append(r)
    out = []
    for reg, recs in by_veh.items():
        recs.sort(key=lambda x: ((x.get("odometer") or 0), x.get("fill_date") or ""))
        prev_odo = None
        for r in recs:
            odo = r.get("odometer") or 0
            litres = r.get("litres") or 0
            miles = (odo - prev_odo) if (prev_odo is not None and odo and odo > prev_odo) else None
            gallons = litres / LITRES_PER_GALLON if litres else 0
            r["miles"] = round(miles, 1) if miles is not None else None
            r["mpg"] = round(miles / gallons, 1) if (miles is not None and gallons) else None
            r["co2_kg"] = round(litres * CO2_PER_LITRE_DIESEL, 1)
            out.append(r)
            if odo:
                prev_odo = odo
    for r in adblue:
        r["miles"] = None
        r["mpg"] = None
        r["co2_kg"] = 0
        out.append(r)
    out.sort(key=lambda x: (x.get("fill_date") or "", x.get("created_at") or ""), reverse=True)
    return out


@api_router.get("/fuel")
async def list_fuel(user: User = Depends(get_current_user)):
    recs = await db.fuel.find({"user_id": user.user_id}, {"_id": 0}).to_list(5000)
    return _enrich_fuel(recs)


@api_router.get("/fuel/summary")
async def fuel_summary(user: User = Depends(get_current_user)):
    recs = _enrich_fuel(await db.fuel.find({"user_id": user.user_id}, {"_id": 0}).to_list(5000))
    per_vehicle = {}
    for r in recs:
        reg = r.get("vehicle_reg")
        is_diesel = (r.get("fill_type") or "diesel") == "diesel"
        pv = per_vehicle.setdefault(reg, {"vehicle_reg": reg, "diesel_litres": 0, "adblue_litres": 0,
                                          "diesel_cost": 0, "adblue_cost": 0, "miles": 0, "co2_kg": 0,
                                          "diesel_fills": 0, "adblue_fills": 0, "_mpg_litres": 0})
        if is_diesel:
            pv["diesel_litres"] += r.get("litres") or 0
            pv["diesel_cost"] += r.get("cost") or 0
            pv["miles"] += r.get("miles") or 0
            pv["co2_kg"] += r.get("co2_kg") or 0
            pv["diesel_fills"] += 1
            if r.get("miles") is not None:
                pv["_mpg_litres"] += r.get("litres") or 0
        else:
            pv["adblue_litres"] += r.get("litres") or 0
            pv["adblue_cost"] += r.get("cost") or 0
            pv["adblue_fills"] += 1
    vehicles = []
    fleet_mpg_litres = 0
    for pv in per_vehicle.values():
        gallons = pv["_mpg_litres"] / LITRES_PER_GALLON if pv["_mpg_litres"] else 0
        pv["avg_mpg"] = round(pv["miles"] / gallons, 1) if (pv["miles"] and gallons) else None
        pv["cost_per_mile"] = round(pv["diesel_cost"] / pv["miles"], 2) if pv["miles"] else None
        fleet_mpg_litres += pv["_mpg_litres"]
        pv.pop("_mpg_litres", None)
        pv["cost"] = round(pv["diesel_cost"] + pv["adblue_cost"], 1)
        for k in ("diesel_litres", "adblue_litres", "diesel_cost", "adblue_cost", "miles", "co2_kg"):
            pv[k] = round(pv[k], 1)
        vehicles.append(pv)
    vehicles.sort(key=lambda x: x["vehicle_reg"] or "")
    totals = {
        "diesel_litres": round(sum(v["diesel_litres"] for v in vehicles), 1),
        "adblue_litres": round(sum(v["adblue_litres"] for v in vehicles), 1),
        "diesel_cost": round(sum(v["diesel_cost"] for v in vehicles), 1),
        "adblue_cost": round(sum(v["adblue_cost"] for v in vehicles), 1),
        "cost": round(sum(v["cost"] for v in vehicles), 1),
        "miles": round(sum(v["miles"] for v in vehicles), 1),
        "co2_kg": round(sum(v["co2_kg"] for v in vehicles), 1),
        "diesel_fills": sum(v["diesel_fills"] for v in vehicles),
        "adblue_fills": sum(v["adblue_fills"] for v in vehicles),
    }
    g = fleet_mpg_litres / LITRES_PER_GALLON if fleet_mpg_litres else 0
    totals["avg_mpg"] = round(totals["miles"] / g, 1) if (totals["miles"] and g) else None
    totals["co2_tonnes"] = round(totals["co2_kg"] / 1000, 2)
    return {"vehicles": vehicles, "totals": totals}


@api_router.get("/fuel/report")
async def fuel_report(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    vehicle_reg: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    recs = _enrich_fuel(await db.fuel.find({"user_id": user.user_id}, {"_id": 0}).to_list(5000))
    if vehicle_reg:
        recs = [r for r in recs if r.get("vehicle_reg") == vehicle_reg]
    if from_date:
        recs = [r for r in recs if (r.get("fill_date") or "") >= from_date]
    if to_date:
        recs = [r for r in recs if (r.get("fill_date") or "") <= to_date]

    cur = "€" if user.region == "IE" else "£"
    per = {}
    for r in recs:
        reg = r.get("vehicle_reg")
        is_diesel = (r.get("fill_type") or "diesel") == "diesel"
        pv = per.setdefault(reg, {"diesel": 0, "adblue": 0, "diesel_cost": 0, "adblue_cost": 0,
                                  "miles": 0, "co2": 0, "diesel_fills": 0, "adblue_fills": 0, "mpg_litres": 0})
        if is_diesel:
            pv["diesel"] += r.get("litres") or 0
            pv["diesel_cost"] += r.get("cost") or 0
            pv["miles"] += r.get("miles") or 0
            pv["co2"] += r.get("co2_kg") or 0
            pv["diesel_fills"] += 1
            if r.get("miles") is not None:
                pv["mpg_litres"] += r.get("litres") or 0
        else:
            pv["adblue"] += r.get("litres") or 0
            pv["adblue_cost"] += r.get("cost") or 0
            pv["adblue_fills"] += 1

    veh_rows = []
    for reg in sorted(per):
        pv = per[reg]
        gal = pv["mpg_litres"] / LITRES_PER_GALLON if pv["mpg_litres"] else 0
        mpg = round(pv["miles"] / gal, 1) if (pv["miles"] and gal) else None
        cost = pv["diesel_cost"] + pv["adblue_cost"]
        cpm = round(pv["diesel_cost"] / pv["miles"], 2) if pv["miles"] else None
        veh_rows.append({"cells": [reg, round(pv["diesel"], 1), round(pv["adblue"], 1),
                                   round(pv["miles"], 1), mpg if mpg is not None else "—",
                                   round(pv["co2"], 1), f"{cur}{round(cost, 2)}",
                                   f"{cur}{cpm}" if cpm is not None else "—"]})

    tot_diesel = round(sum(p["diesel"] for p in per.values()), 1)
    tot_adblue = round(sum(p["adblue"] for p in per.values()), 1)
    tot_diesel_cost = round(sum(p["diesel_cost"] for p in per.values()), 2)
    tot_adblue_cost = round(sum(p["adblue_cost"] for p in per.values()), 2)
    tot_cost = round(tot_diesel_cost + tot_adblue_cost, 2)
    tot_miles = round(sum(p["miles"] for p in per.values()), 1)
    tot_co2 = round(sum(p["co2"] for p in per.values()), 1)
    tot_mpg_l = sum(p["mpg_litres"] for p in per.values())
    g = tot_mpg_l / LITRES_PER_GALLON if tot_mpg_l else 0
    fleet_mpg = round(tot_miles / g, 1) if (tot_miles and g) else None

    diesel_recs = [r for r in recs if (r.get("fill_type") or "diesel") == "diesel"]
    adblue_recs = [r for r in recs if (r.get("fill_type") or "diesel") == "adblue"]
    diesel_rows = [{"cells": [r.get("fill_date"), r.get("vehicle_reg"), r.get("litres") or 0,
                              r.get("odometer") or "—", r.get("miles") if r.get("miles") is not None else "—",
                              r.get("mpg") if r.get("mpg") is not None else "—",
                              r.get("co2_kg") or 0, f"{cur}{r.get('cost') or 0}"]}
                   for r in sorted(diesel_recs, key=lambda x: (x.get("fill_date") or ""), reverse=True)]
    adblue_rows = [{"cells": [r.get("fill_date"), r.get("vehicle_reg"), r.get("litres") or 0, f"{cur}{r.get('cost') or 0}"]}
                   for r in sorted(adblue_recs, key=lambda x: (x.get("fill_date") or ""), reverse=True)]

    sections = [
        {"type": "kv", "heading": "Summary", "pairs": [
            ("Diesel used", f"{tot_diesel} L  ({cur}{tot_diesel_cost})"),
            ("AdBlue used", f"{tot_adblue} L  ({cur}{tot_adblue_cost})"),
            ("Distance", f"{tot_miles} miles"), ("Fleet average MPG", fleet_mpg if fleet_mpg is not None else "—"),
            ("CO₂ emitted", f"{tot_co2} kg ({round(tot_co2/1000, 2)} t)"),
            ("Total spend", f"{cur}{tot_cost}"),
            ("Fills", f"{len(diesel_recs)} diesel · {len(adblue_recs)} AdBlue"),
        ]},
        {"heading": "Per-vehicle breakdown", "columns": ["Vehicle", "Diesel (L)", "AdBlue (L)", "Miles", "MPG", "CO₂ (kg)", "Spend", "Cost/mi"], "rows": veh_rows},
        {"heading": "Diesel fills", "columns": ["Date", "Vehicle", "Litres", "Odo", "Miles", "MPG", "CO₂", "Cost"], "rows": diesel_rows},
        {"heading": "AdBlue fills", "columns": ["Date", "Vehicle", "Litres", "Cost"], "rows": adblue_rows},
    ]
    period = f"{from_date or 'start'} → {to_date or 'today'}"
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    authority = "RSA (Ireland)" if user.region == "IE" else "DVSA (UK)"
    pdf = await asyncio.to_thread(
        build_report_pdf, "Fuel & AdBlue Usage Report", period,
        [("Operator", operator.get("company_name", "")), ("Vehicle", vehicle_reg or "All vehicles")],
        sections, await _get_logo_bytes(user.user_id, operator), authority)
    fname = f"fuel-report-{(from_date or 'all')}-to-{(to_date or 'now')}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


async def _report_data(user_id, kinds, from_date=None, to_date=None):
    """Fetch + status-enrich the collections needed for reports.

    from_date/to_date (YYYY-MM-DD) filter time-series records (defects, service,
    wheel, walkaround, tacho, pmi records) by their event date. Current-state
    records (vehicles, trailers, drivers, pmi schedules) are never date-filtered.
    """
    def in_range(rec, *fields):
        if not (from_date or to_date):
            return True
        val = ""
        for f in fields:
            val = rec.get(f)
            if val:
                break
        val = (val or "")[:10]
        if not val:
            return False
        if from_date and val < from_date:
            return False
        if to_date and val > to_date:
            return False
        return True

    out = {}
    if "vehicles" in kinds:
        vs = await db.vehicles.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        for d in vs:
            d["mot_status"] = compliance_status(days_until(d.get("mot_due")))
        out["vehicles"] = vs
    if "trailers" in kinds:
        ts = await db.trailers.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        for d in ts:
            d["mot_status"] = compliance_status(days_until(d.get("mot_due")))
        out["trailers"] = ts
    if "drivers" in kinds:
        ds = await db.drivers.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        for d in ds:
            d["licence_status"] = compliance_status(days_until(d.get("licence_expiry")))
        out["drivers"] = ds
    if "defects" in kinds:
        dfx = await db.defects.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        out["defects"] = [d for d in dfx if in_range(d, "defect_date", "created_at")]
    if "service" in kinds:
        sv = await db.service_records.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        for d in sv:
            d["status"] = compliance_status(days_until(d.get("next_service_due")))
        out["service"] = [d for d in sv if in_range(d, "service_date")]
    if "wheel" in kinds:
        ws = await db.wheel_audits.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        for d in ws:
            d["status"] = compliance_status(days_until(d.get("next_due")))
        out["wheel"] = [d for d in ws if in_range(d, "audit_date")]
    if "walkaround" in kinds:
        wk = await db.walkaround_checks.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        out["walkaround"] = [d for d in wk if in_range(d, "check_date")]
    if "weekly_walkaround" in kinds:
        ww = await db.weekly_walkarounds.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        out["weekly_walkaround"] = [d for d in ww if in_range(d, "week_start")]
    if "tacho" in kinds:
        tn = await db.tacho_analyses.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        out["tacho"] = [d for d in tn if in_range(d, "created_at")]
    if "pmi" in kinds:
        ps = await db.pmi_schedules.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
        for d in ps:
            d["status"] = compliance_status(days_until(d.get("next_due")))
        out["pmi"] = ps
        pr = await db.pmi_records.find({"user_id": user_id}, {"_id": 0}).to_list(5000)
        out["pmi_records"] = [d for d in pr if in_range(d, "inspection_date")]
    return out


_REPORT_BUILDERS = {
    "vehicles": (["vehicles"], lambda d, r: reports.vehicles_report(d["vehicles"], r)),
    "trailers": (["trailers"], lambda d, r: reports.trailers_report(d["trailers"], r)),
    "drivers": (["drivers"], lambda d, r: reports.drivers_report(d["drivers"], r)),
    "defects": (["defects"], lambda d, r: reports.defects_report(d["defects"], r)),
    "service": (["service"], lambda d, r: reports.service_report(d["service"], r)),
    "wheel": (["wheel"], lambda d, r: reports.wheel_report(d["wheel"], r)),
    "walkaround": (["walkaround"], lambda d, r: reports.walkaround_report(d["walkaround"], r)),
    "weekly_walkaround": (["weekly_walkaround"], lambda d, r: reports.weekly_walkaround_report(d["weekly_walkaround"], r)),
    "pmi": (["pmi"], lambda d, r: reports.pmi_report(d["pmi"], d["pmi_records"], r)),
    "tacho": (["tacho"], lambda d, r: reports.tacho_report(d["tacho"], r)),
    "audit": (["vehicles", "trailers", "drivers", "defects", "service", "wheel", "walkaround", "weekly_walkaround", "tacho", "pmi"],
              lambda d, r: reports.audit_pack(d, r)),
}


_REPORT_FILE_KEYS = {
    "defects": ["defects"], "service": ["service"], "wheel": ["wheel"],
    "walkaround": ["walkaround"], "pmi": ["pmi_records"],
    "audit": ["defects", "service", "wheel", "walkaround", "pmi_records"],
}


def _report_file_ids(kind, data):
    fids = []
    for key in _REPORT_FILE_KEYS.get(kind, []):
        for rec in data.get(key, []):
            for a in (rec.get("attachments") or []):
                if a.get("file_id"):
                    fids.append(a["file_id"])
    return fids


@api_router.get("/reports/{kind}")
async def download_report(kind: str, include_files: bool = Query(False), format: str = Query("pdf"),
                          from_date: str = Query(None), to_date: str = Query(None),
                          user: User = Depends(get_current_user)):
    spec = _REPORT_BUILDERS.get(kind)
    if not spec:
        raise HTTPException(status_code=404, detail="Unknown report type")
    kinds, builder = spec
    data = await _report_data(user.user_id, kinds, from_date, to_date)
    title, subtitle, sections = builder(data, user.region)
    if from_date or to_date:
        subtitle = f"{subtitle} · Period {from_date or 'start'} to {to_date or 'now'}"
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    authority = "RSA (Ireland)" if user.region == "IE" else "DVSA (UK)"
    if format == "json":
        return {
            "title": title, "subtitle": subtitle,
            "operator": operator.get("company_name", ""), "authority": authority,
            "generated": datetime.now(timezone.utc).isoformat(),
            "has_files": bool(_report_file_ids(kind, data)),
            "sections": sections,
        }
    pdf = await asyncio.to_thread(
        build_report_pdf, title, subtitle,
        [("Operator", operator.get("company_name", ""))], sections,
        await _get_logo_bytes(user.user_id, operator), authority)
    if include_files:
        pdf = await asyncio.to_thread(merge_pack, pdf, await _collect_files(user.user_id, _report_file_ids(kind, data)))
    suffix = "-pack" if include_files else ""
    fname = f"{kind}-report{suffix}-{datetime.now(timezone.utc).date().isoformat()}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api_router.post("/fuel")
async def create_fuel(data: FuelInput, user: User = Depends(get_current_user)):
    r = FuelRecord(**data.model_dump(), user_id=user.user_id)
    await db.fuel.insert_one(r.model_dump())
    return r.model_dump()


@api_router.put("/fuel/{fid}")
async def update_fuel(fid: str, data: FuelInput, user: User = Depends(get_current_user)):
    res = await db.fuel.update_one({"id": fid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Fuel record not found")
    return {"ok": True}


@api_router.delete("/fuel/{fid}")
async def delete_fuel(fid: str, user: User = Depends(get_current_user)):
    await db.fuel.delete_one({"id": fid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Insurance ----------
@api_router.get("/insurance")
async def list_insurance(user: User = Depends(get_current_user)):
    docs = await db.insurance.find({"user_id": user.user_id}, {"_id": 0}).sort("expiry_date", 1).to_list(1000)
    for d in docs:
        d["status"] = compliance_status(days_until(d.get("expiry_date")))
        d["days_left"] = days_until(d.get("expiry_date"))
    return docs


@api_router.post("/insurance")
async def create_insurance(data: InsuranceInput, user: User = Depends(get_current_user)):
    p = InsurancePolicy(**data.model_dump(), user_id=user.user_id)
    await db.insurance.insert_one(p.model_dump())
    return p.model_dump()


@api_router.put("/insurance/{iid}")
async def update_insurance(iid: str, data: InsuranceInput, user: User = Depends(get_current_user)):
    res = await db.insurance.update_one({"id": iid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Insurance policy not found")
    return {"ok": True}


@api_router.delete("/insurance/{iid}")
async def delete_insurance(iid: str, user: User = Depends(get_current_user)):
    await db.insurance.delete_one({"id": iid, "user_id": user.user_id})
    return {"ok": True}


INSURANCE_TYPES = ["Goods in Transit (GIT)", "Motor — Truck", "Motor — Trailer", "Green Card", "Public Liability (PL)", "Employers' Liability (EL)", "Other"]


def normalize_policy_type(raw: str) -> str:
    if not raw:
        return "Other"
    if raw in INSURANCE_TYPES:
        return raw
    s = raw.lower()
    if "goods in transit" in s or "git" in s:
        return "Goods in Transit (GIT)"
    if "employ" in s or s.strip() == "el":
        return "Employers' Liability (EL)"
    if "public" in s or s.strip() == "pl":
        return "Public Liability (PL)"
    if "green card" in s or "green" in s:
        return "Green Card"
    if "trailer" in s:
        return "Motor — Trailer"
    if "motor" in s or "truck" in s or "vehicle" in s or "fleet" in s:
        return "Motor — Truck"
    return "Other"


def infer_from_text(text: str) -> str:
    """Best-effort policy type from filename / policy number / insurer text."""
    t = (text or "").lower()
    if "trailer" in t:
        return "Motor — Trailer"
    if "goods in transit" in t or "git-" in t or re.search(r"\bgit\b", t):
        return "Goods in Transit (GIT)"
    if "green card" in t:
        return "Green Card"
    if "employ" in t:
        return "Employers' Liability (EL)"
    if "public liab" in t or "public liability" in t:
        return "Public Liability (PL)"
    if "liability" in t or "liab" in t:  # combined/generic liability → PL (best effort)
        return "Public Liability (PL)"
    if any(w in t for w in ("truck", "tractor", "motor", "fleet", "goods vehicle", "hgv", "lorry")):
        return "Motor — Truck"
    return "Other"


def classify_policy_type(ai_type: str, filename: str = "", policy_number: str = "", insurer: str = "") -> str:
    t = normalize_policy_type(ai_type)
    if t != "Other":
        return t
    return infer_from_text(f"{filename} {policy_number} {insurer}")


def is_combined_liability(text: str) -> bool:
    t = (text or "").lower()
    return "combined" in t and ("liab" in t)


async def ai_extract_insurance(file_bytes: bytes, mime: str, ext: str):
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent, FileContentWithMimeType
    system = (
        "You read UK & Ireland commercial vehicle insurance documents (certificates, schedules, cover notes) "
        "and extract structured data. Classify policy_type as EXACTLY one of: " + ", ".join(INSURANCE_TYPES) + ". "
        "Goods in Transit=GIT; Motor for the tractor unit=Motor — Truck; Motor for trailers=Motor — Trailer; "
        "international motor cover=Green Card. "
        "For liability: an Employers' Liability certificate/section (cover for employees/staff, legally required by the Employers' Liability Act) = Employers' Liability (EL); "
        "public/third-party liability (cover for injury/damage to the public or third parties) = Public Liability (PL). "
        "If a single document is a COMBINED liability policy covering both, choose EL if it contains an Employers' Liability certificate, otherwise PL. Do not use 'Other' for any liability document. "
        "Return ONLY minified JSON with keys: policy_type, insurer, policy_number, start_date (YYYY-MM-DD or null), "
        "expiry_date (YYYY-MM-DD or null), cover_amount (string incl currency symbol or ''), confidence (0-1), "
        "needs_review (true if you are unsure or the document is unclear). No prose, no code fences."
    )
    prompt = "Extract the insurance policy details from this document."
    tmp_path = None
    try:
        if (mime or "").startswith("image/"):
            b64 = base64.b64encode(file_bytes).decode("utf-8")
            chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"ins_{uuid.uuid4().hex[:8]}", system_message=system).with_model("openai", "gpt-4o")
            msg = UserMessage(text=prompt, file_contents=[ImageContent(b64)])
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
            tmp.write(file_bytes)
            tmp.flush()
            tmp.close()
            tmp_path = tmp.name
            chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"ins_{uuid.uuid4().hex[:8]}", system_message=system).with_model("gemini", "gemini-2.5-flash")
            msg = UserMessage(text=prompt, file_contents=[FileContentWithMimeType(mime or "application/pdf", tmp_path)])
        resp = await chat.send_message(msg)
        text = (resp if isinstance(resp, str) else str(resp)).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        s, e = text.find("{"), text.rfind("}")
        return json.loads(text[s:e + 1])
    except Exception as ex:
        logging.error(f"AI insurance extract failed: {ex}")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@api_router.post("/insurance/ai-import")
async def ai_import_insurance(files: List[UploadFile] = File(...), user: User = Depends(get_current_user)):
    created = []
    for file in files:
        data = await file.read()
        if not data:
            continue
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "bin"
        file_id = uuid.uuid4().hex
        content_type = file.content_type or MIME_TYPES.get(ext, "application/octet-stream")
        path = f"{APP_NAME}/uploads/{user.user_id}/{file_id}.{ext}"
        try:
            result = put_object(path, data, content_type)
        except Exception as e:
            logging.error(f"AI import upload failed: {e}")
            continue
        await db.files.insert_one({
            "id": file_id, "user_id": user.user_id, "storage_path": result["path"],
            "original_filename": file.filename, "content_type": content_type,
            "size": result.get("size", len(data)), "is_deleted": False, "created_at": now_iso(),
        })
        attachment = Attachment(file_id=file_id, filename=file.filename or "", content_type=content_type)
        extracted = await ai_extract_insurance(data, content_type, ext)
        # Combined liability policy → ensure one PL and one EL record (deduped), no fragment duplicates
        if extracted and is_combined_liability(f"{file.filename} {extracted.get('policy_type', '')}"):
            ins = extracted.get("insurer") or ""
            num = extracted.get("policy_number") or ""
            common = dict(
                insurer=ins, policy_number=num,
                start_date=extracted.get("start_date") or None, expiry_date=extracted.get("expiry_date") or None,
                cover_amount=str(extracted.get("cover_amount") or ""),
                notes="Combined liability policy (covers Public & Employers' Liability).", ai_extracted=True,
            )
            for ptype in ["Public Liability (PL)", "Employers' Liability (EL)"]:
                key = {"user_id": user.user_id, "policy_type": ptype}
                key["policy_number"] = num if num else ""
                if not num:
                    key["insurer"] = ins
                existing = await db.insurance.find_one(key, {"_id": 0})
                if existing:
                    fids = {a.get("file_id") for a in (existing.get("attachments") or [])}
                    if attachment.file_id not in fids:
                        await db.insurance.update_one({"id": existing["id"], "user_id": user.user_id}, {"$push": {"attachments": attachment.model_dump()}})
                    rid = existing["id"]
                else:
                    pol = InsurancePolicy(user_id=user.user_id, policy_type=ptype, attachments=[attachment], **common)
                    await db.insurance.insert_one(pol.model_dump())
                    rid = pol.id
                created.append({"id": rid, "filename": file.filename, "policy_type": ptype,
                                "insurer": ins, "expiry_date": common["expiry_date"], "needs_review": False})
            continue
        if extracted:
            ptype = classify_policy_type(extracted.get("policy_type"), file.filename or "", extracted.get("policy_number") or "", extracted.get("insurer") or "")
            conf = extracted.get("confidence", 0) or 0
            policy = InsurancePolicy(
                user_id=user.user_id, policy_type=ptype,
                insurer=extracted.get("insurer") or "", policy_number=extracted.get("policy_number") or "",
                start_date=extracted.get("start_date") or None, expiry_date=extracted.get("expiry_date") or None,
                cover_amount=str(extracted.get("cover_amount") or ""),
                needs_review=bool(extracted.get("needs_review")) or conf < 0.6,
                ai_extracted=True, attachments=[attachment],
            )
        else:
            policy = InsurancePolicy(
                user_id=user.user_id, policy_type=infer_from_text(file.filename or ""), needs_review=True, ai_extracted=True,
                attachments=[attachment], notes="AI could not read this document — please review manually.",
            )
        await db.insurance.insert_one(policy.model_dump())
        created.append({"id": policy.id, "filename": file.filename, "policy_type": policy.policy_type,
                        "insurer": policy.insurer, "expiry_date": policy.expiry_date, "needs_review": policy.needs_review})
    return {"count": len(created), "created": created}


@api_router.post("/insurance/reclassify")
async def reclassify_insurance(user: User = Depends(get_current_user)):
    docs = await db.insurance.find({"user_id": user.user_id, "policy_type": "Other"}, {"_id": 0}).to_list(1000)
    moved = 0
    for d in docs:
        atts = d.get("attachments") or []
        fn = atts[0].get("filename", "") if atts else ""
        new_type = "Other"
        # 1) Re-read the actual document content with AI (most accurate, distinguishes PL vs EL)
        if atts and atts[0].get("file_id"):
            frec = await db.files.find_one({"id": atts[0]["file_id"], "user_id": user.user_id, "is_deleted": False}, {"_id": 0})
            if frec:
                try:
                    content, ctype = await asyncio.to_thread(get_object, frec["storage_path"])
                    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "pdf"
                    extracted = await ai_extract_insurance(content, frec.get("content_type") or ctype, ext)
                    if extracted:
                        new_type = classify_policy_type(
                            extracted.get("policy_type"), fn,
                            extracted.get("policy_number") or d.get("policy_number", ""),
                            extracted.get("insurer") or d.get("insurer", ""),
                        )
                except Exception as e:
                    logging.error(f"Reclassify content read failed for {d.get('id')}: {e}")
        # 2) Fallback: filename / number / insurer heuristics
        if new_type == "Other":
            new_type = infer_from_text(f"{fn} {d.get('policy_number', '')} {d.get('insurer', '')}")
        if new_type != "Other":
            await db.insurance.update_one({"id": d["id"], "user_id": user.user_id}, {"$set": {"policy_type": new_type}})
            moved += 1
    return {"ok": True, "moved": moved, "checked": len(docs)}


# ---------- Tacho Portal ----------
def compute_next_due(last: Optional[str], days: int) -> Optional[str]:
    base = last or now_iso()
    try:
        return (datetime.fromisoformat(base) + timedelta(days=days)).date().isoformat()
    except Exception:
        return None


@api_router.get("/tacho")
async def list_tacho(user: User = Depends(get_current_user)):
    docs = await db.tacho.find({"user_id": user.user_id}, {"_id": 0}).sort("next_due", 1).to_list(1000)
    for d in docs:
        d["status"] = compliance_status(days_until(d.get("next_due")), soon_days=TACHO_SOON_DAYS)
        d["days_left"] = days_until(d.get("next_due"))
    return docs


@api_router.post("/tacho")
async def create_tacho(data: TachoInput, user: User = Depends(get_current_user)):
    payload = data.model_dump()
    t = TachoRecord(**payload, user_id=user.user_id)
    t.next_due = compute_next_due(t.last_download, t.frequency_days)
    await db.tacho.insert_one(t.model_dump())
    return t.model_dump()


@api_router.put("/tacho/{tid}")
async def update_tacho(tid: str, data: TachoInput, user: User = Depends(get_current_user)):
    payload = data.model_dump()
    payload["next_due"] = compute_next_due(payload.get("last_download"), payload.get("frequency_days", 28))
    res = await db.tacho.update_one({"id": tid, "user_id": user.user_id}, {"$set": payload})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Tacho record not found")
    return {"ok": True, "next_due": payload["next_due"]}


@api_router.post("/tacho/{tid}/download")
async def log_tacho_download(tid: str, payload: dict, user: User = Depends(get_current_user)):
    rec = await db.tacho.find_one({"id": tid, "user_id": user.user_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Tacho record not found")
    dl_date = payload.get("download_date") or now_iso()[:10]
    attachments = rec.get("attachments", [])
    if payload.get("attachment"):
        attachments = attachments + [payload["attachment"]]
    next_due = compute_next_due(dl_date, rec.get("frequency_days", 28))
    await db.tacho.update_one({"id": tid}, {"$set": {"last_download": dl_date, "next_due": next_due, "attachments": attachments}})
    return {"ok": True, "last_download": dl_date, "next_due": next_due}


@api_router.delete("/tacho/{tid}")
async def delete_tacho(tid: str, user: User = Depends(get_current_user)):
    await db.tacho.delete_one({"id": tid, "user_id": user.user_id})
    return {"ok": True}


async def run_tacho_analysis(data: bytes, mime: str, ext: str, region: str, driver_name: str):
    """Route .ddd digital-tacho downloads to the deterministic decoder; everything else to the AI vision analyser."""
    if (ext or "").lower() in _DDD_EXTS:
        decoded = await asyncio.to_thread(parse_ddd, data)
        if decoded.get("found"):
            return detect_ddd_infringements(decoded, driver_name, region)
        last = parse_ddd_last_timestamp(data)
        return {
            "driver_name": driver_name, "period": f"last activity {last}" if last else "",
            "summary": ("This .ddd file could not be decoded into driver activity records — it may be a vehicle-unit "
                        "download, encrypted, or an unsupported format. Upload the operator's tacho analysis printout "
                        "(PDF or image) instead for AI infringement analysis."),
            "total_infringements": 0, "infringements": [], "confidence": 0,
        }
    return await ai_analyse_tacho(data, mime, ext, region, driver_name) or {}


async def ai_extract_tacho(file_bytes: bytes, mime: str, ext: str):
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent, FileContentWithMimeType
    system = (
        "You read tachograph analysis reports and driver-card/vehicle-unit printouts. Extract: "
        "last_download (the most recent download date or card-read/print date, YYYY-MM-DD or null) and "
        "infringements (integer count of infringements/violations/offences noted, else 0). "
        "Return ONLY minified JSON {\"last_download\": ..., \"infringements\": ..., \"confidence\": 0-1}. No prose."
    )
    tmp_path = None
    try:
        if (mime or "").startswith("image/"):
            b64 = base64.b64encode(file_bytes).decode("utf-8")
            chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"tac_{uuid.uuid4().hex[:8]}", system_message=system).with_model("openai", "gpt-4o")
            msg = UserMessage(text="Extract tacho details from this report.", file_contents=[ImageContent(b64)])
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
            tmp.write(file_bytes)
            tmp.flush()
            tmp.close()
            tmp_path = tmp.name
            chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"tac_{uuid.uuid4().hex[:8]}", system_message=system).with_model("gemini", "gemini-2.5-flash")
            msg = UserMessage(text="Extract tacho details from this report.", file_contents=[FileContentWithMimeType(mime or "application/pdf", tmp_path)])
        resp = await chat.send_message(msg)
        text = (resp if isinstance(resp, str) else str(resp)).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        s, e = text.find("{"), text.rfind("}")
        return json.loads(text[s:e + 1])
    except Exception as ex:
        logging.error(f"AI tacho extract failed: {ex}")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@api_router.post("/tacho/parse")
async def parse_tacho(payload: TachoParseInput, user: User = Depends(get_current_user)):
    rec = await db.files.find_one({"id": payload.file_id, "user_id": user.user_id, "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    data, ct = get_object(rec["storage_path"])
    ct = rec.get("content_type") or ct
    ext = (rec.get("original_filename") or "").rsplit(".", 1)[-1].lower()
    ai_types = (ct or "").startswith("image/") or (ct or "").startswith("text/") or ct == "application/pdf"
    if ai_types or ext in ("pdf", "txt", "csv"):
        extracted = await ai_extract_tacho(data, ct, ext) or {}
        return {"last_download": extracted.get("last_download"), "infringements": extracted.get("infringements"), "method": "ai"}
    last = parse_ddd_last_timestamp(data)
    return {"last_download": last, "infringements": None, "method": "binary"}


async def ai_analyse_tacho(file_bytes: bytes, mime: str, ext: str, region: str, driver_name: str):
    from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent, FileContentWithMimeType
    is_ie = (region or "UK").upper() in ("IE", "IRELAND", "RSA")
    rules = (
        "EU Regulation (EC) 561/2006 drivers' hours rules as enforced by the RSA in Ireland"
        if is_ie else
        "GB domestic and EU Regulation (EC) 561/2006 drivers' hours rules as enforced by the DVSA in the UK"
    )
    system = (
        "You are an expert tachograph analyst for a road-haulage operator. You examine a driver-card / "
        "vehicle-unit printout or tachograph analysis report and identify drivers' hours infringements under "
        f"{rules}. Check for: exceeding 4.5h continuous driving without a 45-min break, daily driving limit "
        "(9h, extendable to 10h twice a week), weekly (56h) and fortnightly (90h) driving limits, insufficient "
        "daily rest (11h, reduced 9h), insufficient weekly rest, missing/insufficient breaks, and card-missing / "
        "mode-switch anomalies. For EACH infringement return: type, datetime (ISO or best-effort), rule (the specific "
        "regulation/limit breached), severity (one of minor, serious, very_serious), detail (what happened), and "
        "action (recommended operator action). Then give an overall summary. "
        "Return ONLY minified JSON: {\"driver_name\":..,\"period\":..,\"summary\":..,\"total_infringements\":int,"
        "\"infringements\":[{\"type\":..,\"datetime\":..,\"rule\":..,\"severity\":..,\"detail\":..,\"action\":..}],"
        "\"confidence\":0-1}. If the file is unreadable or not a tacho printout, return total_infringements 0 with a "
        "summary saying so. No prose outside the JSON."
    )
    hint = f"Driver: {driver_name}. " if driver_name else ""
    tmp_path = None
    try:
        if (mime or "").startswith("image/"):
            b64 = base64.b64encode(file_bytes).decode("utf-8")
            chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"tana_{uuid.uuid4().hex[:8]}", system_message=system).with_model("openai", "gpt-4o")
            msg = UserMessage(text=f"{hint}Analyse this tachograph printout for drivers' hours infringements.", file_contents=[ImageContent(b64)])
        else:
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}")
            tmp.write(file_bytes)
            tmp.flush()
            tmp.close()
            tmp_path = tmp.name
            chat = LlmChat(api_key=EMERGENT_LLM_KEY, session_id=f"tana_{uuid.uuid4().hex[:8]}", system_message=system).with_model("gemini", "gemini-2.5-flash")
            msg = UserMessage(text=f"{hint}Analyse this tachograph report for drivers' hours infringements.", file_contents=[FileContentWithMimeType(mime or "application/pdf", tmp_path)])
        resp = await chat.send_message(msg)
        text = (resp if isinstance(resp, str) else str(resp)).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        s, e = text.find("{"), text.rfind("}")
        return json.loads(text[s:e + 1])
    except Exception as ex:
        logging.error(f"AI tacho analyse failed: {ex}")
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@api_router.post("/tacho/analyse")
async def analyse_tacho(payload: TachoAnalyseInput, user: User = Depends(get_current_user)):
    rec = await db.files.find_one({"id": payload.file_id, "user_id": user.user_id, "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="File not found")
    data, ct = get_object(rec["storage_path"])
    ct = rec.get("content_type") or ct
    ext = (rec.get("original_filename") or "").rsplit(".", 1)[-1].lower()
    result = await run_tacho_analysis(data, ct, ext, user.region, payload.driver_name) or {}
    infr = result.get("infringements") or []
    analysis = TachoAnalysis(
        user_id=user.user_id, driver_name=payload.driver_name or result.get("driver_name") or "",
        period=result.get("period") or "", summary=result.get("summary") or "",
        total_infringements=result.get("total_infringements") if isinstance(result.get("total_infringements"), int) else len(infr),
        infringements=infr, confidence=float(result.get("confidence") or 0), file_id=payload.file_id,
    )
    await db.tacho_analyses.insert_one(analysis.model_dump())
    return analysis.model_dump()


@api_router.get("/tacho/analyses")
async def list_tacho_analyses(user: User = Depends(get_current_user)):
    return await db.tacho_analyses.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", -1).to_list(500)


@api_router.get("/tacho/driver-summary")
async def tacho_driver_summary(user: User = Depends(get_current_user)):
    """Per-driver infringement rollup across all tacho analyses (repeat-offender view)."""
    analyses = await db.tacho_analyses.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000)
    by = {}
    for a in analyses:
        name = a.get("driver_name") or "Unassigned"
        d = by.setdefault(name, {
            "driver_name": name, "analyses": 0, "total_infringements": 0,
            "very_serious": 0, "serious": 0, "minor": 0, "last_analysed": None, "by_type": {},
        })
        d["analyses"] += 1
        d["total_infringements"] += a.get("total_infringements") or 0
        for i in (a.get("infringements") or []):
            sev = i.get("severity") or "minor"
            if sev in ("very_serious", "serious", "minor"):
                d[sev] += 1
            t = i.get("type") or "Other"
            d["by_type"][t] = d["by_type"].get(t, 0) + 1
        ca = a.get("created_at")
        if ca and (not d["last_analysed"] or ca > d["last_analysed"]):
            d["last_analysed"] = ca
    rows = sorted(by.values(), key=lambda x: (-x["total_infringements"], x["driver_name"]))
    totals = {
        "drivers": len(rows),
        "analyses": sum(r["analyses"] for r in rows),
        "infringements": sum(r["total_infringements"] for r in rows),
        "very_serious": sum(r["very_serious"] for r in rows),
        "serious": sum(r["serious"] for r in rows),
        "minor": sum(r["minor"] for r in rows),
    }
    return {"drivers": rows, "totals": totals}


async def _driver_analyses(user_id: str, name: str):
    q = {"user_id": user_id}
    if name and name != "Unassigned":
        q["driver_name"] = name
    else:
        q["$or"] = [{"driver_name": ""}, {"driver_name": None}, {"driver_name": {"$exists": False}}]
    return await db.tacho_analyses.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)


@api_router.get("/tacho/driver-detail")
async def tacho_driver_detail(name: str, user: User = Depends(get_current_user)):
    analyses = await _driver_analyses(user.user_id, name)
    infr = []
    for a in analyses:
        for i in (a.get("infringements") or []):
            infr.append({**i, "analysis_id": a.get("id"), "source_period": a.get("period", "")})
    sev_rank = {"very_serious": 0, "serious": 1, "minor": 2}
    infr.sort(key=lambda x: (x.get("datetime") or ""), reverse=True)
    counts = {"very_serious": 0, "serious": 0, "minor": 0}
    by_type = {}
    for i in infr:
        s = i.get("severity") or "minor"
        if s in counts:
            counts[s] += 1
        t = i.get("type") or "Other"
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "driver_name": name, "total": len(infr), "counts": counts, "by_type": by_type,
        "analyses": [{"id": a.get("id"), "period": a.get("period", ""), "created_at": a.get("created_at"),
                      "total_infringements": a.get("total_infringements", 0)} for a in analyses],
        "infringements": infr,
    }


@api_router.get("/tacho/driver-letter")
async def tacho_driver_letter(name: str, signoff_name: str = "", signoff_role: str = "Transport Manager",
                              user: User = Depends(get_current_user)):
    analyses = await _driver_analyses(user.user_id, name)
    infr = []
    for a in analyses:
        for i in (a.get("infringements") or []):
            infr.append(i)
    if not infr:
        raise HTTPException(status_code=400, detail="No infringements recorded for this driver")
    infr.sort(key=lambda x: (x.get("datetime") or ""))
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    is_ie = (user.region or "UK").upper() in ("IE", "IRELAND", "RSA")
    authority = "RSA (Ireland)" if is_ie else "DVSA (UK)"
    dates = [i.get("datetime", "")[:10] for i in infr if i.get("datetime")]
    period = f"{dates[0]} to {dates[-1]}" if dates else "the analysed period"
    sev_rank = {"very_serious": 0, "serious": 1, "minor": 2}
    type_counts = {}
    for i in infr:
        t = i.get("type") or "Other"
        type_counts[t] = type_counts.get(t, 0) + 1
    summary_lines = "\n".join(f"• {v} × {k}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1]))
    top = sorted(infr, key=lambda x: (sev_rank.get(x.get("severity"), 3), x.get("datetime") or ""))[:30]
    detail_lines = "\n".join(
        f"• {i.get('datetime', '')} — {i.get('type', '')} ({(i.get('severity') or '').replace('_', ' ')}): {i.get('detail', '')}"
        for i in top)
    more = f"\n\n(and {len(infr) - len(top)} further item(s) — see the full tacho analysis on file.)" if len(infr) > len(top) else ""
    body = (
        f"This letter concerns driver's hours and tachograph infringements identified from your digital tachograph "
        f"records covering {period}. Our analysis, carried out under {authority}-enforced EU Regulation 561/2006, "
        f"recorded {len(infr)} potential infringement(s):\n\n"
        f"{summary_lines}\n\n"
        f"The specific matters requiring your attention are:\n\n"
        f"{detail_lines}{more}\n\n"
        f"As the operator we are legally required to monitor drivers' hours and to take action where the rules are not "
        f"followed. You are reminded of your personal responsibility to observe daily and weekly driving limits, "
        f"breaks and rest periods, and to make correct manual entries where the tachograph cannot record your activity.\n\n"
        f"Please treat this as a formal notification. You are asked to acknowledge receipt and to ensure there is no "
        f"recurrence. Repeated or serious breaches may lead to further action under our disciplinary procedure and "
        f"could affect the operator's licence. If you believe any of the above is incorrect, please raise it with us "
        f"immediately so the record can be reviewed.\n\n"
        f"Please sign, date and return a copy of this letter to confirm you have read and understood its contents."
    )
    gen = datetime.now(timezone.utc).strftime("%d %B %Y")
    pdf = await asyncio.to_thread(
        build_letter_pdf, operator, name, "", "Driver's Hours Infringement Notification", body, gen,
        "Infringement Letter", signoff_name or (operator.get("contact_name") or ""), signoff_role,
        await _get_logo_bytes(user.user_id, operator))
    fname = f"infringement-letter-{(name or 'driver').replace(' ', '_')}-{datetime.now(timezone.utc).date().isoformat()}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api_router.delete("/tacho/analyses/{aid}")
async def delete_tacho_analysis(aid: str, user: User = Depends(get_current_user)):
    await db.tacho_analyses.delete_one({"id": aid, "user_id": user.user_id})
    return {"ok": True}


@api_router.get("/tacho/analyses/{aid}/report")
async def tacho_analysis_report(aid: str, user: User = Depends(get_current_user)):
    a = await db.tacho_analyses.find_one({"id": aid, "user_id": user.user_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Analysis not found")
    rows = [{"cells": [i.get("datetime") or "—", i.get("type") or "—", i.get("rule") or "—",
                       (i.get("severity") or "").replace("_", " "), i.get("detail") or "—", i.get("action") or "—"],
             "status": ("expired" if i.get("severity") in ("serious", "very_serious") else "due_soon")}
            for i in (a.get("infringements") or [])]
    sections = [
        {"type": "kv", "heading": "Analysis", "pairs": [
            ("Driver", a.get("driver_name") or "—"), ("Period", a.get("period") or "—"),
            ("Total infringements", a.get("total_infringements", 0)),
            ("AI confidence", f"{round((a.get('confidence') or 0) * 100)}%"),
            ("Summary", a.get("summary") or "—"),
        ]},
        {"heading": "Infringements", "columns": ["When", "Type", "Rule", "Severity", "Detail", "Action"], "rows": rows},
    ]
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    authority = "RSA (Ireland)" if user.region == "IE" else "DVSA (UK)"
    pdf = await asyncio.to_thread(
        build_report_pdf, "Tachograph Analysis", a.get("driver_name") or "",
        [("Operator", operator.get("company_name", ""))], sections,
        await _get_logo_bytes(user.user_id, operator), authority)
    fname = f"tacho-analysis-{(a.get('driver_name') or 'driver').replace(' ', '_')}-{datetime.now(timezone.utc).date().isoformat()}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- Defects ----------
async def summarise_defect(description: str, severity: str) -> str:
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"defect_{uuid.uuid4().hex[:8]}",
            system_message="You are a UK road haulage compliance assistant. Summarise vehicle defect reports into one concise professional line, note if it is safety-critical (roadworthiness), and recommend an action. Keep under 40 words.",
        ).with_model("openai", "gpt-5.4")
        msg = UserMessage(text=f"Severity: {severity}. Defect: {description}")
        resp = await chat.send_message(msg)
        return resp if isinstance(resp, str) else str(resp)
    except Exception as e:
        logging.error(f"AI summary failed: {e}")
        return ""


@api_router.get("/defects")
async def list_defects(user: User = Depends(get_current_user)):
    docs = await db.defects.find({"user_id": user.user_id}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    return docs


@api_router.post("/defects")
async def create_defect(data: DefectInput, user: User = Depends(get_current_user)):
    d = DefectReport(**data.model_dump(), user_id=user.user_id)
    d.ai_summary = await summarise_defect(data.description, data.severity)
    await db.defects.insert_one(d.model_dump())
    return d.model_dump()


@api_router.put("/defects/{did}/status")
async def update_defect_status(did: str, status: str, user: User = Depends(get_current_user)):
    res = await db.defects.update_one({"id": did, "user_id": user.user_id}, {"$set": {"status": status}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Defect not found")
    return {"ok": True}


@api_router.put("/defects/{did}/rectify")
async def rectify_defect(did: str, data: DefectRectifyInput, user: User = Depends(get_current_user)):
    upd = {"status": "rectified", "rectified_date": data.rectified_date or now_iso()[:10],
           "rectified_by": data.rectified_by, "rectification_notes": data.rectification_notes}
    res = await db.defects.update_one({"id": did, "user_id": user.user_id}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Defect not found")
    return {"ok": True}


@api_router.delete("/defects/{did}")
async def delete_defect(did: str, user: User = Depends(get_current_user)):
    await db.defects.delete_one({"id": did, "user_id": user.user_id})
    return {"ok": True}


# ---------- PMI Inspections ----------
def advance_due(inspection_date: str, weeks: int):
    if not weeks or weeks <= 0:
        return None
    d = datetime.fromisoformat(inspection_date)
    return (d + timedelta(weeks=weeks)).date().isoformat()


@api_router.get("/pmi")
async def list_pmi(user: User = Depends(get_current_user)):
    docs = await db.pmi_schedules.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    for d in docs:
        d["status"] = compliance_status(days_until(d.get("next_due")))
        d["days_left"] = days_until(d.get("next_due"))
    docs.sort(key=lambda x: x.get("next_due") or "9999")
    return docs


@api_router.post("/pmi")
async def create_pmi(data: PMIInput, user: User = Depends(get_current_user)):
    payload = data.model_dump()
    if not payload.get("next_due"):
        payload["next_due"] = advance_due(now_iso(), payload.get("frequency_weeks", 6))
    p = PMISchedule(**payload, user_id=user.user_id)
    await db.pmi_schedules.insert_one(p.model_dump())
    return p.model_dump()


@api_router.put("/pmi/{pid}")
async def update_pmi(pid: str, data: PMIInput, user: User = Depends(get_current_user)):
    res = await db.pmi_schedules.update_one({"id": pid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="PMI schedule not found")
    return {"ok": True}


@api_router.delete("/pmi/{pid}")
async def delete_pmi(pid: str, user: User = Depends(get_current_user)):
    await db.pmi_schedules.delete_one({"id": pid, "user_id": user.user_id})
    return {"ok": True}


@api_router.post("/pmi/{pid}/complete")
async def complete_pmi(pid: str, data: PMICompleteInput, user: User = Depends(get_current_user)):
    sched = await db.pmi_schedules.find_one({"id": pid, "user_id": user.user_id}, {"_id": 0})
    if not sched:
        raise HTTPException(status_code=404, detail="PMI schedule not found")
    record = {
        "id": f"pmr_{uuid.uuid4().hex[:10]}",
        "user_id": user.user_id,
        "pmi_id": pid,
        "vehicle_reg": sched["vehicle_reg"],
        "inspection_date": data.inspection_date,
        "result": data.result,
        "inspector": data.inspector,
        "rectified_by": data.rectified_by,
        "notes": data.notes,
        "brake_test_type": data.brake_test_type,
        "laden": data.laden,
        "service_brake_pct": data.service_brake_pct,
        "secondary_brake_pct": data.secondary_brake_pct,
        "parking_brake_pct": data.parking_brake_pct,
        "checklist": data.checklist,
        "attachments": [a.model_dump() for a in data.attachments],
        "inspector_signature": data.inspector_signature,
        "rectifier_signature": data.rectifier_signature,
        "odometer": data.odometer,
        "make_model": data.make_model,
        "inspection_type": "routine",
        "created_at": now_iso(),
    }
    await db.pmi_records.insert_one(dict(record))
    new_due = advance_due(data.inspection_date, sched.get("frequency_weeks", 6))
    await db.pmi_schedules.update_one({"id": pid}, {"$set": {"next_due": new_due}})
    record.pop("_id", None)
    if data.result == "fail":
        failed = [c.get("item") for c in (data.checklist or []) if not c.get("ok")]
        await create_alert(user.user_id, "pmi_fail", "safety_critical",
                           f"PMI FAILED — {sched['vehicle_reg']}",
                           (", ".join(failed) if failed else (data.notes or "PMI inspection failed")),
                           vehicle_reg=sched["vehicle_reg"], driver_name=data.inspector, link="/maintenance")
    return {"ok": True, "next_due": new_due, "record": record}


@api_router.post("/pmi/interim")
async def interim_pmi(data: PMIInterimInput, user: User = Depends(get_current_user)):
    """Record a standalone one-off / interim inspection with no recurring schedule."""
    if not data.vehicle_reg:
        raise HTTPException(status_code=400, detail="Vehicle is required")
    record = {
        "id": f"pmr_{uuid.uuid4().hex[:10]}",
        "user_id": user.user_id,
        "pmi_id": None,
        "vehicle_reg": data.vehicle_reg,
        "inspection_date": data.inspection_date,
        "result": data.result,
        "inspector": data.inspector,
        "rectified_by": data.rectified_by,
        "notes": data.notes,
        "brake_test_type": data.brake_test_type,
        "laden": data.laden,
        "service_brake_pct": data.service_brake_pct,
        "secondary_brake_pct": data.secondary_brake_pct,
        "parking_brake_pct": data.parking_brake_pct,
        "checklist": data.checklist,
        "attachments": [a.model_dump() for a in data.attachments],
        "inspector_signature": data.inspector_signature,
        "rectifier_signature": data.rectifier_signature,
        "odometer": data.odometer,
        "make_model": data.make_model,
        "inspection_type": "interim",
        "created_at": now_iso(),
    }
    await db.pmi_records.insert_one(dict(record))
    record.pop("_id", None)
    if data.result == "fail":
        failed = [c.get("item") for c in (data.checklist or []) if not c.get("ok")]
        await create_alert(user.user_id, "pmi_fail", "safety_critical",
                           f"Interim inspection FAILED — {data.vehicle_reg}",
                           (", ".join(failed) if failed else (data.notes or "Interim inspection failed")),
                           vehicle_reg=data.vehicle_reg, driver_name=data.inspector, link="/maintenance")
    return {"ok": True, "record": record}


@api_router.get("/pmi/records")
async def list_pmi_records(user: User = Depends(get_current_user)):
    docs = await db.pmi_records.find({"user_id": user.user_id}, {"_id": 0}).sort("inspection_date", -1).to_list(1000)
    return docs


@api_router.delete("/pmi/records/{rid}")
async def delete_pmi_record(rid: str, user: User = Depends(get_current_user)):
    await db.pmi_records.delete_one({"id": rid, "user_id": user.user_id})
    return {"ok": True}


@api_router.put("/pmi/records/{rid}")
async def update_pmi_record(rid: str, data: PMICompleteInput, user: User = Depends(get_current_user)):
    rec = await db.pmi_records.find_one({"id": rid, "user_id": user.user_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Inspection record not found")
    upd = {
        "inspection_date": data.inspection_date, "result": data.result, "inspector": data.inspector,
        "rectified_by": data.rectified_by, "notes": data.notes, "brake_test_type": data.brake_test_type,
        "laden": data.laden, "service_brake_pct": data.service_brake_pct,
        "secondary_brake_pct": data.secondary_brake_pct, "parking_brake_pct": data.parking_brake_pct,
        "checklist": data.checklist, "attachments": [a.model_dump() for a in data.attachments],
        "inspector_signature": data.inspector_signature, "rectifier_signature": data.rectifier_signature,
        "odometer": data.odometer, "make_model": data.make_model,
    }
    await db.pmi_records.update_one({"id": rid, "user_id": user.user_id}, {"$set": upd})
    return {"ok": True, "record": {**rec, **upd}}


@api_router.get("/pmi/records/{rid}/sheet")
async def pmi_record_sheet(rid: str, include_files: bool = Query(False), user: User = Depends(get_current_user)):
    rec = await db.pmi_records.find_one({"id": rid, "user_id": user.user_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Inspection record not found")
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    pdf = await asyncio.to_thread(
        build_pmi_sheet_pdf, operator, rec, user.region,
        await _get_logo_bytes(user.user_id, operator))
    if include_files:
        fids = [a.get("file_id") for a in (rec.get("attachments") or [])]
        pdf = await asyncio.to_thread(merge_pack, pdf, await _collect_files(user.user_id, fids))
    fname = f"inspection-sheet-{(rec.get('vehicle_reg') or 'vehicle').replace(' ', '_')}-{rec.get('inspection_date') or datetime.now(timezone.utc).date().isoformat()}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api_router.get("/pmi/{pid}/report")
async def pmi_history_report(pid: str, include_files: bool = Query(False), user: User = Depends(get_current_user)):
    sched = await db.pmi_schedules.find_one({"id": pid, "user_id": user.user_id}, {"_id": 0})
    if not sched:
        raise HTTPException(status_code=404, detail="PMI schedule not found")
    recs = await db.pmi_records.find({"pmi_id": pid, "user_id": user.user_id}, {"_id": 0}).to_list(2000)
    recs.sort(key=lambda r: r.get("inspection_date") or "", reverse=True)
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    logo = await _get_logo_bytes(user.user_id, operator)
    if recs:
        sheets = [await asyncio.to_thread(build_pmi_sheet_pdf, operator, r, user.region, logo) for r in recs]
        pdf = await asyncio.to_thread(concat_pdfs, sheets)
    else:
        authority = "RSA (Ireland)" if user.region == "IE" else "DVSA (UK)"
        title, subtitle, sections = reports.pmi_history_report(sched, recs, user.region)
        pdf = await asyncio.to_thread(
            build_report_pdf, title, subtitle,
            [("Operator", operator.get("company_name", ""))], sections, logo, authority)
    if include_files:
        fids = [a.get("file_id") for r in recs for a in (r.get("attachments") or [])]
        pdf = await asyncio.to_thread(merge_pack, pdf, await _collect_files(user.user_id, fids))
    fname = f"pmi-history-{(sched.get('vehicle_reg') or 'vehicle').replace(' ', '_')}-{datetime.now(timezone.utc).date().isoformat()}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# ---------- Wheel Security Audits ----------
@api_router.get("/wheel-audits")
async def list_wheel_audits(user: User = Depends(get_current_user)):
    docs = await db.wheel_audits.find({"user_id": user.user_id}, {"_id": 0}).sort("audit_date", -1).to_list(1000)
    for d in docs:
        d["status"] = compliance_status(days_until(d.get("next_due")))
        d["days_left"] = days_until(d.get("next_due"))
    return docs


@api_router.post("/wheel-audits")
async def create_wheel_audit(data: WheelAuditInput, user: User = Depends(get_current_user)):
    w = WheelAudit(**data.model_dump(), user_id=user.user_id)
    await db.wheel_audits.insert_one(w.model_dump())
    return w.model_dump()


@api_router.put("/wheel-audits/{wid}")
async def update_wheel_audit(wid: str, data: WheelAuditInput, user: User = Depends(get_current_user)):
    res = await db.wheel_audits.update_one({"id": wid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Wheel security audit not found")
    return {"ok": True}


@api_router.delete("/wheel-audits/{wid}")
async def delete_wheel_audit(wid: str, user: User = Depends(get_current_user)):
    await db.wheel_audits.delete_one({"id": wid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Service records ----------
@api_router.get("/service-records")
async def list_service(user: User = Depends(get_current_user)):
    docs = await db.service_records.find({"user_id": user.user_id}, {"_id": 0}).sort("service_date", -1).to_list(1000)
    for d in docs:
        d["status"] = compliance_status(days_until(d.get("next_service_due")))
        d["days_left"] = days_until(d.get("next_service_due"))
    return docs


@api_router.post("/service-records")
async def create_service(data: ServiceInput, user: User = Depends(get_current_user)):
    s = ServiceRecord(**data.model_dump(), user_id=user.user_id)
    await db.service_records.insert_one(s.model_dump())
    return s.model_dump()


@api_router.put("/service-records/{sid}")
async def update_service(sid: str, data: ServiceInput, user: User = Depends(get_current_user)):
    res = await db.service_records.update_one({"id": sid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Service record not found")
    return {"ok": True}


@api_router.delete("/service-records/{sid}")
async def delete_service(sid: str, user: User = Depends(get_current_user)):
    await db.service_records.delete_one({"id": sid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Daily Walkaround Checks ----------
@api_router.get("/walkarounds")
async def list_walkarounds(user: User = Depends(get_current_user)):
    return await db.walkaround_checks.find({"user_id": user.user_id}, {"_id": 0}).sort("check_date", -1).to_list(2000)


@api_router.post("/walkarounds")
async def create_walkaround(data: WalkaroundInput, user: User = Depends(get_current_user)):
    w = WalkaroundCheck(**data.model_dump(), user_id=user.user_id)
    await db.walkaround_checks.insert_one(w.model_dump())
    return w.model_dump()


@api_router.put("/walkarounds/{wid}")
async def update_walkaround(wid: str, data: WalkaroundInput, user: User = Depends(get_current_user)):
    res = await db.walkaround_checks.update_one({"id": wid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Walkaround check not found")
    return {"ok": True}


@api_router.delete("/walkarounds/{wid}")
async def delete_walkaround(wid: str, user: User = Depends(get_current_user)):
    await db.walkaround_checks.delete_one({"id": wid, "user_id": user.user_id})
    return {"ok": True}


@api_router.put("/walkarounds/{wid}/rectify")
async def rectify_walkaround(wid: str, data: WalkaroundRectifyInput, user: User = Depends(get_current_user)):
    res = await db.walkaround_checks.update_one(
        {"id": wid, "user_id": user.user_id},
        {"$set": {"rectified": True, "rectified_date": data.rectified_date or now_iso()[:10], "rectified_notes": data.rectified_notes}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Walkaround check not found")
    return {"ok": True}


# ---------- Weekly Walkaround Checks ----------
async def _get_or_create_weekly(user_id: str, vehicle_reg: str, week_start: str, driver_name: str = "") -> dict:
    existing = await db.weekly_walkarounds.find_one(
        {"user_id": user_id, "vehicle_reg": vehicle_reg, "week_start": week_start}, {"_id": 0})
    if existing:
        return existing
    w = WeeklyWalkaround(user_id=user_id, vehicle_reg=vehicle_reg, week_start=week_start, driver_name=driver_name)
    await db.weekly_walkarounds.insert_one(w.model_dump())
    return w.model_dump()


@api_router.get("/weekly-walkarounds")
async def list_weekly_walkarounds(user: User = Depends(get_current_user)):
    return await db.weekly_walkarounds.find({"user_id": user.user_id}, {"_id": 0}).sort("week_start", -1).to_list(2000)


@api_router.post("/weekly-walkarounds")
async def create_weekly_walkaround(data: WeeklyCreateInput, user: User = Depends(get_current_user)):
    ws = week_start_of(data.week_start)
    rec = await _get_or_create_weekly(user.user_id, data.vehicle_reg, ws, data.driver_name)
    patch = {}
    if data.driver_name:
        patch["driver_name"] = data.driver_name
    if data.mileage_start:
        patch["mileage_start"] = data.mileage_start
    if data.mileage_finish:
        patch["mileage_finish"] = data.mileage_finish
    if patch:
        patch["updated_at"] = now_iso()
        await db.weekly_walkarounds.update_one({"id": rec["id"], "user_id": user.user_id}, {"$set": patch})
        rec.update(patch)
    return rec


@api_router.put("/weekly-walkarounds/{wid}")
async def update_weekly_walkaround(wid: str, data: WeeklyUpdateInput, user: User = Depends(get_current_user)):
    patch = {k: v for k, v in data.model_dump().items() if v is not None}
    patch["updated_at"] = now_iso()
    res = await db.weekly_walkarounds.update_one({"id": wid, "user_id": user.user_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Weekly walkaround not found")
    return {"ok": True}


@api_router.delete("/weekly-walkarounds/{wid}")
async def delete_weekly_walkaround(wid: str, user: User = Depends(get_current_user)):
    await db.weekly_walkarounds.delete_one({"id": wid, "user_id": user.user_id})
    return {"ok": True}


@api_router.get("/weekly-walkarounds/{wid}/sheet")
async def weekly_walkaround_sheet(wid: str, user: User = Depends(get_current_user)):
    rec = await db.weekly_walkarounds.find_one({"id": wid, "user_id": user.user_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Weekly walkaround not found")
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    pdf = await asyncio.to_thread(
        build_weekly_walkaround_pdf, operator, rec, user.region,
        await _get_logo_bytes(user.user_id, operator))
    fname = f"weekly-walkaround-{(rec.get('vehicle_reg') or 'vehicle').replace(' ', '_')}-{rec.get('week_start')}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api_router.get("/driver/weekly-walkaround")
async def driver_get_weekly(driver: dict = Depends(get_current_driver)):
    reg = driver.get("assigned_vehicle_reg", "")
    ws = week_start_of(None)
    return await _get_or_create_weekly(driver["user_id"], reg, ws, driver.get("name", ""))


@api_router.post("/driver/weekly-walkaround/day")
async def driver_submit_weekly_day(data: WeeklyDayInput, driver: dict = Depends(get_current_driver)):
    reg = data.vehicle_reg or driver.get("assigned_vehicle_reg", "")
    today = datetime.now(timezone.utc).date()
    ws = week_start_of(None)
    dk = WEEK_DAYS[today.weekday()]
    rec = await _get_or_create_weekly(driver["user_id"], reg, ws, driver.get("name", ""))
    days = rec.get("days") or {}
    failed = [c.get("item") for c in data.checklist if not c.get("ok", True)]
    days[dk] = {
        "date": today.isoformat(),
        "checklist": data.checklist,
        "result": "defects_found" if failed else "nil_defect",
        "submitted_at": now_iso(),
    }
    patch = {"days": days, "updated_at": now_iso()}
    if data.mileage:
        if not rec.get("mileage_start"):
            patch["mileage_start"] = data.mileage
        patch["mileage_finish"] = data.mileage
    if data.signature and not rec.get("driver_signature"):
        patch["driver_signature"] = data.signature
    await db.weekly_walkarounds.update_one({"id": rec["id"], "user_id": driver["user_id"]}, {"$set": patch})
    if failed:
        await create_alert(driver["user_id"], "walkaround_defect", "major",
                           f"Weekly walkaround defect — {reg}", ", ".join(failed),
                           vehicle_reg=reg, driver_name=driver.get("name", ""), link="/maintenance")
    rec.update(patch)
    return rec


# ---------- Test History / Prohibitions ----------
@api_router.get("/test-history")
async def list_test_history(user: User = Depends(get_current_user)):
    return await db.test_history.find({"user_id": user.user_id}, {"_id": 0}).sort("event_date", -1).to_list(2000)


@api_router.post("/test-history")
async def create_test_history(data: TestHistoryInput, user: User = Depends(get_current_user)):
    t = TestHistory(**data.model_dump(), user_id=user.user_id)
    await db.test_history.insert_one(t.model_dump())
    return t.model_dump()


@api_router.put("/test-history/{tid}")
async def update_test_history(tid: str, data: TestHistoryInput, user: User = Depends(get_current_user)):
    res = await db.test_history.update_one({"id": tid, "user_id": user.user_id}, {"$set": data.model_dump()})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Test history record not found")
    return {"ok": True}


@api_router.delete("/test-history/{tid}")
async def delete_test_history(tid: str, user: User = Depends(get_current_user)):
    await db.test_history.delete_one({"id": tid, "user_id": user.user_id})
    return {"ok": True}


# ---------- Calendar ----------
@api_router.get("/calendar")
async def calendar(user: User = Depends(get_current_user)):
    events = []
    schedules = await db.pmi_schedules.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    horizon = (datetime.now(timezone.utc).date() + timedelta(weeks=52)).isoformat()
    for s in schedules:
        nd = s.get("next_due")
        fw = s.get("frequency_weeks", 6)
        if not nd:
            continue
        try:
            cur = datetime.fromisoformat(nd).date()
        except Exception:
            continue
        if not fw or fw <= 0:
            iso = cur.isoformat()
            events.append({
                "date": iso, "type": "pmi_due", "title": f"PMI Due — {s['vehicle_reg']}",
                "subtitle": "One-off / interim",
                "status": compliance_status(days_until(iso)),
            })
            continue
        first, count = True, 0
        while cur.isoformat() <= horizon and count < 26:
            iso = cur.isoformat()
            events.append({
                "date": iso, "type": "pmi_due", "title": f"PMI Due — {s['vehicle_reg']}",
                "subtitle": f"Every {fw} weeks" + ("" if first else " · planned"),
                "status": compliance_status(days_until(iso)) if first else "valid",
            })
            cur = cur + timedelta(weeks=fw)
            first, count = False, count + 1
    records = await db.pmi_records.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000)
    for r in records:
        events.append({
            "date": r["inspection_date"], "type": "pmi_done", "title": f"PMI Completed — {r['vehicle_reg']}",
            "subtitle": r.get("result", "pass").title(), "status": "expired" if r.get("result") == "fail" else "valid",
        })
    defects = await db.defects.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000)
    for d in defects:
        events.append({
            "date": d.get("defect_date") or (d.get("created_at") or "")[:10], "type": "defect", "title": f"Defect — {d['vehicle_reg']}",
            "subtitle": f"{d.get('category', 'General')} · {d.get('severity', 'minor').replace('_', ' ')}",
            "status": "expired" if d.get("severity") in ("major", "safety_critical") else "due_soon",
        })
    events = [e for e in events if e.get("date")]
    training = await db.training.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000)
    for t in training:
        if t.get("completed_date"):
            events.append({
                "date": t["completed_date"], "type": "training", "title": f"Training Completed — {t.get('driver_name') or t.get('course_name')}",
                "subtitle": f"{t.get('category', '')} · {t.get('course_name', '')}".strip(" ·"),
                "status": "valid",
            })
        if t.get("expiry_date"):
            events.append({
                "date": t["expiry_date"], "type": "training", "title": f"Training Expiry — {t.get('driver_name') or t.get('course_name')}",
                "subtitle": f"{t.get('category', '')} · {t.get('course_name', '')}".strip(" ·"),
                "status": compliance_status(days_until(t["expiry_date"])),
            })
    insurance = await db.insurance.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000)
    for ins in insurance:
        if ins.get("expiry_date"):
            events.append({
                "date": ins["expiry_date"], "type": "insurance", "title": f"Insurance Renewal — {ins.get('policy_type')}",
                "subtitle": ins.get("insurer") or ins.get("policy_number") or "",
                "status": compliance_status(days_until(ins["expiry_date"])),
            })
    tacho = await db.tacho.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000)
    tacho_latest = {}
    for tc in tacho:
        key = (tc.get("source_type"), tc.get("reference"))
        cur = tacho_latest.get(key)
        if cur is None or (tc.get("last_download") or tc.get("next_due") or "") > (cur.get("last_download") or cur.get("next_due") or ""):
            tacho_latest[key] = tc
    for tc in tacho_latest.values():
        if tc.get("next_due"):
            events.append({
                "date": tc["next_due"], "type": "tacho", "title": f"Tacho Due — {tc.get('reference') or tc.get('source_type')}",
                "subtitle": tc.get("source_type", ""),
                "status": compliance_status(days_until(tc["next_due"]), soon_days=TACHO_SOON_DAYS),
            })
    for tc in tacho:
        if tc.get("last_download"):
            events.append({
                "date": tc["last_download"], "type": "tacho", "title": f"Tacho Downloaded — {tc.get('reference') or tc.get('source_type')}",
                "subtitle": tc.get("source_type", ""), "status": "valid",
            })
    for ev in await db.calendar_events.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000):
        events.append({
            "id": ev.get("id"), "date": ev.get("date"), "type": "custom", "title": ev.get("title", "Event"),
            "subtitle": ev.get("notes", ""), "status": ev.get("status", "valid"),
        })
    for w in await db.wheel_audits.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000):
        if w.get("audit_date"):
            events.append({
                "date": w["audit_date"], "type": "wheel", "title": f"Wheel Audit — {w.get('vehicle_reg')}",
                "subtitle": (w.get("result") or "").title() or "Re-torque check",
                "status": "expired" if w.get("result") == "fail" else "valid",
            })
        if w.get("next_due"):
            events.append({
                "date": w["next_due"], "type": "wheel", "title": f"Wheel Security Due — {w.get('vehicle_reg')}",
                "subtitle": w.get("torque_setting") or "Re-torque check",
                "status": compliance_status(days_until(w["next_due"])),
            })
    for wa in await db.walkaround_checks.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000):
        if wa.get("check_date"):
            events.append({
                "date": wa["check_date"], "type": "walkaround", "title": f"Daily Check — {wa.get('vehicle_reg')}",
                "subtitle": ("Defects found" if wa.get("result") == "defects_found" else "Nil defect") + (f" · {wa.get('driver_name')}" if wa.get("driver_name") else ""),
                "status": "due_soon" if (wa.get("result") == "defects_found" and not wa.get("rectified")) else "valid",
            })
    for sv in await db.service_records.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000):
        if sv.get("service_date"):
            events.append({
                "date": sv["service_date"], "type": "service", "title": f"Serviced — {sv.get('vehicle_reg')}",
                "subtitle": sv.get("service_type") or "Service", "status": "valid",
            })
        if sv.get("next_service_due"):
            events.append({
                "date": sv["next_service_due"], "type": "service", "title": f"Service Due — {sv.get('vehicle_reg')}",
                "subtitle": sv.get("service_type") or "Service", "status": compliance_status(days_until(sv["next_service_due"])),
            })
    is_ie = (user.region or "UK").upper() in ("IE", "IRELAND", "RSA")
    mot_label = "CVRT" if is_ie else "MOT / Annual Test"
    tax_label = "Motor Tax" if is_ie else "Vehicle Tax"
    for v in await db.vehicles.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000):
        reg = v.get("registration")
        sub = f"{v.get('make', '')} {v.get('model', '')}".strip()
        for label, key in [(mot_label, "mot_due"), (tax_label, "tax_due"), ("Service Due", "service_due"),
                           ("Tacho Calibration", "tacho_calibration_due"), ("Speed Limiter Check", "speed_limiter_due")]:
            if v.get(key):
                events.append({
                    "date": v[key], "type": "vehicle", "title": f"{label} — {reg}",
                    "subtitle": sub, "status": compliance_status(days_until(v[key])),
                })
    for dr in await db.drivers.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000):
        name = dr.get("name")
        for label, key in [("Licence Expiry", "licence_expiry"), ("Driver CPC Expiry", "cpc_expiry"),
                           ("Tacho Card Expiry", "tacho_card_expiry"), ("Licence Check Due", "licence_check_due")]:
            if dr.get(key):
                events.append({
                    "date": dr[key], "type": "driver", "title": f"{label} — {name}",
                    "subtitle": "Driver compliance", "status": compliance_status(days_until(dr[key])),
                })
    for h in await db.holidays.find({"user_id": user.user_id}, {"_id": 0}).to_list(2000):
        try:
            start = datetime.fromisoformat(h["from_date"]).date()
            end = datetime.fromisoformat(h["to_date"]).date()
        except Exception:
            continue
        if end < start:
            start, end = end, start
        cur_d = start
        days = 0
        while cur_d <= end and days < 366:
            events.append({
                "id": h.get("id"), "date": cur_d.isoformat(), "type": "holiday",
                "title": f"Holiday — {h.get('name')}",
                "subtitle": h.get("notes") or f"{h['from_date']} → {h['to_date']}", "status": "valid",
            })
            cur_d = cur_d + timedelta(days=1)
            days += 1
    events = [e for e in events if e.get("date")]
    return events


class HolidayInput(BaseModel):
    name: str
    from_date: str
    to_date: str
    notes: str = ""


@api_router.post("/holidays")
async def create_holiday(data: HolidayInput, user: User = Depends(get_current_user)):
    h = {"id": f"hol_{uuid.uuid4().hex[:10]}", "user_id": user.user_id, "name": data.name,
         "from_date": data.from_date, "to_date": data.to_date, "notes": data.notes, "created_at": now_iso()}
    await db.holidays.insert_one(dict(h))
    h.pop("_id", None)
    return h


@api_router.delete("/holidays/{hid}")
async def delete_holiday(hid: str, user: User = Depends(get_current_user)):
    await db.holidays.delete_one({"id": hid, "user_id": user.user_id})
    return {"ok": True}


class CalendarEventInput(BaseModel):
    date: str
    title: str
    notes: str = ""
    status: str = "valid"


@api_router.post("/calendar/events")
async def create_calendar_event(data: CalendarEventInput, user: User = Depends(get_current_user)):
    ev = {"id": f"evt_{uuid.uuid4().hex[:10]}", "user_id": user.user_id, "date": data.date,
          "title": data.title, "notes": data.notes, "status": data.status, "created_at": now_iso()}
    await db.calendar_events.insert_one(dict(ev))
    ev.pop("_id", None)
    return ev


@api_router.delete("/calendar/events/{eid}")
async def delete_calendar_event(eid: str, user: User = Depends(get_current_user)):
    await db.calendar_events.delete_one({"id": eid, "user_id": user.user_id})
    return {"ok": True}


@api_router.put("/calendar/events/{eid}")
async def update_calendar_event(eid: str, data: CalendarEventInput, user: User = Depends(get_current_user)):
    res = await db.calendar_events.update_one(
        {"id": eid, "user_id": user.user_id},
        {"$set": {"date": data.date, "title": data.title, "notes": data.notes, "status": data.status}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Event not found")
    return {"ok": True}


# ---------- Dashboard + AI risk ----------
async def gather_stats(user_id: str):
    vehicles = await db.vehicles.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    drivers = await db.drivers.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    documents = await db.documents.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    defects = await db.defects.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    pmi_schedules = await db.pmi_schedules.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    trailers = await db.trailers.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    training = await db.training.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    insurance = await db.insurance.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    tacho = await db.tacho.find({"user_id": user_id}, {"_id": 0}).to_list(1000)

    alerts = []
    expired = due_soon = 0
    for v in vehicles:
        if v.get("vor"):
            continue
        for label, key in [("MOT", "mot_due"), ("Service", "service_due"), ("Tax", "tax_due"), ("Tacho Calibration", "tacho_calibration_due"), ("Speed Limiter", "speed_limiter_due")]:
            d = days_until(v.get(key))
            st = compliance_status(d)
            if st == "expired":
                expired += 1
                alerts.append({"type": "vehicle", "name": v["registration"], "item": label, "status": "expired", "days": d})
            elif st == "due_soon":
                due_soon += 1
                alerts.append({"type": "vehicle", "name": v["registration"], "item": label, "status": "due_soon", "days": d})
    for dr in drivers:
        for label, key in [("Licence", "licence_expiry"), ("CPC", "cpc_expiry"), ("Tacho Card", "tacho_card_expiry"), ("Licence Check", "licence_check_due")]:
            d = days_until(dr.get(key))
            st = compliance_status(d)
            if st == "expired":
                expired += 1
                alerts.append({"type": "driver", "name": dr["name"], "item": label, "status": "expired", "days": d})
            elif st == "due_soon":
                due_soon += 1
                alerts.append({"type": "driver", "name": dr["name"], "item": label, "status": "due_soon", "days": d})
        if dr.get("weekly_hours", 0) > dr.get("max_weekly_hours", 56):
            expired += 1
            alerts.append({"type": "driver", "name": dr["name"], "item": "Weekly Hours Exceeded", "status": "expired", "days": None})
    for doc in documents:
        d = days_until(doc.get("expiry_date"))
        st = compliance_status(d)
        if st == "expired":
            expired += 1
            alerts.append({"type": "document", "name": doc["title"], "item": doc.get("doc_type", "Document"), "status": "expired", "days": d})
        elif st == "due_soon":
            due_soon += 1
            alerts.append({"type": "document", "name": doc["title"], "item": doc.get("doc_type", "Document"), "status": "due_soon", "days": d})

    for p in pmi_schedules:
        d = days_until(p.get("next_due"))
        st = compliance_status(d)
        if st == "expired":
            expired += 1
            alerts.append({"type": "pmi", "name": p["vehicle_reg"], "item": "PMI Inspection", "status": "expired", "days": d})
        elif st == "due_soon":
            due_soon += 1
            alerts.append({"type": "pmi", "name": p["vehicle_reg"], "item": "PMI Inspection", "status": "due_soon", "days": d})

    for tr in trailers:
        if tr.get("vor"):
            continue
        for label, key in [("Annual Test", "mot_due"), ("Service", "service_due")]:
            d = days_until(tr.get(key))
            st = compliance_status(d)
            if st == "expired":
                expired += 1
                alerts.append({"type": "trailer", "name": tr["trailer_number"], "item": label, "status": "expired", "days": d})
            elif st == "due_soon":
                due_soon += 1
                alerts.append({"type": "trailer", "name": tr["trailer_number"], "item": label, "status": "due_soon", "days": d})

    for t in training:
        d = days_until(t.get("expiry_date"))
        st = compliance_status(d)
        if st == "expired":
            expired += 1
            alerts.append({"type": "training", "name": t.get("driver_name") or t.get("course_name"), "item": t.get("course_name", "Training"), "status": "expired", "days": d})
        elif st == "due_soon":
            due_soon += 1
            alerts.append({"type": "training", "name": t.get("driver_name") or t.get("course_name"), "item": t.get("course_name", "Training"), "status": "due_soon", "days": d})

    for ins in insurance:
        d = days_until(ins.get("expiry_date"))
        st = compliance_status(d)
        if st == "expired":
            expired += 1
            alerts.append({"type": "insurance", "name": ins.get("insurer") or ins.get("policy_type"), "item": ins.get("policy_type", "Insurance"), "status": "expired", "days": d})
        elif st == "due_soon":
            due_soon += 1
            alerts.append({"type": "insurance", "name": ins.get("insurer") or ins.get("policy_type"), "item": ins.get("policy_type", "Insurance"), "status": "due_soon", "days": d})

    # Only the LATEST download per driver-card / vehicle-unit counts toward compliance
    tacho_latest = {}
    for tc in tacho:
        key = (tc.get("source_type"), tc.get("reference"))
        cur = tacho_latest.get(key)
        if cur is None or (tc.get("last_download") or tc.get("next_due") or "") > (cur.get("last_download") or cur.get("next_due") or ""):
            tacho_latest[key] = tc
    for tc in tacho_latest.values():
        d = days_until(tc.get("next_due"))
        st = compliance_status(d, soon_days=TACHO_SOON_DAYS)
        if st == "expired":
            expired += 1
            alerts.append({"type": "tacho", "name": tc.get("reference") or tc.get("source_type"), "item": f"{tc.get('source_type', 'Tacho')} Download", "status": "expired", "days": d})
        elif st == "due_soon":
            due_soon += 1
            alerts.append({"type": "tacho", "name": tc.get("reference") or tc.get("source_type"), "item": f"{tc.get('source_type', 'Tacho')} Download", "status": "due_soon", "days": d})

    open_defects = [d for d in defects if d.get("status") == "open"]
    major_defects = [d for d in open_defects if d.get("severity") in ("major", "safety_critical")]
    wheel = await db.wheel_audits.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    for w in wheel:
        d = days_until(w.get("next_due"))
        st = compliance_status(d)
        if st == "expired":
            expired += 1
            alerts.append({"type": "wheel", "name": w.get("vehicle_reg"), "item": "Wheel Security Check", "status": "expired", "days": d})
        elif st == "due_soon":
            due_soon += 1
            alerts.append({"type": "wheel", "name": w.get("vehicle_reg"), "item": "Wheel Security Check", "status": "due_soon", "days": d})
    alerts.sort(key=lambda a: (a["status"] != "expired", a["days"] if a["days"] is not None else 9999))
    return {
        "counts": {
            "vehicles": len(vehicles), "drivers": len(drivers), "documents": len(documents),
            "open_defects": len(open_defects), "major_defects": len(major_defects),
            "pmi": len(pmi_schedules), "trailers": len(trailers), "training": len(training),
            "insurance": len(insurance), "tacho": len(tacho_latest),
            "expired": expired, "due_soon": due_soon,
        },
        "alerts": alerts,
    }


def _score_and_band(counts, gaps):
    penalty = counts["expired"] * 25 + counts["due_soon"] * 8 + counts["major_defects"] * 15 + counts["open_defects"] * 3
    gap_weights = {"high": 10, "medium": 4, "low": 1}
    penalty += sum(gap_weights.get(g.get("priority"), 0) for g in gaps)
    # Smooth exponential decay (half-life 45) so heavy non-compliance approaches — but never flat-lines at — 0,
    # keeping the relative ordering visible (e.g. UK laden-brake requirement scores strictly below Ireland).
    score = round(100 * (0.5 ** (penalty / 45.0)))
    band = "Low Risk" if score >= 85 else "Moderate Risk" if score >= 60 else "High Risk"
    return score, band


@api_router.get("/dashboard")
async def dashboard(user: User = Depends(get_current_user)):
    stats = await gather_stats(user.user_id)
    gaps = await detect_gaps(user.user_id)
    score, band = _score_and_band(stats["counts"], gaps)
    stats["risk_score"] = score
    stats["risk_band"] = band
    stats["registered_users"] = await db.users.count_documents({})
    today = datetime.now(timezone.utc).date().isoformat()
    await db.compliance_history.update_one(
        {"user_id": user.user_id, "date": today},
        {"$set": {"user_id": user.user_id, "date": today, "score": score, "band": band,
                  "expired": stats["counts"]["expired"], "due_soon": stats["counts"]["due_soon"],
                  "recorded_at": now_iso()}},
        upsert=True,
    )
    return stats


@api_router.get("/compliance/history")
async def compliance_history(days: int = 90, user: User = Depends(get_current_user)):
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
    rows = await db.compliance_history.find(
        {"user_id": user.user_id, "date": {"$gte": cutoff}}, {"_id": 0}
    ).sort("date", 1).to_list(400)
    return {"history": rows}


async def detect_gaps(user_id: str):
    vehicles = await db.vehicles.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    drivers = await db.drivers.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    documents = await db.documents.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    insurance = await db.insurance.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    pmi = await db.pmi_schedules.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    pmi_records = await db.pmi_records.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
    tacho = await db.tacho.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    training = await db.training.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    wheel = await db.wheel_audits.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    walkarounds = await db.walkaround_checks.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
    test_history = await db.test_history.find({"user_id": user_id}, {"_id": 0}).to_list(2000)
    udoc = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    is_ie = udoc.get("region") == "IE"
    mot_label = "CVRT" if is_ie else "MOT"
    test_label = "CVRT test" if is_ie else "annual test"

    gaps = []
    operator = await db.operator.find_one({"user_id": user_id}, {"_id": 0}) or {}
    if not operator.get("operator_licence_number"):
        gaps.append({"area": "Operator", "item": "No Operator Licence number recorded", "priority": "high"})
    if not operator.get("tm_name"):
        gaps.append({"area": "Operator", "item": "No Transport Manager (TM) recorded", "priority": "high"})
    if not operator.get("company_number"):
        gaps.append({"area": "Operator", "item": "No company number recorded", "priority": "low"})

    doc_types = {d.get("doc_type") for d in documents}
    if "Operator Licence" not in doc_types:
        gaps.append({"area": "Documents", "item": "No Operator Licence document on file", "priority": "high"})

    ins_types = {i.get("policy_type") for i in insurance}
    for req, short in [("Goods in Transit (GIT)", "Goods in Transit (GIT)"), ("Motor — Truck", "Motor (Truck) insurance"),
                       ("Public Liability (PL)", "Public Liability (PL)"), ("Employers' Liability (EL)", "Employers' Liability (EL)")]:
        if req not in ins_types:
            gaps.append({"area": "Insurance", "item": f"Missing {short} policy", "priority": "high" if req == "Employers' Liability (EL)" else "medium"})

    pmi_regs = {p.get("vehicle_reg") for p in pmi}
    def _norm(s):
        return " ".join((s or "").lower().split())
    tacho_vu = [_norm(t.get("reference")) for t in tacho if t.get("source_type") == "Vehicle Unit" and t.get("reference")]
    wheel_regs = {w.get("vehicle_reg") for w in wheel}
    walk_regs = {w.get("vehicle_reg") for w in walkarounds}
    test_regs = {t.get("vehicle_reg") for t in test_history}
    pmr_with_brake = {r.get("vehicle_reg") for r in pmi_records if r.get("brake_test_type") and r.get("brake_test_type") != "none"}
    for v in vehicles:
        if v.get("vor"):
            continue
        reg = v.get("registration")
        if not v.get("mot_due"):
            gaps.append({"area": "Fleet", "item": f"{reg}: no {mot_label} date recorded", "priority": "medium"})
        if not v.get("tacho_calibration_due"):
            gaps.append({"area": "Fleet", "item": f"{reg}: no tachograph calibration date (2-yearly)", "priority": "medium"})
        if not v.get("speed_limiter_due"):
            gaps.append({"area": "Fleet", "item": f"{reg}: no speed limiter check date", "priority": "low"})
        if not v.get("first_use_date"):
            gaps.append({"area": "Fleet", "item": f"{reg}: no date of first use recorded", "priority": "low"})
        if reg not in pmi_regs:
            gaps.append({"area": "PMI", "item": f"{reg}: no PMI inspection schedule", "priority": "high"})
        if not is_ie and reg not in pmr_with_brake:
            gaps.append({"area": "PMI", "item": f"{reg}: no laden roller brake test recorded (DVSA safety inspection)", "priority": "medium"})
        if reg not in wheel_regs:
            gaps.append({"area": "Maintenance", "item": f"{reg}: no wheel security audit recorded", "priority": "medium"})
        if reg not in walk_regs:
            gaps.append({"area": "Maintenance", "item": f"{reg}: no daily walkaround checks recorded", "priority": "medium"})
        if reg not in test_regs:
            gaps.append({"area": "Fleet", "item": f"{reg}: no {test_label}/prohibition history recorded", "priority": "low"})
        if reg and not any(_norm(reg) == r or _norm(reg) in r or r in _norm(reg) for r in tacho_vu):
            gaps.append({"area": "Tacho", "item": f"{reg}: no vehicle-unit tacho download record", "priority": "medium"})

    tacho_dc_refs = [_norm(t.get("reference")) for t in tacho if t.get("source_type") == "Driver Card" and t.get("reference")]
    training_drivers = {t.get("driver_name") for t in training}
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=365 * 5)).isoformat()
    for d in drivers:
        nm = d.get("name")
        nmn = _norm(nm)
        if not d.get("licence_expiry"):
            gaps.append({"area": "Drivers", "item": f"{nm}: no driving licence expiry recorded", "priority": "medium"})
        if not d.get("cpc_expiry"):
            gaps.append({"area": "Drivers", "item": f"{nm}: no Driver CPC expiry recorded", "priority": "medium"})
        if not d.get("licence_check_due") and not d.get("licence_check_date"):
            gaps.append({"area": "Drivers", "item": f"{nm}: no licence check recorded (DVLA/NDLS)", "priority": "medium"})
        cpc_hours = sum(float(t.get("hours") or 0) for t in training
                        if (t.get("driver_id") == d["id"] or t.get("driver_name") == nm)
                        and "cpc" in (t.get("category") or "").lower()
                        and (t.get("completed_date") or "9999") >= cutoff)
        cpc_days = days_until(d.get("cpc_expiry"))
        if cpc_hours < 35 and cpc_days is not None and cpc_days <= 365:
            due = d.get("cpc_expiry") or ""
            gaps.append({"area": "Training", "item": f"{nm}: Driver CPC periodic training incomplete ({cpc_hours:.0f}/35h) before CPC renewal {due}", "priority": "medium" if cpc_days <= 90 else "low"})
        if nmn and not any(nmn == r or nmn in r or r in nmn for r in tacho_dc_refs):
            gaps.append({"area": "Tacho", "item": f"{nm}: no driver-card tacho download record", "priority": "medium"})
        if nm not in training_drivers:
            gaps.append({"area": "Training", "item": f"{nm}: no training records", "priority": "low"})

    if not vehicles:
        gaps.append({"area": "Fleet", "item": "No vehicles recorded", "priority": "high"})
    if not drivers:
        gaps.append({"area": "Drivers", "item": "No drivers recorded", "priority": "high"})
    return gaps


@api_router.post("/ai/risk-insight")
async def ai_risk_insight(user: User = Depends(get_current_user)):
    stats = await gather_stats(user.user_id)
    c = stats["counts"]
    top = stats["alerts"][:8]
    alert_text = "; ".join([f"{a['name']} {a['item']} {a['status']}" for a in top]) or "No outstanding alerts"
    gaps = await detect_gaps(user.user_id)
    score, _band = _score_and_band(c, gaps)
    order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: order.get(g["priority"], 3))
    gap_text = "; ".join([f"[{g['priority']}] {g['item']}" for g in gaps[:14]]) or "No obvious record gaps detected"
    is_ie = (await db.users.find_one({"user_id": user.user_id}, {"_id": 0}) or {}).get("region") == "IE"
    region_note = ("This operator is in IRELAND (RSA/CVRT rules). Do NOT recommend laden brake tests or DVSA-specific requirements; use RSA/CVRT terminology (CVRT, CRW)."
                   if is_ie else "This operator is in the UK (DVSA rules); use DVSA terminology (MOT, safety inspections with laden roller brake test).")
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"risk_{uuid.uuid4().hex[:8]}",
            system_message="You are a UK & Ireland operator-licence compliance auditor for road haulage operators (DVSA in the UK, RSA in Ireland). Given fleet stats, outstanding alerts and detected record gaps, write a concise audit briefing (max 110 words) for a transport manager: state the biggest risks to the operator licence and the top prioritised actions, explicitly calling out the most important MISSING records/documents. Only reference gaps that are actually in the provided data — do not invent requirements. Be direct and practical.",
        ).with_model("openai", "gpt-5.4")
        prompt = (f"{region_note} "
                  f"Compliance score: {score}/100. Vehicles: {c['vehicles']}, Drivers: {c['drivers']}, "
                  f"Documents: {c['documents']}, Insurance: {c.get('insurance', 0)}, Tacho: {c.get('tacho', 0)}. "
                  f"Expired: {c['expired']}, Due soon: {c['due_soon']}, Open defects: {c['open_defects']} (major {c['major_defects']}). "
                  f"Top alerts: {alert_text}. Detected gaps: {gap_text}.")
        resp = await chat.send_message(UserMessage(text=prompt))
        insight = resp if isinstance(resp, str) else str(resp)
    except Exception as e:
        logging.error(f"AI risk insight failed: {e}")
        insight = "AI insight unavailable right now. Review the audit checklist below, clear expired items and add any missing mandatory documents/insurance first."
    return {"score": score, "insight": insight, "checklist": gaps}


# ---------- Email reminders (Resend) ----------
ALL_AREAS = ["fleet", "drivers", "tacho", "pmi", "insurance", "training", "documents", "defects", "service"]
AREA_OF = {"vehicle": "fleet", "trailer": "fleet", "driver": "drivers", "tacho": "tacho",
           "pmi": "pmi", "insurance": "insurance", "training": "training", "document": "documents", "defect": "defects", "wheel": "pmi", "service": "service"}
AREA_PRESETS = {
    "Transport Manager": list(ALL_AREAS),
    "Driver": ["drivers", "tacho", "training"],
    "Maintenance": ["fleet", "pmi", "defects", "service"],
}


class Recipient(BaseModel):
    email: EmailStr
    areas: List[str] = Field(default_factory=lambda: list(ALL_AREAS))
    frequency: str = "daily"  # daily | weekly


class ReminderSettingsInput(BaseModel):
    recipients: List[Recipient] = []


def _norm_recipient(r) -> dict:
    if isinstance(r, str):
        return {"email": r, "areas": list(ALL_AREAS), "frequency": "daily"}
    return {
        "email": r.get("email"),
        "areas": r.get("areas") or list(ALL_AREAS),
        "frequency": r.get("frequency", "daily") if r.get("frequency") in ("daily", "weekly") else "daily",
    }


@api_router.get("/reminders/settings")
async def get_reminder_settings(user: User = Depends(get_current_user)):
    doc = await db.reminder_settings.find_one({"user_id": user.user_id}, {"_id": 0})
    recipients = [_norm_recipient(r) for r in (doc or {}).get("recipients", [])]
    return {"recipients": recipients, "areas": ALL_AREAS, "presets": AREA_PRESETS}


@api_router.put("/reminders/settings")
async def update_reminder_settings(data: ReminderSettingsInput, user: User = Depends(get_current_user)):
    recipients = [r.model_dump() for r in data.recipients]
    payload = {"user_id": user.user_id, "recipients": recipients, "updated_at": now_iso()}
    await db.reminder_settings.update_one({"user_id": user.user_id}, {"$set": payload}, upsert=True)
    return {"ok": True, "recipients": recipients}


def build_reminder_html(company: str, alerts: list, authority: str, weekly: bool = False) -> str:
    if alerts:
        rows = ""
        for a in alerts:
            if a["status"] == "expired":
                status_txt, color = "EXPIRED", "#dc2626"
            elif a.get("days") is not None:
                status_txt, color = f"Due in {a['days']} day(s)", "#d97706"
            else:
                status_txt, color = "Action needed", "#d97706"
            rows += (
                f"<tr>"
                f"<td style='padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#475569;text-transform:capitalize;'>{a['type']}</td>"
                f"<td style='padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#0f172a;font-weight:600;'>{a['name']}</td>"
                f"<td style='padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#334155;'>{a['item']}</td>"
                f"<td style='padding:10px 12px;border-bottom:1px solid #e2e8f0;font-size:13px;font-weight:700;color:{color};'>{status_txt}</td>"
                f"</tr>"
            )
        table = (
            "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;margin-top:18px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;'>"
            "<tr style='background:#0f172a;'>"
            "<th style='padding:10px 12px;text-align:left;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#cbd5e1;'>Area</th>"
            "<th style='padding:10px 12px;text-align:left;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#cbd5e1;'>Item</th>"
            "<th style='padding:10px 12px;text-align:left;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#cbd5e1;'>Detail</th>"
            "<th style='padding:10px 12px;text-align:left;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#cbd5e1;'>Status</th>"
            f"</tr>{rows}</table>"
        )
        intro = (f"Your weekly compliance summary — the following <strong>{len(alerts)}</strong> item(s) are expired or due within the next 30 days:"
                 if weekly else
                 f"The following <strong>{len(alerts)}</strong> compliance item(s) are expired or due within the next 30 days and need attention:")
    else:
        table = ""
        intro = ("Your weekly compliance summary — no items are expired or due within the next 30 days. Everything is up to date."
                 if weekly else
                 "Good news — no compliance items are expired or due within the next 30 days.")

    return (
        "<div style='background:#f1f5f9;padding:32px 0;font-family:Arial,Helvetica,sans-serif;'>"
        "<table role='presentation' width='600' align='center' cellpadding='0' cellspacing='0' style='background:#ffffff;border-radius:12px;padding:32px;margin:0 auto;'>"
        "<tr><td>"
        "<p style='margin:0;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:#64748b;font-weight:700;'>HaulCheck · " + authority + " compliance</p>"
        "<h1 style='margin:6px 0 0;font-size:22px;color:#0f172a;'>" + ("Weekly compliance summary" if weekly else "Compliance reminder") + "</h1>"
        "<p style='margin:4px 0 0;font-size:14px;color:#475569;'>" + company + "</p>"
        "<p style='margin:20px 0 0;font-size:14px;color:#334155;line-height:1.6;'>" + intro + "</p>"
        + table +
        "<p style='margin:24px 0 0;font-size:12px;color:#94a3b8;line-height:1.6;'>This is an automated reminder from your HaulCheck fleet-compliance dashboard. Log in to review and clear these items.</p>"
        "</td></tr></table></div>"
    )


async def _deliver_reminder(user_id: str, to_emails: list, alerts: list, weekly: bool = False) -> str:
    operator = await db.operator.find_one({"user_id": user_id}, {"_id": 0}) or {}
    company = operator.get("company_name") or "Your fleet"
    udoc = await db.users.find_one({"user_id": user_id}, {"_id": 0}) or {}
    authority = "RSA" if udoc.get("region") == "IE" else "DVSA"
    html = build_reminder_html(company, alerts, authority, weekly=weekly)
    if weekly:
        subject = f"HaulCheck weekly summary — {len(alerts)} item(s) need attention" if alerts else "HaulCheck weekly summary — all clear"
    else:
        subject = f"HaulCheck reminder — {len(alerts)} compliance item(s) need attention" if alerts else "HaulCheck compliance reminder — all clear"
    import resend
    resend.api_key = os.environ['RESEND_API_KEY']
    params = {"from": os.environ['SENDER_EMAIL'], "to": to_emails, "subject": subject, "html": html}
    result = await asyncio.to_thread(resend.Emails.send, params)
    return result.get("id") if isinstance(result, dict) else getattr(result, "id", None)


def _alert_key(a: dict) -> str:
    return f"{a['type']}|{a['name']}|{a['item']}"


def _filter_alerts(alerts: list, areas: list) -> list:
    allow = set(areas) if areas else set(ALL_AREAS)
    return [a for a in alerts if a.get("area") in allow]


async def _reminder_alerts(user_id: str) -> list:
    """All items expired or due within 30 days (incl. open defects), each tagged with an area."""
    stats = await gather_stats(user_id)
    alerts = [dict(a) for a in stats["alerts"] if a["status"] in ("expired", "due_soon")]
    defects = await db.defects.find({"user_id": user_id, "status": "open"}, {"_id": 0}).to_list(1000)
    for d in defects:
        sev = d.get("severity", "minor")
        alerts.append({
            "type": "defect",
            "name": d.get("vehicle_reg", "Vehicle"),
            "item": f"{sev.replace('_', ' ').title()} defect: {(d.get('description') or '')[:60]}",
            "status": "expired" if sev in ("major", "safety_critical") else "due_soon",
            "days": None,
        })
    services = await db.service_records.find({"user_id": user_id}, {"_id": 0}).to_list(1000)
    for sv in services:
        d = days_until(sv.get("next_service_due"))
        if d is not None and d <= 30:
            alerts.append({
                "type": "service", "name": sv.get("vehicle_reg", "Vehicle"),
                "item": f"{sv.get('service_type', 'Service')} due", "status": "expired" if d < 0 else "due_soon", "days": d,
            })
    for a in alerts:
        a["area"] = AREA_OF.get(a["type"], "documents")
    return alerts
async def _process_daily_user(user_id: str, recipients: list) -> dict:
    """Per daily recipient, email only items that newly entered their filtered 30-day window (dedup)."""
    alerts = await _reminder_alerts(user_id)
    log_doc = await db.reminder_log.find_one({"user_id": user_id}, {"_id": 0}) or {}
    sent = log_doc.get("sent", {})
    total_new = 0
    for raw in recipients:
        r = _norm_recipient(raw)
        if r["frequency"] != "daily":
            continue
        r_alerts = _filter_alerts(alerts, r["areas"])
        current_keys = {_alert_key(a) for a in r_alerts}
        logged = set(sent.get(r["email"], [])) & current_keys  # drop renewed/deleted
        new_items = [a for a in r_alerts if _alert_key(a) not in logged]
        if new_items:
            await _deliver_reminder(user_id, [r["email"]], new_items)
            logged |= {_alert_key(a) for a in new_items}
            total_new += len(new_items)
        sent[r["email"]] = list(logged)
    await db.reminder_log.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "sent": sent, "updated_at": now_iso()}},
        upsert=True,
    )
    return {"new_item_count": total_new}


async def _process_weekly_user(user_id: str, recipients: list) -> int:
    alerts = await _reminder_alerts(user_id)
    count = 0
    for raw in recipients:
        r = _norm_recipient(raw)
        if r["frequency"] != "weekly":
            continue
        r_alerts = _filter_alerts(alerts, r["areas"])
        await _deliver_reminder(user_id, [r["email"]], r_alerts, weekly=True)
        count += 1
    return count


async def run_daily_reminders():
    logger.info("Running daily reminder job")
    settings_list = await db.reminder_settings.find({"recipients": {"$exists": True, "$ne": []}}, {"_id": 0}).to_list(10000)
    for s in settings_list:
        if not s.get("recipients"):
            continue
        try:
            res = await _process_daily_user(s["user_id"], s["recipients"])
            if res["new_item_count"]:
                logger.info(f"Daily reminder sent to {s['user_id']} ({res['new_item_count']} new items)")
        except Exception as e:
            logger.error(f"Daily reminder failed for {s.get('user_id')}: {e}")


async def run_weekly_reminders():
    logger.info("Running weekly reminder job")
    settings_list = await db.reminder_settings.find({"recipients": {"$exists": True, "$ne": []}}, {"_id": 0}).to_list(10000)
    for s in settings_list:
        if not s.get("recipients"):
            continue
        try:
            sent = await _process_weekly_user(s["user_id"], s["recipients"])
            if sent:
                logger.info(f"Weekly summary sent to {s['user_id']} ({sent} recipients)")
        except Exception as e:
            logger.error(f"Weekly reminder failed for {s.get('user_id')}: {e}")


@api_router.post("/reminders/send")
async def send_reminders(user: User = Depends(get_current_user)):
    settings = await db.reminder_settings.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    recipients = settings.get("recipients", [])
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipient emails configured. Add at least one in Settings.")
    alerts = await _reminder_alerts(user.user_id)
    results = []
    try:
        for raw in recipients:
            r = _norm_recipient(raw)
            r_alerts = _filter_alerts(alerts, r["areas"])
            eid = await _deliver_reminder(user.user_id, [r["email"]], r_alerts)
            results.append({"email": r["email"], "item_count": len(r_alerts), "email_id": eid})
    except Exception as e:
        logging.error(f"Reminder email failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {e}")
    return {"ok": True, "results": results, "recipient_count": len(results)}


@api_router.post("/reminders/run-scheduled")
async def run_scheduled_now(user: User = Depends(get_current_user)):
    settings = await db.reminder_settings.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    recipients = settings.get("recipients", [])
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipient emails configured. Add at least one in Settings.")
    try:
        daily = await _process_daily_user(user.user_id, recipients)
        weekly_sent = await _process_weekly_user(user.user_id, recipients)
    except Exception as e:
        logging.error(f"Scheduled reminder run failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to run: {e}")
    return {"ok": True, "new_item_count": daily["new_item_count"], "weekly_sent": weekly_sent}


# ---------- PDF Export ----------
def _fmt(v):
    return v if v not in (None, "") else "—"


async def _get_logo_bytes(user_id: str, operator: dict):
    lid = (operator or {}).get("logo_file_id")
    if not lid:
        return None
    frec = await db.files.find_one({"id": lid, "user_id": user_id, "is_deleted": False}, {"_id": 0})
    if not frec:
        return None
    try:
        data, _ = await asyncio.to_thread(get_object, frec["storage_path"])
        return data
    except Exception as e:
        logging.error(f"Logo fetch failed: {e}")
        return None


async def _collect_files(user_id: str, file_ids: list):
    files = []
    seen = set()
    for fid in file_ids:
        if not fid or fid in seen:
            continue
        seen.add(fid)
        frec = await db.files.find_one({"id": fid, "user_id": user_id, "is_deleted": False}, {"_id": 0})
        if not frec:
            continue
        try:
            data, ct = await asyncio.to_thread(get_object, frec["storage_path"])
            files.append((data, frec.get("content_type") or ct, frec.get("original_filename") or fid))
        except Exception as e:
            logging.error(f"Export file fetch {fid} failed: {e}")
    return files


@api_router.get("/export/driver/{driver_id}")
async def export_driver(driver_id: str, include_files: bool = Query(False), user: User = Depends(get_current_user)):
    d = await db.drivers.find_one({"id": driver_id, "user_id": user.user_id}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Driver not found")
    training = await db.training.find(
        {"user_id": user.user_id, "$or": [{"driver_id": driver_id}, {"driver_name": d.get("name")}]}, {"_id": 0}
    ).to_list(1000)
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    sections = [
        {"type": "kv", "heading": "Driver Details", "pairs": [
            ("Name", d.get("name")), ("Licence number", d.get("licence_number")),
            ("Weekly hours", f"{d.get('weekly_hours', 0)} / {d.get('max_weekly_hours', 56)}h"),
            ("Notes", d.get("notes")),
        ]},
        {"heading": "Licences & Cards", "columns": ["Item", "Expiry", "Status"], "rows": [
            {"cells": ["Driving Licence", _fmt(d.get("licence_expiry"))], "status": compliance_status(days_until(d.get("licence_expiry")))},
            {"cells": ["Driver CPC", _fmt(d.get("cpc_expiry"))], "status": compliance_status(days_until(d.get("cpc_expiry")))},
            {"cells": ["Tachograph Card", _fmt(d.get("tacho_card_expiry"))], "status": compliance_status(days_until(d.get("tacho_card_expiry")))},
        ]},
        {"heading": "Training Records", "columns": ["Course", "Category", "Provider", "Expiry", "Status"], "rows": [
            {"cells": [t.get("course_name"), t.get("category"), t.get("provider"), _fmt(t.get("expiry_date"))],
             "status": compliance_status(days_until(t.get("expiry_date")))} for t in training
        ]},
    ]
    pdf = await asyncio.to_thread(
        build_report_pdf, "Driver Compliance File", d.get("name", ""),
        [("Operator", operator.get("company_name", "")), ("O-Licence", operator.get("operator_licence_number", ""))], sections,
        await _get_logo_bytes(user.user_id, operator), "RSA (Ireland)" if user.region == "IE" else "DVSA (UK)")
    if include_files:
        fids = [a.get("file_id") for t in training for a in (t.get("attachments") or [])]
        pdf = await asyncio.to_thread(merge_pack, pdf, await _collect_files(user.user_id, fids))
    fname = f"driver-{(d.get('name') or 'file').replace(' ', '_')}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@api_router.get("/export/account")
async def export_account(include_files: bool = Query(False), user: User = Depends(get_current_user)):
    pdf, fname = await _build_account_pdf(user, include_files)
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class EmailPackInput(BaseModel):
    to: List[EmailStr]
    message: str = ""


@api_router.post("/export/account/email")
async def email_account_pack(data: EmailPackInput, user: User = Depends(get_current_user)):
    if not data.to:
        raise HTTPException(status_code=400, detail="At least one recipient is required")
    pdf, fname = await _build_account_pdf(user, include_files=True)
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    company = operator.get("company_name") or "our fleet"
    authority = "RSA" if user.region == "IE" else "DVSA"
    body = (data.message or "").replace("\n", "<br/>")
    html = (
        "<div style='background:#f1f5f9;padding:32px 0;font-family:Arial,Helvetica,sans-serif;'>"
        "<table role='presentation' width='600' align='center' cellpadding='0' cellspacing='0' style='background:#ffffff;border-radius:12px;padding:32px;margin:0 auto;'>"
        "<tr><td>"
        f"<p style='margin:0;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:#64748b;font-weight:700;'>HaulCheck · {authority} compliance</p>"
        "<h1 style='margin:6px 0 0;font-size:22px;color:#0f172a;'>Audit Pack</h1>"
        f"<p style='margin:4px 0 0;font-size:14px;color:#475569;'>{company}</p>"
        f"<p style='margin:20px 0 0;font-size:14px;color:#334155;line-height:1.6;'>{body or 'Please find attached the full compliance audit pack.'}</p>"
        f"<p style='margin:20px 0 0;font-size:13px;color:#64748b;'>Attachment: {fname}</p>"
        "</td></tr></table></div>"
    )
    try:
        import resend
        resend.api_key = os.environ['RESEND_API_KEY']
        params = {
            "from": os.environ['SENDER_EMAIL'], "to": data.to,
            "subject": f"{company} — Compliance Audit Pack ({authority})",
            "html": html,
            "attachments": [{"filename": fname, "content": list(pdf)}],
        }
        result = await asyncio.to_thread(resend.Emails.send, params)
        eid = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
        return {"ok": True, "email_id": eid, "filename": fname}
    except Exception as e:
        logging.error(f"Audit pack email failed: {e}")
        raise HTTPException(status_code=502, detail="Could not send email")


async def _build_account_pdf(user: User, include_files: bool):
    operator = await db.operator.find_one({"user_id": user.user_id}, {"_id": 0}) or {}
    vehicles = await db.vehicles.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    trailers = await db.trailers.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    drivers = await db.drivers.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    training = await db.training.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    pmi = await db.pmi_schedules.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    insurance = await db.insurance.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    tacho = await db.tacho.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    defects = await db.defects.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    wheel = await db.wheel_audits.find({"user_id": user.user_id}, {"_id": 0}).to_list(1000)
    cs, du = compliance_status, days_until

    def worst_vehicle(v):
        sts = [cs(du(v.get(k))) for k in ("mot_due", "service_due", "tax_due")]
        return "expired" if "expired" in sts else ("due_soon" if "due_soon" in sts else "valid")

    sections = [
        {"type": "kv", "heading": "Operator Details", "pairs": [
            ("Company", operator.get("company_name")), ("Company number", operator.get("company_number")),
            ("O-Licence number", operator.get("operator_licence_number")), ("Licence type", operator.get("licence_type")),
            ("Operating centre", operator.get("address")),
            ("Authorised vehicles / trailers", f"{operator.get('authorised_vehicles', 0)} / {operator.get('authorised_trailers', 0)}"),
            ("Transport Manager", operator.get("tm_name")), ("TM CPC", operator.get("tm_cpc_number")),
            ("TM email", operator.get("tm_email")),
        ]},
        {"heading": "Vehicles", "columns": ["Reg", "Make/Model", "Type", "MOT", "Service", "Tax", "Status"], "rows": [
            {"cells": [v.get("registration"), f"{v.get('make', '')} {v.get('model', '')}".strip(), v.get("type"),
                       _fmt(v.get("mot_due")), _fmt(v.get("service_due")), _fmt(v.get("tax_due"))], "status": worst_vehicle(v)} for v in vehicles
        ]},
        {"heading": "Trailers", "columns": ["Trailer", "Type", "Annual Test", "Service", "Status"], "rows": [
            {"cells": [t.get("trailer_number"), t.get("type"), _fmt(t.get("mot_due")), _fmt(t.get("service_due"))],
             "status": ("expired" if "expired" in [cs(du(t.get("mot_due"))), cs(du(t.get("service_due")))] else ("due_soon" if "due_soon" in [cs(du(t.get("mot_due"))), cs(du(t.get("service_due")))] else "valid"))} for t in trailers
        ]},
        {"heading": "Drivers", "columns": ["Name", "Licence", "CPC", "Tacho Card", "Hours", "Status"], "rows": [
            {"cells": [dr.get("name"), _fmt(dr.get("licence_expiry")), _fmt(dr.get("cpc_expiry")), _fmt(dr.get("tacho_card_expiry")),
                       f"{dr.get('weekly_hours', 0)}/{dr.get('max_weekly_hours', 56)}h"],
             "status": ("expired" if "expired" in [cs(du(dr.get("licence_expiry"))), cs(du(dr.get("cpc_expiry"))), cs(du(dr.get("tacho_card_expiry")))] else ("due_soon" if "due_soon" in [cs(du(dr.get("licence_expiry"))), cs(du(dr.get("cpc_expiry"))), cs(du(dr.get("tacho_card_expiry")))] else "valid"))} for dr in drivers
        ]},
        {"heading": "Driver Training", "columns": ["Driver", "Course", "Category", "Expiry", "Status"], "rows": [
            {"cells": [t.get("driver_name"), t.get("course_name"), t.get("category"), _fmt(t.get("expiry_date"))],
             "status": cs(du(t.get("expiry_date")))} for t in training
        ]},
        {"heading": "PMI Inspections", "columns": ["Vehicle", "Frequency", "Next Due", "Inspector", "Status"], "rows": [
            {"cells": [p.get("vehicle_reg"), f"{p.get('frequency_weeks', 6)} wks", _fmt(p.get("next_due")), p.get("inspector")],
             "status": cs(du(p.get("next_due")))} for p in pmi
        ]},
        {"heading": "Insurance", "columns": ["Type", "Insurer", "Policy No", "Expiry", "Cover", "Status"], "rows": [
            {"cells": [i.get("policy_type"), i.get("insurer"), i.get("policy_number"), _fmt(i.get("expiry_date")), i.get("cover_amount")],
             "status": cs(du(i.get("expiry_date")))} for i in insurance
        ]},
        {"heading": "Tachograph Downloads", "columns": ["Source", "Reference", "Last Download", "Next Due", "Status"], "rows": [
            {"cells": [t.get("source_type"), t.get("reference"), _fmt(t.get("last_download")), _fmt(t.get("next_due"))],
             "status": cs(du(t.get("next_due")))} for t in tacho
        ]},
        {"heading": "Open Defects", "columns": ["Vehicle", "Severity", "Category", "Description", "Status"], "rows": [
            {"cells": [d.get("vehicle_reg"), d.get("severity", "").replace("_", " "), d.get("category"), (d.get("description") or "")[:70], d.get("status")]} for d in defects if d.get("status") == "open"
        ]},
        {"heading": "Wheel Security Audits", "columns": ["Vehicle", "Date", "Result", "Torque", "Next Due", "Status"], "rows": [
            {"cells": [w.get("vehicle_reg"), _fmt(w.get("audit_date")), w.get("result"), w.get("torque_setting"), _fmt(w.get("next_due"))],
             "status": cs(du(w.get("next_due")))} for w in wheel
        ]},
    ]
    subtitle = operator.get("company_name") or user.name
    authority = "RSA (Ireland)" if user.region == "IE" else "DVSA (UK)"
    pdf = await asyncio.to_thread(
        build_report_pdf, "Fleet Compliance Report", subtitle,
        [("Authority", authority), ("O-Licence", operator.get("operator_licence_number", ""))], sections,
        await _get_logo_bytes(user.user_id, operator), authority)
    if include_files:
        all_files = await db.files.find({"user_id": user.user_id, "is_deleted": False}, {"_id": 0, "id": 1}).to_list(2000)
        pdf = await asyncio.to_thread(merge_pack, pdf, await _collect_files(user.user_id, [f["id"] for f in all_files]))
    if include_files:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", (operator.get("company_name") or "Fleet")).strip("-") or "Fleet"
        fname = f"{slug}-Audit-Pack-{datetime.now(timezone.utc).strftime('%Y-%m')}.pdf"
    else:
        fname = "fleet-compliance-report.pdf"
    return pdf, fname


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
scheduler = AsyncIOScheduler(timezone="UTC")


@app.on_event("startup")
async def startup_event():
    try:
        init_storage()
        logger.info("Object storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    try:
        scheduler.add_job(run_daily_reminders, "cron", hour=7, minute=0, id="daily_reminders", replace_existing=True)
        scheduler.add_job(run_weekly_reminders, "cron", day_of_week="mon", hour=7, minute=0, id="weekly_reminders", replace_existing=True)
        scheduler.start()
        logger.info("Reminder scheduler started (daily 07:00 UTC, weekly Mon 07:00 UTC)")
    except Exception as e:
        logger.error(f"Scheduler start failed: {e}")


@app.on_event("shutdown")
async def shutdown_db_client():
    if scheduler.running:
        scheduler.shutdown(wait=False)
    client.close()
