from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class DailyMetrics:
    report_date: str
    generation_time: str
    
    # Core metrics
    total_analyses: int
    analyses_growth: float
    active_users: int
    users_growth: float
    new_signups: int
    signups_growth: float
    
    # AI Detection
    ai_detected_percent: float
    human_detected_percent: float
    ai_detected_count: int
    human_detected_count: int
    avg_confidence: float
    avg_response_time: float
    success_rate: float
    
    # Business
    premium_conversions: int
    daily_revenue: float
    premium_users_count: int
    
    # Insights
    insight_1: str
    insight_2: str
    insight_3: str
    
    # Activity
    peak_hour: int
    peak_hour_analyses: int
    low_hour: int
    low_hour_analyses: int
    avg_text_length: int
    
    # System
    system_uptime: float
    api_errors: int

class TextAnalyses:
    id: int
    user_id: int
    session_id: str
    text_content: str
    text_length: int
    text_word_count: int
    text_language: str
    ai_probability: float
    is_ai_generated: bool
    confidence_score: int
    model_version: str
    processing_time_ms: str
    api_response_time_ms: int
    user_agent: str
    ip_address: str
    referer_url: str
    country_code: str
    device_type: str
    status: str
    error_message: str
    created_at: datetime
    updated_at: datetime
