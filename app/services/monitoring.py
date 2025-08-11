"""
Monitoring and logging service for system metrics.
Tracks API calls, performance, costs, and errors.
"""

import time
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from pathlib import Path
import sqlite3
from contextlib import contextmanager
import traceback

logger = logging.getLogger(__name__)

class MonitoringService:
    """Service for monitoring system metrics and logging."""
    
    def __init__(self, db_path: str = "data/monitoring.db"):
        """
        Initialize monitoring service.
        
        Args:
            db_path: Path to monitoring database
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        
        # Setup logging
        self._setup_logging()
    
    def _init_database(self):
        """Initialize monitoring database."""
        conn = sqlite3.connect(str(self.db_path))
        
        # API metrics table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT NOT NULL,
                method TEXT NOT NULL,
                status_code INTEGER,
                response_time_ms REAL,
                user_id TEXT,
                ip_address TEXT,
                error_message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Performance metrics table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                metadata TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Cost tracking table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cost_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                operation TEXT NOT NULL,
                tokens_used INTEGER,
                cost_usd REAL,
                metadata TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Error logs table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS error_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                stack_trace TEXT,
                context TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # System metrics table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS system_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cpu_percent REAL,
                memory_mb REAL,
                disk_usage_percent REAL,
                active_connections INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def _setup_logging(self):
        """Setup structured logging."""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # Configure root logger
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / "app.log"),
                logging.StreamHandler()
            ]
        )
        
        # Create specialized loggers
        self.api_logger = logging.getLogger("api")
        self.perf_logger = logging.getLogger("performance")
        self.error_logger = logging.getLogger("errors")
    
    @contextmanager
    def track_api_call(self, endpoint: str, method: str, user_id: Optional[str] = None):
        """
        Context manager to track API call metrics.
        
        Args:
            endpoint: API endpoint
            method: HTTP method
            user_id: Optional user identifier
        """
        start_time = time.time()
        error_message = None
        status_code = 200
        
        try:
            yield
        except Exception as e:
            error_message = str(e)
            status_code = 500
            raise
        finally:
            duration_ms = (time.time() - start_time) * 1000
            self.log_api_metric(
                endpoint=endpoint,
                method=method,
                status_code=status_code,
                response_time_ms=duration_ms,
                user_id=user_id,
                error_message=error_message
            )
    
    @contextmanager
    def track_performance(self, operation: str, metadata: Optional[Dict] = None):
        """
        Context manager to track operation performance.
        
        Args:
            operation: Operation name
            metadata: Optional metadata
        """
        start_time = time.time()
        
        try:
            yield
        finally:
            duration_ms = (time.time() - start_time) * 1000
            self.log_performance_metric(operation, duration_ms, metadata)
    
    def log_api_metric(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        response_time_ms: float,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        error_message: Optional[str] = None
    ):
        """Log API call metrics."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("""
                INSERT INTO api_metrics 
                (endpoint, method, status_code, response_time_ms, user_id, ip_address, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (endpoint, method, status_code, response_time_ms, user_id, ip_address, error_message))
            conn.commit()
            conn.close()
            
            # Also log to file
            self.api_logger.info(
                f"{method} {endpoint} - {status_code} - {response_time_ms:.2f}ms"
            )
        except Exception as e:
            logger.error(f"Failed to log API metric: {e}")
    
    def log_performance_metric(
        self,
        operation: str,
        duration_ms: float,
        metadata: Optional[Dict] = None
    ):
        """Log performance metrics."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            metadata_json = json.dumps(metadata) if metadata else None
            
            conn.execute("""
                INSERT INTO performance_metrics (operation, duration_ms, metadata)
                VALUES (?, ?, ?)
            """, (operation, duration_ms, metadata_json))
            conn.commit()
            conn.close()
            
            # Also log to file
            self.perf_logger.info(f"{operation} - {duration_ms:.2f}ms")
        except Exception as e:
            logger.error(f"Failed to log performance metric: {e}")
    
    def log_cost(
        self,
        service: str,
        operation: str,
        tokens_used: Optional[int] = None,
        cost_usd: Optional[float] = None,
        metadata: Optional[Dict] = None
    ):
        """Log cost metrics."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            metadata_json = json.dumps(metadata) if metadata else None
            
            conn.execute("""
                INSERT INTO cost_tracking (service, operation, tokens_used, cost_usd, metadata)
                VALUES (?, ?, ?, ?, ?)
            """, (service, operation, tokens_used, cost_usd, metadata_json))
            conn.commit()
            conn.close()
            
            logger.info(f"Cost logged: {service}/{operation} - ${cost_usd:.4f}")
        except Exception as e:
            logger.error(f"Failed to log cost: {e}")
    
    def log_error(
        self,
        error_type: str,
        error_message: str,
        stack_trace: Optional[str] = None,
        context: Optional[Dict] = None
    ):
        """Log error details."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            context_json = json.dumps(context) if context else None
            
            if not stack_trace:
                stack_trace = traceback.format_exc()
            
            conn.execute("""
                INSERT INTO error_logs (error_type, error_message, stack_trace, context)
                VALUES (?, ?, ?, ?)
            """, (error_type, error_message, stack_trace, context_json))
            conn.commit()
            conn.close()
            
            # Also log to file
            self.error_logger.error(f"{error_type}: {error_message}")
        except Exception as e:
            logger.error(f"Failed to log error: {e}")
    
    def get_api_metrics_summary(
        self,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get API metrics summary for the last N hours.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Summary statistics
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_requests,
                    AVG(response_time_ms) as avg_response_time,
                    MAX(response_time_ms) as max_response_time,
                    MIN(response_time_ms) as min_response_time,
                    SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) as error_count,
                    COUNT(DISTINCT user_id) as unique_users
                FROM api_metrics
                WHERE timestamp >= ?
            """, (cutoff_time,))
            
            row = cursor.fetchone()
            
            # Get endpoint breakdown
            endpoint_cursor = conn.execute("""
                SELECT 
                    endpoint,
                    COUNT(*) as count,
                    AVG(response_time_ms) as avg_time
                FROM api_metrics
                WHERE timestamp >= ?
                GROUP BY endpoint
                ORDER BY count DESC
                LIMIT 10
            """, (cutoff_time,))
            
            endpoints = [
                {
                    'endpoint': row[0],
                    'count': row[1],
                    'avg_time': row[2]
                }
                for row in endpoint_cursor
            ]
            
            conn.close()
            
            return {
                'period_hours': hours,
                'total_requests': row[0] or 0,
                'avg_response_time_ms': row[1] or 0,
                'max_response_time_ms': row[2] or 0,
                'min_response_time_ms': row[3] or 0,
                'error_count': row[4] or 0,
                'error_rate': (row[4] / row[0] * 100) if row[0] else 0,
                'unique_users': row[5] or 0,
                'top_endpoints': endpoints
            }
        except Exception as e:
            logger.error(f"Failed to get API metrics summary: {e}")
            return {}
    
    def get_cost_summary(
        self,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get cost summary for the last N days.
        
        Args:
            days: Number of days to look back
            
        Returns:
            Cost summary
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cutoff_time = datetime.now() - timedelta(days=days)
            
            cursor = conn.execute("""
                SELECT 
                    service,
                    SUM(tokens_used) as total_tokens,
                    SUM(cost_usd) as total_cost
                FROM cost_tracking
                WHERE timestamp >= ?
                GROUP BY service
            """, (cutoff_time,))
            
            services = {}
            total_cost = 0
            total_tokens = 0
            
            for row in cursor:
                services[row[0]] = {
                    'tokens': row[1] or 0,
                    'cost': row[2] or 0
                }
                total_tokens += row[1] or 0
                total_cost += row[2] or 0
            
            conn.close()
            
            return {
                'period_days': days,
                'total_cost_usd': total_cost,
                'total_tokens': total_tokens,
                'services': services
            }
        except Exception as e:
            logger.error(f"Failed to get cost summary: {e}")
            return {}
    
    def get_error_summary(
        self,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get error summary for the last N hours.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Error summary
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            cursor = conn.execute("""
                SELECT 
                    error_type,
                    COUNT(*) as count,
                    MAX(timestamp) as last_occurrence
                FROM error_logs
                WHERE timestamp >= ?
                GROUP BY error_type
                ORDER BY count DESC
            """, (cutoff_time,))
            
            errors = [
                {
                    'type': row[0],
                    'count': row[1],
                    'last_occurrence': row[2]
                }
                for row in cursor
            ]
            
            total_errors = sum(e['count'] for e in errors)
            
            conn.close()
            
            return {
                'period_hours': hours,
                'total_errors': total_errors,
                'error_types': errors
            }
        except Exception as e:
            logger.error(f"Failed to get error summary: {e}")
            return {}
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get comprehensive dashboard data.
        
        Returns:
            Dashboard data dictionary
        """
        return {
            'api_metrics_24h': self.get_api_metrics_summary(24),
            'api_metrics_7d': self.get_api_metrics_summary(24 * 7),
            'cost_30d': self.get_cost_summary(30),
            'errors_24h': self.get_error_summary(24),
            'timestamp': datetime.now().isoformat()
        }
    
    def cleanup_old_data(self, days: int = 90):
        """
        Clean up old monitoring data.
        
        Args:
            days: Delete data older than N days
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cutoff_time = datetime.now() - timedelta(days=days)
            
            tables = [
                'api_metrics',
                'performance_metrics',
                'cost_tracking',
                'error_logs',
                'system_metrics'
            ]
            
            for table in tables:
                conn.execute(f"""
                    DELETE FROM {table} WHERE timestamp < ?
                """, (cutoff_time,))
            
            conn.commit()
            conn.execute("VACUUM")
            conn.close()
            
            logger.info(f"Cleaned up monitoring data older than {days} days")
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")

# Singleton instance
monitoring_service = MonitoringService()
