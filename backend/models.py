from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


class AppInfo(BaseModel):
    app_id: str
    store: str  # "playstore" | "appstore"
    title: str
    developer: str
    rating: Optional[float] = None
    ratings_count: Optional[int] = None
    reviews_count: Optional[int] = None
    installs: Optional[str] = None
    price: Optional[float] = 0
    currency: Optional[str] = "USD"
    icon_url: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    version: Optional[str] = None
    updated: Optional[str] = None
    content_rating: Optional[str] = None
    url: Optional[str] = None

    @field_validator("installs", "updated", "version", mode="before")
    @classmethod
    def coerce_to_str(cls, v):
        return str(v) if v is not None else None


class ReviewItem(BaseModel):
    review_id: Optional[str] = None
    username: str
    rating: int
    text: str
    date: Optional[str] = None
    thumbs_up: Optional[int] = 0
    reply: Optional[str] = None
    reply_date: Optional[str] = None


class ReviewAnalysis(BaseModel):
    total_reviews: int
    avg_rating: float
    sentiment: dict  # {positive: %, neutral: %, negative: %}
    top_topics: list[dict]  # [{topic, count, sentiment}]
    feature_requests: list[str]
    bug_reports: list[str]
    highlights: list[str]  # best quotes
    lowlights: list[str]  # worst quotes
    summary: str
    recommendations: list[str]


class SecurityFinding(BaseModel):
    severity: str  # critical, high, medium, low, info
    category: str
    title: str
    description: str
    evidence: Optional[str] = None
    recommendation: str


class SecurityReport(BaseModel):
    scan_id: str
    target: str
    started_at: str
    completed_at: str
    score: int  # 0-100
    grade: str  # A-F
    findings: list[SecurityFinding]
    summary: dict


class RevenueOverview(BaseModel):
    provider: str
    total_revenue: float
    mrr: Optional[float] = None
    active_subscribers: Optional[int] = None
    trials: Optional[int] = None
    transactions: list[dict] = []
    currency: str = "USD"


class ConnectRequest(BaseModel):
    provider: str
    api_key: str
    extra: dict = {}
