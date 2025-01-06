from log_handler import InMemoryLogHandler
import logging
import os
from datetime import datetime

# 전역 로거 인스턴스
_logger = None
_log_handler = None
_file_handler = None

def setup_logger():
    global _logger, _log_handler, _file_handler
    if _logger is None:
        _logger = logging.getLogger('test_automation')
        
        if not _logger.handlers:  # 중복 핸들러 방지
            # 로그 포맷 설정
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            
            # 메모리 핸들러 설정
            _log_handler = InMemoryLogHandler()
            _log_handler.setFormatter(formatter)
            
            # 파일 핸들러 설정
            logs_dir = 'logs'
            if not os.path.exists(logs_dir):
                os.makedirs(logs_dir)
                
            log_filename = os.path.join(logs_dir, f'test_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
            _file_handler = logging.FileHandler(log_filename, encoding='utf-8')
            _file_handler.setFormatter(formatter)
            
            # 로그 레벨 설정
            _logger.setLevel(logging.INFO)
            
            # 핸들러 추가
            _logger.addHandler(_log_handler)
            _logger.addHandler(_file_handler)
            
            # 루트 로거로의 전파 방지
            _logger.propagate = False
            
    return _logger

def get_logger():
    global _logger
    if _logger is None:
        _logger = setup_logger()
    return _logger

def get_log_handler():
    global _log_handler
    if _log_handler is None:
        setup_logger()
    return _log_handler