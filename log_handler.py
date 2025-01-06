#log_handler.py
import logging
from threading import Lock

class InMemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self._logs = []
        self._lock = Lock()  # 스레드 안전성을 위한 락 추가
        
    def emit(self, record):
        try:
            msg = self.format(record)
            with self._lock:  # 스레드 안전한 로그 추가
                self._logs.append(msg)
        except Exception:
            self.handleError(record)
            
    def get_logs(self):
        with self._lock:
            return self._logs.copy()  # 안전한 복사본 반환
        
    def clear(self):
        with self._lock:
            self._logs = []
            
    def __len__(self):
        return len(self._logs)