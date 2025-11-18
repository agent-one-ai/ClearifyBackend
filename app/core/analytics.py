from supabase import create_client, Client
from app.core.config import Settings
from datetime import datetime, timedelta, date
from app.schemas.analytics import DailyMetrics
from typing import Dict, List, Optional

class AnalyticsDB:
    def __init__(self):
        self.supabase: Client = create_client(Settings.SUPABASE_URL, Settings.SUPABASE_SERVICE_KEY)
    
    async def get_daily_metrics(self, target_date: date) -> DailyMetrics:
        """Raccoglie tutte le metriche per una data specifica"""
        
        # Query principali
        #TODO - Da implementare
        core_metrics = await self._get_core_metrics(target_date)
        detection_stats = await self._get_detection_stats(target_date)
        business_metrics = await self._get_business_metrics(target_date)
        activity_patterns = await self._get_activity_patterns(target_date)
        growth_metrics = await self._get_growth_metrics(target_date)
        system_health = await self._get_system_health(target_date)
        insights = await self._generate_insights(target_date)
        
        return DailyMetrics(
            report_date=target_date.strftime("%B %d, %Y"),
            generation_time=datetime.utcnow().strftime("%H:%M UTC"),
            
            # Core
            total_analyses=core_metrics['total_analyses'],
            analyses_growth=growth_metrics['analyses_growth'],
            active_users=core_metrics['active_users'],
            users_growth=growth_metrics['users_growth'],
            new_signups=core_metrics['new_signups'],
            signups_growth=growth_metrics['signups_growth'],
            
            # Detection
            ai_detected_percent=detection_stats['ai_percent'],
            human_detected_percent=detection_stats['human_percent'],
            ai_detected_count=detection_stats['ai_count'],
            human_detected_count=detection_stats['human_count'],
            avg_confidence=detection_stats['avg_confidence'],
            avg_response_time=detection_stats['avg_response_time'],
            success_rate=detection_stats['success_rate'],
            
            # Business
            premium_conversions=business_metrics['premium_conversions'],
            daily_revenue=business_metrics['daily_revenue'],
            premium_users_count=business_metrics['premium_users_count'],
            
            # Insights
            insight_1=insights[0] if len(insights) > 0 else "No significant insights today",
            insight_2=insights[1] if len(insights) > 1 else "System running normally",
            insight_3=insights[2] if len(insights) > 2 else "User engagement stable",
            
            # Activity
            peak_hour=activity_patterns['peak_hour'],
            peak_hour_analyses=activity_patterns['peak_analyses'],
            low_hour=activity_patterns['low_hour'],
            low_hour_analyses=activity_patterns['low_analyses'],
            avg_text_length=activity_patterns['avg_text_length'],
            
            # System
            system_uptime=system_health['uptime'],
            api_errors=system_health['errors']
        )
    
    async def _get_core_metrics(self, target_date: date) -> Dict:
        """Metriche core: analisi, utenti, signup"""
        
        # Query per analisi totali del giorno
        analyses_result = self.supabase.table('text_analyses').select(
            'id, user_id, session_id'
        ).gte('created_at', target_date.isoformat()).lt(
            'created_at', (target_date + timedelta(days=1)).isoformat()
        ).execute()
        
        total_analyses = len(analyses_result.data)
        
        # Utenti unici (considerando sia user_id che session_id per anonimi)
        unique_identifiers = set()
        for analysis in analyses_result.data:
            if analysis['user_id']:
                unique_identifiers.add(f"user_{analysis['user_id']}")
            elif analysis['session_id']:
                unique_identifiers.add(f"session_{analysis['session_id']}")
        
        active_users = len(unique_identifiers)
        
        # Nuovi signup
        signups_result = self.supabase.table('users').select('id').gte(
            'created_at', target_date.isoformat()
        ).lt('created_at', (target_date + timedelta(days=1)).isoformat()).execute()
        
        new_signups = len(signups_result.data)
        
        return {
            'total_analyses': total_analyses,
            'active_users': active_users,
            'new_signups': new_signups
        }
    
    async def _get_detection_stats(self, target_date: date) -> Dict:
        """Statistiche detection AI"""
        
        analyses = self.supabase.table('text_analyses').select(
            'is_ai_generated, confidence_score, processing_time_ms, status'
        ).gte('created_at', target_date.isoformat()).lt(
            'created_at', (target_date + timedelta(days=1)).isoformat()
        ).execute()
        
        if not analyses.data:
            return {
                'ai_percent': 0, 'human_percent': 0, 'ai_count': 0,
                'human_count': 0, 'avg_confidence': 0, 'avg_response_time': 0,
                'success_rate': 100
            }
        
        ai_count = sum(1 for a in analyses.data if a['is_ai_generated'])
        human_count = len(analyses.data) - ai_count
        total = len(analyses.data)
        
        avg_confidence = sum(a['confidence_score'] for a in analyses.data) / total
        avg_response_time = sum(a['processing_time_ms'] for a in analyses.data) / total / 1000  # to seconds
        
        successful = sum(1 for a in analyses.data if a['status'] == 'completed')
        success_rate = (successful / total) * 100 if total > 0 else 100
        
        return {
            'ai_percent': round((ai_count / total) * 100, 1) if total > 0 else 0,
            'human_percent': round((human_count / total) * 100, 1) if total > 0 else 0,
            'ai_count': ai_count,
            'human_count': human_count,
            'avg_confidence': round(avg_confidence, 1),
            'avg_response_time': round(avg_response_time, 2),
            'success_rate': round(success_rate, 1)
        }
    
    async def _get_business_metrics(self, target_date: date) -> Dict:
        """Metriche business: pagamenti, conversioni"""
        
        # Pagamenti completati nel giorno
        payments = self.supabase.table('payment_intents').select(
            'amount, customer_name'
        ).eq('status', 'succeeded').gte(
            'created_at', target_date.isoformat()
        ).lt('created_at', (target_date + timedelta(days=1)).isoformat()).execute()
        
        daily_revenue = sum(p['amount'] for p in payments.data) / 100  # convert to euros
        premium_conversions = len(payments.data)
        
        # Utenti premium attivi
        premium_users = self.supabase.table('users').select('id').eq(
            'subscription_tier', 'premium'
        ).execute()
        #.eq('subscription_status', 'active').execute()
        
        return {
            'daily_revenue': round(daily_revenue, 2),
            'premium_conversions': premium_conversions,
            'premium_users_count': len(premium_users.data)
        }
    
    async def _get_activity_patterns(self, target_date: date) -> Dict:
        """Pattern di attività per ora"""
        
        analyses = self.supabase.table('text_analyses').select(
            'created_at, text_word_count'
        ).gte('created_at', target_date.isoformat()).lt(
            'created_at', (target_date + timedelta(days=1)).isoformat()
        ).execute()
        
        if not analyses.data:
            return {
                'peak_hour': 12, 'peak_analyses': 0,
                'low_hour': 4, 'low_analyses': 0,
                'avg_text_length': 0
            }
        
        # Analisi per ora
        hourly_counts = {}
        word_counts = []
        
        for analysis in analyses.data:
            created_at = datetime.fromisoformat(analysis['created_at'].replace('Z', '+00:00'))
            hour = created_at.hour
            hourly_counts[hour] = hourly_counts.get(hour, 0) + 1
            
            if analysis['text_word_count']:
                word_counts.append(analysis['text_word_count'])
        
        # Trova picco e minimo
        peak_hour = max(hourly_counts.items(), key=lambda x: x[1]) if hourly_counts else (12, 0)
        low_hour = min(hourly_counts.items(), key=lambda x: x[1]) if hourly_counts else (4, 0)
        
        avg_text_length = sum(word_counts) / len(word_counts) if word_counts else 0
        
        return {
            'peak_hour': peak_hour[0],
            'peak_analyses': peak_hour[1],
            'low_hour': low_hour[0],
            'low_analyses': low_hour[1],
            'avg_text_length': round(avg_text_length)
        }
    
    async def _get_growth_metrics(self, target_date: date) -> Dict:
        """Metriche di crescita vs giorno precedente"""
        
        previous_date = target_date - timedelta(days=1)
        
        # Metriche oggi
        today_metrics = await self._get_core_metrics(target_date)
        
        # Metriche ieri
        yesterday_metrics = await self._get_core_metrics(previous_date)
        
        def calc_growth(today, yesterday):
            if yesterday == 0:
                return 100 if today > 0 else 0
            return round(((today - yesterday) / yesterday) * 100, 1)
        
        return {
            'analyses_growth': calc_growth(
                today_metrics['total_analyses'], 
                yesterday_metrics['total_analyses']
            ),
            'users_growth': calc_growth(
                today_metrics['active_users'], 
                yesterday_metrics['active_users']
            ),
            'signups_growth': calc_growth(
                today_metrics['new_signups'], 
                yesterday_metrics['new_signups']
            )
        }
    
    async def _get_system_health(self, target_date: date) -> Dict:
        """Salute del sistema: uptime, errori"""
        
        # Errori del giorno
        errors = self.supabase.table('system_events').select('id').eq(
            'event_type', 'error'
        ).gte('created_at', target_date.isoformat()).lt(
            'created_at', (target_date + timedelta(days=1)).isoformat()
        ).execute()
        
        # Calcola uptime basato su analisi completate vs fallite
        failed_analyses = self.supabase.table('text_analyses').select('id').eq(
            'status', 'failed'
        ).gte('created_at', target_date.isoformat()).lt(
            'created_at', (target_date + timedelta(days=1)).isoformat()
        ).execute()
        
        total_analyses = self.supabase.table('text_analyses').select('id').gte(
            'created_at', target_date.isoformat()
        ).lt('created_at', (target_date + timedelta(days=1)).isoformat()).execute()
        
        total = len(total_analyses.data)
        failed = len(failed_analyses.data)
        uptime = ((total - failed) / total) * 100 if total > 0 else 100
        
        return {
            'uptime': round(uptime, 1),
            'errors': len(errors.data)
        }
    
    async def _generate_insights(self, target_date: date) -> List[str]:
        """Genera insights automatici basati sui dati"""
        
        insights = []
        
        # Ottieni metriche base per insights
        core_metrics = await self._get_core_metrics(target_date)
        activity_patterns = await self._get_activity_patterns(target_date)
        growth_metrics = await self._get_growth_metrics(target_date)
        
        # Insight 1: Crescita
        if growth_metrics['analyses_growth'] > 20:
            insights.append(f"Forte crescita: +{growth_metrics['analyses_growth']}% di analisi vs ieri")
        elif growth_metrics['analyses_growth'] > 0:
            insights.append(f"Crescita positiva: +{growth_metrics['analyses_growth']}% di analisi")
        elif growth_metrics['analyses_growth'] < -10:
            insights.append(f"Calo significativo: {growth_metrics['analyses_growth']}% di analisi")
        else:
            insights.append("Volume di analisi stabile rispetto a ieri")
        
        # Insight 2: Pattern di attività
        if activity_patterns['peak_hour'] >= 9 and activity_patterns['peak_hour'] <= 17:
            insights.append(f"Picco durante orario lavorativo alle {activity_patterns['peak_hour']}:00")
        elif activity_patterns['peak_hour'] >= 18 and activity_patterns['peak_hour'] <= 23:
            insights.append(f"Maggiore attività serale alle {activity_patterns['peak_hour']}:00")
        else:
            insights.append(f"Utilizzo insolito con picco alle {activity_patterns['peak_hour']}:00")
        
        # Insight 3: Lunghezza testi
        avg_length = activity_patterns['avg_text_length']
        if avg_length > 500:
            insights.append("Testi lunghi: utenti analizzano contenuti complessi")
        elif avg_length < 100:
            insights.append("Testi brevi: focus su frasi e paragrafi")
        else:
            insights.append(f"Lunghezza media testi: {avg_length} parole")
        
        return insights[:3]  # Massimo 3 insights
    
    async def save_daily_snapshot(self, metrics: DailyMetrics, target_date: date):
        """Salva snapshot giornaliero per storico"""
        
        snapshot_data = {
            'report_date': target_date.isoformat(),
            'total_analyses': metrics.total_analyses,
            'total_active_users': metrics.active_users,
            'total_new_signups': metrics.new_signups,
            'ai_detected_count': metrics.ai_detected_count,
            'human_detected_count': metrics.human_detected_count,
            'ai_detected_percentage': metrics.ai_detected_percent,
            'avg_confidence_score': metrics.avg_confidence,
            'avg_processing_time_ms': metrics.avg_response_time * 1000,
            'success_rate_percentage': metrics.success_rate,
            'total_revenue_cents': int(metrics.daily_revenue * 100),
            'new_premium_conversions': metrics.premium_conversions,
            'active_premium_users': metrics.premium_users_count,
            'peak_hour': metrics.peak_hour,
            'peak_hour_analyses': metrics.peak_hour_analyses,
            'avg_text_length_words': metrics.avg_text_length,
            'analyses_growth_percentage': metrics.analyses_growth,
            'users_growth_percentage': metrics.users_growth,
            'signups_growth_percentage': metrics.signups_growth,
            'system_uptime_percentage': metrics.system_uptime,
            'api_error_count': metrics.api_errors
        }
        
        # Upsert (inserisce o aggiorna se esiste)
        result = self.supabase.table('daily_analytics_snapshots').upsert(
            snapshot_data,
            on_conflict='report_date'
        ).execute()
        
        return result
